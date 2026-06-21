#!/usr/bin/env python3
"""expG_collectives figures -- thin wrapper. STrack-style AI collectives (A2A / Ring-AR /
Butterfly-AR) x failed-links on the 128-node 100G testbed; metric = collective makespan (ms).
Renders into ./figs:
  figG_a2a / figG_ring / figG_bfly   grouped bar charts (x={f0,4,8,12}, 7 arms, y=CCT ms)
  python3 make_figs.py            # render
  python3 make_figs.py --selftest # aggregation self-check (shared math)
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import makespan_figs  # noqa: E402

DATA = os.path.join(HERE, "data"); FIGS = os.path.join(HERE, "figs")
BASELINES = [("ops", "OPS+NSCC", "ops"), ("reps", "REPS+NSCC", "reps"),
             ("swift", "REPS+Swift", "swift"), ("mswift", "REPS+MSwift", "mswift"),
             ("mnscc", "REPS+MNSCC", "mnscc"), ("strack", "STrack", "strack"),
             ("prism", "Prism", "prism")]
SEEDS = [13, 14, 15, 16, 17]
FAILED = [0, 4, 8, 12]
COLLECTIVES = [("a2a", "figG_a2a"), ("ring", "figG_ring"), ("bfly", "figG_bfly")]

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        makespan_figs.selftest()
    else:
        os.makedirs(FIGS, exist_ok=True)
        for coll, stem in COLLECTIVES:
            makespan_figs.render_makespan_bars(DATA, FIGS, f"expG{coll}", BASELINES, FAILED, SEEDS, stem)
