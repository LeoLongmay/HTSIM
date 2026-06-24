#!/bin/bash
# PRISM parameter-sensitivity (robustness): OFAT sweep of T_spray, T_cc, epoch(kappa) around their
# defaults. Delay-driven, 128-node. Sweeps EXISTING flags via run_lib.sh EXTRA_ARGS -- NO controller change.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../common" && pwd)"
DC="$(cd "$HERE/../.." && pwd)"
REL="prism_eval/expA_sensitivity"
cd "$DC"
[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first"; exit 1; }
mkdir -p "$REL/data"
SEEDS="13 14 15 16 17"; TOPO=fat_tree_128_1os.topo
DD="-disable_trim"
ENDV="${EXP_END:-8}"
OUT="$REL/data"
# Dense OFAT grids (off-default values only; the default center is reused from expA_delaydriven).
TSLIST="5 7 10 17 20 24 28 40"                  # T_spray us (default 14 reused)
QLIST="5 7 10 17 20 24 28 40"                   # T_cc us  (-target_q_delay; default ~14 reused)
KLIST="0.125 0.25 0.375 0.5 0.75 1.5 2 3 4 6 8" # kappa    (default 1.0 reused)

echo "== self-tests =="
python3 "$HERE/make_figs.py" --selftest
( cd "$COMMON/tests" && python3 test_metrics.py >/dev/null && echo "ok common metrics selftest" )

echo "== workload (many2many 64->16 pod0 2MB; identical args to expA_delaydriven) =="
python3 "$COMMON/gen/many2many.py" "$OUT/m2m.cm" 64 16 pairs 2000000 128 16
CM="$OUT/m2m.cm"
REFCM="$DC/prism_eval/expA_delaydriven/data/m2m.cm"
[ -f "$REFCM" ] || { echo "ERROR: reference workload $REFCM missing -- run expA_delaydriven/repro.sh first"; exit 1; }
diff -q "$CM" "$REFCM" \
  || { echo "ERROR: workload differs from expA_delaydriven -- default-center reuse not apples-to-apples"; exit 1; }

echo "== guard: reused default-center baselines present =="
for tag in expA_prism expA_reps; do for f in 0 8; do for s in $SEEDS; do
  bf="$DC/prism_eval/expA_delaydriven/data/${tag}_f${f}_s${s}.flow.txt"
  [ -f "$bf" ] || { echo "ERROR: missing reused baseline $bf -- run expA_delaydriven/repro.sh first"; exit 1; }
done; done; done

echo "== Knob 1/3: T_spray {$TSLIST} x failed {0,8} x 5 seeds (Prism) =="
for v in $TSLIST; do for f in 0 8; do for s in $SEEDS; do
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD -prism_t_spray $v" \
    bash "$COMMON/run_lib.sh" prism reps "$f" "$TOPO" "$s" "$CM" flow "expSens_tspray_prism_ts${v}_f${f}_s${s}" "$OUT"
done; done; done

echo "== Knob 2/3: T_cc {$QLIST} x failed {0,8} x 5 seeds (Prism AND REPS+NSCC reference) =="
for v in $QLIST; do for f in 0 8; do for s in $SEEDS; do
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD -target_q_delay $v" \
    bash "$COMMON/run_lib.sh" prism reps "$f" "$TOPO" "$s" "$CM" flow "expSens_tcc_prism_q${v}_f${f}_s${s}" "$OUT"
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD -target_q_delay $v" \
    bash "$COMMON/run_lib.sh" nscc reps "$f" "$TOPO" "$s" "$CM" flow "expSens_tcc_reps_q${v}_f${f}_s${s}" "$OUT"
done; done; done

echo "== Knob 3/3: kappa {$KLIST} x failed {0,8} x 5 seeds (Prism) =="
for v in $KLIST; do for f in 0 8; do for s in $SEEDS; do
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD -prism_kappa $v" \
    bash "$COMMON/run_lib.sh" prism reps "$f" "$TOPO" "$s" "$CM" flow "expSens_kappa_prism_k${v}_f${f}_s${s}" "$OUT"
done; done; done

# Queuing-delay companion (figK3): re-run the f8 sweeps WITH PRISM_PATHRTT logging so we can extract
# end-to-end per-packet queuing delay (raw_rtt-base). Adds the path-RTT log only; the sim is
# unchanged (flow.txt identical). Default center (qd_default_f8) is shared by all three knobs.
echo "== queuing-delay companion (figK3): f8 sweeps with PRISM_PATHRTT =="
qd_run() {  # $1=tag  $2=extra_args
  for s in $SEEDS; do
    PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD $2" PRISM_PATHRTT="$OUT/$1_s${s}.pathrtt.csv" \
      bash "$COMMON/run_lib.sh" prism reps 8 "$TOPO" "$s" "$CM" flow "$1_s${s}" "$OUT"
  done
}
qd_run qd_default_f8 ""
for v in $TSLIST; do qd_run "qd_tspray_ts${v}_f8" "-prism_t_spray $v"; done
for v in $QLIST;  do qd_run "qd_tcc_q${v}_f8"     "-target_q_delay $v"; done
for v in $KLIST;  do qd_run "qd_kappa_k${v}_f8"   "-prism_kappa $v"; done

echo "== render figK_sensitivity + figK2 + figK3 + robustness table =="
python3 "$HERE/make_figs.py" --render
echo "== done: figs/figK_sensitivity.* figK2_kappa_tradeoff.* figK3_*.* =="
