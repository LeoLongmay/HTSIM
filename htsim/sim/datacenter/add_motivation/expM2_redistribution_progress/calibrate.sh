#!/bin/bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ADD_MOTIVATION="$(cd "$HERE/.." && pwd)"
DATACENTER="$(cd "$ADD_MOTIVATION/.." && pwd)"
RUNNER="$ADD_MOTIVATION/common/run_case.py"
GENERATOR="$HERE/gen_workload.py"
TOPOLOGY="$DATACENTER/topologies/fat_tree_128_1os.topo"
DATA_ROOT="$HERE/data/controlled"
CONFIG_HEADER="cell_id,scenario,foreground_flows,degraded_links,degraded_capacity_gbps,seed"
TRACE_SUFFIXES=(ack token epoch background pathmap linkmap)

MODE="${1:-}"
case "$MODE" in
    coarse)
        PHASE=coarse
        CONFIG="$HERE/configs/calibration.csv"
        OUT="$DATA_ROOT/coarse"
        ;;
    confirm)
        PHASE=confirmation
        CONFIG="$DATA_ROOT/coarse/confirmation_selection.csv"
        OUT="$DATA_ROOT/confirmation"
        ;;
    *)
        echo "usage: $0 coarse|confirm" >&2
        exit 2
        ;;
esac

die() { echo "ERROR: $*" >&2; exit 1; }

validate_config() {
    [[ -f "$CONFIG" && ! -L "$CONFIG" ]] || die "missing regular config: $CONFIG"
    awk -F, -v header="$CONFIG_HEADER" -v mode="$MODE" '
        NR == 1 { if ($0 != header) exit 1; next }
        NF != 6 || $1 !~ /^[A-Za-z0-9][A-Za-z0-9_.-]*$/ ||
        ($2 != "" && $2 != "recoverable" && $2 != "persistent") ||
        $3 !~ /^[1-9][0-9]*$/ || $4 !~ /^[1-9][0-9]*$/ ||
        $5 !~ /^[0-9]+(\.[0-9]+)?$/ || $5 + 0 <= 0 || $5 + 0 >= 100 ||
        $6 !~ /^[1-9][0-9]*$/ { exit 1 }
        { if (seen[$1 SUBSEP $6]++) exit 1; count++ }
        END { if (!count || (mode == "coarse" && count != 6) || (mode == "confirm" && count > 6)) exit 1 }
    ' "$CONFIG" || die "invalid $MODE config: $CONFIG"
}

clean_run() {
    local run_id="$1" suffix
    rm -f -- "$OUT/$run_id.cm" "$OUT/$run_id.dat" "$OUT/$run_id.stdout" \
        "$OUT/$run_id.manifest.json"
    for suffix in "${TRACE_SUFFIXES[@]}"; do
        rm -f -- "$OUT/$run_id.$suffix.csv"
    done
}

run_one() {
    local cell_id="$1" scenario="$2" flows="$3" degraded_links="$4" capacity="$5" seed="$6"
    local run_id="${PHASE}_${cell_id}_s${seed}"
    python3 "$RUNNER" --validate-identifier "$cell_id" >/dev/null
    python3 "$RUNNER" --validate-identifier "$run_id" >/dev/null
    clean_run "$run_id"
    python3 "$GENERATOR" --foreground "$OUT/$run_id.cm" --foreground-flows "$flows" --seed "$seed"
    python3 "$RUNNER" \
        --experiment M2_redistribution_progress --phase "$PHASE" --run-id "$run_id" \
        --cc prism --seed "$seed" --topology "$TOPOLOGY" --traffic "$OUT/$run_id.cm" \
        --out-dir "$OUT" --trace-prefix "$OUT/$run_id" \
        --degraded-links "$degraded_links" --degraded-capacity-gbps "$capacity" \
        --m2-cell-id "$cell_id" --m2-scenario "$scenario" \
        --m2-foreground-flows "$flows" --m2-degraded-links "$degraded_links" \
        --m2-degraded-capacity-gbps "$capacity"
}

validate_config
mkdir -p "$OUT"
rm -f -- "$OUT/summary.csv" "$OUT/rounds.csv" "$OUT/epochs.csv"
if [[ "$MODE" == coarse ]]; then
    rm -f -- "$OUT/confirmation_selection.csv"
fi
while IFS=, read -r cell_id scenario flows degraded_links capacity seed; do
    [[ "$cell_id" == cell_id ]] && continue
    run_one "$cell_id" "$scenario" "$flows" "$degraded_links" "$capacity" "$seed"
done < "$CONFIG"
