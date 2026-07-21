#!/bin/bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ADD_MOTIVATION="$(cd "$HERE/.." && pwd)"
DATACENTER="$(cd "$ADD_MOTIVATION/.." && pwd)"
RUNNER="$ADD_MOTIVATION/common/run_case.py"
GENERATOR="$DATACENTER/prism_eval/common/gen/poisson_load.py"
TOPOLOGY="$DATACENTER/topologies/fat_tree_128_1os.topo"
FORMAL_CONFIG="$HERE/configs/formal.csv"

MODE="${1:-}"
case "$MODE" in
    smoke)
        PHASE=smoke
        OUT="$HERE/data/smoke"
        ;;
    full)
        PHASE=formal
        OUT="$HERE/data/formal"
        rows="$(awk 'NR > 1 && NF { count++ } END { print count + 0 }' "$FORMAL_CONFIG")"
        if [ "$rows" -eq 0 ]; then
            echo "ERROR: configs/formal.csv is header-only; run calibration selection first" >&2
            exit 1
        fi
        ;;
    *)
        echo "usage: $0 smoke|full" >&2
        exit 2
        ;;
esac

mkdir -p "$OUT"

run_one() {
    local scenario_id="$1"
    local degraded_links="$2"
    local degraded_capacity="$3"
    local offered_load="$4"
    local seed="$5"
    python3 "$RUNNER" --validate-identifier "$scenario_id" >/dev/null
    local run_id="${PHASE}_${scenario_id}_s${seed}"
    python3 "$RUNNER" --validate-identifier "$run_id" >/dev/null
    local traffic="$OUT/${run_id}.cm"

    python3 "$GENERATOR" "$traffic" 64 16 8000000 128 16 \
        "$offered_load" 8000 1600 "$seed"
    python3 "$RUNNER" \
        --experiment M1_entropy_quality \
        --phase "$PHASE" \
        --run-id "$run_id" \
        --cc nscc \
        --seed "$seed" \
        --topology "$TOPOLOGY" \
        --traffic "$traffic" \
        --out-dir "$OUT" \
        --trace-prefix "$OUT/$run_id" \
        --degraded-links "$degraded_links" \
        --degraded-capacity-gbps "$degraded_capacity"
}

if [ "$MODE" = "smoke" ]; then
    run_one symmetric_l05 0 100 0.5 13
    run_one gray_c50_d2_l05 2 50 0.5 13
else
    while IFS=, read -r scenario_id degraded_links degraded_capacity offered_load seed; do
        scenario_id="${scenario_id%$'\r'}"
        degraded_links="${degraded_links%$'\r'}"
        degraded_capacity="${degraded_capacity%$'\r'}"
        offered_load="${offered_load%$'\r'}"
        seed="${seed%$'\r'}"
        [ "$scenario_id" = "scenario_id" ] && continue
        [ -n "$scenario_id" ] || continue
        run_one "$scenario_id" "$degraded_links" "$degraded_capacity" "$offered_load" "$seed"
    done < "$FORMAL_CONFIG"
fi
