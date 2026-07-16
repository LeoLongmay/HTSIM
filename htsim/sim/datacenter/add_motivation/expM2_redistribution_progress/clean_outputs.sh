#!/usr/bin/env bash
# Remove generated M2 traces, logs, traffic matrices, and aggregate tables.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
rm -rf -- "$HERE/data" "$HERE/__pycache__" "$HERE/tests/__pycache__"
