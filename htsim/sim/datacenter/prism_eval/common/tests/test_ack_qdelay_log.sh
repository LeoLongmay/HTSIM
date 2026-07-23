#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
BIN="$ROOT/htsim_uec"
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

ACK_QDELAY="$TMPDIR/acks.csv" "$BIN" \
  -topo "$ROOT/topologies/fat_tree_128_1os.topo" \
  -tm "$(dirname "$0")/data/ack_qdelay_oneflow.cm" \
  -nodes 128 -sender_cc_algo nscc -load_balancing_algo reps \
  -end 1000 -o "$TMPDIR/out.dat" >"$TMPDIR/out.stdout" 2>&1

test -s "$TMPDIR/acks.csv"
awk -F, 'NF != 8 { exit 1 } $6 < 0 { exit 1 } END { exit NR == 0 }' "$TMPDIR/acks.csv"
