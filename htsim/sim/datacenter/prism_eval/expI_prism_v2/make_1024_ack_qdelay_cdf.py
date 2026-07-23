#!/usr/bin/env python3
"""Render an equal-seed-weighted CDF of genuine ACK queueing-delay samples."""

from __future__ import annotations

import csv
import math
import argparse
from bisect import bisect_right
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.axes_grid1.inset_locator import inset_axes


COLORS = ("#4c78a8", "#f58518", "#54a24b", "#e45756")


def load_qdelay_us(path: Path) -> list[float]:
    """Read the eight-column ACK_QDELAY trace and return finite delay samples in us."""
    values: list[float] = []
    with path.open(newline="", encoding="ascii") as stream:
        for line_number, row in enumerate(csv.reader(stream), start=1):
            if len(row) != 8:
                raise ValueError(f"{path}:{line_number}: expected eight columns")
            try:
                qdelay_ns = int(row[5])
            except ValueError as error:
                raise ValueError(f"{path}:{line_number}: invalid qdelay_ns") from error
            if qdelay_ns < 0:
                raise ValueError(f"{path}:{line_number}: negative qdelay_ns")
            value = qdelay_ns / 1000.0
            if not math.isfinite(value):
                raise ValueError(f"{path}:{line_number}: non-finite qdelay")
            values.append(value)
    if not values:
        raise ValueError(f"{path}: no ACK qdelay samples")
    return values


def mean_seed_ecdf(seed_samples: list[list[float]], grid: list[float]) -> list[float]:
    """Average seed-local ECDFs; each seed has exactly one equal-weight vote."""
    if not seed_samples or any(not samples for samples in seed_samples):
        raise ValueError("all seeds must have nonempty samples")
    ordered_samples = [sorted(samples) for samples in seed_samples]
    return [sum(bisect_right(samples, point) / len(samples) for samples in ordered_samples)
            / len(ordered_samples) for point in grid]


def percentile(values: list[float], percentile_value: float) -> float:
    if not values or not 0.0 < percentile_value <= 1.0:
        raise ValueError("percentile requires nonempty values and 0 < p <= 1")
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(percentile_value * len(ordered)) - 1)]


def _trace_path(data_dir: Path, arm: str, seed: int) -> Path:
    return data_dir / f"{arm}_s{seed}.csv"


def plot_grid(values: list[float], upper: float, max_points: int = 4096) -> list[float]:
    """Bound plotting work while retaining evenly-spaced ECDF order statistics."""
    ordered = sorted(value for value in values if value <= upper)
    if not ordered:
        return [0.0, upper]
    stride = max(1, math.ceil(len(ordered) / max_points))
    return sorted({0.0, upper, *ordered[::stride]})


def render(data_dir: Path, output_stem: Path, arms: dict[str, str], seeds: list[int]) -> None:
    if not arms or not seeds:
        raise ValueError("arms and seeds must be nonempty")

    samples_by_arm: dict[str, list[list[float]]] = {}
    for arm in arms:
        samples_by_arm[arm] = [load_qdelay_us(_trace_path(data_dir, arm, seed)) for seed in seeds]

    all_values = [value for samples in samples_by_arm.values() for seed in samples for value in seed]
    main_xmax = max(percentile([value for seed in samples for value in seed], 0.999)
                    for samples in samples_by_arm.values())
    full_xmax = max(all_values)
    grid = plot_grid(all_values, main_xmax)
    full_grid = plot_grid(all_values, full_xmax)

    figure, axis = plt.subplots(figsize=(7.4, 4.5), layout="constrained")
    inset = inset_axes(axis, width="42%", height="42%", loc="lower right", borderpad=2.0)
    for index, (arm, label) in enumerate(arms.items()):
        color = COLORS[index % len(COLORS)]
        seed_samples = samples_by_arm[arm]
        axis.plot(grid, mean_seed_ecdf(seed_samples, grid), color=color, linewidth=1.8, label=label)
        inset.plot(full_grid, mean_seed_ecdf(seed_samples, full_grid), color=color, linewidth=1.3)
        flattened = [value for samples in seed_samples for value in samples]
        print(f"{label}: samples={len(flattened)} "
              f"p50={percentile(flattened, 0.50):.3f}us "
              f"p95={percentile(flattened, 0.95):.3f}us "
              f"p99={percentile(flattened, 0.99):.3f}us")

    axis.set_xlim(0.0, main_xmax)
    axis.set_ylim(0.0, 1.01)
    axis.set_xlabel("ACK-derived end-to-end queuing delay (us)")
    axis.set_ylabel("Empirical CDF")
    axis.set_title("1024-node many2many, failed=16; equal-weight five-seed ECDF")
    axis.grid(alpha=0.25)
    axis.legend(fontsize=8)
    inset.set_xlim(0.0, full_xmax)
    inset.set_ylim(0.0, 1.01)
    inset.set_title("full range", fontsize=8)
    inset.tick_params(labelsize=7)
    inset.grid(alpha=0.2)
    output_stem.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_stem.with_suffix(".png"), dpi=180, bbox_inches="tight")
    figure.savefig(output_stem.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-stem", type=Path, required=True)
    parser.add_argument("--seeds", type=int, nargs="+", default=[13, 14, 15, 16, 17])
    args = parser.parse_args()
    render(args.data_dir, args.output_stem, {
        "ops": "OPS+NSCC",
        "reps": "REPS+NSCC",
        "strack": "REPS+STrack",
        "v2": "REPS+Prism v2-full",
    }, args.seeds)


if __name__ == "__main__":
    main()
