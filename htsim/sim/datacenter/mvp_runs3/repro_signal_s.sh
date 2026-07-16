#!/bin/bash
# Reproduce only figS1 under independent _s names; existing figS1 files stay untouched.
set -euo pipefail
DC="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DC"
SEEDS="13 14 15 16 17"
TAG_PREFIX="sigL_s"

[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first"; exit 1; }
python3 mvp_runs3/make_signal_fig.py --selftest
python3 mvp_runs3/gen_overload.py "mvp_runs3/${TAG_PREFIX}_n16.cm" 16 0 16
for seed in $SEEDS; do
  PATHS=64 SEED="$seed" END=2 bash mvp_runs3/run_one.sh reps 12 \
    "${TAG_PREFIX}_n16.s${seed}" "mvp_runs3/${TAG_PREFIX}_n16.cm"
done
python3 mvp_runs3/make_signal_fig.py \
  --input-prefix "$TAG_PREFIX" --output-suffix _s --only-dist
