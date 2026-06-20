#!/bin/bash
# Scheme A (spread-persistence) validation: PRISM (reps spray) on the byte-identical expA_delaydriven
# workload (many2many 64->16 pod0, 2MB), delay-driven, failed{0,8}. Configs: delta=0 baseline (today's
# PRISM) + delta{0.5,1.0} x beta{1/16,1/64}. Rides run_lib.sh via EXTRA_ARGS; run_lib unchanged.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../common" && pwd)"
DC="$(cd "$HERE/../.." && pwd)"
cd "$DC"
[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first"; exit 1; }
REL="prism_eval/expA_f0_diagnosis"; OUT="$REL/data"; mkdir -p "$OUT"
SEEDS="13 14 15 16 17"; FAILEDS="0 8"
DELTAS="0.5 1.0"; BETAS="0.0625 0.015625"   # beta 1/16, 1/64 (bracket the 1/32 default)
TOPO=fat_tree_128_1os.topo; DD="-disable_trim"; ENDV="${EXP_END:-8}"

echo "== selftests gate the run =="
( cd "$DC/.." && g++ -I. datacenter/prism_eval/common/tests/test_prism_decompose.cpp -o /tmp/test_prism_dec && /tmp/test_prism_dec )
( cd "$COMMON/tests" && python3 test_metrics.py >/dev/null && echo "ok common metrics selftest" )

echo "== generate byte-identical workload (many2many 64->16 pod0, 2MB) =="
python3 "$COMMON/gen/many2many.py" "$OUT/m2m.cm" 64 16 pairs 2000000 128 16
CM="$OUT/m2m.cm"

echo "== delta=0 baseline (today's PRISM) x failed{0,8} x 5 seeds =="
for f in $FAILEDS; do for s in $SEEDS; do
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD -prism_spread_persist 0" \
    bash "$COMMON/run_lib.sh" prism reps "$f" "$TOPO" "$s" "$CM" flow "persist_d0_b0_f${f}_s${s}" "$OUT"
done; done

echo "== delta{0.5,1.0} x beta{1/16,1/64} x failed{0,8} x 5 seeds =="
for d in $DELTAS; do for b in $BETAS; do for f in $FAILEDS; do for s in $SEEDS; do
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD -prism_spread_persist $d -prism_spread_persist_beta $b" \
    bash "$COMMON/run_lib.sh" prism reps "$f" "$TOPO" "$s" "$CM" flow "persist_d${d}_b${b}_f${f}_s${s}" "$OUT"
done; done; done; done

echo "== summary =="
python3 "$HERE/persist_summary.py"
