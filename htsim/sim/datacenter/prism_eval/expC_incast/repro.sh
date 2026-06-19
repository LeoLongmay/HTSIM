#!/bin/bash
# Exp C, INCAST (delay-driven, -disable_trim): pure shared downstream bottleneck.
# x-axis = fan-in {8,32,64} senders -> 1 dest, symmetric fat_tree_128_1os, -failed=0.
# Message size 1MB (keeps 64:1 tractable in the deep no-trim regime). Tests that PRISM falls
# back to floor-driven CC (C_cc high, C_spray small/transient) and does NOT misuse spray.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../common" && pwd)"
DC="$(cd "$HERE/../.." && pwd)"
REL="prism_eval/expC_incast"
cd "$DC"
[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first"; exit 1; }
mkdir -p "$REL/data"
SEEDS="13 14 15 16 17"
FANIN="8 32 64"
TOPO=fat_tree_128_1os.topo        # symmetric: pure shared bottleneck at the dest ingress
SIZE="${INCAST_SIZE:-1000000}"    # 1MB default; override for the optional 2MB alignment point
DD="-disable_trim"
ENDV="${EXP_END:-8}"

echo "== self-test analysis =="
python3 "$HERE/make_figs.py" --selftest
( cd "$COMMON/tests" && python3 test_metrics.py >/dev/null && echo "ok common metrics selftest" )

echo "== generate incast workloads (fan-in {8,32,64} -> host0, ${SIZE}B) =="
for n in $FANIN; do
  python3 "$COMMON/gen/incast.py" "$REL/data/incast_${n}.cm" "$n" 0 "$SIZE" 128 16
done
OUT="$REL/data"

echo "== main sweep (incast): 4 baselines x fan-in{8,32,64} x 5 seeds =="
for n in $FANIN; do for s in $SEEDS; do
  CM="$REL/data/incast_${n}.cm"
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" nscc oblivious 0 "$TOPO" "$s" "$CM" flow "expC_ops_f${n}_s${s}" "$OUT"
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" nscc reps      0 "$TOPO" "$s" "$CM" flow "expC_reps_f${n}_s${s}" "$OUT"
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_EPOCH="$OUT/expC_prism_f${n}_s${s}.epoch.csv" \
    bash "$COMMON/run_lib.sh" prism reps 0 "$TOPO" "$s" "$CM" flow "expC_prism_f${n}_s${s}" "$OUT"
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" strack reps   0 "$TOPO" "$s" "$CM" flow "expC_strack_f${n}_s${s}" "$OUT"
done; done

echo "== mechanism condition: fan-in=64, seed=13, all 4 arms with PRISM_PATHRTT =="
CM64="$REL/data/incast_64.cm"
PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_PATHRTT="$OUT/expC_ops_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" nscc oblivious 0 "$TOPO" 13 "$CM64" flow expC_ops_mech "$OUT"
PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_PATHRTT="$OUT/expC_reps_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" nscc reps 0 "$TOPO" 13 "$CM64" flow expC_reps_mech "$OUT"
PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_EPOCH="$OUT/expC_prism_mech.epoch.csv" PRISM_PATHRTT="$OUT/expC_prism_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" prism reps 0 "$TOPO" 13 "$CM64" flow expC_prism_mech "$OUT"
PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_PATHRTT="$OUT/expC_strack_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" strack reps 0 "$TOPO" 13 "$CM64" flow expC_strack_mech "$OUT"

echo "== render figC1 + figC2 =="
python3 "$HERE/make_figs.py"
echo "== done: figs/figC1_main_perf.{png,pdf} figs/figC2_mechanism.{png,pdf} =="
