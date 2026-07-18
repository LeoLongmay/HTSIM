#!/usr/bin/env bash
# LAPS-only ExpA sweep. Existing artifacts are fail-closed unless --replace-laps is explicit.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
EXPERIMENT="$HERE"
COMMON="$(cd "$EXPERIMENT/../common" && pwd)"
DEFAULT_DATA_DIR="$EXPERIMENT/data"
DEFAULT_RUN_LIB="$COMMON/run_lib.sh"
DATA_DIR="${DATA_DIR:-$DEFAULT_DATA_DIR}"
RUN_LIB="${RUN_LIB:-$DEFAULT_RUN_LIB}"
FIGS_DIR="${FIGS_DIR:-$EXPERIMENT/figs}"
WORKLOAD="$DATA_DIR/m2m.cm"
RUN_LIB_DIR="$(cd "$(dirname "$RUN_LIB")" && pwd)"
DATACENTER_DIR="$(cd "$RUN_LIB_DIR/../.." && pwd)"
SHARED_IDMAP="$DATACENTER_DIR/idmap.txt"

SEEDS=(13 14 15 16 17)
FAILEDS=(0 2 4 6 8 10 12)
TOPOLOGY="fat_tree_128_1os.topo"

dry_run=false
replace_laps=false
case "$#:$*" in
  0:) ;;
  1:--dry-run) dry_run=true ;;
  1:--replace-laps) replace_laps=true ;;
  2:--replace-laps\ --dry-run) replace_laps=true; dry_run=true ;;
  *)
    echo "usage: $0 [--dry-run|--replace-laps [--dry-run]]" >&2
    exit 2
    ;;
esac

print_run() {
  local failed="$1"
  local seed="$2"
  local tag="expA_laps_f${failed}_s${seed}"
  printf 'PATHS=8 END_MS=8 EXTRA_ARGS=-disable_trim bash %s laps laps %s %s %s %s flow %s %s\n' \
    "$RUN_LIB" "$failed" "$TOPOLOGY" "$seed" "$WORKLOAD" "$tag" "$DATA_DIR"
}

print_replacement_targets() {
  local failed seed tag suffix stem extension
  for failed in "${FAILEDS[@]}"; do
    for seed in "${SEEDS[@]}"; do
      tag="expA_laps_f${failed}_s${seed}"
      for suffix in flow.txt stdout idmap dat ascii.tmp; do
        printf 'LAPS replacement target: %s\n' "$DATA_DIR/$tag.$suffix"
      done
    done
  done
  for stem in figA1dd_goodput_laps figA1dd_avg_fct_laps figA1dd_p99_fct_laps figA1dd_legend_laps; do
    for extension in pdf png; do
      printf 'LAPS replacement target: %s\n' "$FIGS_DIR/$stem.$extension"
    done
  done
}

remove_replacement_targets() {
  local failed seed tag suffix stem extension
  print_replacement_targets
  for failed in "${FAILEDS[@]}"; do
    for seed in "${SEEDS[@]}"; do
      tag="expA_laps_f${failed}_s${seed}"
      for suffix in flow.txt stdout idmap dat ascii.tmp; do
        rm -f -- "$DATA_DIR/$tag.$suffix"
      done
    done
  done
  for stem in figA1dd_goodput_laps figA1dd_avg_fct_laps figA1dd_p99_fct_laps figA1dd_legend_laps; do
    for extension in pdf png; do
      rm -f -- "$FIGS_DIR/$stem.$extension"
    done
  done
}

if "$dry_run"; then
  if "$replace_laps"; then
    print_replacement_targets
  fi
  for failed in "${FAILEDS[@]}"; do
    for seed in "${SEEDS[@]}"; do
      print_run "$failed" "$seed"
    done
  done
  exit 0
fi

[ -f "$WORKLOAD" ] || {
  echo "ERROR: workload missing: $WORKLOAD" >&2
  exit 1
}
[ -f "$RUN_LIB" ] || {
  echo "ERROR: run library missing: $RUN_LIB" >&2
  exit 1
}

if ! "$replace_laps"; then
  for failed in "${FAILEDS[@]}"; do
    for seed in "${SEEDS[@]}"; do
      tag="expA_laps_f${failed}_s${seed}"
      # run_lib opens .dat before KEEPDAT decides whether to retain it.  Guard it
      # unconditionally, alongside every output that this flow-only invocation writes.
      for artifact in "$DATA_DIR/$tag.flow.txt" "$DATA_DIR/$tag.stdout" \
        "$DATA_DIR/$tag.idmap" "$DATA_DIR/$tag.dat" "$DATA_DIR/$tag.ascii.tmp"; do
        [ ! -e "$artifact" ] || {
          echo "ERROR: collision: refusing to overwrite $artifact" >&2
          exit 1
        }
      done
    done
  done
fi

idmap_existed=false
idmap_backup=""
if [ -e "$SHARED_IDMAP" ] || [ -L "$SHARED_IDMAP" ]; then
  [ -f "$SHARED_IDMAP" ] && [ ! -L "$SHARED_IDMAP" ] || {
    echo "ERROR: shared idmap is not a regular file: $SHARED_IDMAP" >&2
    exit 1
  }
  idmap_backup="$(mktemp "${TMPDIR:-/tmp}/repro_laps-idmap.XXXXXX")"
  if ! cp -- "$SHARED_IDMAP" "$idmap_backup"; then
    rm -f -- "$idmap_backup"
    echo "ERROR: could not back up shared idmap: $SHARED_IDMAP" >&2
    exit 1
  fi
  idmap_existed=true
fi

restore_shared_idmap() {
  local status="$1"
  trap - EXIT HUP INT TERM
  if "$idmap_existed"; then
    if ! cp -- "$idmap_backup" "$SHARED_IDMAP"; then
      echo "ERROR: could not restore shared idmap: $SHARED_IDMAP" >&2
      status=1
    fi
  elif ! rm -f -- "$SHARED_IDMAP"; then
    echo "ERROR: could not remove generated shared idmap: $SHARED_IDMAP" >&2
    status=1
  fi
  [ -z "$idmap_backup" ] || rm -f -- "$idmap_backup"
  exit "$status"
}

trap 'restore_shared_idmap $?' EXIT
trap 'restore_shared_idmap 129' HUP
trap 'restore_shared_idmap 130' INT
trap 'restore_shared_idmap 143' TERM

if "$replace_laps"; then
  remove_replacement_targets
fi

for failed in "${FAILEDS[@]}"; do
  for seed in "${SEEDS[@]}"; do
    tag="expA_laps_f${failed}_s${seed}"
    PATHS=8 END_MS=8 EXTRA_ARGS=-disable_trim \
      bash "$RUN_LIB" laps laps "$failed" "$TOPOLOGY" "$seed" "$WORKLOAD" flow "$tag" "$DATA_DIR"
  done
done
