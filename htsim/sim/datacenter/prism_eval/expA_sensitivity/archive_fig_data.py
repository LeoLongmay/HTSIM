#!/usr/bin/env python3
"""Archive and redraw the three selected FigK queueing-delay panels."""
from __future__ import annotations

import argparse
import csv
import importlib.util
import math
from pathlib import Path

import matplotlib as mpl

mpl.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("sensitivity_figs", HERE / "make_figs.py")
assert SPEC and SPEC.loader
source = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(source)
BASE_NS = 13945.0
QCOL = "#e67e22"


def _qdelay_us(path: Path) -> float:
    total = count = 0
    with path.open(encoding="ascii") as stream:
        for line in stream:
            columns = line.split(",")
            if len(columns) >= 4:
                total += float(columns[3]); count += 1
    return ((total / count) - BASE_NS) / 1000.0 if count else float("nan")


def _point(data: Path, tag: str) -> tuple[float, float]:
    goodputs, delays = [], []
    for seed in source.SEEDS:
        flow = data / f"{tag}_s{seed}.flow.txt"
        trace = data / f"{tag}_s{seed}.pathrtt.csv"
        if flow.exists(): goodputs.append(source.metrics.aggregate_goodput_gbps(flow))
        if trace.exists(): delays.append(_qdelay_us(trace))
    return source._mean(goodputs), source._mean(delays)


def extract(data: Path, archive: Path) -> None:
    rows = []
    for knob in source.KNOBS:
        for x in knob["xs"]:
            tag = "qd_default_f8" if x == knob["default"] else f"qd_{knob['name']}_{knob['token']}{'%g' % x}_f8"
            goodput, delay = _point(data, tag)
            if not (math.isfinite(goodput) and math.isfinite(delay)):
                raise ValueError(f"missing plotted data for {knob['name']}={x}")
            rows.append({"knob": knob["name"], "x": repr(x), "goodput_gbps": repr(goodput),
                         "queueing_delay_us": repr(delay)})
    archive.mkdir(parents=True, exist_ok=True)
    with (archive / "figK_qd_panels.csv").open("w", encoding="ascii", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["knob", "x", "goodput_gbps", "queueing_delay_us"], lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)


def render(archive: Path, figures: Path) -> None:
    with (archive / "figK_qd_panels.csv").open(encoding="ascii", newline="") as stream:
        rows = list(csv.DictReader(stream))
    source.plot_style.apply_style(26)
    figures.mkdir(parents=True, exist_ok=True)
    for knob in source.KNOBS:
        selected = [row for row in rows if row["knob"] == knob["name"]]
        selected.sort(key=lambda row: float(row["x"]))
        xs = [float(row["x"]) for row in selected]
        good = [float(row["goodput_gbps"]) for row in selected]
        qd = [float(row["queueing_delay_us"]) for row in selected]
        fig, axg = plt.subplots(figsize=(6.8, 4.4)); axq = axg.twinx()
        axg.plot(xs, good, "s-", lw=2.3, ms=7, color=source.plot_style.COLORS["prism"])
        axq.plot(xs, qd, "o--", lw=2.2, ms=7, color=QCOL)
        if knob.get("logx"):
            axg.set_xscale("log", base=2)
            ticks = [0.125, 1, 2, 4, 8]
            axg.set_xticks(ticks); axg.set_xticklabels(["%g" % tick for tick in ticks])
        else:
            axg.set_xticks([10, 20, 30, 40])
        axg.set_xlabel(knob["title"])
        axg.set_ylabel("Goodput (Gbps)")
        axg.yaxis.set_label_coords(-0.27, 0.40)
        axq.set_ylabel("Queuing delay (us)")
        axq.yaxis.set_label_coords(1.2, 0.38)
        axg.grid(alpha=0.3)
        plt.tight_layout()
        source.plot_style.save(fig, f"figK_qd_{knob['name']}", figures)
        plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extract", action="store_true")
    parser.add_argument("--data", type=Path, default=HERE / "data")
    parser.add_argument("--archive-dir", type=Path, default=HERE / "archive_data")
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--figs", type=Path, default=HERE / "figs")
    args = parser.parse_args()
    if args.extract: extract(args.data, args.archive_dir)
    if args.render: render(args.archive_dir, args.figs)
    if not args.extract and not args.render: parser.error("provide --extract, --render, or both")


if __name__ == "__main__": main()
