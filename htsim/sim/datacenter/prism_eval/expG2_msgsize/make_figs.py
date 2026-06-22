#!/usr/bin/env python3
"""expG2_msgsize figures -- thin wrapper. STrack-style collective CCT vs per-flow message size,
relative to the REPS+NSCC (UEC) baseline, at fixed -failed 8 on the 128-node 100G testbed.
Renders into ./figs:
  figH_a2a_msgsize / figH_bfly_msgsize   line charts (x=message size log2, y=CCT relative to
                                         REPS+NSCC, 7 arms; dashed reference at 1.0)
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
SEEDS = [13, 14, 15, 16, 17]
SIZES = [16384, 65536, 262144, 1048576, 4194304]
REF = "reps"  # reference arm for the relative-CCT y-axis: REPS+NSCC (the UEC baseline)
COLLECTIVES = [("a2a", "figH_a2a_msgsize"), ("bfly", "figH_bfly_msgsize")]

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        msgsweep_figs.selftest()
    else:
        os.makedirs(FIGS, exist_ok=True)
        for coll, stem in COLLECTIVES:
            msgsweep_figs.render_relative_lines(DATA, FIGS, f"expG2{coll}", BASELINES, REF,
                                                SIZES, SEEDS, stem)
        msgsweep_figs.render_legend(FIGS, BASELINES, "figH_legend")
