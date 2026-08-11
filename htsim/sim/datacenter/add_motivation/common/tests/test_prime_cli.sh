#!/bin/bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DC="$(cd "$HERE/../../.." && pwd)"
BIN="${1:-$DC/htsim_uec}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

TOPO="$DC/topologies/fat_tree_128_1os.topo"
TM="$HERE/one_flow.cm"

"$BIN" -topo "$TOPO" -tm "$TM" -nodes 128 -sender_cc_algo nscc -sender_cc_only \
    -load_balancing_algo prime -paths 8 -disable_trim -end 2 -o "$TMP/prime.dat" \
    >"$TMP/prime.stdout" 2>&1

test -s "$TMP/prime.dat"
grep -q 'PRIME configuration: ecn_penalty=1 nack_penalty=4 decay=1' "$TMP/prime.stdout"

if "$BIN" -topo "$TOPO" -tm "$TM" -nodes 128 -sender_cc_algo prism -sender_cc_only \
    -load_balancing_algo prime -paths 8 -end 2 -o "$TMP/non-nscc.dat" \
    >"$TMP/non-nscc.stdout" 2>&1; then
    echo "PRIME unexpectedly accepted a non-NSCC sender" >&2
    exit 1
fi
grep -q 'PRIME requires -sender_cc_algo nscc' "$TMP/non-nscc.stdout"

if "$BIN" -goal "$TMP/unsupported.goal" -nodes 128 -sender_cc_algo nscc -sender_cc_only \
    -load_balancing_algo prime -paths 8 -end 2 -o "$TMP/goal.dat" \
    >"$TMP/goal.stdout" 2>&1; then
    echo "PRIME unexpectedly accepted an ATLAHS/GOAL run" >&2
    exit 1
fi
grep -q 'PRIME does not support -goal/ATLAHS runs' "$TMP/goal.stdout"

if "$BIN" -topo "$TOPO" -tm "$TM" -nodes 128 -sender_cc_algo nscc -sender_cc_only \
    -load_balancing_algo prime -planes 2 -paths 8 -end 2 -o "$TMP/multiplane.dat" \
    >"$TMP/multiplane.stdout" 2>&1; then
    echo "PRIME unexpectedly accepted multiple planes" >&2
    exit 1
fi
grep -q 'PRIME requires -planes 1' "$TMP/multiplane.stdout"

for args in \
    '-prime_ecn_penalty 0' \
    '-prime_ecn_penalty 4 -prime_nack_penalty 4' \
    '-prime_decay 0'; do
    if "$BIN" -topo "$TOPO" -tm "$TM" -nodes 128 -sender_cc_algo nscc -sender_cc_only \
        -load_balancing_algo prime -paths 8 -end 2 -o "$TMP/bad-penalty.dat" $args \
        >"$TMP/bad-penalty.stdout" 2>&1; then
        echo "PRIME unexpectedly accepted invalid penalties: $args" >&2
        exit 1
    fi
    grep -q 'invalid PRIME penalty configuration' "$TMP/bad-penalty.stdout"
done

"$BIN" -topo "$TOPO" -tm "$TM" -nodes 128 -sender_cc_algo nscc -sender_cc_only \
    -load_balancing_algo prime -paths 8 -disable_trim -prime_ecn_penalty 2 \
    -prime_nack_penalty 5 -prime_decay 3 -end 2 -o "$TMP/custom.dat" \
    >"$TMP/custom.stdout" 2>&1
test -s "$TMP/custom.dat"
grep -q 'PRIME configuration: ecn_penalty=2 nack_penalty=5 decay=3' "$TMP/custom.stdout"
