#!/bin/bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DC="$(cd "$HERE/../../.." && pwd)"
TMP="$(mktemp -d "$HERE/.degraded-cli.XXXXXX")"
OUT="$TMP/stdout"
trap 'rm -rf "$TMP"' EXIT

cd "$TMP"
BASE=(
    "$DC/htsim_uec"
    -topo "$DC/topologies/fat_tree_128_1os.topo"
    -tm "$HERE/one_flow.cm"
    -nodes 128
    -sender_cc_algo nscc
    -load_balancing_algo reps_legacy
    -end 2
)

"${BASE[@]}" \
    -linkspeed 200000 \
    -degraded_links 2 \
    -degraded_capacity_gbps 50 \
    -o "$TMP/simulation.dat" \
    >"$OUT" 2>&1

grep -q "degraded_links 2" "$OUT"
grep -q "degraded_capacity_gbps 50" "$OUT"
grep -q "Degraded:" "$OUT"
grep -q "linkspeed set to 50" "$OUT"
if grep -q "Unknown parameter" "$OUT"; then
    echo "degraded CLI aliases were rejected" >&2
    exit 1
fi

"${BASE[@]}" -failed 1 -o "$TMP/legacy.dat" >"$TMP/legacy.stdout" 2>&1
grep -q "Degraded:" "$TMP/legacy.stdout"
grep -q "linkspeed set to 25" "$TMP/legacy.stdout"

run_rejected() {
    local name="$1"
    local expected="$2"
    shift 2
    if "${BASE[@]}" -o "$TMP/$name.dat" "$@" >"$TMP/$name.stdout" 2>&1; then
        echo "expected rejected degraded CLI case: $name" >&2
        exit 1
    fi
    grep -q "$expected" "$TMP/$name.stdout"
}

run_rejected missing_links "missing operand for -degraded_links" -degraded_links
run_rejected negative_links "invalid -degraded_links" -degraded_links -1
run_rejected junk_links "invalid -degraded_links" -degraded_links 12junk
run_rejected overflow_links "invalid -degraded_links" -degraded_links 4294967296
run_rejected topology_links "degraded link count 129 exceeds topology maximum 128" \
    -degraded_links 129 -degraded_capacity_gbps 50
run_rejected missing_capacity "missing operand for -degraded_capacity_gbps" -degraded_capacity_gbps
run_rejected junk_capacity "invalid -degraded_capacity_gbps" -degraded_capacity_gbps 50junk
run_rejected nonfinite_capacity "invalid -degraded_capacity_gbps" -degraded_capacity_gbps nan
run_rejected tiny_capacity "degraded scaling would produce zero link rate" \
    -degraded_links 2 -degraded_capacity_gbps 1e-12
run_rejected tiny_queue "degraded scaling would produce zero downlink queue size" \
    -degraded_links 2 -degraded_capacity_gbps 1e-9
run_rejected tiny_ecn "degraded scaling would produce zero ECN low threshold" \
    -degraded_links 2 -degraded_capacity_gbps 0.001
run_rejected excessive_capacity "degraded_capacity_gbps must be in" \
    -degraded_links 2 -degraded_capacity_gbps 101
run_rejected control_mismatch "control degraded_capacity_gbps must match affected topology rate" \
    -degraded_links 0 -degraded_capacity_gbps 50
run_rejected gray_mismatch "degraded_capacity_gbps must be in" \
    -degraded_links 2 -degraded_capacity_gbps 100
run_rejected mixed_aliases "cannot mix -failed with degraded aliases" \
    -failed 2 -degraded_links 2 -degraded_capacity_gbps 50

AUTO_BASE=(
    "$DC/htsim_uec"
    -tm "$HERE/one_flow.cm"
    -nodes 128
    -tiers 3
    -linkspeed 400000
    -q 211
    -sender_cc_algo nscc
    -load_balancing_algo reps_legacy
    -end 2
)

"${AUTO_BASE[@]}" -degraded_links 2 -degraded_capacity_gbps 100 \
    -o "$TMP/auto400-gray.dat" >"$TMP/auto400-gray.stdout" 2>&1
grep -q "Degraded:" "$TMP/auto400-gray.stdout"
grep -q "linkspeed set to 100" "$TMP/auto400-gray.stdout"

"${AUTO_BASE[@]}" -degraded_links 0 -degraded_capacity_gbps 400 \
    -o "$TMP/auto400-control.dat" >"$TMP/auto400-control.stdout" 2>&1
if grep -q "Degraded:" "$TMP/auto400-control.stdout"; then
    echo "400 Gbps control unexpectedly degraded links" >&2
    exit 1
fi
