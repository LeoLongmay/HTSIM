#!/bin/bash
# Run one config with per-path RTT logging. Args: lb_algo, failed, tag, [cm_file].
# PATHS (env, default 8) = entropy/path-pool size the sender sprays over. We use a
# small pool so each path is densely sampled: q_i = rtt_i - rtt_min_i needs enough
# samples per path to capture both the path's near-unloaded min and its congested
# state, otherwise sparsely-sampled paths sit at their own min (q_i=0) and zero out
# C_cc = min_i q_i. (Default REPS pool of 64 is too sparse here; see smoke gate.)
set -euo pipefail
DC="$(cd "$(dirname "$0")/.." && pwd)"   # .../sim/datacenter
cd "$DC"
LB="$1"; FAILED="$2"; TAG="$3"; CM="${4:-mvp_runs3/incast.cm}"
PATHS="${PATHS:-8}"
END="${END:-2}"
SEED="${SEED:-13}"   # explicit RNG seed (htsim default is also 13); vary for multi-seed runs
OUT=mvp_runs3
echo "[run_one] lb=$LB failed=$FAILED tag=$TAG cm=$CM paths=$PATHS end=$END seed=$SEED"
PRISM_PATHRTT="$OUT/$TAG.pathrtt.csv" ./htsim_uec \
    -topo topologies/fat_tree_128_1os.topo -tm "$CM" -nodes 128 \
    -sender_cc_algo nscc -load_balancing_algo "$LB" -failed "$FAILED" -mtu 4150 \
    -paths "$PATHS" -seed "$SEED" -end "$END" -o "$OUT/$TAG.dat" > "$OUT/$TAG.stdout" 2>&1
echo "[run_one] done $TAG: $(wc -l < "$OUT/$TAG.pathrtt.csv") rtt rows; $(grep -m1 'Load balancing algorithm set to' "$OUT/$TAG.stdout")"
