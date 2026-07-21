#!/usr/bin/env python3
"""Render the fixed M6 path-robust signal experiment from summary CSV only."""

from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path
from typing import Sequence


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "prism_eval" / "common"))
import plot_style  # noqa: E402


ARMS = (
    ("reps_nscc", "REPS+NSCC", plot_style.COLORS["reps"]),
    ("original_prism", "Original Prism", plot_style.COLORS["prism"]),
    ("path_robust_spread_prism", "Path-Robust Spread Prism", plot_style.COLORS["strack"]),
)
FAILED_LINKS = (0, 4, 8)
FAILED_LABELS = ("Symmetric", "Failed=4", "Failed=8")


def _read_summary(path: Path) -> dict[tuple[str, int], dict]:
    required = {
        "arm", "failed_links", "n_seeds", "mean_avg_fct_us", "mean_p99_fct_us",
        "mean_goodput_gbps", "mean_completion_rate", "min_avg_fct_us", "max_avg_fct_us",
        "min_p99_fct_us", "max_p99_fct_us", "min_goodput_gbps", "max_goodput_gbps",
    }
    try:
        with path.open(newline="", encoding="ascii") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None or set(reader.fieldnames) != required:
                raise ValueError("summary CSV has missing or unexpected fields")
            rows = list(reader)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise ValueError(f"cannot read summary CSV: {path}") from exc
    expected = {(arm, failed) for arm, _label, _color in ARMS for failed in FAILED_LINKS}
    indexed = {}
    for row in rows:
        try:
            key = (row["arm"], int(row["failed_links"]))
            if int(row["n_seeds"]) != 10:
                raise ValueError("summary CSV must aggregate ten seeds")
            for field in required - {"arm", "failed_links", "n_seeds"}:
                if not math.isfinite(float(row[field])):
                    raise ValueError("summary CSV has nonfinite numeric values")
        except (TypeError, ValueError) as exc:
            raise ValueError("summary CSV has invalid numeric values") from exc
        if key not in expected or key in indexed:
            raise ValueError("summary CSV has duplicate or unexpected rows")
        indexed[key] = row
    if set(indexed) != expected:
        raise ValueError("summary CSV must contain exactly twelve rows")
    return indexed


def render_figure(summary_path: Path, figures_root: Path) -> Path:
    import matplotlib.pyplot as plt

    summary = _read_summary(Path(summary_path))
    plot_style.apply_style(11)
    figure, axes = plt.subplots(1, 3, figsize=(13.0, 3.7))
    panels = (
        ("Avg FCT (us)", "avg_fct_us", "(a) Avg FCT (us)"),
        ("P99 FCT (us)", "p99_fct_us", "(b) P99 FCT (us)"),
        ("Goodput (Gbps)", "goodput_gbps", "(c) Goodput (Gbps)"),
    )
    bar_width = 0.23
    centers = (0.0, 1.2, 2.4)
    handles = []
    for panel_index, (ylabel, metric, title) in enumerate(panels):
        axis = axes[panel_index]
        for arm_index, (arm, label, color) in enumerate(ARMS):
            offset = (arm_index - 1.0) * bar_width
            values = [float(summary[(arm, failed)][f"mean_{metric}"]) for failed in FAILED_LINKS]
            lower = [
                value - float(summary[(arm, failed)][f"min_{metric}"])
                for value, failed in zip(values, FAILED_LINKS)
            ]
            upper = [
                float(summary[(arm, failed)][f"max_{metric}"]) - value
                for value, failed in zip(values, FAILED_LINKS)
            ]
            bars = axis.bar(
                [center + offset for center in centers],
                values,
                width=bar_width,
                color=color,
                yerr=[lower, upper],
                capsize=3,
                error_kw={"linewidth": 1.0},
                label=label,
            )
            if panel_index == 0:
                handles.append(bars[0])
        axis.set_title(title, fontsize=11)
        axis.set_ylabel(ylabel)
        axis.set_xticks(centers, FAILED_LABELS)
        axis.grid(axis="y", alpha=0.3)
        axis.set_axisbelow(True)
    figure.legend(handles, [label for _arm, label, _color in ARMS], loc="upper center", ncol=3, frameon=False)
    figure.tight_layout(rect=(0, 0, 1, 0.84))
    figures_root = Path(figures_root)
    figures_root.mkdir(parents=True, exist_ok=True)
    stem = figures_root / "m6_path_robust_signal"
    pdf_path = stem.with_suffix(".pdf")
    figure.savefig(pdf_path, bbox_inches="tight", pad_inches=0.04)
    figure.savefig(stem.with_suffix(".png"), bbox_inches="tight", pad_inches=0.04)
    plt.close(figure)
    return pdf_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, default=HERE / "data" / "aggregate" / "m6_summary.csv")
    parser.add_argument("--figures-root", type=Path, default=HERE / "figs")
    args = parser.parse_args(argv)
    render_figure(args.summary, args.figures_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
