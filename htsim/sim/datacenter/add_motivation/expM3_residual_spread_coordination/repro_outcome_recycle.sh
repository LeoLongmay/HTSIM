#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/../../../../../" && pwd)"
DATA_ROOT="$HERE/data/outcome_recycle"

cmake --build "$HERE/../../../build" --target htsim_uec -j2
rm -rf "$DATA_ROOT"
cd "$REPO_ROOT"
python3 -u "$HERE/run_outcome_recycle.py"
