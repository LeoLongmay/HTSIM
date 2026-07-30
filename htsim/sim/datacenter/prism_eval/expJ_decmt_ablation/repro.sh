#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"

python3 "$HERE/run.py" smoke
python3 "$HERE/run.py" formal
python3 "$HERE/analyze.py"
python3 "$HERE/make_figs.py"
