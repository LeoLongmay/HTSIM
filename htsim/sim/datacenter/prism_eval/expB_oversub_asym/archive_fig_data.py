#!/usr/bin/env python3
"""Compact plotting-data archive for the three 4:1 oversubscription panels."""
from __future__ import annotations
import argparse, csv, os, sys
from pathlib import Path
import matplotlib as mpl
mpl.rcParams["pdf.fonttype"] = 42
mpl.rcParams["ps.fonttype"] = 42
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))
import perf_figs, plot_style  # noqa: E402

ARCHIVE = HERE / "archive_data"; DATA = HERE / "data"; FIGS = HERE / "figs"
SEEDS = [13, 14, 15, 16, 17]; FAILED = [0, 4, 8, 12]
BASELINES = [("ops", "ops"), ("reps", "reps"), ("swift", "swift"), ("mswift", "mswift"), ("mnscc", "mnscc"), ("strack", "strack"), ("prism", "prism")]
ARCHIVE_FILE = "figBa_4os_sweep.csv"
FIELDS = ("failed", "algorithm", "goodput_mean_gbps", "goodput_std_gbps", "avg_fct_mean_us", "avg_fct_std_us", "p99_fct_mean_us", "p99_fct_std_us", "n_seeds")

def extract(archive: Path = ARCHIVE):
    rows = []
    for arm, _color in BASELINES:
        aggs = perf_figs.aggregate(str(DATA), "expBa4os", arm, FAILED, SEEDS)
        if set(aggs) != set(FAILED): raise ValueError(f"incomplete source series: {arm}")
        for failed in FAILED:
            cell = aggs[failed]
            rows.append({"failed": failed, "algorithm": arm, "goodput_mean_gbps": repr(cell["goodput"][0]), "goodput_std_gbps": repr(cell["goodput"][1]), "avg_fct_mean_us": repr(cell["avg_fct"][0]), "avg_fct_std_us": repr(cell["avg_fct"][1]), "p99_fct_mean_us": repr(cell["p99_fct"][0]), "p99_fct_std_us": repr(cell["p99_fct"][1]), "n_seeds": 5})
    archive.mkdir(parents=True, exist_ok=True)
    with (archive / ARCHIVE_FILE).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n"); writer.writeheader(); writer.writerows(rows)

def render(archive: Path = ARCHIVE, figs: Path = FIGS):
    import matplotlib.pyplot as plt
    with (archive / ARCHIVE_FILE).open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(FIELDS): raise ValueError("unexpected archive schema")
        rows = list(reader)
    if len(rows) != 28: raise ValueError("archive must contain all 28 plotted cells")
    plot_style.apply_style(24)
    panels = (("goodput", "Goodput (Gbps)", "goodput_mean_gbps", "goodput_std_gbps", 1.0), ("avg_fct", "Avg FCT (ms)", "avg_fct_mean_us", "avg_fct_std_us", 1e-3), ("p99_fct", "P99 FCT (ms)", "p99_fct_mean_us", "p99_fct_std_us", 1e-3))
    for suffix, ylabel, mean_key, std_key, scale in panels:
        fig, axis = plt.subplots(1, 1, figsize=(5.2, 3.8))
        for arm, color in BASELINES:
            series = [next(row for row in rows if row["algorithm"] == arm and int(row["failed"]) == failed) for failed in FAILED]
            axis.errorbar(FAILED, [float(row[mean_key]) * scale for row in series], yerr=[float(row[std_key]) * scale for row in series], marker="o", lw=2.0, ms=6, capsize=3, color=plot_style.COLORS[color])
        axis.set_ylabel(ylabel); axis.set_xlabel("Number of throttled links"); axis.set_xticks(FAILED); axis.grid(alpha=0.3)
        axis.xaxis.label.set_x({"avg_fct": 0.42, "goodput": 0.38, "p99_fct": 0.45}[suffix])
        if suffix == "goodput": axis.yaxis.set_label_coords(-0.23, 0.45)
        plt.tight_layout(); plot_style.save(fig, f"figBa_4os_{suffix}", str(figs)); plt.close(fig)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--extract", action="store_true"); parser.add_argument("--render", action="store_true"); parser.add_argument("--archive", type=Path, default=ARCHIVE); parser.add_argument("--figs", type=Path, default=FIGS); args = parser.parse_args()
    if args.extract: extract(args.archive)
    elif args.render: render(args.archive, args.figs)
    else: parser.error("choose --extract or --render")
