#!/usr/bin/env python3
"""Render the locked M3 traffic-distribution figure from aggregate CSVs."""

from __future__ import annotations

import csv
import math
import os
from collections import defaultdict
from pathlib import Path


HERE = Path(__file__).resolve().parent
DEFAULT_AGGREGATE = HERE / "data" / "distribution" / "aggregate"
DEFAULT_FIGS = HERE / "figs"
os.environ.setdefault("MPLCONFIGDIR", str(DEFAULT_AGGREGATE / ".matplotlib-cache"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


MODES = ("original_prism", "prism_recycle")
SCENARIOS = ("recoverable", "persistent")
COLORS = {"original_prism": "#4c78a8", "prism_recycle": "#f58518"}
LABELS = {"original_prism": "original", "prism_recycle": "recycle"}
SUMMARY_FIELDS = {"scenario", "mode", "seed", "throttled_ratio"}
EFFECT_FIELDS = {"scenario", "mode", "seed", "post_window_complete", "post_throttled_ratio"}


def _read_csv(path: Path, required_fields: set[str], *, allow_empty: bool = False) -> list[dict[str, str]]:
    with path.open(newline="", encoding="ascii") as stream:
        reader = csv.DictReader(stream)
        missing = required_fields - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"{path} is missing columns: {sorted(missing)}")
        rows = list(reader)
    if not rows and not allow_empty:
        raise ValueError(f"{path} has no rows")
    return rows


def _finite_number(row: dict[str, str], field: str) -> float:
    try:
        value = float(row[field])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field}: {row.get(field)!r}") from exc
    if not math.isfinite(value):
        raise ValueError(f"non-finite {field}: {row[field]!r}")
    return value


def _mode_seed_ratios(summaries: list[dict[str, str]], scenario: str, mode: str) -> list[float]:
    rows = [
        row for row in summaries
        if row["scenario"] == scenario and row["mode"] == mode
    ]
    if not rows:
        raise ValueError(f"no summary rows for {scenario}/{mode}")
    return [_finite_number(row, "throttled_ratio") for row in rows]


def _refresh_markers(effects: list[dict[str, str]], scenario: str) -> list[float]:
    return [
        _finite_number(row, "post_throttled_ratio")
        for row in effects
        if row["scenario"] == scenario
        and row["mode"] == "prism_recycle"
        and row["post_window_complete"] == "1"
        and row["post_throttled_ratio"] != ""
    ]


def _render_panel(axis, *, scenario: str, summaries: list[dict[str, str]], effects: list[dict[str, str]]) -> None:
    x = list(range(len(MODES)))
    means, lower, upper = [], [], []
    for mode in MODES:
        values = _mode_seed_ratios(summaries, scenario, mode)
        mean = sum(values) / len(values)
        means.append(mean)
        lower.append(max(0.0, mean - min(values)))
        upper.append(max(0.0, max(values) - mean))
    axis.bar(x, means, color=[COLORS[mode] for mode in MODES], width=0.62, zorder=2)
    axis.errorbar(x, means, yerr=[lower, upper], fmt="none", color="#222222", capsize=4, zorder=3,
                  label="seed min/max")

    markers = _refresh_markers(effects, scenario)
    if markers:
        offsets = [0.92 + 0.05 * (index % 3) for index in range(len(markers))]
        axis.scatter(offsets, markers, marker="x", color="#222222", s=32, linewidths=1.1, zorder=4,
                     label="recycle refresh completion")

    axis.set_xticks(x, [LABELS[mode] for mode in MODES])
    axis.set_ylim(bottom=0)
    axis.set_ylabel("throttled traffic ratio")
    axis.set_title(scenario)
    axis.grid(axis="y", alpha=0.25, zorder=0)
    axis.legend(frameon=False, fontsize=8, loc="upper right")


def render_distribution_figure(aggregate_root: Path | str, figure_root: Path | str) -> None:
    """Write `distribution.pdf` and `distribution.png` from analysis aggregate CSVs."""
    aggregate_root = Path(aggregate_root)
    figure_root = Path(figure_root)
    summaries = _read_csv(aggregate_root / "summary.csv", SUMMARY_FIELDS)
    effects = _read_csv(aggregate_root / "refresh_effects.csv", EFFECT_FIELDS, allow_empty=True)

    figure, axes = plt.subplots(1, 2, figsize=(8.6, 3.4), sharey=True)
    for axis, scenario in zip(axes, SCENARIOS):
        _render_panel(axis, scenario=scenario, summaries=summaries, effects=effects)
    figure.tight_layout()
    figure_root.mkdir(parents=True, exist_ok=True)
    figure.savefig(figure_root / "distribution.png", dpi=180, bbox_inches="tight")
    figure.savefig(figure_root / "distribution.pdf", bbox_inches="tight")
    plt.close(figure)


def main() -> int:
    render_distribution_figure(DEFAULT_AGGREGATE, DEFAULT_FIGS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
