#!/usr/bin/env bash
# Contract checks for the isolated four-arm lossless/PFC preview matrix.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
RUNNER="$HERE/../repro.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

LOSSLESS_FLAGS='-queue_type lossless_input -queue_size_bytes 150000 -pfc_high_bytes 122880 -pfc_low_bytes 92160 -shared_buffer_bytes 33554432'
DC="$(cd "$HERE/../../.." && pwd)"
COMMON_RUNNER="$DC/prism_eval/common/run_lib.sh"

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
FAILED_ONLY=8 bash "$RUNNER" --dry-run | grep -c '^PATHS=8 END_MS=80 EXTRA_ARGS=' | grep -qx 20

# The four formal arms share the same PFC environment.  REPS and Prism must
# use the non-legacy implementation; Prism explicitly pins its coordination
# semantics so a later default change cannot silently alter the comparison.
PREVIEW="$TMP/preview.txt"
grep -Fq ' nscc oblivious 0 fat_tree_128_1os.topo ' "$PREVIEW"
grep -Fq ' nscc reps_actual 0 fat_tree_128_1os.topo ' "$PREVIEW"
grep -Fq ' prism reps_actual 0 fat_tree_128_1os.topo ' "$PREVIEW"
grep -Fq -- '-prism_coordination_mode original_prism' "$PREVIEW"
grep -Fq ' laps_control laps_control 0 fat_tree_128_1os.topo ' "$PREVIEW"

# A normal CMake build places htsim_uec under sim/build/datacenter.  The
# lossless runner must not require a hand-created datacenter/htsim_uec symlink.
[ -x "$DC/../build/datacenter/htsim_uec" ]
grep -Fq 'BIN=../build/datacenter/htsim_uec' "$COMMON_RUNNER"
grep -Fq 'BIN="$DC/../build/datacenter/htsim_uec"' "$RUNNER"

echo 'ok lossless/PFC preview runner contract'
