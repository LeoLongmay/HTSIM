#!/usr/bin/env bash
# Reproduce the locked ExpL delivery-rate stability evidence.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

usage() {
  echo "usage: $0 {smoke|historical-check|full}" >&2
}

run_formal() {
  python3 run.py --phase formal
  python3 analyze.py
  python3 make_figs.py
}

case "${1:-full}" in
  smoke)
    python3 run.py --phase smoke
    ;;
  historical-check)
    python3 run.py --phase smoke
    python3 analyze.py --historical-check --input data/smoke
    ;;
  full)
    run_formal
    ;;
  *)
    usage
    exit 2
    ;;
esac
