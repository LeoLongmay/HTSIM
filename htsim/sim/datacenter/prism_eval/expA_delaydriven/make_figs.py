#!/usr/bin/env python3
"""Experiment A, DELAY-DRIVEN regime (-disable_trim) figures -- thin wrapper over
common/perf_figs.py. Renders three standalone perf panels figA1dd_{goodput,avg_fct,p99_fct}
(FCT in ms) + two standalone mechanism panels figA2dd_{signal,cwnd} from ./data into ./figs.
  python3 make_figs.py            # render default figures
  python3 make_figs.py --with-laps # render three LAPS-overlay performance figures + legend
  python3 make_figs.py --selftest # aggregation self-check
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import perf_figs  # noqa: E402

DATA = os.path.join(HERE, "data")
FIGS = os.path.join(HERE, "figs")
BASELINES = [("ops", "OPS+NSCC", "ops"), ("reps", "REPS+NSCC", "reps"),
             ("swift", "REPS+Swift", "swift"), ("mswift", "REPS+MSwift", "mswift"),
             ("mnscc", "REPS+MNSCC", "mnscc"), ("strack", "STrack", "strack"),
             ("prism", "Prism", "prism")]
LAPS_BASELINES = [("ops", "OPS+NSCC", "ops"), ("reps", "REPS+NSCC", "reps"),
                  ("swift", "REPS+Swift", "swift"), ("mswift", "REPS+MSwift", "mswift"),
                  ("mnscc", "REPS+MNSCC", "mnscc"), ("strack", "STrack", "strack"),
                  ("laps", "LAPS", "laps"), ("prism", "Prism", "prism")]
FAILED = [0, 2, 4, 6, 8, 10, 12]
SEEDS = [13, 14, 15, 16, 17]
XLABEL = "Number of failed links"
LOADS = [10, 30, 50, 70, 90]   # offered-load x-axis tick values = rho*100 (% of the 1.6 Tbps receiver-access capacity)
XLABEL_LOAD = "Network load (%)"


def render_laps_overlay():
    """Render only the three ExpA performance panels and a LAPS-inclusive legend."""
    perf_figs.render_main_perf_split(DATA, FIGS, "expA", LAPS_BASELINES, FAILED, SEEDS,
                                     "figA1dd", XLABEL, goodput_tbps=True, output_suffix="_laps")
    perf_figs.render_legend(FIGS, LAPS_BASELINES, "figA1dd_legend_laps", row_counts=[4, 4])


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        perf_figs.selftest()
    elif "--with-laps" in sys.argv:
        os.makedirs(FIGS, exist_ok=True)
        render_laps_overlay()
    else:
        os.makedirs(FIGS, exist_ok=True)
        perf_figs.render_main_perf_split(DATA, FIGS, "expA", BASELINES, FAILED, SEEDS, "figA1dd", XLABEL, goodput_tbps=True)
        perf_figs.render_legend(FIGS, BASELINES, "figA1dd_legend", row_counts=[3, 4])
        perf_figs.render_fairness(DATA, FIGS, "expA", BASELINES, FAILED, SEEDS, "figA1dd_fairness", XLABEL)
        perf_figs.render_mechanism_split(DATA, FIGS, "expA", "figA2dd", 8, xlim_ms=3.0)
        perf_figs.render_decomposition(DATA, FIGS, "expA",
            [(0, "128 nodes, failed=0 (symmetric)"), (8, "128 nodes, failed=8 (asymmetric)")],
            "figA2dd_decomp", ylim_us=100)
        perf_figs.render_main_perf_split(DATA, FIGS, "expAload", BASELINES, LOADS, SEEDS,
                                         "figA3dd_load", XLABEL_LOAD, token="L")
