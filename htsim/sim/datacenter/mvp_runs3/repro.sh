#!/bin/bash
# Reproduce the paper motivation figures (figA/figB/figC) from scratch.
#
# Requirements:
#   - htsim_uec built from a commit that contains the read-only PRISM_PATHRTT logging
#     hook in htsim/sim/uec.cpp (added in commit 32fde90). Build from sim/ with:
#         cmake -S . -B build && cmake --build build -j
#     (the symlink ./htsim_uec points at build/datacenter/htsim_uec)
#   - python3 + matplotlib
#
# Determinism: every run passes an explicit -seed; htsim is deterministic given
# (seed, inputs) -- reruns are byte-identical. We average over 5 seeds (13..17) and
# plot mean +/- std error bars. Traffic generators are deterministic (no RNG).
#
# Usage:  bash mvp_runs3/repro.sh
set -euo pipefail
DC="$(cd "$(dirname "$0")/.." && pwd)"   # .../sim/datacenter
cd "$DC"
SEEDS="13 14 15 16 17"

[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing. Build it: (cd .. && cmake -S . -B build && cmake --build build -j)"; exit 1; }

echo "== 1. deterministic traffic matrices =="
python3 mvp_runs3/gen_incast.py   mvp_runs3/incast_n1.cm  1  0
python3 mvp_runs3/gen_incast.py   mvp_runs3/incast_n16.cm 16 0
python3 mvp_runs3/gen_incast.py   mvp_runs3/incast_n32.cm 32 0
python3 mvp_runs3/gen_incast.py   mvp_runs3/incast_n64.cm 64 0
python3 mvp_runs3/gen_overload.py mvp_runs3/overload.cm   32 0 8

echo "== 2. propagation floor (uncontended N=1, deterministic -> seed 13 only) =="
SEED=13 END=8 bash mvp_runs3/run_one.sh reps 0 mp_inc_reps_n1.s13 mvp_runs3/incast_n1.cm

echo "== 3. incast (symmetric, vary load) REPS & OBL, END=8, seeds $SEEDS =="
for s in $SEEDS; do
  for n in 16 32 64; do
    SEED=$s END=8 bash mvp_runs3/run_one.sh reps      0 mp_inc_reps_n$n.s$s mvp_runs3/incast_n$n.cm
    SEED=$s END=8 bash mvp_runs3/run_one.sh oblivious 0 mp_inc_obl_n$n.s$s  mvp_runs3/incast_n$n.cm
  done
done

echo "== 4. whole-pod overload (vary asymmetry) REPS & OBL, END=2, seeds $SEEDS =="
for s in $SEEDS; do
  for f in 0 4 8 12; do
    SEED=$s END=2 bash mvp_runs3/run_one.sh reps      $f mp_wp_reps_f$f.s$s mvp_runs3/overload.cm
    SEED=$s END=2 bash mvp_runs3/run_one.sh oblivious $f mp_wp_obl_f$f.s$s  mvp_runs3/overload.cm
  done
done

echo "== 5. REPS load sweep under asymmetry (failed=12) for figD/figE, END=2, seeds $SEEDS =="
for n in 2 4 8 16 32; do
  python3 mvp_runs3/gen_overload.py mvp_runs3/overload_n$n.cm $n 0 8
  for s in $SEEDS; do
    SEED=$s END=2 bash mvp_runs3/run_one.sh reps 12 mp_load_reps_n$n.s$s mvp_runs3/overload_n$n.cm
  done
done

echo "== 6. CC-strength sweep (REPS failed=12, high load, vary target_q_delay) for figF, seeds $SEEDS =="
for q in 2 4 6 8 12 16; do
  for s in $SEEDS; do
    SEED=$s TQD=$q END=2 bash mvp_runs3/run_one.sh reps 12 mp_cc_tqd$q.s$s mvp_runs3/overload_n32.cm
  done
done

echo "== 7. CC-alone necessity (whole-pod overload 64->16, failed sweep, REPS vs OBL) for figG/figH, seeds $SEEDS =="
python3 mvp_runs3/gen_overload.py mvp_runs3/overload_n64_d16.cm 64 0 16
for f in 0 4 8 12; do
  for s in $SEEDS; do
    SEED=$s END=2 bash mvp_runs3/run_meas.sh reps      $f cc_reps_f$f.s$s mvp_runs3/overload_n64_d16.cm sink
    SEED=$s END=2 bash mvp_runs3/run_meas.sh oblivious $f cc_obl_f$f.s$s  mvp_runs3/overload_n64_d16.cm sink
  done
done

echo "== 8. figures =="
python3 mvp_runs3/make_paper_figs.py
python3 mvp_runs3/make_cc_figs.py
echo "== done: figA_floor_vs_load.png figB_spray_lb_removable.png figC_lb_depends_on_bottleneck.png =="
echo "==       figD_reps_floor_emerges.png figE_floor_vs_load_reps_asym.png figF_cc_strength_sets_floor.png =="
echo "==       figG_cc_alone_underutilization.png figH_cc_alone_congestion.png =="
