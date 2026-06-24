#!/bin/bash
# PRISM overhead analysis: build+run the microbench, generate PRISM_EPOCH logs (kappa sweep for the
# samples/decision + reaction-latency figures), render figO1..figO4. Measurement-only; no FCT/goodput.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../common" && pwd)"
DC="$(cd "$HERE/../.." && pwd)"
REL="prism_eval/expH_overhead"
cd "$DC"
[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first"; exit 1; }
mkdir -p "$REL/data" "$REL/figs"
SEEDS="13 14 15 16 17"; TOPO=fat_tree_128_1os.topo; OUT="$REL/data"
KLIST="0.5 1 2 4"

echo "== self-test =="
python3 "$HERE/make_figs.py" --selftest

echo "== microbench (standalone; no simulator linkage) =="
# headers (prism_decompose.h etc.) live in htsim/sim == $DC/.. ($DC is .../htsim/sim/datacenter)
g++ -O2 -std=c++17 -I "$DC/.." "$HERE/overhead_bench.cpp" -o "$HERE/overhead_bench"
"$HERE/overhead_bench" "$HERE/data"

echo "== workload (reuse expA_delaydriven m2m; byte-identical) =="
CM="prism_eval/expA_delaydriven/data/m2m.cm"
[ -f "$CM" ] || { echo "ERROR: $CM missing -- run expA_delaydriven/repro.sh first"; exit 1; }

echo "== PRISM_EPOCH runs: kappa {$KLIST} x 5 seeds, failed=8 (asymmetric, signal active) =="
for k in $KLIST; do for s in $SEEDS; do
  PATHS=8 END_MS=8 EXTRA_ARGS="-disable_trim -prism_kappa $k" \
    PRISM_EPOCH="$OUT/epoch_k${k}_s${s}.epoch.csv" \
    bash "$COMMON/run_lib.sh" prism reps 8 "$TOPO" "$s" "$CM" flow "epoch_k${k}_s${s}" "$OUT"
done; done

echo "== render figO1..figO4 =="
python3 "$HERE/make_figs.py" --render
echo "== done: figs/figO1_state figO2_compute figO3_samples figO4_latency =="
