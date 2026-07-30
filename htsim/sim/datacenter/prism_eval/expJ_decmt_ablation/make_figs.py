#!/usr/bin/env python3
"""Render the three-panel ExpJ DecMT component-ablation figure."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Iterable, Mapping

import run


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))
import plot_style  # noqa: E402

OUTPUT_BASENAME = "figJ1_decmt_ablation"
DISPLAY_LABELS = {
    "original_nscc": "Original NSCC",
    "matched_nscc": "Matched-Target NSCC",
    "floor_only": "Floor-Only",
    "decmt": "DecMT",
}
COLORS = ("#7f7f7f", "#4e79a7", "#f28e2b", "#59a14f")
PANEL_ARMS = (
    ("original_nscc", "ops"),
    ("matched_nscc", "reps"),
    ("floor_only", "ccc"),
    ("decmt", "prism"),
)
PANEL_METRICS = (
    ("mean_goodput_gbps", "std_goodput_gbps", "Goodput (Gbps)", 1.0, "figJ1_goodput"),
    ("mean_avg_fct_us", "std_avg_fct_us", "Average FCT (ms)", 1e-3, "figJ1_avg_fct"),
    ("mean_p99_fct_us", "std_p99_fct_us", "P99 FCT (ms)", 1e-3, "figJ1_p99_fct"),
)


def _normalize(summary: Iterable[Mapping[str, object]]) -> dict[tuple[str, int], dict[str, float | int | str]]:
    rows: dict[tuple[str, int], dict[str, float | int | str]] = {}
    numeric = (
        "n_seeds", "mean_goodput_gbps", "std_goodput_gbps", "mean_avg_fct_us",
        "std_avg_fct_us", "mean_p99_fct_us", "std_p99_fct_us",
    )
    for source in summary:
        try:
            arm = str(source["arm"])
            failed = int(source["failed_links"])
            row: dict[str, float | int | str] = {"arm": arm, "failed_links": failed}
            for name in numeric:
                row[name] = int(source[name]) if name == "n_seeds" else float(source[name])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid summary row") from exc
        key = (arm, failed)
        if key in rows:
            raise ValueError(f"duplicate summary row for {arm}/failed={failed}")
        rows[key] = row
    expected = {(arm, failed) for arm in run.ARMS for failed in run.FAILED_LINKS}
    if set(rows) != expected:
        raise ValueError("missing summary rows for locked ExpJ arms and failed-link controls")
    return rows


def _control_text(rows: Mapping[tuple[str, int], Mapping[str, float | int | str]]) -> str:
    parts = []
    for arm in run.ARMS:
        row = rows[(arm, 0)]
        parts.append(
            f"{DISPLAY_LABELS[arm]}: {float(row['mean_goodput_gbps']):.2f} Gbps, "
            f"{float(row['mean_avg_fct_us']) / 1e3:.3f}/{float(row['mean_p99_fct_us']) / 1e3:.3f} ms"
        )
    return "failed=0 control (goodput; avg/p99 FCT): " + " | ".join(parts)


def render_single_panels(
    rows: Mapping[tuple[str, int], Mapping[str, float | int | str]], output_dir: Path,
) -> None:
    """Render each failed=8 metric as a self-contained grouped-bar panel."""
    import matplotlib as mpl
    import matplotlib.pyplot as plt

    with mpl.rc_context():
        plot_style.apply_style(16)
        arms = tuple(run.ARMS)
        x = [0]
        group_width = 0.66
        bar_width = group_width / len(arms)
        for mean_name, std_name, ylabel, scale, stem in PANEL_METRICS:
            fig, axis = plt.subplots(figsize=(6.4, 2.8))
            for position, (arm, color_key) in enumerate(PANEL_ARMS):
                offsets = [index - group_width / 2 + bar_width * (position + 0.5) for index in x]
                values = [float(rows[(arm, 8)][mean_name]) * scale]
                errors = [float(rows[(arm, 8)][std_name]) * scale]
                axis.bar(offsets, values, bar_width, yerr=errors, capsize=2,
                         color=plot_style.COLORS[color_key], label=DISPLAY_LABELS[arm])
            axis.set_xticks(x, ["8"])
            axis.set_xlabel("Number of failed links")
            axis.set_ylabel(ylabel)
            axis.grid(axis="y", alpha=0.3)
            axis.legend(ncol=2, fontsize=9, frameon=False)
            plt.tight_layout()
            plot_style.save(fig, stem, output_dir)
            plt.close(fig)


def render(summary: Iterable[Mapping[str, object]], output_dir: Path) -> None:
    """Render failed=8 bars plus a compact failed=0 textual control comparison."""
    rows = _normalize(summary)
    output_dir = Path(output_dir)

    import matplotlib.pyplot as plt

    arms = tuple(run.ARMS)
    x = list(range(len(arms)))
    panels = tuple(metric[:4] for metric in PANEL_METRICS)
    fig, axes = plt.subplots(1, 3, figsize=(12.6, 4.5))
    for axis, (mean_name, std_name, title, scale) in zip(axes, panels):
        means = [float(rows[(arm, 8)][mean_name]) * scale for arm in arms]
        stds = [float(rows[(arm, 8)][std_name]) * scale for arm in arms]
        axis.bar(x, means, yerr=stds, capsize=3, color=COLORS, edgecolor="black", linewidth=0.5)
        axis.set_title(title)
        axis.set_xticks(x, [DISPLAY_LABELS[arm] for arm in arms], rotation=20, ha="right")
        axis.grid(axis="y", color="0.9", linewidth=0.7)
        axis.set_axisbelow(True)
    fig.text(0.5, 0.015, _control_text(rows), ha="center", va="bottom", fontsize=7)
    fig.tight_layout(rect=(0, 0.13, 1, 1))
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf = output_dir / f"{OUTPUT_BASENAME}.pdf"
    fig.savefig(pdf, bbox_inches="tight", pad_inches=0.04)
    fig.savefig(pdf.with_suffix(".png"), bbox_inches="tight", pad_inches=0.04, dpi=220)
    plt.close(fig)
    render_single_panels(rows, output_dir)


def _read_summary(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="ascii", newline="") as stream:
        return list(csv.DictReader(stream))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=HERE / "data" / "aggregate" / "summary.csv")
    parser.add_argument("--output", type=Path, default=HERE / "figs")
    args = parser.parse_args()
    render(_read_summary(args.input), args.output)


if __name__ == "__main__":
    main()
