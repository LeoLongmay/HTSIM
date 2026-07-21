#!/usr/bin/env python3
"""expE_permutation figures -- thin wrapper over common/perf_figs.py. Renders two performance
triplets from ./data into ./figs: figE_p128_{goodput,avg_fct,p99_fct} (128-node) and
figE_p1024_{...} (1024-node). Permutation traffic x failed-links, delay-driven.
  python3 make_figs.py            # render
  python3 make_figs.py --selftest # aggregation self-check (shared perf_figs math)
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import perf_figs  # noqa: E402

DATA = os.path.join(HERE, "data"); FIGS = os.path.join(HERE, "figs")
BASELINES = [("ops", "OPS+NSCC", "ops"), ("reps", "REPS+NSCC", "reps"),
             ("swift", "REPS+Swift", "swift"), ("mswift", "REPS+MSwift", "mswift"),
             ("mnscc", "REPS+MNSCC", "mnscc"), ("strack", "STrack", "strack"),
             ("prism", "Prism", "prism")]
SEEDS = [13, 14, 15, 16, 17]
FAILED_128 = [0, 2, 4, 6, 8, 10, 12]
FAILED_1024 = [0, 8, 16, 24, 32, 40, 48]
XLABEL = "Number of failed links"

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        perf_figs.selftest()
    else:
        os.makedirs(FIGS, exist_ok=True)
        perf_figs.render_main_perf_split(DATA, FIGS, "expEp128", BASELINES, FAILED_128, SEEDS,
                                         "figE_p128", XLABEL, goodput_tbps=True)
        perf_figs.render_main_perf_split(DATA, FIGS, "expEp1024", BASELINES, FAILED_1024, SEEDS,
                                         "figE_p1024", XLABEL, goodput_tbps=True)
