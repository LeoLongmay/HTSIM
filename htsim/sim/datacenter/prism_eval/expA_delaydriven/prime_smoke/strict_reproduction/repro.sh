#!/usr/bin/env bash
# Bounded reproduction of PRIME's ExpA fault/coalescing observation surface.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SMOKE="$(cd "$HERE/.." && pwd)"
REPO="$(cd "$HERE/../../../../../../.." && pwd)"
BUILD="$SMOKE/build/strict_reproduction"
OUT=""

usage() {
    echo "usage: $0 --out OUTPUT_DIRECTORY" >&2
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --out) OUT="${2:-}"; shift 2 ;;
        *) usage; exit 2 ;;
    esac
done
[[ -n "$OUT" ]] || { usage; exit 2; }

OUT="$(python3 - "$OUT" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).resolve())
PY
)"
if [[ "$OUT" != "$SMOKE/"* ]]; then
    echo "output directory must be below $SMOKE: $OUT" >&2
    exit 2
fi
[[ ! -e "$OUT" ]] || { echo "refusing to overwrite $OUT" >&2; exit 1; }

TOOL_TMP="$BUILD/toolchain-tmp"
mkdir -p "$TOOL_TMP"
TMPDIR="$TOOL_TMP" TMP="$TOOL_TMP" TEMP="$TOOL_TMP" \
    cmake -S "$REPO/htsim/sim" -B "$BUILD" -DENABLE_TESTS=OFF \
    -DHTSIM_CREATE_SOURCE_SYMLINKS=OFF
TMPDIR="$TOOL_TMP" TMP="$TOOL_TMP" TEMP="$TOOL_TMP" \
    cmake --build "$BUILD" --target htsim_uec parse_output -j2

SIMULATOR="$BUILD/datacenter/htsim_uec"
DECODER="$BUILD/parse_output"
DATACENTER="$REPO/htsim/sim/datacenter"
TOPOLOGY="$DATACENTER/topologies/fat_tree_128_1os.topo"
[[ -x "$SIMULATOR" && -x "$DECODER" ]] || {
    echo "strict build did not produce htsim_uec and parse_output" >&2
    exit 1
}

mkdir -p "$OUT"
CM="$OUT/m2m.cm"
python3 "$REPO/htsim/sim/datacenter/prism_eval/common/gen/many2many.py" \
    "$CM" 64 16 pairs 2000000 128 16

MANIFEST="$OUT/run_manifest.tsv"
printf 'trace\tfailed\tseed\ttopology\tpaths\tend_ms\tdisable_trim\tuec_delivery_summary\tprime_diag\n' > "$MANIFEST"

run_one() {
    local failed="$1"
    local run_dir="$OUT/prime_strict_f${failed}_s13"
    local trace="$run_dir/run.prime.tsv"
    mkdir -p "$run_dir"
    (
        cd "$run_dir"
        UEC_DELIVERY_SUMMARY=1 PRIME_DIAG="$trace" "$SIMULATOR" \
            -topo "$TOPOLOGY" -tm "$CM" -nodes 128 \
            -sender_cc_algo nscc -load_balancing_algo prime -failed "$failed" \
            -mtu 4150 -paths 16 -seed 13 -disable_trim -end 8 \
            -o "$run_dir/run.dat" > "$run_dir/run.stdout" 2>&1
        "$DECODER" "$run_dir/run.dat" -ascii > "$run_dir/run.ascii" 2>/dev/null || true
        grep ' FLOW_EVENT ' "$run_dir/run.ascii" > "$run_dir/run.flow.txt" || true
        cp idmap.txt "$run_dir/run.idmap" 2>/dev/null || true
        rm -f "$run_dir/run.ascii" "$run_dir/run.dat"
    )
    printf '%s\t%s\t13\tfat_tree_128_1os.topo\t16\t8\t1\t1\t1\n' \
        "${trace#"$OUT/"}" "$failed" >> "$MANIFEST"
}

run_one 0
run_one 8
python3 "$HERE/analyze.py" --input "$OUT"
echo "completed strict PRIME reproduction in $OUT"
