#!/usr/bin/env bash
# Four-arm ExpA recovery comparison.  This runner does not change simulator
# settings beyond selecting the requested sender/load-balancing arm.
set -euo pipefail

if [[ $# -ne 2 ]]; then
    echo "usage: $0 SIMULATOR OUTPUT_DIR" >&2
    exit 2
fi

SIMULATOR="$1"
OUTPUT_DIR="$2"
HERE="$(cd "$(dirname "$0")" && pwd)"
DATACENTER_DIR="$(cd "$HERE/../../.." && pwd)"
TOPOLOGY="$DATACENTER_DIR/topologies/fat_tree_128_1os.topo"
WORKLOAD="$HERE/data_pacing_liveness/m2m.cm"

[[ -x "$SIMULATOR" ]] || { echo "ERROR: simulator is not executable: $SIMULATOR" >&2; exit 1; }
[[ -f "$TOPOLOGY" ]] || { echo "ERROR: topology missing: $TOPOLOGY" >&2; exit 1; }
[[ -f "$WORKLOAD" ]] || { echo "ERROR: workload missing: $WORKLOAD" >&2; exit 1; }
FLOW_COUNT="$(awk '$1 == "Connections" { print $2; exit }' "$WORKLOAD")"
[[ "$FLOW_COUNT" =~ ^[0-9]+$ ]] || { echo "ERROR: workload has no Connections count" >&2; exit 1; }

mkdir -p "$OUTPUT_DIR"
SUMMARY="$OUTPUT_DIR/summary.tsv"
[[ ! -e "$SUMMARY" ]] || { echo "ERROR: refusing to overwrite $SUMMARY" >&2; exit 1; }
printf 'arm\tcompletion_count\tnew\trtx\tprobe_sent\tprobe_acked\tdiagnostic_events\tdiagnostics\n' \
    | tee "$SUMMARY"

run_arm() {
    local arm="$1"
    local sender_cc="$2"
    local load_balancing="$3"
    local result="$OUTPUT_DIR/${arm}.dat"
    local log="$OUTPUT_DIR/${arm}.stdout"
    local diagnostics="$OUTPUT_DIR/${arm}.laps.csv"
    local completion_records completion_count new rtx probe_sent probe_acked diagnostic_events diagnostics_state

    if [[ -e "$result" || -e "$log" || -e "$diagnostics" ]]; then
        echo "ERROR: refusing to overwrite $result, $log, or $diagnostics" >&2
        exit 1
    fi

    if [[ "$arm" == "OPS" ]]; then
        "$SIMULATOR" \
            -topo "$TOPOLOGY" \
            -tm "$WORKLOAD" \
            -nodes 128 \
            -sender_cc_algo "$sender_cc" -sender_cc_only \
            -load_balancing_algo "$load_balancing" \
            -failed 8 -mtu 4150 -paths 8 -seed 14 -disable_trim -end 8 \
            -o "$result" >"$log" 2>&1
        probe_sent=0
        probe_acked=0
        diagnostic_events=0
        diagnostics_state=not-applicable
    else
        LAPS_DIAG="$diagnostics" "$SIMULATOR" \
            -topo "$TOPOLOGY" \
            -tm "$WORKLOAD" \
            -nodes 128 \
            -sender_cc_algo "$sender_cc" -sender_cc_only \
            -load_balancing_algo "$load_balancing" \
            -failed 8 -mtu 4150 -paths 8 -seed 14 -disable_trim -end 8 \
            -o "$result" >"$log" 2>&1
        [[ -f "$diagnostics" ]] || { echo "ERROR: missing diagnostics for $arm" >&2; exit 1; }
        read -r probe_sent probe_acked diagnostic_events < <(
            awk -F, 'NR > 1 { ++events; if ($4 == "probe_sent") ++sent; if ($4 == "probe_acked") ++acked }
                END { print sent + 0, acked + 0, events + 0 }' "$diagnostics")
        diagnostics_state=enabled
    fi

    completion_records="$(strings "$result" | sed -n 's/^# numrecords=//p')"
    [[ -n "$completion_records" ]] || { echo "ERROR: missing completion records for $arm" >&2; exit 1; }
    [[ "$completion_records" =~ ^[0-9]+$ && "$completion_records" -ge "$FLOW_COUNT" ]] || {
        echo "ERROR: invalid flow-event record count for $arm: $completion_records" >&2; exit 1;
    }
    # The default flow logger emits one START record for every configured
    # connection and one FINISH record only when that connection completes.
    completion_count=$((completion_records - FLOW_COUNT))
    read -r new rtx < <(
        awk '/^New:/ {
            for (i = 1; i <= NF; ++i) {
                if ($i == "New:") new = $(i + 1)
                if ($i == "Rtx:") rtx = $(i + 1)
            }
        }
        END { if (new == "" || rtx == "") exit 1; print new, rtx }' "$log")
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$arm" "$completion_count" "$new" "$rtx" "$probe_sent" "$probe_acked" \
        "$diagnostic_events" "$diagnostics_state" | tee -a "$SUMMARY"
}

run_arm OPS nscc oblivious
run_arm laps_control laps_control laps_control
run_arm laps_control_paperack laps_control_paperack laps_control_paperack
run_arm laps laps laps
