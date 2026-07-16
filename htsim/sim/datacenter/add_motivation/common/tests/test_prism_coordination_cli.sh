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
    -prism_coordination_mode full_prism -motivation_trace_prefix "$PREFIX" \
    -motivation_run_id coord_cli -motivation_scenario coord_cli -end 2 -o "$OUT" \
    >"$TMP/accepted.stdout" 2>&1

for suffix in ack token epoch background pathmap linkmap; do
    if [[ ! -s "$PREFIX.$suffix.csv" ]]; then
        echo "accepted coordination mode did not emit $suffix trace" >&2
        exit 1
    fi
done

if "$BIN" -topo "$TOPO" -tm "$TM" -nodes 128 -sender_cc_algo prism -sender_cc_only \
    -load_balancing_algo reps_legacy -paths 8 -disable_trim \
    -prism_coordination_mode full_prism -end 2 -o "$TMP/rejected.dat" \
    >"$TMP/rejected.stdout" 2>&1; then
    echo "full_prism with reps_legacy unexpectedly succeeded" >&2
    exit 1
fi

grep -q 'requires -load_balancing_algo reps_actual' "$TMP/rejected.stdout"
