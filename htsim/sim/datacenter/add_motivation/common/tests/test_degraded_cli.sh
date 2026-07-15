#!/bin/bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DC="$(cd "$HERE/../../.." && pwd)"
TMP="$(mktemp -d "$HERE/.degraded-cli.XXXXXX")"
OUT="$TMP/stdout"
trap 'rm -rf "$TMP"' EXIT

cd "$TMP"
"$DC/htsim_uec" \
    -topo "$DC/topologies/fat_tree_128_1os.topo" \
    -tm "$HERE/one_flow.cm" \
    -nodes 128 \
    -sender_cc_algo nscc \
    -load_balancing_algo reps_legacy \
    -degraded_links 2 \
    -degraded_capacity_gbps 50 \
    -end 2 \
    -o "$TMP/simulation.dat" \
    >"$OUT" 2>&1

grep -q "degraded_links 2" "$OUT"
grep -q "degraded_capacity_gbps 50" "$OUT"
grep -q "Degraded:" "$OUT"
if grep -q "Unknown parameter" "$OUT"; then
    echo "degraded CLI aliases were rejected" >&2
    exit 1
fi
