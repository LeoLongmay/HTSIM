#!/usr/bin/env bash
# Paired, opt-in strict-LAPS diagnostic run; never changes LAPS parameters.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../../common" && pwd)"
DATA_DIR="${DATA_DIR:-$HERE/data_diagnostics}"
RUN_LIB="${RUN_LIB:-$COMMON/run_lib.sh}"
CM="$DATA_DIR/m2m.cm"
TOPO="fat_tree_128_1os.topo"

[[ $# -le 1 && ${1:-} == "" || ${1:-} == "--dry-run" ]] || { echo "usage: $0 [--dry-run]" >&2; exit 2; }
DRY=false; [[ ${1:-} == "--dry-run" ]] && DRY=true

emit() {
    local label="$1" failed="$2" seed="$3"
    local tag="expA_laps_diag_${label}"
    local trace="$DATA_DIR/${label}.laps.csv"
    if "$DRY"; then
        printf 'LAPS_DIAG=%q failed=%s seed=%s PATHS=8 END_MS=8 EXTRA_ARGS=-disable_trim bash %q laps laps %s %q %s %q flow %q %q\n' \
            "$trace" "$failed" "$seed" "$RUN_LIB" "$failed" "$TOPO" "$seed" "$CM" "$tag" "$DATA_DIR"
    else
        LAPS_DIAG="$trace" PATHS=8 END_MS=8 EXTRA_ARGS=-disable_trim \
            bash "$RUN_LIB" laps laps "$failed" "$TOPO" "$seed" "$CM" flow "$tag" "$DATA_DIR"
    fi
}

if "$DRY"; then
    emit reference 0 13
    emit degraded 8 14
    exit 0
fi

mkdir -p "$DATA_DIR"
for label in reference degraded; do
    for suffix in laps.csv stdout flow.txt idmap; do
        [[ ! -e "$DATA_DIR/expA_laps_diag_${label}.${suffix}" && ! -e "$DATA_DIR/${label}.${suffix}" ]] || {
            echo "ERROR: refusing to overwrite diagnostic artifact for $label" >&2; exit 1;
        }
    done
done
python3 "$COMMON/gen/many2many.py" "$CM" 64 16 pairs 2000000 128 16
emit reference 0 13
emit degraded 8 14
python3 "$HERE/analyze_laps_diag.py" \
    --reference-trace "$DATA_DIR/reference.laps.csv" --reference-flow "$DATA_DIR/expA_laps_diag_reference.flow.txt" \
    --degraded-trace "$DATA_DIR/degraded.laps.csv" --degraded-flow "$DATA_DIR/expA_laps_diag_degraded.flow.txt" \
    --output-dir "$DATA_DIR/analysis"
