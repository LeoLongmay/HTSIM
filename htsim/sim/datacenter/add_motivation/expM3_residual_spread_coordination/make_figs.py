#!/usr/bin/env python3
"""Render M3 scenario figures from aggregate CSVs only."""

from __future__ import annotations

import csv
import math
import os
from collections import defaultdict
from pathlib import Path


HERE = Path(__file__).resolve().parent
AGGREGATE = HERE / "data" / "aggregate"
FIGS = HERE / "figs"
os.environ.setdefault("MPLCONFIGDIR", str(AGGREGATE / ".matplotlib-cache"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


COLORS = {"original_prism": "#4c78a8", "prism_recycle": "#f58518", "full_prism": "#54a24b"}
LABELS = {"original_prism": "original", "prism_recycle": "recycle", "full_prism": "full PRISM"}


def _read(name: str, required: set[str], *, allow_empty: bool = False) -> list[dict]:
    path = AGGREGATE / name
    with path.open(newline="", encoding="ascii") as stream:
        reader = csv.DictReader(stream)
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"{path} is missing columns: {sorted(missing)}")
        rows = list(reader)
    if not rows and not allow_empty:
        raise ValueError(f"{path} has no rows")
    return rows


def _number(row: dict, field: str) -> float:
    value = float(row[field])
    if not math.isfinite(value):
        raise ValueError(f"non-finite {field}")
    return value


def _render(scenario: str, summaries: list[dict], epochs: list[dict], rounds: list[dict], metrics: list[dict]) -> None:
    scenario_summaries = {row["mode"]: row for row in summaries if row["scenario"] == scenario}
    modes = [mode for mode in COLORS if mode in scenario_summaries]
    if not modes:
        raise ValueError(f"no summary rows for {scenario}")
    figure, axes = plt.subplots(1, 3, figsize=(13.2, 3.5))

    axis = axes[0]
    x = list(range(len(modes)))
    axis.bar(x, [_number(scenario_summaries[mode], "mean_healthy_to_throttled_ratio") for mode in modes], color=[COLORS[mode] for mode in modes])
    axis.set_xticks(x, [LABELS[mode] for mode in modes], rotation=20, ha="right")
    axis.set_ylabel("healthy / throttled ACKed bytes")
    axis.set_title("Traffic ratio")
    axis.grid(axis="y", alpha=0.25)

    axis = axes[1]
    cwnd_axis = axis.twinx()
    for mode in modes:
        rows = sorted((row for row in epochs if row["scenario"] == scenario and row["mode"] == mode), key=lambda row: (int(row["seed"]), int(row["epoch_index"])))
        if rows:
            axis.plot(range(len(rows)), [_number(row, "floor_ps") / 1e6 for row in rows], color=COLORS[mode], linewidth=1.4, label=f"{LABELS[mode]} floor")
            axis.plot(range(len(rows)), [_number(row, "spread_ps") / 1e6 for row in rows], color=COLORS[mode], linewidth=1.0, linestyle="--", label=f"{LABELS[mode]} spread")
            cwnd_axis.plot(range(len(rows)), [_number(row, "cwnd_bytes") / 1000 for row in rows], color=COLORS[mode], linewidth=0.9, linestyle=":", label=f"{LABELS[mode]} cwnd")
        handoffs = [row for row in rounds if row["scenario"] == scenario and row["mode"] == mode and row["handoff"] == "True"]
        if handoffs:
            axis.scatter([len(rows) - 1], [_number(handoffs[-1], "floor_ps") / 1e6], color=COLORS[mode], marker="x", zorder=3)
    axis.set_xlabel("epoch index within seed")
    axis.set_ylabel("delay (us)")
    cwnd_axis.set_ylabel("cwnd (KB)")
    axis.set_title("Floor, spread, control")
    axis.grid(axis="y", alpha=0.25)
    handles, labels = axis.get_legend_handles_labels()
    cwnd_handles, cwnd_labels = cwnd_axis.get_legend_handles_labels()
    axis.legend(handles + cwnd_handles, labels + cwnd_labels, frameon=False, fontsize=7, loc="upper left", bbox_to_anchor=(1.02, 1))

    axis = axes[2]
    for mode in modes:
        rows = sorted((row for row in metrics if row["scenario"] == scenario and row["mode"] == mode), key=lambda row: int(row["seed"]))
        seeds = [row["seed"] for row in rows]
        axis.plot(seeds, [_number(row, "goodput_gbps") for row in rows], marker="o", color=COLORS[mode], label=f"{LABELS[mode]} goodput")
    axis.set_xlabel("seed")
    axis.set_ylabel("goodput (Gbps)")
    axis.set_title("Three-seed goodput and P99")
    right = axis.twinx()
    for mode in modes:
        rows = sorted((row for row in metrics if row["scenario"] == scenario and row["mode"] == mode), key=lambda row: int(row["seed"]))
        right.plot([row["seed"] for row in rows], [_number(row, "p99_genuine_qdelay_ps") / 1e6 for row in rows], marker="s", linestyle="--", color=COLORS[mode], label=f"{LABELS[mode]} P99")
    right.set_ylabel("P99 genuine queue delay (us)")
    axis.grid(axis="y", alpha=0.25)
    handles, labels = axis.get_legend_handles_labels()
    right_handles, right_labels = right.get_legend_handles_labels()
    axis.legend(handles + right_handles, labels + right_labels, frameon=False, fontsize=7, loc="upper left", bbox_to_anchor=(1.02, 0.58))

    FIGS.mkdir(parents=True, exist_ok=True)
    figure.tight_layout()
    figure.savefig(FIGS / f"m3_{scenario}.png", dpi=180, bbox_inches="tight")
    figure.savefig(FIGS / f"m3_{scenario}.pdf", bbox_inches="tight")
    plt.close(figure)


def main() -> int:
    summaries = _read("summary.csv", {"scenario", "mode", "mean_healthy_to_throttled_ratio"})
    epochs = _read("epoch_series.csv", {"scenario", "mode", "seed", "epoch_index", "floor_ps", "spread_ps", "cwnd_bytes"})
    rounds = _read("rounds.csv", {"scenario", "mode", "handoff", "floor_ps"}, allow_empty=True)
    metrics = _read("per_seed_metrics.csv", {"scenario", "mode", "seed", "goodput_gbps", "p99_genuine_qdelay_ps"})
    for scenario in ("recoverable", "persistent"):
        _render(scenario, summaries, epochs, rounds, metrics)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
