#!/usr/bin/env python3
"""Render figA1dd_v2_{goodput,avg_fct,p99_fct} (+ figA1dd_v2_legend) -- the same three perf panels
as figA1dd_* but with an EXTRA 'Prism v2' line (relative gate m=2) re-run into expA_prismv2_* tags.
All baselines and the original default-'Prism' line are reused from existing data; this writes a
DISTINCT stem 'figA1dd_v2' so the original figA1dd_* figures are NOT overwritten.
  python3 make_figs_v2.py
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import perf_figs   # noqa: E402
import plot_style  # noqa: E402

# Prism v2 gets its own color (distinct from default Prism = green), added at runtime only.
plot_style.COLORS.setdefault("prismv2", "crimson")

DATA = os.path.join(HERE, "data")
FIGS = os.path.join(HERE, "figs")
# original 7 arms (default Prism relabelled to distinguish) + the re-run Prism v2 line
BASELINES = [("ops", "OPS+NSCC", "ops"), ("reps", "REPS+NSCC", "reps"),
             ("swift", "REPS+Swift", "swift"), ("mswift", "REPS+MSwift", "mswift"),
             ("mnscc", "REPS+MNSCC", "mnscc"), ("strack", "STrack", "strack"),
             ("prism", "Prism (default)", "prism"), ("prismv2", "Prism v2", "prismv2")]
FAILED = [0, 2, 4, 6, 8, 10, 12]
SEEDS = [13, 14, 15, 16, 17]
XLABEL = "Number of failed links"

if __name__ == "__main__":
    os.makedirs(FIGS, exist_ok=True)
    perf_figs.render_main_perf_split(DATA, FIGS, "expA", BASELINES, FAILED, SEEDS,
                                     "figA1dd_v2", XLABEL, goodput_tbps=True)
    perf_figs.render_legend(FIGS, BASELINES, "figA1dd_v2_legend", row_counts=[4, 4])
    print("wrote figA1dd_v2_{goodput,avg_fct,p99_fct} + figA1dd_v2_legend (originals untouched)")
