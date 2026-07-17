#!/usr/bin/env bash
# Remove generated traces and aggregates while preserving locally rendered figures.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
rm -rf -- "$HERE/data" "$HERE/__pycache__" "$HERE/tests/__pycache__"
