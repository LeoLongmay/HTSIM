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
FORMAL_CONFIG="$HERE/configs/formal.csv"
BASE_RTT_FILE="$HERE/configs/base_rtt_ps.txt"
PREFLIGHT_MANIFEST="$HERE/data/preflight/preflight.json"
SMOKE_FIGURE_DIR="$HERE/figs/smoke"
SMOKE_FIGURE_STEM="m2_redistribution_progress_smoke"
CONFIG_HEADER="cell_id,scenario,foreground_flows,hot_path_groups,background_utilization,seed"
TRACE_SUFFIXES=(ack token epoch background pathmap linkmap)

[[ "$SMOKE_FIGURE_STEM" == "m2_redistribution_progress_smoke" ]] || {
    echo "ERROR: smoke figure stem no longer matches the plotter contract" >&2
    exit 1
}

MODE="${1:-}"
case "$MODE" in
    smoke)
        PHASE=smoke
        OUT="$HERE/data/smoke"
        ;;
    full)
        PHASE=formal
        OUT="$HERE/data/formal"
        ;;
    *)
        echo "usage: $0 smoke|full" >&2
        exit 2
        ;;
esac

die() {
    echo "ERROR: $*" >&2
    exit 1
}

clean_run() {
    local out="$1"
    local run_id="$2"
    local suffix
    rm -f -- \
        "$out/$run_id.cm" \
        "$out/$run_id.background-config.csv" \
        "$out/$run_id.dat" \
        "$out/$run_id.stdout" \
        "$out/$run_id.manifest.json"
    for suffix in "${TRACE_SUFFIXES[@]}"; do
        rm -f -- "$out/$run_id.$suffix.csv"
    done
}

read_base_rtt() {
    local lines=()
    [[ -f "$BASE_RTT_FILE" && ! -L "$BASE_RTT_FILE" ]] || \
        die "missing regular base RTT file: $BASE_RTT_FILE"
    mapfile -t lines < "$BASE_RTT_FILE"
    [[ "${#lines[@]}" -eq 1 && "${lines[0]}" =~ ^[1-9][0-9]*$ ]] || \
        die "$BASE_RTT_FILE must contain exactly one positive integer"
    BASE_RTT_PS="${lines[0]}"
}

run_preflight() {
    local out="$HERE/data/preflight"
    local run_id="preflight_cross_pod_s101"
    local traffic="$out/$run_id.cm"
    local prefix="$out/$run_id"

    mkdir -p "$out" "$HERE/configs"
    clean_run "$out" "$run_id"
    rm -f -- "$BASE_RTT_FILE" "$PREFLIGHT_MANIFEST"
    {
        printf 'Nodes 128\n'
        printf 'Connections 1\n'
        printf '16->0 id 1 start 1 size 256000000\n'
    } > "$traffic"

    python3 "$RUNNER" \
        --experiment M2_base_rtt_preflight \
        --phase coarse \
        --run-id "$run_id" \
        --cc prism \
        --seed 101 \
        --topology "$TOPOLOGY" \
        --traffic "$traffic" \
        --out-dir "$out" \
        --trace-prefix "$prefix" \
        --degraded-links 0 \
        --degraded-capacity-gbps 100

    python3 "$ANALYZER" \
        --preflight-prefix "$prefix" \
        --base-rtt-output "$BASE_RTT_FILE" \
        --preflight-manifest "$PREFLIGHT_MANIFEST"
    [[ -s "$PREFLIGHT_MANIFEST" && ! -L "$PREFLIGHT_MANIFEST" ]] || \
        die "preflight analysis did not write $PREFLIGHT_MANIFEST"
    read_base_rtt
}

validate_formal_config() {
    [[ -f "$FORMAL_CONFIG" && ! -L "$FORMAL_CONFIG" ]] || \
        die "missing regular formal config: $FORMAL_CONFIG"
    awk -F, -v header="$CONFIG_HEADER" '
        NR == 1 {
            if ($0 != header) {
                print "invalid formal CSV header" > "/dev/stderr"
                exit 1
            }
            next
        }
        {
            if (NF != 6 || $1 !~ /^[A-Za-z0-9][A-Za-z0-9_.-]*$/ ||
                ($2 != "recoverable" && $2 != "persistent") ||
                $3 !~ /^[1-9][0-9]*$/ || $4 !~ /^[1-9][0-9]*$/ ||
                $5 !~ /^(0\.[0-9]+)$/ || $5 + 0 <= 0 || $5 + 0 >= 1 ||
                $6 !~ /^(13|14|15|16|17)$/) {
                print "invalid formal row at line " NR > "/dev/stderr"
                exit 1
            }
            key = $2 SUBSEP $6
            if (seen[key]++) {
                print "duplicate formal scenario/seed at line " NR > "/dev/stderr"
                exit 1
            }
            signature = $1 SUBSEP $3 SUBSEP $4 SUBSEP $5
            if ($2 in scenario_signature && scenario_signature[$2] != signature) {
                print "formal scenario does not lock one stable cell" > "/dev/stderr"
                exit 1
            }
            scenario_signature[$2] = signature
            count++
        }
        END {
            if (NR == 0 || count != 10) {
                print "formal config must contain exactly 10 rows" > "/dev/stderr"
                exit 1
            }
            split("recoverable persistent", scenarios, " ")
            split("13 14 15 16 17", seeds, " ")
            for (i = 1; i <= 2; i++) {
                for (j = 1; j <= 5; j++) {
                    if (!seen[scenarios[i] SUBSEP seeds[j]]) {
                        print "formal config must contain each scenario at seeds 13-17" > "/dev/stderr"
                        exit 1
                    }
                }
            }
        }
    ' "$FORMAL_CONFIG" || die "formal config validation failed; selection is not weakened"
}

