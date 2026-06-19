#!/bin/bash
# f0 (symmetric) penalty diagnosis -- delay-driven regime. READ-ONLY: no controller change.
# Reuses ../expA_delaydriven/data for the kappa=1.0 default arm, the REPS+NSCC reference, and the
# failed=8 PRISM epoch log (contrast). Run expA_delaydriven/repro.sh first if that data is absent.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../common" && pwd)"
DELAY="$(cd "$HERE/../expA_delaydriven" && pwd)"
DC="$(cd "$HERE/../.." && pwd)"
cd "$DC"
[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first"; exit 1; }

REL="prism_eval/expA_f0_diagnosis"; OUT="$REL/data"; mkdir -p "$OUT" "$REL/figs"
DELAY_REL="prism_eval/expA_delaydriven/data"
# reused read-only: kappa=1.0 ref + REPS ref (f0/f8 perf) and the failed=8 mechanism logs (f8 contrast).
need="$DELAY_REL/expA_reps_f0_s13.flow.txt $DELAY_REL/expA_prism_f0_s13.flow.txt \
$DELAY_REL/expA_reps_f8_s13.flow.txt $DELAY_REL/expA_prism_f8_s13.flow.txt \
$DELAY_REL/expA_prism_mech.epoch.csv $DELAY_REL/expA_prism_mech.pathrtt.csv $DELAY_REL/expA_reps_mech.pathrtt.csv"
for fpath in $need; do
  [ -f "$fpath" ] || { echo "ERROR: missing $fpath -- run prism_eval/expA_delaydriven/repro.sh first (this group reuses it)"; exit 1; }
done

echo "== self-test analysis =="
python3 "$HERE/diagnose.py" --selftest

# Byte-identical workload to expA_delaydriven (reuse if present, else regenerate).
CM="$DELAY_REL/m2m.cm"
[ -f "$CM" ] || python3 "$COMMON/gen/many2many.py" "$CM" 64 16 pairs 2000000 128 16

echo "== f0 mechanism logs: PRISM (pathrtt+epoch) and REPS+NSCC (pathrtt), seed 13 =="
PATHS=8 END_MS=8 EXTRA_ARGS="-disable_trim" \
  PRISM_PATHRTT="$OUT/f0_prism.pathrtt.csv" PRISM_EPOCH="$OUT/f0_prism.epoch.csv" \
  bash "$COMMON/run_lib.sh" prism reps 0 fat_tree_128_1os.topo 13 "$CM" flow f0_prism "$OUT"
PATHS=8 END_MS=8 EXTRA_ARGS="-disable_trim" \
  PRISM_PATHRTT="$OUT/f0_reps.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" nscc reps 0 fat_tree_128_1os.topo 13 "$CM" flow f0_reps "$OUT"

echo "== kappa sweep: kappa{0.25,0.5} x failed{0,8} x seeds{13..17} (kappa=1.0 reused from expA_delaydriven) =="
for k in 0.25 0.5; do for f in 0 8; do for s in 13 14 15 16 17; do
  PATHS=8 END_MS=8 EXTRA_ARGS="-disable_trim -prism_kappa $k" \
    bash "$COMMON/run_lib.sh" prism reps "$f" fat_tree_128_1os.topo "$s" "$CM" flow "kap${k}_f${f}_s${s}" "$OUT"
done; done; done

echo "== analyze + render figD1_undergrowth, figD2_kappa =="
python3 "$HERE/diagnose.py"
echo "== done =="
