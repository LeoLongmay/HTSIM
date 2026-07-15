#!/bin/bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ADD_MOTIVATION="$(cd "$HERE/.." && pwd)"
DATACENTER="$(cd "$ADD_MOTIVATION/.." && pwd)"
RUNNER="$ADD_MOTIVATION/common/run_case.py"
GENERATOR="$HERE/gen_workload.py"
ANALYZER="$HERE/analyze.py"
TOPOLOGY="$DATACENTER/topologies/fat_tree_128_1os.topo"
COARSE_CONFIG="$HERE/configs/calibration.csv"
FORMAL_CONFIG="$HERE/configs/formal.csv"
CONFIRMATION_CONFIG="$HERE/data/coarse/confirmation_selection.csv"
COARSE_SUMMARY="$HERE/data/coarse/summary.csv"
BASE_RTT_FILE="$HERE/configs/base_rtt_ps.txt"
CONFIG_HEADER="cell_id,scenario,foreground_flows,hot_path_groups,background_utilization,seed"
TRACE_SUFFIXES=(ack token epoch background pathmap linkmap)

MODE="${1:-}"
case "$MODE" in
    coarse)
        PHASE=coarse
        CONFIG="$COARSE_CONFIG"
        OUT="$HERE/data/coarse"
        ;;
    confirm)
        PHASE=confirmation
        CONFIG="$CONFIRMATION_CONFIG"
        OUT="$HERE/data/confirmation"
        ;;
    *)
        echo "usage: $0 coarse|confirm" >&2
        exit 2
        ;;
esac

die() {
    echo "ERROR: $*" >&2
    exit 1
}

