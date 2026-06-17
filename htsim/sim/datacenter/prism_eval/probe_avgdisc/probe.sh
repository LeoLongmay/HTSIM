#!/bin/bash
# READ-ONLY probe for proposal (b): generate PRISM f0 & f8 runs (2MB many2many, delay-driven) with
# PRISM_PATHRTT + PRISM_EPOCH logged, then run discriminator.py. NO controller change -- this only
# measures whether avg per-epoch delay separates f0 (transient) from f8 (structural) HOLD epochs.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../common" && pwd)"
DC="$(cd "$HERE/../.." && pwd)"
REL="prism_eval/probe_avgdisc"
cd "$DC"
[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first"; exit 1; }
mkdir -p "$REL/data"
TOPO=fat_tree_128_1os.topo; DD="-disable_trim"; ENDV="${EXP_END:-8}"
SEEDS="13 14 15"; FAILEDS="0 8"

echo "== selftest =="
python3 "$HERE/discriminator.py" --selftest

echo "== workload (many2many 64->16 pod0, 2MB; matches the f0 cost condition) =="
python3 "$COMMON/gen/many2many.py" "$REL/data/m2m.cm" 64 16 pairs 2000000 128 16
CM="$REL/data/m2m.cm"; OUT="$REL/data"

echo "== PRISM runs failed{0,8} x seeds{13,14,15} with PATHRTT+EPOCH =="
for f in $FAILEDS; do for s in $SEEDS; do
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" \
    PRISM_PATHRTT="$OUT/probe_prism_f${f}_s${s}.pathrtt.csv" \
    PRISM_EPOCH="$OUT/probe_prism_f${f}_s${s}.epoch.csv" \
    bash "$COMMON/run_lib.sh" prism reps "$f" "$TOPO" "$s" "$CM" flow,sink "probe_prism_f${f}_s${s}" "$OUT"
done; done

echo "== analyze (verdict + figP) =="
python3 "$HERE/discriminator.py"
