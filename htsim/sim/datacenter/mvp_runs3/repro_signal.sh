#!/bin/bash
# Reproduce figS1 (per-path delay distribution) + figS2 (load sweep) for the
# mean-vs-floor signal conflation (PRISM motivation Section 2).
# Fixed asymmetry failed=12 (US3 healthy -> a clean-path minority survives), sweep load,
# 5 seeds. Requires htsim_uec built with the 6-col PRISM_PATHRTT log.
# Usage:  bash mvp_runs3/repro_signal.sh
set -euo pipefail
DC="$(cd "$(dirname "$0")/.." && pwd)"   # .../sim/datacenter
cd "$DC"
SEEDS="13 14 15 16 17"
LOADS="4 8 16 32 64"
[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first"; exit 1; }

echo "== self-test analysis script =="
python3 mvp_runs3/make_signal_fig.py --selftest

echo "== runs: load sweep (n senders -> 16 pod0 receivers), failed=12, paths 64, END=2 =="
for n in $LOADS; do
  python3 mvp_runs3/gen_overload.py mvp_runs3/sigL_n${n}.cm ${n} 0 16
  for s in $SEEDS; do
    PATHS=64 SEED=$s END=2 bash mvp_runs3/run_one.sh reps 12 sigL_n${n}.s${s} mvp_runs3/sigL_n${n}.cm
  done
done

echo "== render figS1 + figS2 =="
python3 mvp_runs3/make_signal_fig.py
echo "== done: figS1_path_distribution.{png,pdf} figS2_load_sweep.{png,pdf} =="
