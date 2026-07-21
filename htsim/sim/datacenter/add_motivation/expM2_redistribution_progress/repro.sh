#!/bin/bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ADD_MOTIVATION="$(cd "$HERE/.." && pwd)"
DATACENTER="$(cd "$ADD_MOTIVATION/.." && pwd)"
RUNNER="$ADD_MOTIVATION/common/run_case.py"
GENERATOR="$HERE/gen_workload.py"
ANALYZER="$HERE/analyze.py"
PLOTTER="$HERE/make_figs.py"
TOPOLOGY="$DATACENTER/topologies/fat_tree_128_1os.topo"
DATA_ROOT="$HERE/data/controlled"
TRACE_SUFFIXES=(ack token epoch background pathmap linkmap)

MODE="${1:-}"
case "$MODE" in
    smoke) PHASE=smoke; OUT="$DATA_ROOT/smoke"; FLOWS=12; LINKS=8; CAPACITY=50; SEED=101 ;;
    full) PHASE=formal; OUT="$DATA_ROOT/formal"; FLOWS=; LINKS=; CAPACITY=; SEED= ;;
    *) echo "usage: $0 smoke|full" >&2; exit 2 ;;
esac

clean_run() {
    local run_id="$1" suffix
    rm -f -- "$OUT/$run_id.cm" "$OUT/$run_id.dat" "$OUT/$run_id.stdout" \
        "$OUT/$run_id.manifest.json"
    for suffix in "${TRACE_SUFFIXES[@]}"; do rm -f -- "$OUT/$run_id.$suffix.csv"; done
}

run_one() {
    local cell_id="$1" scenario="$2" flows="$3" links="$4" capacity="$5" seed="$6"
    local run_id="${PHASE}_${cell_id}_s${seed}"
    clean_run "$run_id"
    python3 "$GENERATOR" --foreground "$OUT/$run_id.cm" --foreground-flows "$flows" --seed "$seed"
    python3 "$RUNNER" \
        --experiment M2_redistribution_progress --phase "$PHASE" --run-id "$run_id" \
        --cc prism --seed "$seed" --topology "$TOPOLOGY" --traffic "$OUT/$run_id.cm" \
        --out-dir "$OUT" --trace-prefix "$OUT/$run_id" \
        --degraded-links "$links" --degraded-capacity-gbps "$capacity" \
        --m2-cell-id "$cell_id" --m2-scenario "$scenario" \
        --m2-foreground-flows "$flows" --m2-degraded-links "$links" \
        --m2-degraded-capacity-gbps "$capacity"
}

mkdir -p "$OUT"
rm -f -- "$OUT/summary.csv" "$OUT/rounds.csv" "$OUT/epochs.csv" "$OUT/formal_result.csv"
if [[ "$MODE" == smoke ]]; then
    run_one smoke-f12-d8-c50 "" "$FLOWS" "$LINKS" "$CAPACITY" "$SEED"
    python3 "$ANALYZER" --smoke
    python3 "$PLOTTER" --render-smoke
    exit 0
fi

header='cell_id,scenario,foreground_flows,degraded_links,degraded_capacity_gbps,seed'
[[ "$(head -n 1 "$HERE/configs/formal.csv")" == "$header" ]] || {
    echo "ERROR: invalid formal config header" >&2; exit 1;
}
[[ "$(wc -l < "$HERE/configs/formal.csv")" -eq 11 ]] || {
    echo "ERROR: formal config must contain 10 locked rows" >&2; exit 1;
}
while IFS=, read -r cell_id scenario flows links capacity seed; do
    [[ "$cell_id" == cell_id ]] && continue
    run_one "$cell_id" "$scenario" "$flows" "$links" "$capacity" "$seed"
done < "$HERE/configs/formal.csv"
python3 "$ANALYZER" --formal
python3 "$PLOTTER" --render
