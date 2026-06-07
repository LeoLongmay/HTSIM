#!/bin/bash
# Run one config: lb_algo, failed, tag. Captures stdout + per-run idmap + agg-core q.txt.
# NOTE: the LB algorithm is set by -load_balancing_algo (reps|oblivious|mixed|...),
# NOT by -strat (which sets the route strategy: ecmp/adaptive/...). Route strategy is
# left at its default (ECMP), matching the round-1 runs.
set -euo pipefail
DC="$(cd "$(dirname "$0")/.." && pwd)"   # .../sim/datacenter
cd "$DC"
LB="$1"; FAILED="$2"; TAG="$3"
OUT=mvp_runs2
echo "[run_one] lb_algo=$LB failed=$FAILED tag=$TAG"
./htsim_uec -topo topologies/fat_tree_128_1os.topo -tm "$OUT/perm.cm" -nodes 128 \
    -sender_cc_algo nscc -load_balancing_algo "$LB" -failed "$FAILED" -mtu 4150 \
    -log tor_upqueue -logtime_us 2 -end 2 -o "$OUT/$TAG.dat" > "$OUT/$TAG.stdout" 2>&1  # NOTE: htsim -end is in milliseconds (despite usage string), so -end 2 = 2ms
cp idmap.txt "$OUT/$TAG.idmap"
../build/parse_output "$OUT/$TAG.dat" -ascii \
    | grep ' QUEUE_APPROX ' | grep ' RANGE ' > "$OUT/$TAG.q.txt" || {
        echo "[run_one] WARNING: no QUEUE_APPROX RANGE records in $TAG.dat — check -log flag" >&2
        exit 1
    }
echo "[run_one] done $TAG  .dat=$(du -h "$OUT/$TAG.dat" | cut -f1)  q.txt_lines=$(wc -l < "$OUT/$TAG.q.txt")"
