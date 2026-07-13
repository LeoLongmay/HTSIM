#!/bin/bash
# PRISM oracle validation: compare Prism's O(1) epoch estimator against a
# simulator-side read-only path oracle.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../common" && pwd)"
DC="$(cd "$HERE/../.." && pwd)"
REL="prism_eval/expJ_oracle_validation"
cd "$DC"

[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first"; exit 1; }
mkdir -p "$REL/data/raw" "$REL/figs"

MODE="${1:-smoke}"
ENDV="${EXP_END:-8}"
DD="-disable_trim"
OUT="$REL/data"
RAW="$OUT/raw"
CM="$OUT/m2m.cm"
export MPLCONFIGDIR="$OUT/mplconfig"
mkdir -p "$MPLCONFIGDIR"

# Never aggregate stale rows from the previous boundary-only oracle schema.
rm -f "$RAW"/*.oracle.csv

echo "== selftest =="
python3 "$HERE/make_figs.py" --selftest

echo "== workload (many2many 64->16 pod0, 2MB) =="
python3 "$COMMON/gen/many2many.py" "$CM" 64 16 pairs 2000000 128 16

run_one() {
  local scenario="$1" topo="$2" failed="$3" kappa="$4" nmin="$5" seed="$6"
  local tag="oracle_${scenario}_k${kappa}_n${nmin}_s${seed}"
  local raw="$RAW/${tag}.oracle.csv"
  PATHS=8 END_MS="$ENDV" \
    EXTRA_ARGS="$DD -prism_kappa $kappa -prism_n_min $nmin -enable_prism_oracle_validation 1 -prism_oracle_log $raw -prism_oracle_run_id $tag -prism_oracle_scenario $scenario" \
    bash "$COMMON/run_lib.sh" prism reps "$failed" "$topo" "$seed" "$CM" flow "$tag" "$OUT"
}

if [ "$MODE" = "smoke" ]; then
  echo "== smoke matrix: 3 scenarios x one parameter point x one seed =="
  run_one symmetric fat_tree_128_1os.topo 0 1 3 13
  run_one asymmetry fat_tree_128_1os.topo 8 1 3 13
  run_one mixed fat_tree_128_4os.topo 8 1 3 13
elif [ "$MODE" = "full" ]; then
  echo "== full matrix: 3 scenarios x 3 kappa x 3 n_min x 5 seeds =="
  SEEDS="13 14 15 16 17"
  KAPPAS="0.5 1 2"
  NMINS="1 3 6"
  for k in $KAPPAS; do for n in $NMINS; do for s in $SEEDS; do
    run_one symmetric fat_tree_128_1os.topo 0 "$k" "$n" "$s"
    run_one asymmetry fat_tree_128_1os.topo 8 "$k" "$n" "$s"
    run_one mixed fat_tree_128_4os.topo 8 "$k" "$n" "$s"
  done; done; done
else
  echo "usage: $0 [smoke|full]" >&2
  exit 2
fi

echo "== aggregate and render =="
python3 "$HERE/make_figs.py" --render
echo "== done: data/{summary,confusion,lead_lag}.csv figs/prism_oracle_validation.{png,pdf} =="
