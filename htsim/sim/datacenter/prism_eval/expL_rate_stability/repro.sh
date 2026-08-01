#!/usr/bin/env bash
# Reproduce the locked ExpL delivery-rate stability evidence.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

usage() {
  echo "usage: $0 {smoke|deterministic-check|full}" >&2
}

deterministic_check() (
  local gate_root first_root second_root trace_name
  gate_root="$(mktemp -d "${TMPDIR:-/tmp}/expL-deterministic.XXXXXX")"
  trap 'rm -rf "$gate_root"' EXIT
  first_root="$gate_root/first"
  second_root="$gate_root/second"
  trace_name="rate_asymmetric_decmt_s13.sink.txt"

  python3 run.py --phase smoke --output-root "$first_root"
  python3 run.py --phase smoke --output-root "$second_root"
  if ! cmp -s "$first_root/$trace_name" "$second_root/$trace_name"; then
    echo "ERROR: deterministic twin-run sink traces differ" >&2
    return 1
  fi
  echo "deterministic twin-run gate passed"
)

run_formal() {
  deterministic_check
  python3 run.py --phase formal
  python3 analyze.py
  python3 make_figs.py
}

case "${1:-full}" in
  smoke)
    python3 run.py --phase smoke
    ;;
  deterministic-check|historical-check)
    deterministic_check
    ;;
  full)
    run_formal
    ;;
  *)
    usage
    exit 2
    ;;
esac
