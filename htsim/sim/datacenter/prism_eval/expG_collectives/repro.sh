#!/bin/bash
# expG_collectives: STrack-style AI collectives (A2A / Ring-AR / Butterfly-AR) x failed-links.
# Full multi-step collectives with inter-step barriers; metric = collective makespan (ms).
# 128-node fat_tree_128_1os (our 100G/COMPOSITE fabric), delay-driven, flow-only logging.
#   bash repro.sh            # full sweep + render
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../common" && pwd)"
DC="$(cd "$HERE/../.." && pwd)"
REL="prism_eval/expG_collectives"
cd "$DC"
[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first"; exit 1; }
mkdir -p "$REL/data"
SEEDS="13 14 15 16 17"
DD="-disable_trim"
ENDV="${EXP_END:-20}"
OUT="$REL/data"
FAILED="0 4 8 12"
SIZE=131072
PAR=32
ARMS_CC=(nscc nscc prism strack mnscc swift mswift)
ARMS_LB=(oblivious reps reps reps reps reps reps)
ARMS_TAG=(ops reps prism strack mnscc swift mswift)
# collective tag -> generator command (per seed cm written to $OUT/<coll>_s<seed>.cm)
COLLS="a2a ring bfly"

echo "== self-test analysis =="
python3 "$HERE/make_figs.py" --selftest
( cd "$COMMON/tests" && python3 test_metrics.py >/dev/null && python3 test_generators.py >/dev/null \
  && echo "ok common selftests" )

gen_cm() { # coll seed outfile
  case "$1" in
    a2a)  python3 "$COMMON/gen/coll_alltoall.py"  "$3" 128 128 "$PAR" "$SIZE" "$2";;
    ring) python3 "$COMMON/gen/coll_ring.py"      "$3" 128 128 "$SIZE" "$2";;
    bfly) python3 "$COMMON/gen/coll_butterfly.py" "$3" 128 128 "$SIZE" "$2";;
  esac
}

run_arm() { # coll failed seed cm
  local coll="$1" f="$2" s="$3" cm="$4" i tag epoch
  for i in "${!ARMS_TAG[@]}"; do
    tag="expG${coll}_${ARMS_TAG[$i]}_f${f}_s${s}"
    epoch=""
    [ "${ARMS_TAG[$i]}" = prism ] && epoch="PRISM_EPOCH=$OUT/${tag}.epoch.csv"
    env $epoch PATHS=8 NODES=128 END_MS="$ENDV" EXTRA_ARGS="$DD" \
      bash "$COMMON/run_lib.sh" "${ARMS_CC[$i]}" "${ARMS_LB[$i]}" "$f" \
           fat_tree_128_1os.topo "$s" "$cm" flow "$tag" "$OUT"
  done
}

for coll in $COLLS; do
  echo "== gen per-seed $coll .cm =="
  for s in $SEEDS; do gen_cm "$coll" "$s" "$OUT/${coll}_s${s}.cm"; done
  echo "== sweep: $coll x failed{$FAILED} x 7 arms x 5 seeds =="
  for f in $FAILED; do for s in $SEEDS; do
    run_arm "$coll" "$f" "$s" "$OUT/${coll}_s${s}.cm"
  done; done
done

echo "== render figG_{a2a,ring,bfly} =="
python3 "$HERE/make_figs.py"
echo "== done: figs/figG_a2a.* figs/figG_ring.* figs/figG_bfly.* =="
