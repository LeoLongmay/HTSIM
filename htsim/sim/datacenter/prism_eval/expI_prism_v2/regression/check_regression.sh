#!/bin/bash
# Byte-for-byte regression: default-flag PRISM must produce an identical flow.txt before/after the
# v2 controller change. Deterministic: fixed seed/topo/cm/flags. Run from anywhere.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
EVAL="$(cd "$HERE/../.." && pwd)"
COMMON="$EVAL/common"
DC="$(cd "$EVAL/.." && pwd)"
cd "$DC"
[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first"; exit 1; }
OUT="$HERE/data"; mkdir -p "$OUT"
TOPO=fat_tree_128_1os.topo
CM="$OUT/golden_incast_n8_512k.cm"
python3 "$COMMON/gen/incast.py" "$CM" 8 0 512000 128 16 >/dev/null
# Anti-stale guard: never hash a leftover flow.txt from a prior run. Remove it first; require the
# sim to succeed and produce a non-empty flow.txt before hashing -- otherwise the guard could
# spuriously "pass" on stale output if the run silently failed.
rm -f "$OUT/golden_prism.flow.txt"
PATHS=8 END_MS=3 EXTRA_ARGS="-disable_trim" \
  bash "$COMMON/run_lib.sh" prism reps 8 "$TOPO" 13 "$CM" flow golden_prism "$OUT" >/dev/null 2>&1 \
  || { echo "ERROR: sim run failed"; exit 1; }
[ -s "$OUT/golden_prism.flow.txt" ] || { echo "ERROR: golden_prism.flow.txt missing/empty after run"; exit 1; }
H=$(sha256sum "$OUT/golden_prism.flow.txt" | awk '{print $1}')
if [ "${1:-check}" = "capture" ]; then
  echo "$H" > "$HERE/golden.sha256"; echo "captured golden sha256=$H"; exit 0
fi
EXP=$(cat "$HERE/golden.sha256")
if [ "$H" = "$EXP" ]; then echo "ok: default PRISM byte-identical (sha256=$H)"; exit 0
else echo "DRIFT: default PRISM changed!  got=$H  want=$EXP"; exit 1; fi
