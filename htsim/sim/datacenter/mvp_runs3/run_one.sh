#!/bin/bash
# Run one config with per-path RTT logging. Args: lb_algo, failed, tag, [cm_file].
set -euo pipefail
DC="$(cd "$(dirname "$0")/.." && pwd)"   # .../sim/datacenter
cd "$DC"
LB="$1"; FAILED="$2"; TAG="$3"; CM="${4:-mvp_runs3/incast.cm}"
OUT=mvp_runs3
echo "[run_one] lb=$LB failed=$FAILED tag=$TAG cm=$CM"
PRISM_PATHRTT="$OUT/$TAG.pathrtt.csv" ./htsim_uec \
    -topo topologies/fat_tree_128_1os.topo -tm "$CM" -nodes 128 \
    -sender_cc_algo nscc -load_balancing_algo "$LB" -failed "$FAILED" -mtu 4150 \
    -end 2 -o "$OUT/$TAG.dat" > "$OUT/$TAG.stdout" 2>&1
echo "[run_one] done $TAG: $(wc -l < "$OUT/$TAG.pathrtt.csv") rtt rows; $(grep -m1 'Load balancing algorithm set to' "$OUT/$TAG.stdout")"
