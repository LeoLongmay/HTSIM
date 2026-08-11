#!/usr/bin/env bash
# Run the gated ExpA falsification comparison without changing simulator policy.
set -euo pipefail

if [[ $# -ne 4 ]]; then
    echo "usage: $0 SIMULATOR TEST_BUILD OUTPUT_DIR {fixed|matrix}" >&2
    exit 2
fi

SIMULATOR="$1"
TEST_BUILD="$2"
OUTPUT_DIR="$3"
MODE="$4"
HERE="$(cd "$(dirname "$0")" && pwd)"
DATACENTER_DIR="$(cd "$HERE/../../.." && pwd)"
TOPOLOGY="$DATACENTER_DIR/topologies/fat_tree_128_1os.topo"
WORKLOAD="$HERE/data/m2m.cm"
SUMMARY="$OUTPUT_DIR/summary.tsv"
DECODER="$TEST_BUILD/parse_output"

[[ -x "$SIMULATOR" ]] || { echo "ERROR: simulator is not executable: $SIMULATOR" >&2; exit 1; }
[[ -d "$TEST_BUILD" ]] || { echo "ERROR: test build is not a directory: $TEST_BUILD" >&2; exit 1; }
[[ -x "$DECODER" ]] || { echo "ERROR: parse_output is not executable: $DECODER" >&2; exit 1; }
[[ -f "$TOPOLOGY" ]] || { echo "ERROR: topology missing: $TOPOLOGY" >&2; exit 1; }
[[ -f "$WORKLOAD" ]] || { echo "ERROR: workload missing: $WORKLOAD" >&2; exit 1; }
case "$MODE" in fixed|matrix) ;; *) echo "ERROR: mode must be fixed or matrix" >&2; exit 2 ;; esac

if [[ -e "$OUTPUT_DIR" && ! -d "$OUTPUT_DIR" ]]; then
    echo "ERROR: output path is not a directory: $OUTPUT_DIR" >&2
    exit 1
fi
if [[ -d "$OUTPUT_DIR" && -n "$(find "$OUTPUT_DIR" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
    echo "ERROR: refusing nonempty output directory: $OUTPUT_DIR" >&2
    exit 1
fi

# This semantic gate is intentionally before mkdir/simulation so a failed gate
# cannot be mistaken for a measurement result.
ctest --test-dir "$TEST_BUILD" -R 'laps_(falsification_ladder|multipath|cc_decision|source_routing|packet_feedback)' --output-on-failure

mkdir -p "$OUTPUT_DIR"
printf 'arm\tfailed\tseed\tcompletion_count\tcensored_count\tfct_sample_count\tfct_mean_us\tfct_p50_us\tfct_p95_us\tdelivered_bytes\tgoodput_gbps\tnew\trtx\tprobe_sent\tprobe_acked\tdiagnostic_events\tpit_invariant_violations\n' >"$SUMMARY"

FLOW_COUNT="$(awk '$1 == "Connections" { print $2; exit }' "$WORKLOAD")"
[[ "$FLOW_COUNT" =~ ^[0-9]+$ ]] || { echo "ERROR: workload has no Connections count" >&2; exit 1; }

run_cell() {
    local arm="$1" sender_cc="$2" load_balancing="$3" failed="$4" seed="$5"
    local tag="${arm}_f${failed}_s${seed}"
    local result="$OUTPUT_DIR/${tag}.dat"
    local log="$OUTPUT_DIR/${tag}.stdout"
    local diagnostics="$OUTPUT_DIR/${tag}.laps.csv"
    local flow="$OUTPUT_DIR/${tag}.flow.txt"
    local fct="$OUTPUT_DIR/${tag}.fct.tsv"
    local censored="$OUTPUT_DIR/${tag}.censored.tsv"
    local metrics

    [[ ! -e "$result" && ! -e "$log" && ! -e "$diagnostics" ]] || {
        echo "ERROR: refusing to overwrite artifacts for $tag" >&2
        exit 1
    }

    echo "[falsification] arm=$arm failed=$failed seed=$seed"
    if [[ "$arm" == "LAPS" ]]; then
        if ! UEC_DELIVERY_SUMMARY=1 LAPS_DIAG="$diagnostics" "$SIMULATOR" \
            -topo "$TOPOLOGY" -tm "$WORKLOAD" -nodes 128 \
            -sender_cc_algo "$sender_cc" -load_balancing_algo "$load_balancing" \
            -failed "$failed" -mtu 4150 -paths 8 -seed "$seed" -disable_trim -end 8 \
            -o "$result" >"$log" 2>&1; then
            echo "ERROR: simulator failed for $tag; preserving $OUTPUT_DIR" >&2
            exit 1
        fi
        [[ -f "$diagnostics" ]] || { echo "ERROR: missing LAPS diagnostics for $tag" >&2; exit 1; }
    else
        if ! UEC_DELIVERY_SUMMARY=1 "$SIMULATOR" \
            -topo "$TOPOLOGY" -tm "$WORKLOAD" -nodes 128 \
            -sender_cc_algo "$sender_cc" -load_balancing_algo "$load_balancing" \
            -failed "$failed" -mtu 4150 -paths 8 -seed "$seed" -disable_trim -end 8 \
            -o "$result" >"$log" 2>&1; then
            echo "ERROR: simulator failed for $tag; preserving $OUTPUT_DIR" >&2
            exit 1
        fi
    fi

    if ! "$DECODER" "$result" -ascii 2>/dev/null | awk '/ FLOW_EVENT /' >"$flow"; then
        echo "ERROR: failed to decode flow events for $tag" >&2
        exit 1
    fi
    extract_args=(--extract-cell --flow "$flow" --stdout "$log"
        --fct-output "$fct" --censored-output "$censored"
        --horizon-seconds 0.008 --expected-flows "$FLOW_COUNT")
    if [[ "$arm" == "LAPS" ]]; then
        extract_args+=(--diagnostics "$diagnostics")
    fi
    metrics="$(python3 "$HERE/report_falsification_expa.py" "${extract_args[@]}")" || {
        echo "ERROR: metric extraction failed for $tag" >&2
        exit 1
    }
    printf '%s\t%s\t%s\t%s\n' "$arm" "$failed" "$seed" "$metrics" >>"$SUMMARY"
}

ARMS=("OPS:nscc:oblivious" "REPS:nscc:reps" "DecMT:prism:reps" "LAPS:laps:laps")
if [[ "$MODE" == "fixed" ]]; then
    FAILURES=(8)
    SEEDS=(14)
else
    FAILURES=(0 8)
    SEEDS=(13 14 15)
fi

for spec in "${ARMS[@]}"; do
    IFS=: read -r arm sender_cc load_balancing <<<"$spec"
    for failed in "${FAILURES[@]}"; do
        for seed in "${SEEDS[@]}"; do
            run_cell "$arm" "$sender_cc" "$load_balancing" "$failed" "$seed"
        done
    done
done

python3 "$HERE/report_falsification_expa.py" "$SUMMARY" --output-dir "$OUTPUT_DIR" --gate-status passed