ensure_only_expected_manifests() {
    local manifest run_id
    for manifest in "$OUT"/*.manifest.json; do
        [[ -e "$manifest" ]] || continue
        run_id="$(basename "$manifest" .manifest.json)"
        [[ -n "${EXPECTED_RUNS[$run_id]+present}" ]] || \
            die "unexpected manifest in $OUT; refusing to mix runs: $manifest"
    done
}

clean_expected_runs() {
    local run_id
    for run_id in "${!EXPECTED_RUNS[@]}"; do
        clean_run "$OUT" "$run_id"
    done
}

run_one() {
    local cell_id="$1"
    local scenario="$2"
    local foreground_flows="$3"
    local hot_path_groups="$4"
    local background_utilization="$5"
    local seed="$6"
    local run_id="${PHASE}_${cell_id}_s${seed}"
    local traffic="$OUT/$run_id.cm"
    local background_config="$OUT/$run_id.background-config.csv"

    python3 "$RUNNER" --validate-identifier "$cell_id" >/dev/null
    python3 "$RUNNER" --validate-identifier "$run_id" >/dev/null
    clean_run "$OUT" "$run_id"
    python3 "$GENERATOR" \
        --foreground "$traffic" \
        --background-config "$background_config" \
        --foreground-flows "$foreground_flows" \
        --hot-path-groups "$hot_path_groups" \
        --background-utilization "$background_utilization" \
        --seed "$seed" \
        --base-rtt-ps "$BASE_RTT_PS"
    python3 "$RUNNER" \
        --experiment M2_redistribution_progress \
        --phase "$PHASE" \
        --run-id "$run_id" \
        --cc prism \
        --seed "$seed" \
        --topology "$TOPOLOGY" \
        --traffic "$traffic" \
        --out-dir "$OUT" \
        --trace-prefix "$OUT/$run_id" \
        --degraded-links 0 \
        --degraded-capacity-gbps 100 \
        --background-config "$background_config" \
        --m2-cell-id "$cell_id" \
        --m2-scenario "$scenario" \
        --m2-foreground-flows "$foreground_flows" \
        --m2-hot-path-groups "$hot_path_groups" \
        --m2-background-utilization "$background_utilization"
}

mkdir -p "$OUT"
declare -A EXPECTED_RUNS=()

if [[ "$MODE" == smoke ]]; then
    run_preflight
    EXPECTED_RUNS["smoke_smoke-f8-h1-u25_s101"]=1
    clean_run "$OUT" "smoke_smoke-f4-h2-u50_s13"
    ensure_only_expected_manifests
    clean_expected_runs
    rm -f -- "$OUT/summary.csv" "$OUT/rounds.csv" "$OUT/epochs.csv"
    rm -f -- \
        "$SMOKE_FIGURE_DIR/$SMOKE_FIGURE_STEM.png" \
        "$SMOKE_FIGURE_DIR/$SMOKE_FIGURE_STEM.pdf"
    run_one smoke-f8-h1-u25 "" 8 1 0.25 101
    python3 "$ANALYZER" --smoke
    python3 "$PLOTTER" --render-smoke
    [[ -s "$OUT/summary.csv" && -s "$OUT/rounds.csv" ]] || \
        die "smoke analysis did not produce nonempty summary.csv and rounds.csv"
    [[ -s "$SMOKE_FIGURE_DIR/$SMOKE_FIGURE_STEM.png" && \
       -s "$SMOKE_FIGURE_DIR/$SMOKE_FIGURE_STEM.pdf" ]] || \
        die "smoke rendering did not produce nonempty diagnostic PNG and PDF outputs"
    exit 0
fi

validate_formal_config
read_base_rtt
while IFS=, read -r cell_id scenario foreground_flows hot_path_groups background_utilization seed; do
    EXPECTED_RUNS["formal_${cell_id}_s${seed}"]=1
done < <(tail -n +2 "$FORMAL_CONFIG")
ensure_only_expected_manifests
clean_expected_runs
rm -f -- \
    "$OUT/summary.csv" \
    "$OUT/rounds.csv" \
    "$OUT/epochs.csv" \
    "$OUT/formal_result.csv"

while IFS=, read -r cell_id scenario foreground_flows hot_path_groups background_utilization seed; do
    run_one "$cell_id" "$scenario" "$foreground_flows" "$hot_path_groups" \
        "$background_utilization" "$seed"
done < <(tail -n +2 "$FORMAL_CONFIG")

python3 "$ANALYZER" --formal
rm -f -- \
    "$HERE/figs/m2_redistribution_progress.png" \
    "$HERE/figs/m2_redistribution_progress.pdf"
python3 "$PLOTTER" --render
[[ -s "$OUT/summary.csv" && -s "$OUT/rounds.csv" ]] || \
    die "formal analysis did not produce nonempty summary.csv and rounds.csv"
[[ -s "$HERE/figs/m2_redistribution_progress.png" && \
   -s "$HERE/figs/m2_redistribution_progress.pdf" ]] || \
    die "formal rendering did not produce real PNG and PDF outputs"
