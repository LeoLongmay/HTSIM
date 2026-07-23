#!/usr/bin/env bash
# Contract checks for the small REPS/Prism path-engine calibration.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
RUNNER="$HERE/../repro_calibration.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

LOSSLESS_FLAGS='-queue_type lossless_input -queue_size_bytes 150000 -pfc_high_bytes 122880 -pfc_low_bytes 92160 -shared_buffer_bytes 33554432'

bash "$RUNNER" --dry-run >"$TMP/commands.txt"

grep -c '^PATHS=8 END_MS=80 EXTRA_ARGS=' "$TMP/commands.txt" | grep -qx 50
[ "$(wc -l <"$TMP/commands.txt" | tr -d ' ')" -eq 50 ]
grep -F -- "$LOSSLESS_FLAGS" "$TMP/commands.txt" | wc -l | tr -d ' ' | grep -qx 50
grep -F -- 'nscc reps ' "$TMP/commands.txt" | wc -l | tr -d ' ' | grep -qx 10
grep -F -- 'nscc reps_actual ' "$TMP/commands.txt" | wc -l | tr -d ' ' | grep -qx 10
grep -F -- 'prism reps ' "$TMP/commands.txt" | wc -l | tr -d ' ' | grep -qx 10
grep -F -- 'prism reps_actual ' "$TMP/commands.txt" | wc -l | tr -d ' ' | grep -qx 10
grep -F -- '-prism_coordination_mode original_prism' "$TMP/commands.txt" | wc -l | tr -d ' ' | grep -qx 10
grep -F -- 'nscc oblivious ' "$TMP/commands.txt" | wc -l | tr -d ' ' | grep -qx 10
! grep -q -- '-disable_trim' "$TMP/commands.txt"

echo 'ok REPS/Prism calibration runner contract'
