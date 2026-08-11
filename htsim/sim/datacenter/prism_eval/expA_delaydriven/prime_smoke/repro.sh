#!/usr/bin/env bash
# Fixed 24-cell ExpA runner.  PRIME_DIAG is observation-only and set per cell.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../../common" && pwd)"
RUN_LIB="${RUN_LIB:-$COMMON/run_lib.sh}"
OUT=""

usage() {
    echo "usage: $0 --out OUTPUT_DIRECTORY" >&2
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --out) OUT="${2:-}"; shift 2 ;;
        *) usage; exit 2 ;;
    esac
done
[[ -n "$OUT" ]] || { usage; exit 2; }

OUT="$(python3 - "$OUT" <<'PY'
from pathlib import Path
import sys

print(Path(sys.argv[1]).resolve())
PY
)"
if [[ "$OUT" != "$HERE/"* ]]; then
    echo "output directory must be below $HERE: $OUT" >&2
    exit 2
fi

OUT="$(mkdir -p "$OUT" && cd "$OUT" && pwd)"
CM="$OUT/m2m.cm"
TOPO="fat_tree_128_1os.topo"
ARMS=("ops:nscc:oblivious" "reps:nscc:reps" "decmt:prism:reps_actual" "prime:nscc:prime")
FAILEDS=(0 8)
SEEDS=(13 14 15)

tag() { printf 'expA_prime_smoke_%s_f%s_s%s' "$1" "$2" "$3"; }

for spec in "${ARMS[@]}"; do
    IFS=: read -r arm cc lb <<<"$spec"
    for failed in "${FAILEDS[@]}"; do
        for seed in "${SEEDS[@]}"; do
            run_dir="$OUT/$(tag "$arm" "$failed" "$seed")"
            [[ ! -e "$run_dir" ]] || { echo "refusing to overwrite $run_dir" >&2; exit 1; }
        done
    done
done

python3 "$COMMON/gen/many2many.py" "$CM" 64 16 pairs 2000000 128 16

for spec in "${ARMS[@]}"; do
    IFS=: read -r arm cc lb <<<"$spec"
    for failed in "${FAILEDS[@]}"; do
        for seed in "${SEEDS[@]}"; do
            run_dir="$OUT/$(tag "$arm" "$failed" "$seed")"
            mkdir -p "$run_dir"
            if [[ "$arm" == prime ]]; then
                UEC_DELIVERY_SUMMARY=1 PRIME_DIAG="$run_dir/run.prime.tsv" PATHS=8 END_MS=8 EXTRA_ARGS="-disable_trim" \
                    bash "$RUN_LIB" "$cc" "$lb" "$failed" "$TOPO" "$seed" "$CM" flow,sink run "$run_dir"
            else
                UEC_DELIVERY_SUMMARY=1 PATHS=8 END_MS=8 EXTRA_ARGS="-disable_trim" \
                    bash "$RUN_LIB" "$cc" "$lb" "$failed" "$TOPO" "$seed" "$CM" flow,sink run "$run_dir"
            fi
        done
    done
done

echo "completed 24 fixed ExpA cells in $OUT"
