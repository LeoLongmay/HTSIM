#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PHASE="${1:-}"
case "$PHASE" in
    smoke|formal) ;;
    *) echo "usage: $0 smoke|formal" >&2; exit 2 ;;
esac

cmake --build "$HERE/../../../build" --target htsim_uec parse_output -j2
bash "$HERE/clean_outputs.sh"
python3 "$HERE/run.py" --phase "$PHASE"
if [ "$PHASE" = "formal" ]; then
    python3 "$HERE/analyzer.py"
    python3 "$HERE/make_figs.py"
fi
