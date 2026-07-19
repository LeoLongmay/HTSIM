#!/usr/bin/env python3
"""Render the M4 fixed-arm performance ablation from its aggregate CSV only."""

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
    ("residual_prism", "Residual Prism", plot_style.COLORS["strack"]),
    ("full_prism", "Full Prism", plot_style.COLORS["laps"]),
)
SCENARIOS = ("recoverable", "persistent")


def _read_summary(path: Path) -> dict[tuple[str, str], dict]:
    required = {
        "arm", "scenario", "n_seeds", "mean_avg_fct_us", "mean_p99_fct_us", "mean_goodput_gbps",
        "mean_completion_rate", "min_avg_fct_us", "max_avg_fct_us", "min_p99_fct_us", "max_p99_fct_us",
        "min_goodput_gbps", "max_goodput_gbps",
    }
    try:
        with path.open(newline="", encoding="ascii") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None or not required.issubset(reader.fieldnames):
                raise ValueError("summary CSV has missing fields")
            rows = list(reader)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise ValueError(f"cannot read summary CSV: {path}") from exc
    expected = {(arm, scenario) for arm, _label, _color in ARMS for scenario in SCENARIOS}
    indexed = {}
    for row in rows:
        key = (row.get("arm"), row.get("scenario"))
        if key not in expected or key in indexed:
            raise ValueError("summary CSV has duplicate or unexpected rows")
        try:
            if int(row["n_seeds"]) != 3:
                raise ValueError("summary CSV must aggregate three seeds")
            for field in required - {"arm", "scenario", "n_seeds"}:
                if not math.isfinite(float(row[field])):
                    raise ValueError("summary CSV has nonfinite numeric values")
        except (TypeError, ValueError) as exc:
            raise ValueError("summary CSV has invalid numeric values") from exc
        indexed[key] = row
    if set(indexed) != expected:
        raise ValueError("summary CSV must contain exactly eight rows")
    return indexed


def render_figure(summary_path: Path, figures_root: Path) -> Path:
    import matplotlib.pyplot as plt

    summary = _read_summary(Path(summary_path))
    plot_style.apply_style(11)
    figure, axes = plt.subplots(1, 3, figsize=(12.0, 3.7))
    panels = (
        ("Avg FCT (us)", "avg_fct_us", "(a) Avg FCT (us)"),
        ("P99 FCT (us)", "p99_fct_us", "(b) P99 FCT (us)"),
        ("Goodput (Gbps)", "goodput_gbps", "(c) Goodput (Gbps)"),
    )
    bar_width = 0.18
    group_centers = (0.0, 1.15)
    handles = []
    for panel_index, (ylabel, metric, title) in enumerate(panels):
        axis = axes[panel_index]
        for arm_index, (arm, label, color) in enumerate(ARMS):
            offset = (arm_index - 1.5) * bar_width
            values = [float(summary[(arm, scenario)][f"mean_{metric}"]) for scenario in SCENARIOS]
            lower = [
                value - float(summary[(arm, scenario)][f"min_{metric}"])
                for value, scenario in zip(values, SCENARIOS)
            ]
            upper = [
                float(summary[(arm, scenario)][f"max_{metric}"]) - value
                for value, scenario in zip(values, SCENARIOS)
            ]
            bars = axis.bar(
                [center + offset for center in group_centers],
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
        axis.set_xticks(group_centers, ("Recoverable", "Persistent"))
        axis.grid(axis="y", alpha=0.3)
        axis.set_axisbelow(True)
    figure.legend(handles, [label for _arm, label, _color in ARMS], loc="upper center", ncol=4, frameon=False)
    figure.tight_layout(rect=(0, 0, 1, 0.84))
    figures_root = Path(figures_root)
    figures_root.mkdir(parents=True, exist_ok=True)
    pdf_path = figures_root / "m4_performance_ablation.pdf"
    png_path = figures_root / "m4_performance_ablation.png"
    figure.savefig(pdf_path, bbox_inches="tight", pad_inches=0.04)
    figure.savefig(png_path, bbox_inches="tight", pad_inches=0.04)
    plt.close(figure)
    return pdf_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, default=HERE / "data" / "aggregate" / "m4_summary.csv")
    parser.add_argument("--figures-root", type=Path, default=HERE / "figs")
    args = parser.parse_args(argv)
    render_figure(args.summary, args.figures_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
