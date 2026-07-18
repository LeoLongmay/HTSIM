#!/bin/bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DC="$(cd "$HERE/../../.." && pwd)"
BIN="${1:-$DC/htsim_uec}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

TOPO="$DC/topologies/fat_tree_128_1os.topo"
TM="$HERE/one_flow.cm"

"$BIN" -topo "$TOPO" -tm "$TM" -nodes 128 -sender_cc_algo laps -sender_cc_only \
    -load_balancing_algo laps -paths 8 -disable_trim -end 2 -o "$TMP/accepted.dat" \
    >"$TMP/accepted.stdout" 2>&1

if [[ ! -s "$TMP/accepted.dat" ]]; then
    echo "paired LAPS configuration did not produce simulation output" >&2
    exit 1
fi

if "$BIN" -topo "$TOPO" -tm "$TM" -nodes 128 -sender_cc_algo laps -sender_cc_only \
    -load_balancing_algo laps -paths 8 -disable_trim -laps_queue_margin 1 -end 2 \
    -o "$TMP/queue-margin.dat" >"$TMP/queue-margin.stdout" 2>&1; then
    echo "strict LAPS unexpectedly accepted -laps_queue_margin" >&2
    exit 1
fi
grep -q -- '-laps_queue_margin is not supported by strict LAPS' "$TMP/queue-margin.stdout"

if "$BIN" -topo "$TOPO" -tm "$TM" -nodes 128 -sender_cc_algo laps -sender_cc_only \
    -load_balancing_algo reps_actual -paths 8 -disable_trim -end 2 -o "$TMP/unpaired-cc.dat" \
    >"$TMP/unpaired-cc.stdout" 2>&1; then
    echo "LAPS sender CC with reps_actual unexpectedly succeeded" >&2
    exit 1
fi
grep -q 'requires -load_balancing_algo laps' "$TMP/unpaired-cc.stdout"

if "$BIN" -topo "$TOPO" -tm "$TM" -nodes 128 -sender_cc_algo prism -sender_cc_only \
    -load_balancing_algo laps -paths 8 -disable_trim -end 2 -o "$TMP/unpaired-lb.dat" \
    >"$TMP/unpaired-lb.stdout" 2>&1; then
    echo "PRISM sender CC with LAPS load balancing unexpectedly succeeded" >&2
    exit 1
fi
grep -q 'requires -sender_cc_algo laps' "$TMP/unpaired-lb.stdout"
