#!/usr/bin/env bash
# Small lossless/PFC calibration: isolate REPS implementation and Prism LB effects.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../common" && pwd)"
DC="$(cd "$HERE/../.." && pwd)"
REL="prism_eval/expL_laps_lossless"
OUT="$REL/data/calibration"
TOPO="fat_tree_128_1os.topo"
SEEDS=(13 14 15 16 17)
FAILEDS=(0 8)
ARMS=(ops reps_legacy reps_actual prism_legacy prism_actual)
LOSSLESS_ARGS="-queue_type lossless_input -queue_size_bytes 150000 -pfc_high_bytes 122880 -pfc_low_bytes 92160 -shared_buffer_bytes 33554432"
END_MS="${END_MS:-80}"

usage() {
  echo "usage: END_MS=<ms> $0 [--dry-run]" >&2
}

dry_run=false
for arg in "$@"; do
  case "$arg" in
    --dry-run) dry_run=true ;;
    *) usage; exit 2 ;;
  esac
done

arm_config() {
  case "$1" in
    ops)          printf '%s|%s|%s' nscc oblivious '' ;;
    reps_legacy)  printf '%s|%s|%s' nscc reps '' ;;
    reps_actual)  printf '%s|%s|%s' nscc reps_actual '' ;;
    prism_legacy) printf '%s|%s|%s' prism reps '' ;;
    prism_actual) printf '%s|%s|%s' prism reps_actual '-prism_coordination_mode original_prism' ;;
    *) echo "unknown calibration arm: $1" >&2; exit 2 ;;
  esac
}

emit_cell() {
  local arm="$1" failed="$2" seed="$3" cc lb extra
  IFS='|' read -r cc lb extra <<<"$(arm_config "$arm")"
  printf "PATHS=8 END_MS=%s EXTRA_ARGS='%s %s' bash %s %s %s %s %s %s %s flow expLc_%s_f%s_s%s %s\n" \
    "$END_MS" "$LOSSLESS_ARGS" "$extra" "$COMMON/run_lib.sh" "$cc" "$lb" "$failed" "$TOPO" "$seed" \
    "$OUT/m2m.cm" "$arm" "$failed" "$seed" "$OUT"
}

if "$dry_run"; then
  for failed in "${FAILEDS[@]}"; do
    for seed in "${SEEDS[@]}"; do
      for arm in "${ARMS[@]}"; do
        emit_cell "$arm" "$failed" "$seed"
      done
    done
  done
  exit 0
fi

cd "$DC"
BIN="$DC/../build/datacenter/htsim_uec"
[ -x "$BIN" ] || { echo "ERROR: $BIN missing -- build it first" >&2; exit 1; }
mkdir -p "$OUT"
python3 "$COMMON/gen/many2many.py" "$OUT/m2m.cm" 64 16 pairs 2000000 128 16

for failed in "${FAILEDS[@]}"; do
  for seed in "${SEEDS[@]}"; do
    for arm in "${ARMS[@]}"; do
      IFS='|' read -r cc lb extra <<<"$(arm_config "$arm")"
      PATHS=8 END_MS="$END_MS" EXTRA_ARGS="$LOSSLESS_ARGS $extra" \
        bash "$COMMON/run_lib.sh" "$cc" "$lb" "$failed" "$TOPO" "$seed" "$OUT/m2m.cm" \
          flow "expLc_${arm}_f${failed}_s${seed}" "$OUT"
    done
  done
done
