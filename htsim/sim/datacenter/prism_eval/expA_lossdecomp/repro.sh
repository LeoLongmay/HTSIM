#!/bin/bash
# Loss-decomposition Exp A, TRIMMING regime (P2 setup: NO -disable_trim, END=2). 4 arms:
# ops / reps / prism (delay-only, -prism_loss_decomp 0) / prismL (loss-decomp, -prism_loss_decomp 1).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; COMMON="$(cd "$HERE/../common" && pwd)"; DC="$(cd "$HERE/../.." && pwd)"
REL="prism_eval/expA_lossdecomp"; cd "$DC"
[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first"; exit 1; }
mkdir -p "$REL/data"
SEEDS="13 14 15 16 17"; FAILEDS="0 2 4 8 12"; TOPO=fat_tree_128_1os.topo; ENDV="${EXP_END:-2}"

echo "== self-tests =="
python3 "$HERE/make_figs.py" --selftest
( cd "$COMMON/tests" && python3 test_metrics.py >/dev/null && echo "ok common metrics selftest" )
( cd "$DC/.." && g++ -I. datacenter/prism_eval/common/tests/test_prism_decompose.cpp -o /tmp/test_prism_dec && /tmp/test_prism_dec )

echo "== workload (many2many 64->16 pod0, 2MB) =="
python3 "$COMMON/gen/many2many.py" "$REL/data/m2m.cm" 64 16 pairs 2000000 128 16
CM="$REL/data/m2m.cm"; OUT="$REL/data"

echo "== main sweep (trimming): 4 arms x failed{0,2,4,8,12} x 5 seeds =="
for f in $FAILEDS; do for s in $SEEDS; do
  PATHS=8 END_MS="$ENDV" bash "$COMMON/run_lib.sh" nscc oblivious "$f" "$TOPO" "$s" "$CM" flow "expL_ops_f${f}_s${s}" "$OUT"
  PATHS=8 END_MS="$ENDV" bash "$COMMON/run_lib.sh" nscc reps      "$f" "$TOPO" "$s" "$CM" flow "expL_reps_f${f}_s${s}" "$OUT"
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="-prism_loss_decomp 0" PRISM_EPOCH="$OUT/expL_prism_f${f}_s${s}.epoch.csv" \
    bash "$COMMON/run_lib.sh" prism reps "$f" "$TOPO" "$s" "$CM" flow "expL_prism_f${f}_s${s}" "$OUT"
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="-prism_loss_decomp 1" PRISM_EPOCH="$OUT/expL_prismL_f${f}_s${s}.epoch.csv" \
    bash "$COMMON/run_lib.sh" prism reps "$f" "$TOPO" "$s" "$CM" flow "expL_prismL_f${f}_s${s}" "$OUT"
done; done

echo "== mechanism (failed=8, seed=13) =="
PATHS=8 END_MS="$ENDV" PRISM_PATHRTT="$OUT/expL_reps_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" nscc reps 8 "$TOPO" 13 "$CM" flow expL_reps_mech "$OUT"
PATHS=8 END_MS="$ENDV" EXTRA_ARGS="-prism_loss_decomp 0" PRISM_EPOCH="$OUT/expL_prism_mech.epoch.csv" PRISM_PATHRTT="$OUT/expL_prism_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" prism reps 8 "$TOPO" 13 "$CM" flow expL_prism_mech "$OUT"
PATHS=8 END_MS="$ENDV" EXTRA_ARGS="-prism_loss_decomp 1" PRISM_EPOCH="$OUT/expL_prismL_mech.epoch.csv" PRISM_PATHRTT="$OUT/expL_prismL_mech.pathrtt.csv" PRISM_LOSS="$OUT/expL_prismL_mech.loss.csv" \
  bash "$COMMON/run_lib.sh" prism reps 8 "$TOPO" 13 "$CM" flow expL_prismL_mech "$OUT"

echo "== render figL1 + figL2 + loss-HOLD fraction =="
python3 "$HERE/make_figs.py"
echo "== done: figs/figL1_main_perf.* figs/figL2_mechanism.* =="
