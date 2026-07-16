#!/usr/bin/env bash
# Reproduce FigD1 only, with isolated data and output names.
set -euo pipefail

DC="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DC"

test -x ./htsim_uec || { echo "missing ./htsim_uec; build the simulator first" >&2; exit 1; }

python3 mvp_runs3/gen_incast.py mvp_runs3/incast_n1_s.cm 1 0
python3 mvp_runs3/gen_overload.py mvp_runs3/overload_n4_s.cm 4 0 8

SEED=13 END=8 bash mvp_runs3/run_one.sh reps 0 mp_inc_reps_n1_s.s13 mvp_runs3/incast_n1_s.cm
SEED=13 END=2 bash mvp_runs3/run_one.sh reps 12 mp_load_reps_n4_s.s13 mvp_runs3/overload_n4_s.cm

MPLCONFIGDIR="$DC/mvp_runs3/.mplconfig" python3 mvp_runs3/make_figD1_s.py \
    --baseline mvp_runs3/mp_inc_reps_n1_s.s13.pathrtt.csv \
    --timeseries mvp_runs3/mp_load_reps_n4_s.s13.pathrtt.csv \
    --output-stem mvp_runs3/figD1_reps_floor_emerges_s
