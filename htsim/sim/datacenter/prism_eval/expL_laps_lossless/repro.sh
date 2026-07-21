#!/usr/bin/env bash
# Four-arm lossless/PFC preview.  ExpA remains an independent delay-driven experiment.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../common" && pwd)"
DC="$(cd "$HERE/../.." && pwd)"
REL="prism_eval/expL_laps_lossless"
OUT="$REL/data"
TOPO="fat_tree_128_1os.topo"
SEEDS=(13 14 15 16 17)
FAILEDS=(0 2 4 6 8 10 12)
PREVIEW=(ops reps laps prism)
ALL=(ops reps swift mswift mnscc strack laps prism)
LOSSLESS_ARGS="-queue_type lossless_input -queue_size_bytes 150000 -pfc_high_bytes 122880 -pfc_low_bytes 92160 -shared_buffer_bytes 33554432"
END_MS="${END_MS:-80}"

usage() {
  echo "usage: END_MS=<ms> $0 [--all-baselines] [--dry-run]" >&2
}

all_baselines=false
dry_run=false
for arg in "$@"; do
  case "$arg" in
    --all-baselines) all_baselines=true ;;
    --dry-run) dry_run=true ;;
    *) usage; exit 2 ;;
  esac
done

if "$all_baselines"; then
  BASELINES=("${ALL[@]}")
else
  BASELINES=("${PREVIEW[@]}")
fi

arm_config() {
  case "$1" in
    ops) printf '%s %s' nscc oblivious ;;
    reps) printf '%s %s' nscc reps ;;
    laps) printf '%s %s' laps laps ;;
    prism) printf '%s %s' prism reps ;;
    swift) printf '%s %s' swift reps ;;
    mswift) printf '%s %s' mswift reps ;;
    mnscc) printf '%s %s' mnscc reps ;;
    strack) printf '%s %s' strack reps ;;
    *) echo "unknown baseline: $1" >&2; exit 2 ;;
  esac
}

emit_cell() {
  local arm="$1" failed="$2" seed="$3" cc lb
  read -r cc lb <<<"$(arm_config "$arm")"
  printf "PATHS=8 END_MS=%s EXTRA_ARGS='%s' bash %s %s %s %s %s %s %s flow expL_%s_f%s_s%s %s\n" \
    "$END_MS" "$LOSSLESS_ARGS" "$COMMON/run_lib.sh" "$cc" "$lb" "$failed" "$TOPO" "$seed" \
    "$OUT/m2m.cm" "$arm" "$failed" "$seed" "$OUT"
}

if "$dry_run"; then
  for failed in "${FAILEDS[@]}"; do
    for seed in "${SEEDS[@]}"; do
      for arm in "${BASELINES[@]}"; do
        emit_cell "$arm" "$failed" "$seed"
      done
    done
  done
  exit 0
fi

cd "$DC"
[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first" >&2; exit 1; }
mkdir -p "$OUT"
python3 "$COMMON/gen/many2many.py" "$OUT/m2m.cm" 64 16 pairs 2000000 128 16

for failed in "${FAILEDS[@]}"; do
  for seed in "${SEEDS[@]}"; do
    for arm in "${BASELINES[@]}"; do
      read -r cc lb <<<"$(arm_config "$arm")"
      PATHS=8 END_MS="$END_MS" EXTRA_ARGS="$LOSSLESS_ARGS" \
        bash "$COMMON/run_lib.sh" "$cc" "$lb" "$failed" "$TOPO" "$seed" "$OUT/m2m.cm" \
          flow "expL_${arm}_f${failed}_s${seed}" "$OUT"
    done
  done
done
