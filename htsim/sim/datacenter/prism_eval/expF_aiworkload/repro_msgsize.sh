#!/bin/bash
# expF AI-ring message-size sweep: seven ExpF arms at failed=8, without touching expF_* data or figs.
# Override calibration axes with SIZES="..." and SEEDS="...".
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../common" && pwd)"
DC="$(cd "$HERE/../.." && pwd)"
REL="prism_eval/expF_aiworkload"
cd "$DC"

[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first"; exit 1; }
mkdir -p "$REL/data"

SIZES="${SIZES:-16384 65536 262144 1048576 4194304}"
SEEDS="${SEEDS:-13 14 15 16 17}"
OUT="$REL/data"
FAILED=8
DD="-disable_trim"
ARMS_CC=(nscc nscc prism strack mnscc swift mswift)
ARMS_LB=(oblivious reps reps reps reps reps reps)
ARMS_TAG=(ops reps prism strack mnscc swift mswift)

end_ms() { # size -> conservative 4x serialized ring drain at 100 Gb/s, at least ExpF's 8 ms
  python3 -c "import math; print(max(8, math.ceil(4 * 127 * $1 * 8 / 1e11 * 1000)))"
}

run_arms() { # size seed cm
  local sz="$1" s="$2" cm="$3" i tag epoch endv
  endv="$(end_ms "$sz")"
  for i in "${!ARMS_TAG[@]}"; do
    tag="expFmsg_${ARMS_TAG[$i]}_sz${sz}_s${s}"
    epoch=""
    [ "${ARMS_TAG[$i]}" = prism ] && epoch="PRISM_EPOCH=$OUT/${tag}.epoch.csv"
    env $epoch PATHS=8 NODES=128 END_MS="$endv" EXTRA_ARGS="$DD" \
      bash "$COMMON/run_lib.sh" "${ARMS_CC[$i]}" "${ARMS_LB[$i]}" "$FAILED" \
           fat_tree_128_1os.topo "$s" "$cm" flow "$tag" "$OUT"
  done
}

echo "== ExpF AI-ring message-size sweep: failed=$FAILED, sizes={$SIZES}, seeds={$SEEDS} =="
for sz in $SIZES; do
  for s in $SEEDS; do
    cm="$OUT/ai_ring_sz${sz}_s${s}.cm"
    python3 "$COMMON/gen/ai_ring.py" "$cm" 128 16 8 8 "$sz" "$s"
    run_arms "$sz" "$s" "$cm"
  done
done

echo "== done: expFmsg_<arm>_sz<size>_s<seed>.flow.txt =="
