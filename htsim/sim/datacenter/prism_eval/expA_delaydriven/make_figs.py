#!/usr/bin/env python3
"""Experiment A, DELAY-DRIVEN regime (-disable_trim) figures -- thin wrapper over
common/perf_figs.py. Renders figA1dd_main_perf + figA2dd_mechanism from ./data into ./figs.
  python3 make_figs.py            # render
  python3 make_figs.py --selftest # aggregation self-check
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import perf_figs  # noqa: E402

DATA = os.path.join(HERE, "data")
FIGS = os.path.join(HERE, "figs")
BASELINES = [("ops", "OPS+NSCC", "ops"), ("reps", "REPS+NSCC", "reps"),
             ("strack", "STrack", "strack"), ("prism", "PRISM", "prism")]
FAILED = [0, 2, 4, 8, 12]
SEEDS = [13, 14, 15, 16, 17]
XLABEL = "# constrained core->agg links (-failed), delay-driven (-disable_trim)"

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        perf_figs.selftest()
    else:
        os.makedirs(FIGS, exist_ok=True)
        perf_figs.render_main_perf(DATA, FIGS, "expA", BASELINES, FAILED, SEEDS, "figA1dd_main_perf", XLABEL)
        perf_figs.render_mechanism(DATA, FIGS, "expA", "figA2dd_mechanism", 8)
