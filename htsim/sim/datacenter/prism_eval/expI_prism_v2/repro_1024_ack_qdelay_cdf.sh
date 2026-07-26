#!/usr/bin/env bash
# 1024-node ACK-derived queueing-delay CDF: five equal-weight seeds.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
COMMON=$(cd "$HERE/../common" && pwd)
DC=$(cd "$HERE/../.." && pwd)
REL="prism_eval/expI_prism_v2"
FAILED=${FAILED:-16}
DATA_REL=${DATA_REL:-"$REL/data/ack_qdelay_1024"}
OUTPUT_STEM=${OUTPUT_STEM:-"$REL/figs/figI_1024_ack_qdelay_cdf"}
cd "$DC"

DRYRUN=${DRYRUN:-0}
END_MS=${END_MS:-8}
SEEDS="${SEEDS:-13 14 15 16 17}"
TOPO=fat_tree_1024.topo
CM="$DATA_REL/m2m256.cm"
DD="-disable_trim"
V2="$DD -prism_smooth_beta 0.3 -prism_hysteresis 0.25 -prism_engage_spread 28 -prism_disengage_spread 20"

[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first" >&2; exit 1; }

if [ "$DRYRUN" = 1 ]; then
  echo "python3 $COMMON/gen/many2many.py $DATA_REL/m2m256.cm 256 64 pairs 2000000 1024 64"
else
  mkdir -p "$DATA_REL"
  rm -f "$DATA_REL"/*.csv "$DATA_REL"/*.flow.txt "$DATA_REL"/*.stdout "$DATA_REL"/*.idmap
  python3 "$COMMON/gen/many2many.py" "$CM" 256 64 pairs 2000000 1024 64
fi

run_one() {
  local token=$1 cc=$2 lb=$3 extra=$4 seed=$5
  local tag="ackcdf_${token}_f${FAILED}_s${seed}"
  local trace="$DATA_REL/${token}_s${seed}.csv"
  local command="ACK_QDELAY=$trace PATHS=8 NODES=1024 END_MS=$END_MS EXTRA_ARGS=\"$extra\" bash $COMMON/run_lib.sh $cc $lb $FAILED $TOPO $seed $CM flow $tag $DATA_REL"
  echo "$command"
  if [ "$DRYRUN" != 1 ]; then
    ACK_QDELAY="$trace" PATHS=8 NODES=1024 END_MS="$END_MS" EXTRA_ARGS="$extra" \
      bash "$COMMON/run_lib.sh" "$cc" "$lb" "$FAILED" "$TOPO" "$seed" "$CM" flow "$tag" "$DATA_REL"
  fi
}

for seed in $SEEDS; do
  run_one ops    nscc   oblivious "$DD" "$seed"
  run_one reps   nscc   reps      "$DD" "$seed"
  run_one mnscc  mnscc  reps      "$DD" "$seed"
  run_one strack strack reps      "$DD" "$seed"
  run_one v2     prism  reps      "$V2" "$seed"
done

if [ "$DRYRUN" = 1 ]; then
  exit 0
fi

for token in ops reps mnscc strack v2; do
  for seed in $SEEDS; do
    flow="$DATA_REL/ackcdf_${token}_f${FAILED}_s${seed}.flow.txt"
    test -s "$flow"
    test -s "$DATA_REL/${token}_s${seed}.csv"
    cr=$(PYTHONPATH="$COMMON" python3 -c "import metrics; print(metrics.fct_stats('$flow')['completion_rate'])")
    awk -v cr="$cr" 'BEGIN { exit !(cr >= 0.999) }' || {
      echo "ERROR: completion rate $cr below 0.999 for $token seed $seed" >&2
      exit 1
    }
  done
done

python3 "$HERE/make_1024_ack_qdelay_cdf.py" \
  --data-dir "$DATA_REL" \
  --output-stem "$OUTPUT_STEM" \
  --simple-cdf --failure "$FAILED" \
  --seeds $SEEDS
echo "done: $OUTPUT_STEM.{png,pdf}"
