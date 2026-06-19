#!/bin/bash
# Exp B, OVERSUBSCRIPTION (delay-driven, -disable_trim): graded core bottleneck.
# x-axis = oversubscription ratio {1,4,8} via topo file; -failed=0 (oversub is the only stressor,
# orthogonal to expA's link-asymmetry axis). Same 64->16 m2m workload as expA_delaydriven.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../common" && pwd)"
DC="$(cd "$HERE/../.." && pwd)"
REL="prism_eval/expB_oversub"
cd "$DC"
[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first"; exit 1; }
mkdir -p "$REL/data"
SEEDS="13 14 15 16 17"
RATIOS="1 4 8"
declare -A TOPO=( [1]=fat_tree_128_1os.topo [4]=fat_tree_128_4os.topo [8]=fat_tree_128_8os.topo )
DD="-disable_trim"                # delay-driven knob
ENDV="${EXP_END:-8}"              # ms; deep no-trim queues need time to drain (see README caveat)

echo "== self-test analysis =="
python3 "$HERE/make_figs.py" --selftest
( cd "$COMMON/tests" && python3 test_metrics.py >/dev/null && echo "ok common metrics selftest" )

echo "== generate workload (many2many: 64 -> 16 pod0, 2MB; same as expA_delaydriven) =="
python3 "$COMMON/gen/many2many.py" "$REL/data/m2m.cm" 64 16 pairs 2000000 128 16
CM="$REL/data/m2m.cm"; OUT="$REL/data"

echo "== main sweep (oversub): 4 baselines x ratio{1,4,8} x 5 seeds =="
for r in $RATIOS; do for s in $SEEDS; do
  T="${TOPO[$r]}"
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" nscc oblivious 0 "$T" "$s" "$CM" flow "expB_ops_f${r}_s${s}" "$OUT"
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" nscc reps      0 "$T" "$s" "$CM" flow "expB_reps_f${r}_s${s}" "$OUT"
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_EPOCH="$OUT/expB_prism_f${r}_s${s}.epoch.csv" \
    bash "$COMMON/run_lib.sh" prism reps 0 "$T" "$s" "$CM" flow "expB_prism_f${r}_s${s}" "$OUT"
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" strack reps   0 "$T" "$s" "$CM" flow "expB_strack_f${r}_s${s}" "$OUT"
done; done

echo "== mechanism condition: ratio=8 (8os), seed=13, all 4 arms with PRISM_PATHRTT =="
T8="${TOPO[8]}"
PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_PATHRTT="$OUT/expB_ops_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" nscc oblivious 0 "$T8" 13 "$CM" flow expB_ops_mech "$OUT"
PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_PATHRTT="$OUT/expB_reps_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" nscc reps 0 "$T8" 13 "$CM" flow expB_reps_mech "$OUT"
PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_EPOCH="$OUT/expB_prism_mech.epoch.csv" PRISM_PATHRTT="$OUT/expB_prism_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" prism reps 0 "$T8" 13 "$CM" flow expB_prism_mech "$OUT"
PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_PATHRTT="$OUT/expB_strack_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" strack reps 0 "$T8" 13 "$CM" flow expB_strack_mech "$OUT"

echo "== render figB1 + figB2 =="
python3 "$HERE/make_figs.py"
echo "== done: figs/figB1_main_perf.{png,pdf} figs/figB2_mechanism.{png,pdf} =="
