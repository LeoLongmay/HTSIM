#!/bin/bash
# expG2_msgsize: STrack/MSwift-style collective CCT-slowdown vs per-flow message size, fixed -failed 8.
# A2A (parallel=32) + Butterfly, 128-node fat_tree_128_1os (100G), delay-driven, flow-only logging.
# END_MS scales with message size (A2A is NIC-bound). Metric = CCT slowdown (makespan / zero-queue LB).
#   bash repro.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../common" && pwd)"
DC="$(cd "$HERE/../.." && pwd)"
REL="prism_eval/expG2_msgsize"
cd "$DC"
[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first"; exit 1; }
mkdir -p "$REL/data"
SEEDS="13 14 15 16 17"
DD="-disable_trim"
FAILED=8
SIZES="16384 65536 262144 1048576 4194304"
PAR=32
OUT="$REL/data"
ARMS_CC=(nscc nscc prism strack mnscc swift mswift)
ARMS_LB=(oblivious reps reps reps reps reps reps)
ARMS_TAG=(ops reps prism strack mnscc swift mswift)
COLLS="a2a bfly"

echo "== self-test analysis =="
python3 "$HERE/make_figs.py" --selftest
( cd "$COMMON/tests" && python3 test_metrics.py >/dev/null && python3 test_generators.py >/dev/null \
  && echo "ok common selftests" )

gen_cm() { # coll size seed outfile
  case "$1" in
    a2a)  python3 "$COMMON/gen/coll_alltoall.py"  "$4" 128 128 "$PAR" "$2" "$3";;
    bfly) python3 "$COMMON/gen/coll_butterfly.py" "$4" 128 128 "$2" "$3";;
  esac
}

end_ms() { # size -> END_MS = max(20, ceil(4 * 127 * size * 8 / 1e11 * 1000))
  python3 -c "import math;print(max(20,math.ceil(4*127*$1*8/1e11*1000)))"
}

run_arm() { # coll size failed seed cm
  local coll="$1" sz="$2" f="$3" s="$4" cm="$5" i tag epoch endv
  endv="$(end_ms "$sz")"
  for i in "${!ARMS_TAG[@]}"; do
    tag="expG2${coll}_${ARMS_TAG[$i]}_sz${sz}_s${s}"
    epoch=""
    [ "${ARMS_TAG[$i]}" = prism ] && epoch="PRISM_EPOCH=$OUT/${tag}.epoch.csv"
    env $epoch PATHS=8 NODES=128 END_MS="$endv" EXTRA_ARGS="$DD" \
      bash "$COMMON/run_lib.sh" "${ARMS_CC[$i]}" "${ARMS_LB[$i]}" "$f" \
           fat_tree_128_1os.topo "$s" "$cm" flow "$tag" "$OUT"
  done
}

for coll in $COLLS; do
  for sz in $SIZES; do
    echo "== gen $coll sz$sz .cm (per seed) =="
    for s in $SEEDS; do gen_cm "$coll" "$sz" "$s" "$OUT/${coll}_sz${sz}_s${s}.cm"; done
  done
  echo "== sweep: $coll x size{$SIZES} x failed$FAILED x 7 arms x 5 seeds =="
  for sz in $SIZES; do for s in $SEEDS; do
    run_arm "$coll" "$sz" "$FAILED" "$s" "$OUT/${coll}_sz${sz}_s${s}.cm"
  done; done
done

echo "== render figH_a2a_msgsize / figH_bfly_msgsize / figH_legend =="
python3 "$HERE/make_figs.py"
echo "== done: figs/figH_a2a_msgsize.* figs/figH_bfly_msgsize.* figs/figH_legend.* =="
