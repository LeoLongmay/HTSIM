#!/usr/bin/env python3
"""expB_oversub_asym_1024 figures -- thin wrapper. Renders the 1024-node 4:1-oversub asymmetric
results (data REUSED from expD_scale1024's expD2_4os sweep -- NOT re-run here) as three split
performance figures, matching expB_oversub_asym's 128-node figBa_4os_* for a scale contrast:
  figBb_4os_{goodput,avg_fct,p99_fct}  (goodput in Tbps, FCT in ms)
  python3 make_figs.py            # render
  python3 make_figs.py --selftest # aggregation self-check (shared perf_figs math)
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import perf_figs  # noqa: E402

EXPD_DATA = os.path.join(HERE, "..", "expD_scale1024", "data")   # reuse expD2_4os data (no re-run)
FIGS = os.path.join(HERE, "figs")
BASELINES = [("ops", "OPS+NSCC", "ops"), ("reps", "REPS+NSCC", "reps"),
             ("swift", "REPS+Swift", "swift"), ("mswift", "REPS+MSwift", "mswift"),
             ("mnscc", "REPS+MNSCC", "mnscc"), ("strack", "STrack", "strack"),
             ("prism", "Prism", "prism")]
SEEDS = [13, 14, 15, 16, 17]
FAILED = [0, 1, 2, 3, 4]

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        perf_figs.selftest()
    else:
        os.makedirs(FIGS, exist_ok=True)
        perf_figs.render_main_perf_split(EXPD_DATA, FIGS, "expD2_4os", BASELINES, FAILED, SEEDS,
                                         "figBb_4os", "Number of failed links", goodput_tbps=True)
