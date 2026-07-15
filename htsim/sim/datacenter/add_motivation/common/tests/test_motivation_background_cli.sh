#!/bin/bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DC="$(cd "$HERE/../../.." && pwd)"
BIN="${1:-$DC/htsim_uec}"
TMP="$(mktemp -d "$HERE/.background-cli.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

CM="$TMP/empty.cm"
printf 'Nodes 128\nConnections 0\n' >"$CM"

COMMON=(
    "$BIN"
    -topo "$DC/topologies/fat_tree_128_1os.topo"
    -nodes 128
    -queue_type ecn
    -host_queue_type fair_prio
    -disable_trim
    -q 16
    -ecn 1 8
    -sender_cc_algo nscc
    -load_balancing_algo reps_legacy
    -end 2
)
BASE=("${COMMON[@]}" -tm "$CM")

assert_no_artifacts() {
    local trace_prefix="$1"
    local logfile="$2"
    shopt -s nullglob
    local traces=("$trace_prefix".*.csv)
    shopt -u nullglob
    if ((${#traces[@]} != 0)) || [[ -e "$logfile" ]]; then
        echo "early background config failure created output artifacts" >&2
        exit 1
    fi
}

MALFORMED="$TMP/malformed.csv"
printf 'bad header\n' >"$MALFORMED"
if "${BASE[@]}" -o "$TMP/malformed.dat" \
    -motivation_trace_prefix "$TMP/malformed-trace" \
    -motivation_background_config "$MALFORMED" \
    >"$TMP/malformed.stdout" 2>&1; then
    echo "malformed background config unexpectedly succeeded" >&2
    exit 1
fi
grep -q 'motivation background config header mismatch' "$TMP/malformed.stdout"
assert_no_artifacts "$TMP/malformed-trace" "$TMP/malformed.dat"

if "${BASE[@]}" -o "$TMP/missing.dat" \
    -motivation_trace_prefix "$TMP/missing-trace" \
    -motivation_background_config "$TMP/missing.csv" \
    >"$TMP/missing.stdout" 2>&1; then
    echo "missing background config unexpectedly succeeded" >&2
    exit 1
fi
grep -q 'failed to open motivation background config' "$TMP/missing.stdout"
assert_no_artifacts "$TMP/missing-trace" "$TMP/missing.dat"

HEADER='background_id,src,dst,path_index,rate_gbps,start_ps,stop_ps'
VALID="$TMP/valid.csv"
printf '%s\n%s\n' "$HEADER" '0,16,0,3,25,200000000,1200000000' >"$VALID"
"${BASE[@]}" -o "$TMP/valid.dat" \
    -motivation_trace_prefix "$TMP/valid-trace" \
    -motivation_run_id task9-cli \
    -motivation_scenario fixed-path \
    -motivation_background_config "$VALID" \
    >"$TMP/valid.stdout" 2>&1

TRACE="$TMP/valid-trace.background.csv"
python3 - "$TRACE" <<'PY'
import csv
import sys

with open(sys.argv[1], newline="", encoding="ascii") as trace:
    rows = list(csv.DictReader(trace))

assert len(rows) == 2, rows
start, finish = rows
assert (start["event_seq"], start["time_ps"], start["background_id"],
        start["operation"], start["src"], start["dst"], start["path_index"],
        start["configured_rate_gbps"], start["delivered_bytes"]) == (
            "0", "200000000", "0", "start", "16", "0", "3", "25", "0")
assert (finish["event_seq"], finish["time_ps"], finish["background_id"],
        finish["operation"], finish["configured_rate_gbps"],
        finish["delivered_bytes"]) == (
            "1", "1200000000", "0", "finish", "25", "3105000")
assert finish["queue_fingerprint"] == start["queue_fingerprint"]

fingerprint = start["queue_fingerprint"]
expected_path = [
    "SRC16->LS4(0)",
    "LS4->US4(0)",
    "US4->CS12(0)",
    "CS12->US0(0)",
    "US0->LS_0(0)",
    "LS0->DST0(0)",
]
position = -1
for queue in expected_path:
    position = fingerprint.find(queue, position + 1)
    assert position >= 0, (queue, fingerprint)
assert fingerprint.count("|") == 5, fingerprint
PY

TRANSACTION="$TMP/transaction.csv"
printf '%s\n%s\n%s\n' "$HEADER" \
    '0,16,0,3,25,200000000,1200000000' \
    '1,17,1,99999,25,300000000,1100000000' >"$TRANSACTION"
if "${BASE[@]}" -o "$TMP/transaction.dat" \
    -motivation_trace_prefix "$TMP/transaction-trace" \
    -motivation_background_config "$TRANSACTION" \
    >"$TMP/transaction.stdout" 2>&1; then
    echo "later-invalid background row unexpectedly succeeded" >&2
    exit 1
fi
grep -q 'path_index is invalid for ID 1' "$TMP/transaction.stdout"
[[ "$(wc -l <"$TMP/transaction-trace.background.csv")" -eq 1 ]]

SHARED_SOURCE="$TMP/shared-source.csv"
printf '%s\n%s\n%s\n' "$HEADER" \
    '0,16,0,3,25,200000000,1200000000' \
    '1,16,1,0,25,300000000,1100000000' >"$SHARED_SOURCE"
if "${BASE[@]}" -o "$TMP/shared-source.dat" \
    -motivation_trace_prefix "$TMP/shared-source-trace" \
    -motivation_background_config "$SHARED_SOURCE" \
    >"$TMP/shared-source.stdout" 2>&1; then
    echo "shared background source unexpectedly succeeded" >&2
    exit 1
fi
grep -q 'source endpoint is shared by multiple backgrounds for ID 1' \
    "$TMP/shared-source.stdout"
[[ "$(wc -l <"$TMP/shared-source-trace.background.csv")" -eq 1 ]]

CONTENDED_CM="$TMP/contended.cm"
printf 'Nodes 128\nConnections 1\n0->16 start 1 size 1000000\n' >"$CONTENDED_CM"
if "${COMMON[@]}" -tm "$CONTENDED_CM" -o "$TMP/contended.dat" \
    -motivation_trace_prefix "$TMP/contended-trace" \
    -motivation_background_config "$VALID" \
    >"$TMP/contended.stdout" 2>&1; then
    echo "foreground endpoint contention unexpectedly succeeded" >&2
    exit 1
fi
grep -q 'background source endpoint is used by foreground traffic for ID 0' \
    "$TMP/contended.stdout"
[[ "$(wc -l <"$TMP/contended-trace.background.csv")" -eq 1 ]]

if "$BIN" -topo "$DC/topologies/fat_tree_128_1os.topo" -tm "$CM" -nodes 128 \
    -sender_cc_algo nscc -load_balancing_algo reps_legacy -end 2 \
    -o "$TMP/composite.dat" \
    -motivation_trace_prefix "$TMP/composite-trace" \
    -motivation_background_config "$VALID" \
    >"$TMP/composite.stdout" 2>&1; then
    echo "unsupported default composite queue unexpectedly succeeded" >&2
    exit 1
fi
grep -q 'background route queue class has no proven drain bound' \
    "$TMP/composite.stdout"

# Under BASE, this route's conservative drain bound is exactly 33,280,000 ps.
EQUAL_DEADLINE="$TMP/equal-deadline.csv"
printf '%s\n%s\n' "$HEADER" \
    '0,16,0,3,25,1900000000,1966720000' >"$EQUAL_DEADLINE"
if "${BASE[@]}" -o "$TMP/equal-deadline.dat" \
    -motivation_trace_prefix "$TMP/equal-deadline-trace" \
    -motivation_background_config "$EQUAL_DEADLINE" \
    >"$TMP/equal-deadline.stdout" 2>&1; then
    echo "background drain deadline equal to simulation end unexpectedly succeeded" >&2
    exit 1
fi
grep -q 'cannot drain before simulation end for ID 0' "$TMP/equal-deadline.stdout"

MARGIN_DEADLINE="$TMP/margin-deadline.csv"
printf '%s\n%s\n' "$HEADER" \
    '0,16,0,3,25,1900000000,1966719999' >"$MARGIN_DEADLINE"
"${BASE[@]}" -o "$TMP/margin-deadline.dat" \
    -motivation_trace_prefix "$TMP/margin-deadline-trace" \
    -motivation_background_config "$MARGIN_DEADLINE" \
    >"$TMP/margin-deadline.stdout" 2>&1
