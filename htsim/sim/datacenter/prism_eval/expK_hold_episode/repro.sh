#!/bin/bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DC="$(cd "$HERE/../.." && pwd)"

pytest -q "$HERE/tests"

cd "$DC"
[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first" >&2; exit 1; }
[ -x ../build/parse_output ] || { echo "ERROR: ../build/parse_output missing -- build it first" >&2; exit 1; }

python3 "$HERE/run.py" --output "$HERE/data"
python3 "$HERE/analyze.py" --input "$HERE/data" --output "$HERE/data/aggregate"
python3 "$HERE/make_figs.py" --input "$HERE/data/aggregate" --output "$HERE/figs/hold_episode.pdf"
