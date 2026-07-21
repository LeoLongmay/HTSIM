#!/usr/bin/env bash
# Contract checks for the isolated four-arm lossless/PFC preview matrix.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
RUNNER="$HERE/../repro.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

LOSSLESS_FLAGS='-queue_type lossless_input -queue_size_bytes 150000 -pfc_high_bytes 122880 -pfc_low_bytes 92160 -shared_buffer_bytes 33554432'

assert_matrix() {
  local mode="$1"
  local expected="$2"
  local output="$TMP/${mode:-preview}.txt"
  bash "$RUNNER" $mode --dry-run >"$output"

  grep -c '^PATHS=8 END_MS=80 EXTRA_ARGS=' "$output" | grep -qx "$expected"
  [ "$(wc -l <"$output" | tr -d ' ')" -eq "$expected" ] || {
    echo "dry-run printed non-command output" >&2
    exit 1
  }
  grep -F -- "$LOSSLESS_FLAGS" "$output" | wc -l | tr -d ' ' | grep -qx "$expected"
  ! grep -q -- '-disable_trim' "$output"
  ! grep -q -- 'expA_delaydriven' "$output"
}

assert_matrix '' 140
assert_matrix '--all-baselines' 280
END_MS=37 bash "$RUNNER" --dry-run | grep -c '^PATHS=8 END_MS=37 EXTRA_ARGS=' | grep -qx 140

echo 'ok lossless/PFC preview runner contract'
