#!/bin/bash
# ρ-gate validation: PRISM (reps spray) on the byte-identical expA_delaydriven workload
# (many2many 64->16 pod0, 2MB), delay-driven, failed{0,8} x rho{0,3,5,8} x seed{13..17}.
# rho=0 = regression replica of today's PRISM. Rides run_lib.sh via EXTRA_ARGS; run_lib unchanged.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../common" && pwd)"
DC="$(cd "$HERE/../.." && pwd)"
REL="prism_eval/expA_f0_diagnosis"
cd "$DC"
[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first"; exit 1; }
mkdir -p "$REL/data"
SEEDS="13 14 15 16 17"; FAILEDS="0 8"; RHOS="0 3 5 8"
TOPO=fat_tree_128_1os.topo; DD="-disable_trim"; ENDV="${EXP_END:-8}"
OUT="$REL/data"

echo "== selftests gate the run (decide_region rho-gate + common metrics) =="
( cd "$DC/.." && g++ -I. datacenter/prism_eval/common/tests/test_prism_decompose.cpp -o /tmp/test_prism_dec && /tmp/test_prism_dec )
( cd "$COMMON/tests" && python3 test_metrics.py >/dev/null && echo "ok common metrics selftest" )

echo "== generate byte-identical workload (many2many 64->16 pod0, 2MB) =="
python3 "$COMMON/gen/many2many.py" "$OUT/m2m.cm" 64 16 pairs 2000000 128 16
CM="$OUT/m2m.cm"

echo "== sweep: failed{0,8} x rho{0,3,5,8} x 5 seeds (40 runs) =="
for rho in $RHOS; do for f in $FAILEDS; do for s in $SEEDS; do
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD -prism_spread_ratio $rho" \
    bash "$COMMON/run_lib.sh" prism reps "$f" "$TOPO" "$s" "$CM" flow "rgate_rho${rho}_f${f}_s${s}" "$OUT"
done; done; done

echo "== summary =="
python3 "$HERE/ratio_gate_summary.py"
