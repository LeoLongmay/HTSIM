#!/bin/bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DC="$(cd "$HERE/../../.." && pwd)"
BIN="${1:-$DC/htsim_uec}"
if [[ ! -x "$BIN" && -x "$DC/../build-lossless/htsim_uec" ]]; then
    BIN="$DC/../build-lossless/htsim_uec"
fi
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

TM="$TMP/two_flow.cm"
cat >"$TM" <<'EOF'
Nodes 128
Connections 2
16->0 start 1 size 100000
17->1 start 1 size 100000
EOF

BASE=(
    "$BIN"
    -topo "$DC/topologies/fat_tree_128_1os.topo"
    -tm "$TM"
    -nodes 128
    -queue_type lossless_input
    -queue_size_bytes 10000
    -pfc_high_bytes 8000
    -pfc_low_bytes 4000
    -shared_buffer_bytes 10000000
    -ecn 1 2
    -end 2
)

"${BASE[@]}" -o "$TMP/valid.dat" >"$TMP/valid.stdout" 2>&1
grep -q 'queue_size_bytes 10000' "$TMP/valid.stdout"
grep -q 'pfc_high_bytes 8000' "$TMP/valid.stdout"
grep -q 'pfc_low_bytes 4000' "$TMP/valid.stdout"
grep -q 'shared_buffer_bytes 10000000' "$TMP/valid.stdout"

run_rejected() {
    local name="$1"
    shift
    if "${BASE[@]}" -o "$TMP/$name.dat" "$@" >"$TMP/$name.stdout" 2>&1; then
        echo "expected rejected lossless CLI case: $name" >&2
        exit 1
    fi
}

run_rejected pfc_high_zero -pfc_high_bytes 0
run_rejected equal_pfc_thresholds -pfc_high_bytes 90 -pfc_low_bytes 90
run_rejected pfc_high_above_queue -pfc_high_bytes 10001
run_rejected shared_buffer_zero -shared_buffer_bytes 0
run_rejected queue_size_zero -queue_size_bytes 0
run_rejected packet_and_byte_queue_sizes -q 10
