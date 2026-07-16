#!/usr/bin/env bash
# Reproduce only figI2 with isolated raw-data and figure suffixes.
set -euo pipefail

DC="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DC"

test -x ./htsim_uec || { echo "missing ./htsim_uec; build the simulator first" >&2; exit 1; }
python3 mvp_runs3/make_coupling_fig.py --selftest

python3 mvp_runs3/gen_overload.py mvp_runs3/overload_cpA_s.cm 8 0 16
python3 mvp_runs3/gen_incast.py mvp_runs3/incast_cpB_s.cm 32 0 20000000 128 16

for q in 2 4 6 8 12 16; do
    for seed in 13 14 15 16 17; do
        SEED="$seed" END=2 TQD="$q" bash mvp_runs3/run_meas.sh reps 12 \
            "cpA_s_tqd${q}.s${seed}" mvp_runs3/overload_cpA_s.cm sink
        SEED="$seed" END=2 TQD="$q" LOGTIME=1 bash mvp_runs3/run_meas.sh reps 0 \
            "cpB_s_tqd${q}.s${seed}" mvp_runs3/incast_cpB_s.cm queue
    done
done

MPLCONFIGDIR="$DC/mvp_runs3/.mplconfig" python3 mvp_runs3/make_coupling_fig.py \
    --input-suffix _s --output-suffix _s --only-dualaxis
