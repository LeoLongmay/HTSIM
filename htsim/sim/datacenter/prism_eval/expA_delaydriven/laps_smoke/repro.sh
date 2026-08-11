#!/usr/bin/env bash
# Isolated 24-cell ExpA comparison; strict LAPS only, no algorithm changes.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../../common" && pwd)"
DATA_DIR="${DATA_DIR:-$HERE/data}"
RUN_LIB="${RUN_LIB:-$COMMON/run_lib.sh}"
CM="$DATA_DIR/m2m.cm"
ARMS=("ops:nscc:oblivious" "reps:nscc:reps" "decmt:prism:reps" "laps:laps:laps")
FAILEDS=(0 8)
SEEDS=(13 14 15)
TOPO="fat_tree_128_1os.topo"

if [[ $# -gt 1 || ( $# -eq 1 && $1 != "--dry-run" ) ]]; then
    echo "usage: $0 [--dry-run]" >&2
    exit 2
fi
DRY_RUN=false
[[ ${1:-} == "--dry-run" ]] && DRY_RUN=true

emit_or_run() {
    local arm="$1" cc="$2" lb="$3" failed="$4" seed="$5"
    local tag="expA_smoke_${arm}_f${failed}_s${seed}"
    local cmd=(bash "$RUN_LIB" "$cc" "$lb" "$failed" "$TOPO" "$seed" "$CM" flow "$tag" "$DATA_DIR")
    if "$DRY_RUN"; then
        printf 'PATHS=8 END_MS=8 EXTRA_ARGS=-disable_trim '
        printf '%q ' "${cmd[@]}"
        printf '\n'
    else
        PATHS=8 END_MS=8 EXTRA_ARGS=-disable_trim "${cmd[@]}"
    fi
}

for spec in "${ARMS[@]}"; do
    IFS=: read -r arm cc lb <<<"$spec"
    for failed in "${FAILEDS[@]}"; do
        for seed in "${SEEDS[@]}"; do
            tag="expA_smoke_${arm}_f${failed}_s${seed}"
            if ! "$DRY_RUN" && [[ -e "$DATA_DIR/$tag.stdout" || -e "$DATA_DIR/$tag.flow.txt" || -e "$DATA_DIR/$tag.idmap" ]]; then
                echo "ERROR: refusing to overwrite existing smoke artifact: $tag" >&2
                exit 1
            fi
        done
    done
done

if ! "$DRY_RUN"; then
    mkdir -p "$DATA_DIR"
    python3 "$COMMON/gen/many2many.py" "$CM" 64 16 pairs 2000000 128 16
fi

for spec in "${ARMS[@]}"; do
    IFS=: read -r arm cc lb <<<"$spec"
    for failed in "${FAILEDS[@]}"; do
        for seed in "${SEEDS[@]}"; do
            emit_or_run "$arm" "$cc" "$lb" "$failed" "$seed"
        done
    done
done
