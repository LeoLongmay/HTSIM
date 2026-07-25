#!/usr/bin/env bash
# Contract: the predeclared sweep declares every arm/failure/seed cell without
# creating raw data when run in dry-run mode.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
DATA="$ROOT/data/double_evidence"
if [ -e "$DATA" ]; then
  BEFORE=$(find "$DATA" -printf '%P:%s:%T@\n' | sort)
else
  BEFORE="__absent__"
fi

OUT=$(DRYRUN=1 bash "$ROOT/repro_1024_double_evidence.sh")

test "$(grep -c 'run_lib.sh' <<<"$OUT")" -eq 100
test "$(grep -c 'PRISM_EPOCH=' <<<"$OUT")" -eq 25
for f in 0 8 16 24 32; do
  grep -F -- " $f fat_tree_1024.topo" <<<"$OUT" >/dev/null
  test "$(grep -c " $f fat_tree_1024.topo" <<<"$OUT")" -eq 20
done
for arm in \
  'run_lib.sh nscc oblivious' \
  'run_lib.sh nscc reps' \
  'run_lib.sh strack reps' \
  'run_lib.sh prism reps'; do
  grep -F -- "$arm" <<<"$OUT" >/dev/null
  test "$(grep -c "$arm" <<<"$OUT")" -eq 25
done
grep -F -- '-prism_smooth_beta 0.3 -prism_hysteresis 0.25 -prism_engage_spread 28 -prism_disengage_spread 20' <<<"$OUT" >/dev/null
if [ -e "$DATA" ]; then
  AFTER=$(find "$DATA" -printf '%P:%s:%T@\n' | sort)
else
  AFTER="__absent__"
fi
test "$AFTER" = "$BEFORE"
