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
test "$(grep -c 'END_MS=8' <<<"$OUT")" -eq 100
test "$(grep -c 'PRISM_EPOCH=' <<<"$OUT")" -eq 25
EPOCH_PATHS=$(grep -o 'PRISM_EPOCH=[^ ]*' <<<"$OUT" | cut -d= -f2)
test "$(sort -u <<<"$EPOCH_PATHS" | wc -l)" -eq 25
for f in 0 8 16 24 32; do
  grep -F -- " $f fat_tree_1024.topo" <<<"$OUT" >/dev/null
  test "$(grep -c " $f fat_tree_1024.topo" <<<"$OUT")" -eq 20
done
for seed in 13 14 15 16 17; do
  test "$(grep -cF -- "fat_tree_1024.topo $seed " <<<"$OUT")" -eq 20
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

POLLUTED_ERR=$(mktemp)
FIXTURE=$(mktemp -d)
trap 'rm -f "$POLLUTED_ERR"; rm -rf "$FIXTURE"' EXIT
if END_MS=7 DRYRUN=1 bash "$ROOT/repro_1024_double_evidence.sh" \
    >/dev/null 2>"$POLLUTED_ERR"; then
  echo "polluted END_MS unexpectedly changed the predeclared run" >&2
  exit 1
fi
grep -F -- 'ERROR: END_MS must be 8 for the predeclared double-evidence sweep' \
  "$POLLUTED_ERR" >/dev/null

if [ -e "$DATA" ]; then
  AFTER=$(find "$DATA" -printf '%P:%s:%T@\n' | sort)
else
  AFTER="__absent__"
fi
test "$AFTER" = "$BEFORE"

# Exercise the real pre-render gate with cheap local stubs. No simulator runs,
# and a non-finite first-cell completion rate must stop before the renderer.
FIXTURE_EXP="$FIXTURE/dc/prism_eval/expI_prism_v2"
FIXTURE_COMMON="$FIXTURE/dc/prism_eval/common"
mkdir -p "$FIXTURE_EXP" "$FIXTURE_COMMON/gen"
cp "$ROOT/repro_1024_double_evidence.sh" "$FIXTURE_EXP/"
touch "$FIXTURE/dc/htsim_uec"
chmod +x "$FIXTURE/dc/htsim_uec"
cat >"$FIXTURE_COMMON/gen/many2many.py" <<'PY'
from pathlib import Path
import sys

Path(sys.argv[1]).touch()
PY
cat >"$FIXTURE_COMMON/metrics.py" <<'PY'
def fct_stats(_path):
    return {"completion_rate": float("nan")}
PY
cat >"$FIXTURE_COMMON/run_lib.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
out=$9
tag=$8
mkdir -p "$out"
printf 'stub flow\n' >"$out/$tag.flow.txt"
if [ -n "${PRISM_EPOCH:-}" ]; then
  mkdir -p "$(dirname "$PRISM_EPOCH")"
  printf '0,1,1,1,1,0,1,1,0,1,28,20\n' >"$PRISM_EPOCH"
fi
SH
cat >"$FIXTURE_EXP/make_1024_ack_qdelay_cdf.py" <<'PY'
from pathlib import Path

Path("renderer-called").touch()
PY

NAN_OUT="$FIXTURE/nan.out"
if (
  cd "$FIXTURE/dc"
  bash prism_eval/expI_prism_v2/repro_1024_double_evidence.sh
) >"$NAN_OUT" 2>&1; then
  echo "nan completion rate unexpectedly passed the pre-render gate" >&2
  exit 1
fi
if ! grep -F -- \
    'ERROR: invalid completion rate nan for arm=ops failed=0 seed=13 (require finite value >= 0.999)' \
    "$NAN_OUT" >/dev/null; then
  cat "$NAN_OUT" >&2
  exit 1
fi
test ! -e "$FIXTURE/dc/renderer-called"
