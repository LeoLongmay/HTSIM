#!/bin/bash
# Experiment A, DELAY-DRIVEN regime: identical to expA_asymmetric but every run adds
# EXTRA_ARGS="-disable_trim" (no trimming, 5xBDP buffer -> queues build, delay-MD drives cwnd).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../common" && pwd)"
DC="$(cd "$HERE/../.." && pwd)"
REL="prism_eval/expA_delaydriven"
cd "$DC"
[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first"; exit 1; }
mkdir -p "$REL/data"
SEEDS="13 14 15 16 17"; FAILEDS="0 2 4 8 12"; TOPO=fat_tree_128_1os.topo
DD="-disable_trim"   # the delay-driven knob
# END (ms). Default 8: the 5xBDP no-trim regime builds deep queues, so 2 ms left many flows
# unfinished (completion-stressed, FCT confounded). 8 ms lets the workload drain. Override EXP_END.
ENDV="${EXP_END:-8}"

echo "== self-test analysis =="
python3 "$HERE/make_figs.py" --selftest
( cd "$COMMON/tests" && python3 test_metrics.py >/dev/null && echo "ok common metrics selftest" )

echo "== generate workload (many2many: 64 -> 16 pod0, 2MB) =="
python3 "$COMMON/gen/many2many.py" "$REL/data/m2m.cm" 64 16 pairs 2000000 128 16
CM="$REL/data/m2m.cm"; OUT="$REL/data"

echo "== main sweep (delay-driven): 3 baselines x failed{0,2,4,8,12} x 5 seeds =="
for f in $FAILEDS; do for s in $SEEDS; do
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" nscc oblivious "$f" "$TOPO" "$s" "$CM" flow,sink "expA_ops_f${f}_s${s}" "$OUT"
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" nscc reps      "$f" "$TOPO" "$s" "$CM" flow,sink "expA_reps_f${f}_s${s}" "$OUT"
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_EPOCH="$OUT/expA_prism_f${f}_s${s}.epoch.csv" \
    bash "$COMMON/run_lib.sh" prism reps "$f" "$TOPO" "$s" "$CM" flow,sink "expA_prism_f${f}_s${s}" "$OUT"
done; done

echo "== mechanism condition: failed=8, seed=13, all 3 with PRISM_PATHRTT =="
PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_PATHRTT="$OUT/expA_ops_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" nscc oblivious 8 "$TOPO" 13 "$CM" flow,sink expA_ops_mech "$OUT"
PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_PATHRTT="$OUT/expA_reps_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" nscc reps 8 "$TOPO" 13 "$CM" flow,sink expA_reps_mech "$OUT"
PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_EPOCH="$OUT/expA_prism_mech.epoch.csv" PRISM_PATHRTT="$OUT/expA_prism_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" prism reps 8 "$TOPO" 13 "$CM" flow,sink expA_prism_mech "$OUT"

echo "== render figA1dd + figA2dd =="
python3 "$HERE/make_figs.py"
echo "== done: figs/figA1dd_main_perf.{png,pdf} figs/figA2dd_mechanism.{png,pdf} =="
