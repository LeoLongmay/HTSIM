#!/usr/bin/env bash
# Prime-only topology coverage validation.  It is intentionally outside ExpA perf results.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../../common" && pwd)"
RUN_LIB="${RUN_LIB:-$COMMON/run_lib.sh}"
OUT=""

usage() {
    echo "usage: $0 --out VALIDATION_DIRECTORY" >&2
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
if [[ "$OUT" != "$HERE/"* ]]; then
    echo "output directory must be below $HERE: $OUT" >&2
    exit 2
fi
if [[ -e "$OUT" && ! -d "$OUT" ]]; then
    echo "validation output is not a directory: $OUT" >&2
    exit 1
fi
if [[ -d "$OUT" && -n "$(find "$OUT" -mindepth 1 -print -quit)" ]]; then
    echo "refusing nonempty validation output: $OUT" >&2
    exit 1
fi
OUT="$(mkdir -p "$OUT" && cd "$OUT" && pwd)"
CM="$OUT/m2m.cm"
RUN="$OUT/prime_paths16"

python3 "$COMMON/gen/many2many.py" "$CM" 64 16 pairs 2000000 128 16
mkdir -p "$RUN"
UEC_DELIVERY_SUMMARY=1 PRIME_DIAG="$RUN/run.prime.tsv" PATHS=16 END_MS=8 EXTRA_ARGS="-disable_trim" \
    bash "$RUN_LIB" nscc prime 0 fat_tree_128_1os.topo 13 "$CM" flow run "$RUN"

python3 - "$RUN/run.prime.tsv" "$OUT/validation.txt" <<'PY'
import csv
import pathlib
import sys

trace, output = map(pathlib.Path, sys.argv[1:])
tuples = set()
with trace.open(newline="") as stream:
    for row in csv.DictReader(stream, delimiter="\t"):
        if row["event"] == "selection":
            tuples.add(tuple(int(port) for port in row["tuple"].split("/")))
expected = {(source_uplink, core_uplink)
            for source_uplink in range(4) for core_uplink in range(4)}
if tuples != expected:
    raise SystemExit(f"PATHS=16 coverage mismatch: observed={sorted(tuples)} expected={sorted(expected)}")
output.write_text(
    "validation=Prime PATHS=16 topology coverage only; not a performance result\n"
    "source_tor_uplinks=0,1,2,3\n"
    "tuple_combinations=16 (4x4)\n",
    encoding="ascii",
)
print(output.read_text(encoding="ascii"), end="")
PY
