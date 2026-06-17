#!/usr/bin/env python3
"""Experiment A, DELAY-DRIVEN regime (-disable_trim) figures -- thin wrapper over
common/perf_figs.py. Renders three standalone perf panels figA1dd_{goodput,avg_fct,p99_fct}
(FCT in ms) + two standalone mechanism panels figA2dd_{signal,cwnd} from ./data into ./figs.
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
             ("strack", "STrack", "strack"), ("prism", "Prism", "prism")]
FAILED = [0, 2, 4, 6, 8, 10, 12]
SEEDS = [13, 14, 15, 16, 17]
XLABEL = "# constrained core->agg links (-failed)"

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        perf_figs.selftest()
    else:
        os.makedirs(FIGS, exist_ok=True)
        perf_figs.render_main_perf_split(DATA, FIGS, "expA", BASELINES, FAILED, SEEDS, "figA1dd", XLABEL)
        perf_figs.render_mechanism_split(DATA, FIGS, "expA", "figA2dd", 8, xlim_ms=3.0)
