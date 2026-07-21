#!/bin/bash
# expF_aiworkload: MSwift AI-training collective (Llama-70B HSDP ring single step) x failed-links.
# Tests whether PRISM's delay-driven asymmetric-fabric advantage carries to a realistic AI collective.
# 128-node fat_tree_128_1os (our 100G/COMPOSITE fabric), delay-driven, flow-only logging.
#   bash repro.sh            # full sweep + render
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../common" && pwd)"
DC="$(cd "$HERE/../.." && pwd)"
REL="prism_eval/expF_aiworkload"
cd "$DC"
[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first"; exit 1; }
mkdir -p "$REL/data"
SEEDS="13 14 15 16 17"
DD="-disable_trim"
ENDV="${EXP_END:-8}"
OUT="$REL/data"
FAILED="0 4 8 12"
SIZE=13697024
ARMS_CC=(nscc nscc prism strack mnscc swift mswift)
ARMS_LB=(oblivious reps reps reps reps reps reps)
ARMS_TAG=(ops reps prism strack mnscc swift mswift)

echo "== self-test analysis =="
python3 "$HERE/make_figs.py" --selftest
( cd "$COMMON/tests" && python3 test_metrics.py >/dev/null && python3 test_generators.py >/dev/null \
  && echo "ok common selftests" )

run_arm() { # failed seed cm
  local f="$1" s="$2" cm="$3" i tag epoch
  for i in "${!ARMS_TAG[@]}"; do
    tag="expF_${ARMS_TAG[$i]}_f${f}_s${s}"
    epoch=""
    [ "${ARMS_TAG[$i]}" = prism ] && epoch="PRISM_EPOCH=$OUT/${tag}.epoch.csv"
    env $epoch PATHS=8 NODES=128 END_MS="$ENDV" EXTRA_ARGS="$DD" \
      bash "$COMMON/run_lib.sh" "${ARMS_CC[$i]}" "${ARMS_LB[$i]}" "$f" \
           fat_tree_128_1os.topo "$s" "$cm" flow "$tag" "$OUT"
  done
}

echo "== gen per-seed AI ring .cm =="
for s in $SEEDS; do python3 "$COMMON/gen/ai_ring.py" "$OUT/ai_ring_s${s}.cm" 128 16 8 8 "$SIZE" "$s"; done

echo "== sweep: AI ring x failed{$FAILED} x 7 arms x 5 seeds = 140 runs =="
for f in $FAILED; do for s in $SEEDS; do
  run_arm "$f" "$s" "$OUT/ai_ring_s${s}.cm"
done; done

echo "== render figF1/figF2/figF4 =="
python3 "$HERE/make_figs.py"
echo "== done: figs/figF1_cct_bars.* figs/figF2_fct_cdf_f{0,8}.* figs/figF4_ai_decomp.* =="
