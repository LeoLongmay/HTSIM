#!/usr/bin/env python3
"""expG2_msgsize figures -- thin wrapper. STrack-style collective CCT vs per-flow message size,
relative to the REPS+NSCC (UEC) baseline, at fixed -failed 8 on the 128-node 100G testbed.
Renders into ./figs:
  figH_a2a_msgsize / figH_bfly_msgsize   grouped bar charts (x groups=message size, y=CCT relative
                                         to REPS+NSCC, 7 arms/bars; dashed reference at 1.0)
  figH_legend                            shared standalone legend
  python3 make_figs.py            # render
  python3 make_figs.py --selftest # aggregation self-check (shared math)
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import msgsweep_figs  # noqa: E402

DATA = os.path.join(HERE, "data"); FIGS = os.path.join(HERE, "figs")
BASELINES = [("ops", "OPS+NSCC", "ops"), ("reps", "REPS+NSCC", "reps"),
             ("swift", "REPS+Swift", "swift"), ("mswift", "REPS+MSwift", "mswift"),
             ("mnscc", "REPS+MNSCC", "mnscc"), ("strack", "STrack", "strack"),
             ("prism", "Prism", "prism")]
SIZES = [16384, 65536, 262144, 1048576, 4194304]
REF = "reps"  # reference arm for the relative-CCT y-axis: REPS+NSCC (the UEC baseline)
# Y-axis mode. True  -> genuine "CCT slowdown" vs the per-seed best arm (every bar >= 1.0, but the
#                       winning arm collapses to a zero-height bar; semantically a true slowdown).
#            False -> ratio to a FIXED reference (REPS+NSCC); values may be < 1.0 (faster than UEC).
VS_BEST = True
# Seed counts differ by collective: A2A stays at 5 (A2A@4M is NIC-bound and expensive to run),
# Butterfly uses 30 (every bfly run is ~0.3-3 s, so extra seeds are nearly free) to tighten the
# error bar at the bimodal 256 K knee. Disclosed in the README.
A2A_SEEDS  = list(range(13, 18))   # 13..17  (n=5)
BFLY_SEEDS = list(range(13, 43))   # 13..42  (n=30)
# (label, fig_stem, y-axis floor, seeds, yticks): zoom the y-axis per collective; yticks=None keeps
# the auto ticks, an explicit list (e.g. bfly -> [0,1,2]) forces integer-only ticks.
COLLECTIVES = [("a2a", "figH_a2a_msgsize", 0.75, A2A_SEEDS, None),
               ("bfly", "figH_bfly_msgsize", 0.5, BFLY_SEEDS, [0, 1, 2])]

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        msgsweep_figs.selftest()
    else:
        os.makedirs(FIGS, exist_ok=True)
        for coll, stem, rel_floor, seeds, yticks in COLLECTIVES:
            ybot   = 0.0 if VS_BEST else rel_floor    # slowdown bars drawn from 0 (winner = full 1.0 bar)
            ylabel = "CCT slowdown" if VS_BEST else "CCT / REPS+NSCC"
            msgsweep_figs.render_relative_bars(DATA, FIGS, f"expG2{coll}", BASELINES, REF,
                                               SIZES, seeds, stem, ylabel=ylabel,
                                               ybottom=ybot, vs_best=VS_BEST, yticks=yticks)
        msgsweep_figs.render_legend(FIGS, BASELINES, "figH_legend")
