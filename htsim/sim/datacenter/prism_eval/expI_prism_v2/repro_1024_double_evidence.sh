#!/usr/bin/env bash
# Predeclared 1024-node many2many failure sweep: four arms x five failures x five seeds.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
COMMON=$(cd "$HERE/../common" && pwd)
DC=$(cd "$HERE/../.." && pwd)
REL="prism_eval/expI_prism_v2"
DATA_REL="$REL/data/double_evidence"
cd "$DC"

DRYRUN=${DRYRUN:-0}
if [ "${END_MS+x}" = x ] && [ "$END_MS" != 8 ]; then
  echo "ERROR: END_MS must be 8 for the predeclared double-evidence sweep" >&2
  exit 1
fi
END_MS=8
FAILURES="0 8 16 24 32"
SEEDS="13 14 15 16 17"
TOPO=fat_tree_1024.topo
CM="$DATA_REL/m2m256.cm"
DD="-disable_trim"
V2="$DD -prism_smooth_beta 0.3 -prism_hysteresis 0.25 -prism_engage_spread 28 -prism_disengage_spread 20"

[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first" >&2; exit 1; }

if [ "$DRYRUN" = 1 ]; then
  echo "python3 $COMMON/gen/many2many.py $CM 256 64 pairs 2000000 1024 64"
else
  mkdir -p "$DATA_REL"
  rm -f "$DATA_REL"/*.dat "$DATA_REL"/*.flow.txt "$DATA_REL"/*.epoch.csv \
    "$DATA_REL"/*.stdout "$DATA_REL"/*.idmap "$CM"
  python3 "$COMMON/gen/many2many.py" "$CM" 256 64 pairs 2000000 1024 64
fi

run_one() {
  local token=$1 cc=$2 lb=$3 extra=$4 failed=$5 seed=$6
  local tag="double_${token}_f${failed}_s${seed}"
  local flow="$DATA_REL/${tag}.flow.txt"
  local epoch="$DATA_REL/double_v2_f${failed}_s${seed}.epoch.csv"
  local command

  if [ "$token" = v2 ]; then
    command="PRISM_EPOCH=$epoch PATHS=8 NODES=1024 END_MS=$END_MS EXTRA_ARGS=\"$extra\" bash $COMMON/run_lib.sh $cc $lb $failed $TOPO $seed $CM flow $tag $DATA_REL"
  else
    command="PATHS=8 NODES=1024 END_MS=$END_MS EXTRA_ARGS=\"$extra\" bash $COMMON/run_lib.sh $cc $lb $failed $TOPO $seed $CM flow $tag $DATA_REL"
  fi
  echo "$command"

  if [ "$DRYRUN" = 1 ]; then
    return
  fi

  if [ "$token" = v2 ]; then
    PRISM_EPOCH="$epoch" PATHS=8 NODES=1024 END_MS="$END_MS" EXTRA_ARGS="$extra" \
      bash "$COMMON/run_lib.sh" "$cc" "$lb" "$failed" "$TOPO" "$seed" "$CM" flow "$tag" "$DATA_REL"
    test -s "$epoch"
  else
    PATHS=8 NODES=1024 END_MS="$END_MS" EXTRA_ARGS="$extra" \
      bash "$COMMON/run_lib.sh" "$cc" "$lb" "$failed" "$TOPO" "$seed" "$CM" flow "$tag" "$DATA_REL"
  fi
  test -s "$flow"
}

for failed in $FAILURES; do
  for seed in $SEEDS; do
    run_one ops    nscc   oblivious "$DD" "$failed" "$seed"
    run_one reps   nscc   reps      "$DD" "$failed" "$seed"
    run_one strack strack reps      "$DD" "$failed" "$seed"
    run_one v2     prism  reps      "$V2" "$failed" "$seed"
  done
done

RENDER=(
  python3 "$HERE/make_1024_ack_qdelay_cdf.py"
  --sweep-data-dir "$DATA_REL"
  --figs-dir "$REL/figs"
  --failures $FAILURES
  --seeds $SEEDS
)

if [ "$DRYRUN" = 1 ]; then
  echo "${RENDER[*]}"
  exit 0
fi

for failed in $FAILURES; do
  for seed in $SEEDS; do
    for token in ops reps strack v2; do
      flow="$DATA_REL/double_${token}_f${failed}_s${seed}.flow.txt"
      FLOW="$flow" ARM="$token" FAILED="$failed" SEED="$seed" \
        PYTHONPATH="$COMMON" python3 -c '
import math
import os
import sys

import metrics

raw = metrics.fct_stats(os.environ["FLOW"])["completion_rate"]
arm = os.environ["ARM"]
failed = os.environ["FAILED"]
seed = os.environ["SEED"]
try:
    completion_rate = float(raw)
except (TypeError, ValueError):
    valid = False
else:
    valid = math.isfinite(completion_rate) and completion_rate >= 0.999
if not valid:
    print(
        f"ERROR: invalid completion rate {raw} for arm={arm} "
        f"failed={failed} seed={seed} "
        "(require finite value >= 0.999)",
        file=sys.stderr,
    )
    raise SystemExit(1)
'
    done
  done
done

"${RENDER[@]}"
echo "done: $REL/figs/figI_1024_{failure_sweep,f32_fct_cdf,v2_engagement_sweep}.{png,pdf}"
