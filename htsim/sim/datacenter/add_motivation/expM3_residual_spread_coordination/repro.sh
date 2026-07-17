#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
MODE="${1:-}"
case "$MODE" in
    smoke|full) ;;
    *) echo "usage: $0 smoke|full" >&2; exit 2 ;;
esac

bash "$HERE/clean_outputs.sh"
if [ "$MODE" = "smoke" ]; then
    python3 "$HERE/run.py" --phase smoke --smoke-seed 13
else
    python3 "$HERE/run.py" --phase formal
fi
python3 "$HERE/analyze.py"
python3 "$HERE/make_figs.py"
