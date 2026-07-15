#!/bin/bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ADD_MOTIVATION="$(cd "$HERE/.." && pwd)"
DATACENTER="$(cd "$ADD_MOTIVATION/.." && pwd)"
CONFIG="$HERE/configs/calibration.csv"
OUT="$HERE/data/calibration"
RUNNER="$ADD_MOTIVATION/common/run_case.py"
GENERATOR="$DATACENTER/prism_eval/common/gen/poisson_load.py"
TOPOLOGY="$DATACENTER/topologies/fat_tree_128_1os.topo"

mkdir -p "$OUT"

while IFS=, read -r scenario_id degraded_links degraded_capacity offered_load seed; do
    [ "$scenario_id" = "scenario_id" ] && continue
    [ -n "$scenario_id" ] || continue
    python3 "$RUNNER" --validate-identifier "$scenario_id" >/dev/null

    run_id="calibration_${scenario_id}"
    python3 "$RUNNER" --validate-identifier "$run_id" >/dev/null
    traffic="$OUT/${run_id}.cm"
    python3 "$GENERATOR" "$traffic" 64 16 8000000 128 16 \
        "$offered_load" 8000 1600 "$seed"
    python3 "$RUNNER" \
        --experiment M1_entropy_quality \
        --phase calibration \
        --run-id "$run_id" \
        --cc nscc \
        --seed "$seed" \
        --topology "$TOPOLOGY" \
        --traffic "$traffic" \
        --out-dir "$OUT" \
        --trace-prefix "$OUT/$run_id" \
        --degraded-links "$degraded_links" \
        --degraded-capacity-gbps "$degraded_capacity"
done < "$CONFIG"
