#!/bin/bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DC="$(cd "$HERE/../../.." && pwd)"
BIN="${1:-$DC/htsim_uec}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

TOPO="$DC/topologies/fat_tree_128_1os.topo"
TM="$HERE/one_flow.cm"
PREFIX="$TMP/coord-cli"
OUT="$TMP/coord-cli.dat"

"$BIN" -topo "$TOPO" -tm "$TM" -nodes 128 -sender_cc_algo prism -sender_cc_only \
    -load_balancing_algo reps_actual -paths 8 -disable_trim \
    -degraded_links 8 -degraded_capacity_gbps 1 \
    -prism_coordination_mode full_prism -motivation_trace_prefix "$PREFIX" \
    -motivation_run_id coord_cli -motivation_scenario coord_cli -end 2 -o "$OUT" \
    >"$TMP/accepted.stdout" 2>&1

for suffix in ack token epoch background pathmap linkmap coordination; do
    if [[ ! -s "$PREFIX.$suffix.csv" ]]; then
        echo "accepted coordination mode did not emit $suffix trace" >&2
        exit 1
    fi
done

if ! awk 'END { exit NR > 1 ? 0 : 1 }' "$PREFIX.coordination.csv"; then
    echo "accepted coordination mode emitted only a coordination header" >&2
    exit 1
fi

PYTHONPATH="$(cd "$DC/../../.." && pwd)" python3 - "$PREFIX" "$TMP/terminal-no-op" <<'PY'
import csv
import shutil
import sys
from pathlib import Path

from htsim.sim.datacenter.add_motivation.common.trace_schema import load_trace

prefix = Path(sys.argv[1])
no_op_prefix = Path(sys.argv[2])
kinds = ("ack", "token", "epoch", "background", "pathmap", "linkmap", "coordination")

# Strictly loading the emitted bundle also checks its epoch-close event ordering.
load_trace(prefix)

with Path(f"{prefix}.coordination.csv").open(newline="", encoding="utf-8") as stream:
    reader = csv.DictReader(stream)
    fieldnames = reader.fieldnames
    rows = list(reader)

assert fieldnames is not None
terminal_actions = {
    "round_complete_progress",
    "round_complete_handoff",
    "round_complete_retry",
}
for index, row in enumerate(rows):
    if row["action"] not in terminal_actions:
        continue
    if row["action"] == "round_complete_progress":
        assert row["progress"] == "1"
    if row["action"] == "round_complete_retry":
        assert row["refresh_complete"] == "1"
        assert row["progress"] == "0"
        assert row["handoff"] == "0"
    if row["action"] != "round_complete_handoff":
        continue
    assert row["refresh_complete"] == "1"
    assert row["progress"] == "0"
    if row["handoff"] != "1":
        continue
    assert index > 0
    evidence = rows[index - 1]
    assert (evidence["flow_id"], evidence["epoch_id"], evidence["round_id"]) == (
        row["flow_id"], row["epoch_id"], row["round_id"]
    )
    assert int(row["cwnd_bytes"]) < int(evidence["cwnd_bytes"])

for kind in kinds:
    shutil.copyfile(f"{prefix}.{kind}.csv", f"{no_op_prefix}.{kind}.csv")

rows[0].update({
    "action": "round_complete_handoff",
    "refresh_complete": "1",
    "progress": "0",
    "handoff": "0",
    "cwnd_bytes": "1000",
})
with Path(f"{no_op_prefix}.coordination.csv").open("w", newline="", encoding="utf-8") as stream:
    writer = csv.DictWriter(stream, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

load_trace(no_op_prefix)
PY

if "$BIN" -topo "$TOPO" -tm "$TM" -nodes 128 -sender_cc_algo prism -sender_cc_only \
    -load_balancing_algo reps_legacy -paths 8 -disable_trim \
    -prism_coordination_mode full_prism -end 2 -o "$TMP/rejected.dat" \
    >"$TMP/rejected.stdout" 2>&1; then
    echo "full_prism with reps_legacy unexpectedly succeeded" >&2
    exit 1
fi

grep -q 'requires -load_balancing_algo reps_actual' "$TMP/rejected.stdout"
