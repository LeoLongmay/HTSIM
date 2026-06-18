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
SEEDS="13 14 15 16 17"; FAILEDS="0 2 4 6 8 10 12"; TOPO=fat_tree_128_1os.topo
DD="-disable_trim"   # the delay-driven knob
# END (ms). Default 8: the 5xBDP no-trim regime builds deep queues, so 2 ms left many flows
# unfinished (completion-stressed, FCT confounded). 8 ms lets the workload drain. Override EXP_END.
ENDV="${EXP_END:-8}"

echo "== self-test analysis =="
python3 "$HERE/make_figs.py" --selftest
( cd "$COMMON/tests" && python3 test_metrics.py >/dev/null && echo "ok common metrics selftest" )
( cd "$DC/.." && g++ -I. datacenter/prism_eval/common/tests/test_strack_cc.cpp -o /tmp/test_strack_cc && /tmp/test_strack_cc )

echo "== generate workload (many2many: 64 -> 16 pod0, 2MB) =="
python3 "$COMMON/gen/many2many.py" "$REL/data/m2m.cm" 64 16 pairs 2000000 128 16
CM="$REL/data/m2m.cm"; OUT="$REL/data"
# Mechanism condition uses a LARGER message size (4MB) so every arm's makespan > 3 ms, giving a
# clean [0,3] ms window in figA2dd (the main perf sweep above stays at 2 MB). Override MECH_SIZE.
MECH_SIZE="${MECH_SIZE:-4000000}"
python3 "$COMMON/gen/many2many.py" "$REL/data/m2m_mech.cm" 64 16 pairs "$MECH_SIZE" 128 16
CM_MECH="$REL/data/m2m_mech.cm"

echo "== start-unit guard: confirm .cm 'start' is picoseconds + no overflow at the window scale =="
printf 'Nodes 128\nConnections 2\n80->0 start 1000000 size 2000000\n81->1 start 8000000000 size 2000000\n' > "$OUT/_unit_probe.cm"
PATHS=8 END_MS=12 EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" nscc reps 0 "$TOPO" 13 "$OUT/_unit_probe.cm" flow _unit_probe "$OUT"
python3 - "$OUT/_unit_probe.flow.txt" <<'PY'
import sys
starts = sorted(float(ln.split()[0]) for ln in open(sys.argv[1]) if " START " in ln)
assert len(starts) >= 2, f"probe produced too few START events: {starts}"
# start in ps: 1e6 ps -> 1us=0.000001s ; 8e9 ps -> 8ms=0.008s (also checks no uint32 overflow at 8ms)
assert 0.0079 < starts[-1] < 0.0081, f"start-unit NOT picoseconds / overflow (start 8e9 -> {starts[-1]}s)"
print("ok start-unit = picoseconds, no overflow at 8ms:", starts)
PY

echo "== main sweep (delay-driven): 5 baselines x failed{0,2,4,8,12} x 5 seeds =="
for f in $FAILEDS; do for s in $SEEDS; do
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" nscc oblivious "$f" "$TOPO" "$s" "$CM" flow,sink "expA_ops_f${f}_s${s}" "$OUT"
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" nscc reps      "$f" "$TOPO" "$s" "$CM" flow,sink "expA_reps_f${f}_s${s}" "$OUT"
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_EPOCH="$OUT/expA_prism_f${f}_s${s}.epoch.csv" \
    bash "$COMMON/run_lib.sh" prism reps "$f" "$TOPO" "$s" "$CM" flow,sink "expA_prism_f${f}_s${s}" "$OUT"
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" strack reps  "$f" "$TOPO" "$s" "$CM" flow,sink "expA_strack_f${f}_s${s}" "$OUT"
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" nscc ecmp "$f" "$TOPO" "$s" "$CM" flow,sink "expA_ecmp_f${f}_s${s}" "$OUT"
done; done

echo "== mechanism condition: failed=8, seed=13, 4MB workload (CM_MECH), all 4 with PRISM_PATHRTT =="
PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_PATHRTT="$OUT/expA_ops_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" nscc oblivious 8 "$TOPO" 13 "$CM_MECH" flow,sink expA_ops_mech "$OUT"
PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_PATHRTT="$OUT/expA_reps_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" nscc reps 8 "$TOPO" 13 "$CM_MECH" flow,sink expA_reps_mech "$OUT"
PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_EPOCH="$OUT/expA_prism_mech.epoch.csv" PRISM_PATHRTT="$OUT/expA_prism_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" prism reps 8 "$TOPO" 13 "$CM_MECH" flow,sink expA_prism_mech "$OUT"
PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_PATHRTT="$OUT/expA_strack_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" strack reps 8 "$TOPO" 13 "$CM_MECH" flow,sink expA_strack_mech "$OUT"

echo "== offered-load sweep (Poisson, failed=8, 2MB): 5 arms x rho{10,30,50,70,90}% x 5 seeds =="
LOAD_W_US=8000; LOAD_END=20; REF_GBPS=1600
for rho in 10 30 50 70 90; do
  rhof="$(python3 -c "print($rho/100.0)")"
  for s in $SEEDS; do
    LCM="$OUT/m2m_load_L${rho}_s${s}.cm"
    python3 "$COMMON/gen/poisson_load.py" "$LCM" 64 16 2000000 128 16 "$rhof" "$LOAD_W_US" "$REF_GBPS" "$s"
    PATHS=8 END_MS="$LOAD_END" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" nscc oblivious 8 "$TOPO" "$s" "$LCM" flow,sink "expAload_ops_L${rho}_s${s}" "$OUT"
    PATHS=8 END_MS="$LOAD_END" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" nscc reps      8 "$TOPO" "$s" "$LCM" flow,sink "expAload_reps_L${rho}_s${s}" "$OUT"
    PATHS=8 END_MS="$LOAD_END" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" prism reps     8 "$TOPO" "$s" "$LCM" flow,sink "expAload_prism_L${rho}_s${s}" "$OUT"
    PATHS=8 END_MS="$LOAD_END" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" strack reps    8 "$TOPO" "$s" "$LCM" flow,sink "expAload_strack_L${rho}_s${s}" "$OUT"
    PATHS=8 END_MS="$LOAD_END" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" nscc ecmp      8 "$TOPO" "$s" "$LCM" flow,sink "expAload_ecmp_L${rho}_s${s}" "$OUT"
  done
done

echo "== render figA1dd_{goodput,avg_fct,p99_fct} + figA2dd_{signal,cwnd} =="
python3 "$HERE/make_figs.py"
echo "== done: figs/figA1dd_*.{png,pdf} figs/figA2dd_{signal,cwnd}.{png,pdf} =="
