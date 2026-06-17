#!/usr/bin/env python3
"""Exp B, OVERSUBSCRIPTION (delay-driven, -disable_trim) figures -- thin wrapper over
common/perf_figs.py. Renders figB1_main_perf + figB2_mechanism from ./data into ./figs.
x-axis = oversubscription ratio {1,4,8}, encoded in the f{ratio} filename token (-failed is 0).
  python3 make_figs.py            # render
  python3 make_figs.py --selftest # aggregation self-check (shared perf_figs math)
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import perf_figs  # noqa: E402

DATA = os.path.join(HERE, "data")
FIGS = os.path.join(HERE, "figs")
BASELINES = [("ops", "OPS+NSCC", "ops"), ("reps", "REPS+NSCC", "reps"),
             ("strack", "STrack", "strack"), ("prism", "PRISM", "prism")]
RATIOS = [1, 4, 8]          # oversubscription ratio N:1 (x-axis) and the f{ratio} filename token
SEEDS = [13, 14, 15, 16, 17]
XLABEL = "oversubscription ratio (N:1), delay-driven (-disable_trim)"

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        perf_figs.selftest()
    else:
        os.makedirs(FIGS, exist_ok=True)
        perf_figs.render_main_perf(DATA, FIGS, "expB", BASELINES, RATIOS, SEEDS, "figB1_main_perf", XLABEL)
        perf_figs.render_mechanism(DATA, FIGS, "expB", "figB2_mechanism", 8, mech_label="oversub=8:1")
