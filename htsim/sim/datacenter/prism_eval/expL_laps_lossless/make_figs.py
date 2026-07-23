#!/usr/bin/env python3
"""Render independent lossless/PFC preview performance figures from ``data`` into ``figs``."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import metrics  # noqa: E402
import perf_figs  # noqa: E402

DATA = os.path.join(HERE, "data")
FIGS = os.path.join(HERE, "figs")
PREVIEW_BASELINES = [
    ("ops", "OPS", "ops"),
    ("reps", "REPS", "reps"),
    ("laps_control", "LAPS-Control", "laps"),
    ("prism", "Prism", "prism"),
]
ALL_BASELINES = [
    ("ops", "OPS", "ops"),
    ("reps", "REPS", "reps"),
    ("swift", "REPS+Swift", "swift"),
    ("mswift", "REPS+MSwift", "mswift"),
    ("mnscc", "REPS+MNSCC", "mnscc"),
    ("strack", "STrack", "strack"),
    ("laps_control", "LAPS-Control", "laps"),
    ("prism", "Prism", "prism"),
]
FAILED = [0, 2, 4, 6, 8, 10, 12]
SEEDS = [13, 14, 15, 16, 17]
XLABEL = "Number of failed links"


def require_complete_cells(data_dir, tag_prefix, baselines, failed, seeds):
    """Reject missing or partially completed flow logs before performance rendering."""
    failures = []
    for label, _display, _color in baselines:
        for failed_links in failed:
            for seed in seeds:
                path = os.path.join(data_dir, f"{tag_prefix}_{label}_f{failed_links}_s{seed}.flow.txt")
                if not os.path.exists(path):
                    failures.append(f"missing {os.path.basename(path)}")
                    continue
                rate = metrics.fct_stats(path)["completion_rate"]
                if rate != 1.0:
                    failures.append(f"{os.path.basename(path)} completion_rate={rate:.6f}")
    if failures:
        raise RuntimeError("ExpL refuses incomplete cells: " + "; ".join(failures))


def render(baselines, legend_rows):
    """Render goodput, average-FCT, P99-FCT, and an ordered legend."""
    os.makedirs(FIGS, exist_ok=True)
    require_complete_cells(DATA, "expL", baselines, FAILED, SEEDS)
    perf_figs.render_main_perf_split(
        DATA, FIGS, "expL", baselines, FAILED, SEEDS, "figL1", XLABEL, goodput_tbps=True
    )
    perf_figs.render_legend(FIGS, baselines, "figL1_legend", row_counts=legend_rows)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        perf_figs.selftest()
    elif "--all-baselines" in sys.argv:
        render(ALL_BASELINES, [4, 4])
    elif len(sys.argv) == 1:
        render(PREVIEW_BASELINES, [4])
    else:
        raise SystemExit(f"usage: {sys.argv[0]} [--all-baselines|--selftest]")
