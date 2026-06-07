#!/bin/bash
# Run one config: strat, failed, tag. Captures stdout + per-run idmap + agg-core q.txt.
set -euo pipefail
DC="$(cd "$(dirname "$0")/.." && pwd)"   # .../sim/datacenter
cd "$DC"
STRAT="$1"; FAILED="$2"; TAG="$3"
OUT=mvp_runs2
echo "[run_one] strat=$STRAT failed=$FAILED tag=$TAG"
./htsim_uec -topo topologies/fat_tree_128_1os.topo -tm "$OUT/perm.cm" -nodes 128 \
    -sender_cc_algo nscc -strat "$STRAT" -failed "$FAILED" -mtu 4150 \
    -log tor_upqueue -logtime_us 2 -end 2 -o "$OUT/$TAG.dat" > "$OUT/$TAG.stdout" 2>&1
cp idmap.txt "$OUT/$TAG.idmap"
../build/parse_output "$OUT/$TAG.dat" -ascii | grep ' QUEUE_APPROX ' | grep ' RANGE ' > "$OUT/$TAG.q.txt"
echo "[run_one] done $TAG  .dat=$(du -h "$OUT/$TAG.dat" | cut -f1)  q.txt_lines=$(wc -l < "$OUT/$TAG.q.txt")"
