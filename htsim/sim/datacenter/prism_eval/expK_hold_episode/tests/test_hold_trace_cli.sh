#!/usr/bin/env bash
# Contract test for the opt-in read-only PRISM_HOLD_TRACE ACK stream.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DC="$(cd "$HERE/../../.." && pwd)"
BIN="$DC/htsim_uec"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

[ -x "$BIN" ] || {
  echo "missing simulator binary: $BIN" >&2
  exit 1
}

cat >"$TMP/two-flow.cm" <<'EOF'
Nodes 128
Connections 2
0->100 start 0 size 400000
1->101 start 0 size 400000
EOF

(
  cd "$DC"
  PRISM_HOLD_TRACE="$TMP/hold.csv" "$BIN" \
    -topo topologies/fat_tree_128_1os.topo \
    -tm "$TMP/two-flow.cm" \
    -nodes 128 \
    -sender_cc_algo prism \
    -load_balancing_algo reps \
    -paths 8 \
    -seed 13 \
    -disable_trim \
    -end 2000 \
    -o "$TMP/output.dat" >/dev/null
)

[ -s "$TMP/hold.csv" ] || {
  echo "PRISM_HOLD_TRACE did not create a nonempty trace" >&2
  exit 1
}

awk -F, '
  NF != 8 { exit 1 }
  $1 !~ /^[0-9]+$/ || $2 !~ /^[0-9]+$/ || $3 !~ /^[01]$/ { exit 1 }
  $4 !~ /^[0-9]+$/ || $5 !~ /^[0-9]+$/ || $6 !~ /^[01]$/ { exit 1 }
  $7 !~ /^[0-9]+$/ || $8 !~ /^[0-9]+$/ { exit 1 }
  $7 > 0 { seen_progress = 1 }
  END { exit !(NR > 0 && seen_progress) }
' "$TMP/hold.csv"
