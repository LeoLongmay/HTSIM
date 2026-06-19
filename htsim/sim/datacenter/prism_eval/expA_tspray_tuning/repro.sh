#!/bin/bash
# PRISM T_spray tuning (delay-driven regime). Stage 1 always; Stage 2 when TS_STAR is set.
# Sweeps the EXISTING -prism_t_spray knob via run_lib.sh EXTRA_ARGS -- no controller code change.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../common" && pwd)"
DC="$(cd "$HERE/../.." && pwd)"
REL="prism_eval/expA_tspray_tuning"
cd "$DC"
[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first"; exit 1; }
mkdir -p "$REL/data"
SEEDS="13 14 15 16 17"; TSLIST="2 3 4 6 9 14"; TOPO=fat_tree_128_1os.topo
DD="-disable_trim"   # delay-driven knob
ENDV="${EXP_END:-8}"

echo "== self-tests =="
python3 "$HERE/tspray_select.py" --selftest
python3 "$HERE/make_figs.py" --selftest
( cd "$COMMON/tests" && python3 test_metrics.py >/dev/null && echo "ok common metrics selftest" )

echo "== generate workload (many2many 64->16 pod0, 2MB; same args as expA_delaydriven => identical) =="
python3 "$COMMON/gen/many2many.py" "$REL/data/m2m.cm" 64 16 pairs 2000000 128 16
CM="$REL/data/m2m.cm"; OUT="$REL/data"
# Guard: compares against the committed delay-driven workload to ensure Stage-2 baseline reuse is apples-to-apples.
if [ -f "$DC/prism_eval/expA_delaydriven/data/m2m.cm" ]; then
  diff -q "$CM" "$DC/prism_eval/expA_delaydriven/data/m2m.cm" \
    || { echo "ERROR: workload differs from expA_delaydriven -- Stage-2 reuse would not be apples-to-apples"; exit 1; }
fi

# Stage 1 sweeps only the endpoints (f0 = symmetric cost, f8 = asymmetric win) to find the knee cheaply;
# Stage 2 validates the chosen T_spray* over the full failed grid {0,2,4,8,12}.
echo "== Stage 1: T_spray {$(echo $TSLIST)} x failed {0,8} x 5 seeds =="
for ts in $TSLIST; do for f in 0 8; do for s in $SEEDS; do
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD -prism_t_spray $ts" \
    bash "$COMMON/run_lib.sh" prism reps "$f" "$TOPO" "$s" "$CM" flow "tsweep_ts${ts}_f${f}_s${s}" "$OUT"
done; done; done

echo "== Stage 1 analysis (knee fig + criterion + T_spray*) =="
python3 "$HERE/make_figs.py" --stage1

if [ -n "${TS_STAR:-}" ]; then
  echo "== Stage 2: validate PRISM at T_spray=$TS_STAR over failed {0,2,4,8,12} x 5 seeds =="
  for f in 0 2 4 8 12; do for s in $SEEDS; do
    PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD -prism_t_spray $TS_STAR" \
      bash "$COMMON/run_lib.sh" prism reps "$f" "$TOPO" "$s" "$CM" flow "tsval_f${f}_s${s}" "$OUT"
  done; done
  echo "== Stage 2 figure (figT2_compare) =="
  python3 "$HERE/make_figs.py" --stage2 --ts-star "$TS_STAR"
  echo "== done: figs/figT1_knee.* figs/figT2_compare.* =="
else
  echo "TS_STAR unset -> Stage 2 skipped. Pick T_spray* from the Stage-1 table above, then run:"
  echo "    TS_STAR=<us> bash $REL/repro.sh"
  echo "== done: figs/figT1_knee.* =="
fi
