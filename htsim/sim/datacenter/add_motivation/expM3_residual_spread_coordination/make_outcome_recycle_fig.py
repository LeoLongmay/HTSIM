#!/usr/bin/env python3
"""Render compact outcome-recycle exposure and traffic-share evidence."""

from __future__ import annotations

import csv
import os
import tempfile
from collections import defaultdict
from pathlib import Path


HERE = Path(__file__).resolve().parent
os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "htsim-m3-outcome-recycle"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


STAGES = ("pre", "post1", "post2")


def render_outcome_recycle_figure(aggregate_root: Path | str, figure_root: Path | str) -> None:
    aggregate_root = Path(aggregate_root)
    figure_root = Path(figure_root)
    with (aggregate_root / "outcomes.csv").open(newline="", encoding="ascii") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError("outcome-recycle figure requires at least one completed outcome")
    grouped: dict[tuple[str, str], dict[str, dict[str, str]]] = defaultdict(dict)
    for row in rows:
        grouped[(row["run_id"], row["round_id"])][row["stage"]] = row
    complete = [stages for stages in grouped.values() if set(stages) == set(STAGES)]
    if not complete:
        raise ValueError("outcome-recycle figure requires complete pre/post1/post2 outcomes")
    figure, axes = plt.subplots(1, 2, figsize=(6.6, 2.8), sharex=True)
    for stages in complete:
        x = range(3)
        axes[0].plot(x, [float(stages[stage]["online_exposure"]) for stage in STAGES],
                     color="#d95f02", alpha=0.35, linewidth=1.0)
        axes[1].plot(x, [float(stages[stage]["offline_reduced_link_share"]) for stage in STAGES],
                     color="#1f77b4", alpha=0.35, linewidth=1.0)
    for axis, field, label, color in (
        (axes[0], "online_exposure", "High-residual exposure", "#d95f02"),
        (axes[1], "offline_reduced_link_share", "Throttled-path traffic ratio", "#1f77b4"),
    ):
        means = [sum(float(stages[stage][field]) for stages in complete) / len(complete) for stage in STAGES]
        axis.plot(range(3), means, color=color, linewidth=2.3)
        axis.set_xticks(range(3), ("pre", "post1", "post2"))
        axis.set_ylim(0, 1)
        axis.set_ylabel(label)
        axis.grid(axis="y", alpha=0.25)
    figure.tight_layout()
    figure_root.mkdir(parents=True, exist_ok=True)
    figure.savefig(figure_root / "outcome_recycle.pdf", bbox_inches="tight")
    figure.savefig(figure_root / "outcome_recycle.png", dpi=180, bbox_inches="tight")
    plt.close(figure)


if __name__ == "__main__":
    render_outcome_recycle_figure(
        HERE / "data" / "outcome_recycle" / "aggregate",
        HERE / "figs",
    )
