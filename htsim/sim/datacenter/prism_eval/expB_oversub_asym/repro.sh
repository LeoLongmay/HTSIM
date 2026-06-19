#!/bin/bash
# expB asymmetric oversubscription: does PRISM's delay-driven asymmetric win extend to an
# oversubscribed core? Sweeps -failed x 4 arms at fixed oversub {4:1, 8:1}, delay-driven, 2MB
# many2many (same workload as expA/expB). Orthogonal asymmetry axis on top of the committed
# symmetric expB_oversub/. No controller change.
#
# IMPORTANT: `-failed N` does NOT degrade N core links on oversub topos (the index interacts with
# the reduced core radix). Total core->agg links: 4:1=32, 8:1=16. Actual degraded (see the report
# below): 8:1 failed{0,2,4,8} -> {0,3,7,15} (failed=8 = near-total core loss); 4:1 failed{0,4,8,12}
# -> {0,1,2,3} (knob barely acts on the reduced core). 8:1 is the real asymmetry axis; 4:1 is a
# degenerate reference.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../common" && pwd)"
DC="$(cd "$HERE/../.." && pwd)"
REL="prism_eval/expB_oversub_asym"
cd "$DC"
[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first"; exit 1; }
mkdir -p "$REL/data"
SEEDS="13 14 15 16 17"; DD="-disable_trim"; ENDV="${EXP_END:-8}"
FAILED_8OS="0 2 4 8"; FAILED_4OS="0 4 8 12"
declare -A TOPO=( [4os]=fat_tree_128_4os.topo [8os]=fat_tree_128_8os.topo )

echo "== selftest =="
python3 "$HERE/make_figs.py" --selftest
( cd "$COMMON/tests" && python3 test_metrics.py >/dev/null && echo "ok common metrics selftest" )
( cd "$DC/.." && g++ -I. datacenter/prism_eval/common/tests/test_swift_cc.cpp -o /tmp/test_swift_cc && /tmp/test_swift_cc )
( cd "$DC/.." && g++ -I. datacenter/prism_eval/common/tests/test_mnscc_median.cpp -o /tmp/test_mnscc_median && /tmp/test_mnscc_median )

echo "== workload (many2many 64->16 pod0, 2MB) =="
python3 "$COMMON/gen/many2many.py" "$REL/data/m2m.cm" 64 16 pairs 2000000 128 16
CM="$REL/data/m2m.cm"; OUT="$REL/data"

echo "== main sweep: {8os,4os} x -failed x 4 arms x 5 seeds =="
for R in 8os 4os; do
  if [ "$R" = 8os ]; then FS="$FAILED_8OS"; else FS="$FAILED_4OS"; fi
  T="${TOPO[$R]}"
  for f in $FS; do for s in $SEEDS; do
    PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" nscc oblivious "$f" "$T" "$s" "$CM" flow,sink "expBa${R}_ops_f${f}_s${s}" "$OUT"
    PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" nscc reps      "$f" "$T" "$s" "$CM" flow,sink "expBa${R}_reps_f${f}_s${s}" "$OUT"
    PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_EPOCH="$OUT/expBa${R}_prism_f${f}_s${s}.epoch.csv" \
      bash "$COMMON/run_lib.sh" prism reps "$f" "$T" "$s" "$CM" flow,sink "expBa${R}_prism_f${f}_s${s}" "$OUT"
    PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" strack reps   "$f" "$T" "$s" "$CM" flow,sink "expBa${R}_strack_f${f}_s${s}" "$OUT"
    PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" swift  reps "$f" "$T" "$s" "$CM" flow,sink "expBa${R}_swift_f${f}_s${s}"  "$OUT"
    PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" mswift reps "$f" "$T" "$s" "$CM" flow,sink "expBa${R}_mswift_f${f}_s${s}" "$OUT"
    PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" mnscc  reps "$f" "$T" "$s" "$CM" flow,sink "expBa${R}_mnscc_f${f}_s${s}"  "$OUT"
  done; done
done

echo "== degraded-core-link report (actual links degraded per -failed, from the sweep stdouts) =="
for R in 8os 4os; do
  if [ "$R" = 8os ]; then FS="$FAILED_8OS"; else FS="$FAILED_4OS"; fi
  for f in $FS; do
    d=$(grep -c 'Adding link failure' "$OUT/expBa${R}_reps_f${f}_s13.stdout" 2>/dev/null || echo 0)
    echo "  $R: -failed $f -> $d core links degraded"
  done
done

echo "== mechanism: 4:1, failed=8 (2/32 core links degraded -- the win point, cr=1.0), seed=13, all 4 arms with PRISM_PATHRTT =="
T="${TOPO[4os]}"
PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_PATHRTT="$OUT/expBa4os_ops_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" nscc oblivious 8 "$T" 13 "$CM" flow,sink expBa4os_ops_mech "$OUT"
PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_PATHRTT="$OUT/expBa4os_reps_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" nscc reps 8 "$T" 13 "$CM" flow,sink expBa4os_reps_mech "$OUT"
PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_EPOCH="$OUT/expBa4os_prism_mech.epoch.csv" PRISM_PATHRTT="$OUT/expBa4os_prism_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" prism reps 8 "$T" 13 "$CM" flow,sink expBa4os_prism_mech "$OUT"
PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_PATHRTT="$OUT/expBa4os_strack_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" strack reps 8 "$T" 13 "$CM" flow,sink expBa4os_strack_mech "$OUT"

echo "== render figBa_8os_main + figBa_4os_main + figBa_mech =="
python3 "$HERE/make_figs.py"
echo "== done: figs/figBa_{8os_main,4os_main,mech}.{png,pdf} =="
