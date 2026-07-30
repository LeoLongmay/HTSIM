#!/usr/bin/env python3
"""Render the three-panel ExpJ DecMT component-ablation figure."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Iterable, Mapping

import run


HERE = Path(__file__).resolve().parent
OUTPUT_BASENAME = "figJ1_decmt_ablation"
DISPLAY_LABELS = {
    "original_nscc": "Original NSCC",
    "matched_nscc": "Matched-Target NSCC",
    "floor_only": "Floor-Only",
    "decmt": "DecMT",
}
COLORS = ("#7f7f7f", "#4e79a7", "#f28e2b", "#59a14f")


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


def render(summary: Iterable[Mapping[str, object]], output_dir: Path) -> None:
    """Render failed=8 bars plus a compact failed=0 textual control comparison."""
    rows = _normalize(summary)
    output_dir = Path(output_dir)

    import matplotlib.pyplot as plt

    arms = tuple(run.ARMS)
    x = list(range(len(arms)))
    panels = (
        ("mean_goodput_gbps", "std_goodput_gbps", "Goodput (Gbps)", 1.0),
        ("mean_avg_fct_us", "std_avg_fct_us", "Average FCT (ms)", 1e-3),
        ("mean_p99_fct_us", "std_p99_fct_us", "P99 FCT (ms)", 1e-3),
    )
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