invalidate_formal_lock() {
    local tmp
    mkdir -p "$HERE/configs"
    tmp="$(mktemp "$HERE/configs/.formal.csv.tmp.XXXXXX")" || \
        die "could not create temporary formal config"
    if ! printf '%s\n' "$CONFIG_HEADER" > "$tmp"; then
        rm -f -- "$tmp"
        die "could not reset formal config"
    fi
    if ! mv -f -- "$tmp" "$FORMAL_CONFIG"; then
        rm -f -- "$tmp"
        die "could not install reset formal config"
    fi
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

validate_coarse_config() {
    [[ -f "$COARSE_CONFIG" && ! -L "$COARSE_CONFIG" ]] || \
        die "missing regular coarse config: $COARSE_CONFIG"
    awk -F, -v header="$CONFIG_HEADER" '
        NR == 1 {
            if ($0 != header) {
                print "invalid coarse CSV header" > "/dev/stderr"
                exit 1
            }
            next
        }
        {
            if (NF != 6 || $2 != "" || $6 != "101") {
                print "invalid coarse row at line " NR > "/dev/stderr"
                exit 1
            }
            if ($3 != "8" && $3 != "16" && $3 != "32") {
                print "invalid foreground_flows at line " NR > "/dev/stderr"
                exit 1
            }
            if ($4 != "2" && $4 != "4" && $4 != "6") {
                print "invalid hot_path_groups at line " NR > "/dev/stderr"
                exit 1
            }
            if ($5 == "0.25") token = "25"
            else if ($5 == "0.50") token = "50"
            else if ($5 == "0.75") token = "75"
            else {
                print "invalid background_utilization at line " NR > "/dev/stderr"
                exit 1
            }
            expected = "coarse-f" $3 "-h" $4 "-u" token
            if ($1 != expected || seen[$1]++) {
                print "invalid or duplicate coarse cell_id at line " NR > "/dev/stderr"
                exit 1
            }
            count++
        }
        END {
            if (NR == 0 || count != 27) {
                print "coarse config must contain exactly 27 cells" > "/dev/stderr"
                exit 1
            }
        }
    ' "$COARSE_CONFIG" || die "coarse config validation failed"
}

validate_confirmation_config() {
    [[ -f "$CONFIRMATION_CONFIG" && ! -L "$CONFIRMATION_CONFIG" ]] || \
        die "run coarse analysis with --select-confirmation first: $CONFIRMATION_CONFIG"
    awk -F, -v header="$CONFIG_HEADER" '
        NR == 1 {
            if ($0 != header) {
                print "invalid confirmation CSV header" > "/dev/stderr"
                exit 1
            }
            next
        }
        {
            if (NF != 6 || $1 !~ /^[A-Za-z0-9][A-Za-z0-9_.-]*$/ ||
                ($2 != "recoverable" && $2 != "persistent") ||
                $3 !~ /^[1-9][0-9]*$/ || $4 !~ /^[1-9][0-9]*$/ ||
                $5 !~ /^(0\.[0-9]+)$/ || $5 + 0 <= 0 || $5 + 0 >= 1 ||
                ($6 != "101" && $6 != "102" && $6 != "103")) {
                print "invalid confirmation row at line " NR > "/dev/stderr"
                exit 1
            }
            cell = $2 SUBSEP $1
            key = cell SUBSEP $6
            if (seen[key]++) {
                print "duplicate confirmation scenario/cell/seed at line " NR > "/dev/stderr"
                exit 1
            }
            signature = $3 SUBSEP $4 SUBSEP $5
            if (cell in cell_signature && cell_signature[cell] != signature) {
                print "confirmation cell parameters vary by seed" > "/dev/stderr"
                exit 1
            }
            cell_signature[cell] = signature
            cells[cell] = 1
            count++
        }
        END {
            if (NR == 0 || count == 0 || count > 18) {
                print "confirmation selection must contain 1 through 18 rows" > "/dev/stderr"
                exit 1
            }
            for (cell in cells) {
                if (!seen[cell SUBSEP "101"] || !seen[cell SUBSEP "102"] ||
                    !seen[cell SUBSEP "103"]) {
                    print "each selected confirmation cell must contain seeds 101-103" > "/dev/stderr"
                    exit 1
                }
            }
        }
    ' "$CONFIRMATION_CONFIG" || die "confirmation selection validation failed"
}

validate_confirmation_inputs() {
    [[ -s "$COARSE_SUMMARY" && ! -L "$COARSE_SUMMARY" ]] || \
        die "missing nonempty regular coarse summary: $COARSE_SUMMARY"
    [[ -s "$CONFIRMATION_CONFIG" && ! -L "$CONFIRMATION_CONFIG" ]] || \
        die "run current coarse analysis with --select-confirmation first: $CONFIRMATION_CONFIG"
    [[ ! "$CONFIRMATION_CONFIG" -ot "$COARSE_SUMMARY" ]] || \
        die "confirmation selection is older than coarse summary; rerun --coarse --select-confirmation"
    validate_confirmation_config
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

run_preflight() {
    local out="$HERE/data/preflight"
    local run_id="preflight_cross_pod_s101"
    local traffic="$out/$run_id.cm"
    local prefix="$out/$run_id"
    local evidence_manifest="$out/preflight.json"

    mkdir -p "$out" "$HERE/configs"
    clean_run "$out" "$run_id"
    rm -f -- "$BASE_RTT_FILE" "$evidence_manifest"
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
        --preflight-manifest "$evidence_manifest"
    [[ -s "$evidence_manifest" && ! -L "$evidence_manifest" ]] || \
        die "preflight analysis did not write $evidence_manifest"
    read_base_rtt
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

if [[ "$MODE" == coarse ]]; then
    invalidate_formal_lock
    mkdir -p "$OUT"
    rm -f -- \
        "$OUT/summary.csv" \
        "$OUT/rounds.csv" \
        "$OUT/epochs.csv" \
        "$OUT/confirmation_selection.csv"
    validate_coarse_config
    run_preflight
else
    invalidate_formal_lock
    validate_confirmation_inputs
    read_base_rtt
fi

mkdir -p "$OUT"
declare -A EXPECTED_RUNS=()
while IFS=, read -r cell_id scenario foreground_flows hot_path_groups background_utilization seed; do
    EXPECTED_RUNS["${PHASE}_${cell_id}_s${seed}"]=1
done < <(tail -n +2 "$CONFIG")
ensure_only_expected_manifests
clean_expected_runs

while IFS=, read -r cell_id scenario foreground_flows hot_path_groups background_utilization seed; do
    run_one "$cell_id" "$scenario" "$foreground_flows" "$hot_path_groups" \
        "$background_utilization" "$seed"
done < <(tail -n +2 "$CONFIG")
