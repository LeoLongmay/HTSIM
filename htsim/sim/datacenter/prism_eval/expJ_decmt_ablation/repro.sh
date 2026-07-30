#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

python3 run.py smoke
python3 run.py formal
python3 analyze.py
python3 make_figs.py
