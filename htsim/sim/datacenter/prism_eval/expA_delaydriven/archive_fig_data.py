#!/usr/bin/env python3
"""Compact plotting-data archive for the six FigA delay-driven performance panels."""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

import matplotlib as mpl

mpl.rcParams["pdf.fonttype"] = 42
mpl.rcParams["ps.fonttype"] = 42

HERE = Path(__file__).resolve().parent
COMMON = HERE.parent / "common"
sys.path.insert(0, str(COMMON))
import perf_figs  # noqa: E402
import plot_style  # noqa: E402

ARCHIVE = HERE / "archive_data"
DATA = HERE / "data"
FIGS = HERE / "figs"
SEEDS = [13, 14, 15, 16, 17]
FAILED = [0, 2, 4, 6, 8, 10, 12]
LOADS = [10, 30, 50, 70, 90]
BASELINES = [("ops", "OPS+NSCC", "ops"), ("reps", "REPS+NSCC", "reps"),
             ("swift", "REPS+Swift", "swift"), ("mswift", "REPS+MSwift", "mswift"),
             ("mnscc", "REPS+MNSCC", "mnscc"), ("strack", "STrack", "strack"),
             ("prism", "Prism", "prism")]
ARCHIVE_FILES = {"failed": "figA1dd_failed_sweep.csv", "load": "figA3dd_load_sweep.csv"}
FIELDS = ("x", "algorithm", "goodput_mean_gbps", "goodput_std_gbps", "avg_fct_mean_us", "avg_fct_std_us", "p99_fct_mean_us", "p99_fct_std_us", "n_seeds")


def _write(name: str, rows: list[dict[str, object]], archive: Path) -> None:
    archive.mkdir(parents=True, exist_ok=True)
    with (archive / ARCHIVE_FILES[name]).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)


def _read(name: str, archive: Path) -> list[dict[str, str]]:
    path = archive / ARCHIVE_FILES[name]
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(FIELDS):
            raise ValueError(f"unexpected archive schema in {path}")
        rows = list(reader)
    if not rows:
        raise ValueError(f"archive is empty: {path}")
    return rows


def extract(archive: Path = ARCHIVE) -> None:
    """Read flow logs once and retain only the displayed means and error bars."""
    for name, prefix, xs, token in (("failed", "expA", FAILED, "f"), ("load", "expAload", LOADS, "L")):
        rows: list[dict[str, object]] = []
        for label, _display, _color in BASELINES:
            aggregates = perf_figs.aggregate(str(DATA), prefix, label, xs, SEEDS, token)
            if set(aggregates) != set(xs):
                raise ValueError(f"incomplete source data for {name}/{label}: {sorted(aggregates)}")
            for x in xs:
                cell = aggregates[x]
                rows.append({"x": x, "algorithm": label,
                             "goodput_mean_gbps": repr(cell["goodput"][0]), "goodput_std_gbps": repr(cell["goodput"][1]),
                             "avg_fct_mean_us": repr(cell["avg_fct"][0]), "avg_fct_std_us": repr(cell["avg_fct"][1]),
                             "p99_fct_mean_us": repr(cell["p99_fct"][0]), "p99_fct_std_us": repr(cell["p99_fct"][1]),
                             "n_seeds": len(SEEDS)})
        _write(name, rows, archive)


def _render_sweep(name: str, stem: str, xlabel: str, archive: Path, figs: Path) -> None:
    import matplotlib.pyplot as plt

    rows = _read(name, archive)
    xs = FAILED if name == "failed" else LOADS
    goodput_panel = ("goodput", "Goodput (Tbps)", "goodput_mean_gbps", "goodput_std_gbps", 1e-3) if name == "failed" else ("goodput", "Goodput (Gbps)", "goodput_mean_gbps", "goodput_std_gbps", 1.0)
    panels = (goodput_panel,
              ("avg_fct", "Avg FCT (ms)", "avg_fct_mean_us", "avg_fct_std_us", 1e-3),
              ("p99_fct", "P99 FCT (ms)", "p99_fct_mean_us", "p99_fct_std_us", 1e-3))
    plot_style.apply_style(24)
    for suffix, ylabel, mean_key, std_key, scale in panels:
        fig, axis = plt.subplots(1, 1, figsize=(5.2, 3.8))
        for label, _display, color_key in BASELINES:
            series = [next(row for row in rows if row["algorithm"] == label and int(row["x"]) == x) for x in xs]
            axis.errorbar(xs, [float(row[mean_key]) * scale for row in series], yerr=[float(row[std_key]) * scale for row in series],
                          marker="o", lw=2.0, ms=6, capsize=3, color=plot_style.COLORS[color_key])
        axis.set_ylabel(ylabel); axis.set_xlabel(xlabel); axis.set_xticks(xs); axis.grid(alpha=0.3)
        if name == "failed":
            axis.xaxis.label.set_x(0.40)
            if suffix == "goodput":
                axis.yaxis.set_label_coords(-0.2, 0.45)
        elif suffix == "goodput":
            axis.yaxis.set_label_coords(-0.22, 0.45); axis.xaxis.label.set_x(0.45)
        plt.tight_layout(); plot_style.save(fig, f"{stem}_{suffix}", str(figs)); plt.close(fig)


def render(archive: Path = ARCHIVE, figs: Path = FIGS) -> None:
    """Render the six panels using only the two compact CSV tables."""
    _render_sweep("failed", "figA1dd", "Number of throttled links", archive, figs)
    _render_sweep("load", "figA3dd_load", "Network load (%)", archive, figs)


def selftest() -> None:
    if tuple(ARCHIVE_FILES) != ("failed", "load"):
        raise RuntimeError("unexpected archive file map")
    print("ExpA archive self-test: PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extract", action="store_true")
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--archive", type=Path, default=ARCHIVE)
    parser.add_argument("--figs", type=Path, default=FIGS)
    args = parser.parse_args()
    if args.selftest: selftest()
    elif args.extract: extract(args.archive)
    elif args.render: render(args.archive, args.figs)
    else: parser.error("choose --extract, --render, or --selftest")
