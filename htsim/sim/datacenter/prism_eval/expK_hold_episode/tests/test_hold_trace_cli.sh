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

validate_trace() {
awk -F, '
  NF != 8 { invalid = 1; next }
  $1 !~ /^[0-9]+$/ || $2 !~ /^[0-9]+$/ || $3 !~ /^[01]$/ { invalid = 1; next }
  $4 !~ /^[0-9]+$/ || $5 !~ /^[0-9]+$/ || $6 !~ /^[01]$/ { invalid = 1; next }
  $7 !~ /^[0-9]+$/ || $8 !~ /^[0-9]+$/ { invalid = 1; next }
  $7 > 0 { seen_progress = 1 }
  END { exit invalid || !(NR > 0 && seen_progress) }
' "$1"
}

validate_trace "$TMP/hold.csv"

printf '1,1,1,0,1,0,1,1\nmalformed\n' >"$TMP/malformed.csv"
if validate_trace "$TMP/malformed.csv"; then
  echo "validator accepted a malformed trace row" >&2
  exit 1
fi

NO_TRACE_DIR="$TMP/no-trace"
mkdir "$NO_TRACE_DIR"
(
  cd "$DC"
  env -u PRISM_HOLD_TRACE "$BIN" \
    -topo topologies/fat_tree_128_1os.topo \
    -tm "$TMP/two-flow.cm" \
    -nodes 128 \
    -sender_cc_algo prism \
    -load_balancing_algo reps \
    -paths 8 \
    -seed 13 \
    -disable_trim \
    -end 2000 \
    -o "$NO_TRACE_DIR/output.dat" >/dev/null
)

unexpected_csv="$(find "$NO_TRACE_DIR" -maxdepth 1 -type f -name '*.csv' -print -quit)"
[ -z "$unexpected_csv" ] || {
  echo "PRISM_HOLD_TRACE unset created unexpected trace: $unexpected_csv" >&2
  exit 1
}
