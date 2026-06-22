#!/usr/bin/env python3
"""expG2_msgsize figures -- thin wrapper. STrack/MSwift-style collective CCT-slowdown vs per-flow
message size at fixed -failed 8 on the 128-node 100G testbed.
Renders into ./figs:
  figH_a2a_msgsize / figH_bfly_msgsize   line charts (x=message size log2, y=CCT slowdown, 7 arms)
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
# (collective tag, figure stem, critical-path step count k for the zero-queue lower bound)
COLLECTIVES = [("a2a", "figH_a2a_msgsize", 4), ("bfly", "figH_bfly_msgsize", 7)]

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        msgsweep_figs.selftest()
    else:
        os.makedirs(FIGS, exist_ok=True)
        for coll, stem, k in COLLECTIVES:
            msgsweep_figs.render_slowdown_lines(DATA, FIGS, f"expG2{coll}", BASELINES, k,
                                                SIZES, SEEDS, stem)
        msgsweep_figs.render_legend(FIGS, BASELINES, "figH_legend")
