#!/usr/bin/env python3
"""Render per-refresh M3 outcome evidence from read-only analysis CSVs."""

from __future__ import annotations

import csv
import math
import os
import tempfile
from collections import defaultdict
from pathlib import Path


HERE = Path(__file__).resolve().parent
DEFAULT_AGGREGATE = HERE / "data" / "distribution" / "aggregate"
DEFAULT_FIGS = HERE / "figs"
os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "htsim-m3-refresh-outcomes"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


SCENARIOS = ("recoverable", "persistent")
OUTCOME_FIELDS = {
    "scenario", "pre_complete", "post1_complete", "post2_complete",
    "pre_throttled_ratio", "post1_throttled_ratio", "post2_throttled_ratio",
}
SUMMARY_FIELDS = {
    "scenario", "seed", "complete_outcome_count", "mean_pre_throttled_ratio",
    "mean_post1_throttled_ratio", "mean_post2_throttled_ratio",
}
_RATIO_FIELDS = (
    "pre_throttled_ratio", "post1_throttled_ratio", "post2_throttled_ratio",
)
_MEAN_FIELDS = (
    "mean_pre_throttled_ratio", "mean_post1_throttled_ratio",
    "mean_post2_throttled_ratio",
)


def _read_csv(path: Path, required_fields: set[str]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="ascii") as stream:
        reader = csv.DictReader(stream)
        missing = required_fields - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"{path} is missing columns: {sorted(missing)}")
        return list(reader)


def _finite_number(row: dict[str, str], field: str) -> float:
    try:
        value = float(row[field])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field}: {row.get(field)!r}") from exc
    if not math.isfinite(value):
        raise ValueError(f"non-finite {field}: {row[field]!r}")
    return value


def _complete_lines(outcomes: list[dict[str, str]], scenario: str) -> list[list[float]]:
    lines = []
    for row in outcomes:
        if row["scenario"] != scenario:
            continue
        completion = tuple(row[field] for field in ("pre_complete", "post1_complete", "post2_complete"))
        if any(value not in ("0", "1") for value in completion):
            raise ValueError(f"invalid completion flags for {scenario}: {completion!r}")
        if completion == ("1", "1", "1"):
            lines.append([_finite_number(row, field) for field in _RATIO_FIELDS])
    return lines


def _mean_line(summaries: list[dict[str, str]], scenario: str) -> list[float]:
    rows = [row for row in summaries if row["scenario"] == scenario]
    if not rows:
        raise ValueError(f"no refresh-outcome summary rows for {scenario}")
    values = []
    for field in _MEAN_FIELDS:
        weighted_total = 0.0
        complete_total = 0.0
        for row in rows:
            complete_count = _finite_number(row, "complete_outcome_count")
            if complete_count <= 0:
                continue
            weighted_total += complete_count * _finite_number(row, field)
            complete_total += complete_count
        if complete_total <= 0:
            raise ValueError(f"no finite {field} values for {scenario}")
        values.append(weighted_total / complete_total)
    return values


def _render_panel(axis, *, scenario: str, outcomes: list[dict[str, str]], summaries: list[dict[str, str]]) -> None:
    x = (0, 1, 2)
    for values in _complete_lines(outcomes, scenario):
        axis.plot(x, values, color="#4c78a8", alpha=0.28, linewidth=1.0)
    axis.plot(x, _mean_line(summaries, scenario), color="#e45756", linewidth=2.4, label="mean")
    axis.set_xticks(x, ("pre", "post1", "post2"))
    axis.set_ylim(0, 1)
    axis.set_ylabel("throttled traffic ratio")
    axis.set_title(scenario)
    axis.grid(axis="y", alpha=0.25)
    axis.legend(frameon=False, fontsize=8, loc="upper right")


def render_refresh_outcome_figure(aggregate_root: Path | str, figure_root: Path | str) -> None:
    """Write `refresh_outcomes.pdf` and `.png` from the outcome analysis CSVs."""
    aggregate_root = Path(aggregate_root)
    figure_root = Path(figure_root)
    outcomes = _read_csv(aggregate_root / "refresh_outcomes.csv", OUTCOME_FIELDS)
    summaries = _read_csv(aggregate_root / "refresh_outcome_summary.csv", SUMMARY_FIELDS)
    figure, axes = plt.subplots(1, 2, figsize=(8.6, 3.4), sharey=True)
    for axis, scenario in zip(axes, SCENARIOS):
        _render_panel(axis, scenario=scenario, outcomes=outcomes, summaries=summaries)
    figure.tight_layout()
    figure_root.mkdir(parents=True, exist_ok=True)
    figure.savefig(figure_root / "refresh_outcomes.png", dpi=180, bbox_inches="tight")
    figure.savefig(figure_root / "refresh_outcomes.pdf", bbox_inches="tight")
    plt.close(figure)


def main() -> int:
    render_refresh_outcome_figure(DEFAULT_AGGREGATE, DEFAULT_FIGS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
