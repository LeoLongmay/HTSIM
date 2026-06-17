#!/bin/bash
# expA_holdleak: do-no-harm controlled experiment for the HOLD-leak prototype (flag-gated, default
# OFF). Sweeps -prism_hold_leak x failed x seed (PRISM) + REPS+NSCC reference, delay-driven, 2MB
# many2many (same as expA_delaydriven). Reports whether a leak recovers f0 without eroding f8/f12.
#
# NOTE (result NEGATIVE -> controller REVERTED): the `-prism_hold_leak` flag this script passes was
# reverted from the controller after the negative result (PRISM kept O(1), byte-identical). To
# reproduce, FIRST re-apply the controller patch in
# docs/superpowers/plans/2026-06-17-prism-holdleak.md (Task 1) and rebuild htsim_uec; otherwise the
# binary does not recognize -prism_hold_leak. The committed figs/README are the recorded result.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../common" && pwd)"
DC="$(cd "$HERE/../.." && pwd)"
REL="prism_eval/expA_holdleak"
cd "$DC"
[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first"; exit 1; }
mkdir -p "$REL/data"
SEEDS="13 14 15 16 17"; FAILEDS="0 2 4 8 12"
LEAKS="0 0.1 0.25 0.5 0.75 1.0"
declare -A CODE=( [0]=0 [0.1]=10 [0.25]=25 [0.5]=50 [0.75]=75 [1.0]=100 )
DD="-disable_trim"; ENDV="${EXP_END:-8}"; TOPO=fat_tree_128_1os.topo

echo "== selftest =="
python3 "$HERE/holdleak_analyze.py" --selftest
( cd "$COMMON/tests" && python3 test_metrics.py >/dev/null && echo "ok common metrics selftest" )

echo "== workload (many2many 64->16 pod0, 2MB) =="
python3 "$COMMON/gen/many2many.py" "$REL/data/m2m.cm" 64 16 pairs 2000000 128 16
CM="$REL/data/m2m.cm"; OUT="$REL/data"

echo "== REPS+NSCC reference: failed{0,2,4,8,12} x 5 seeds =="
for f in $FAILEDS; do for s in $SEEDS; do
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" nscc reps "$f" "$TOPO" "$s" "$CM" flow,sink "hl_reps_f${f}_s${s}" "$OUT"
done; done

echo "== PRISM HOLD-leak sweep: leak{0,0.1,0.25,0.5,0.75,1.0} x failed x 5 seeds =="
for L in $LEAKS; do C="${CODE[$L]}"; for f in $FAILEDS; do for s in $SEEDS; do
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD -prism_hold_leak $L" \
    bash "$COMMON/run_lib.sh" prism reps "$f" "$TOPO" "$s" "$CM" flow,sink "hl_prism_l${C}_f${f}_s${s}" "$OUT"
done; done; done

echo "== analyze (verdict + figHL) =="
python3 "$HERE/holdleak_analyze.py"
echo "== done: figs/figHL_holdleak.{png,pdf} =="
