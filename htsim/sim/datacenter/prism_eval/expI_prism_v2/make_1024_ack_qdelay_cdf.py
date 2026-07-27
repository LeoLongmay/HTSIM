#!/usr/bin/env python3
"""Render equal-seed-weighted ACK-delay and failure-sweep evidence."""

from __future__ import annotations

import argparse
import csv
import math
import random
import statistics
import sys
from bisect import bisect_right
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.axes_grid1.inset_locator import inset_axes

COMMON = Path(__file__).resolve().parent.parent / "common"
sys.path.insert(0, str(COMMON))
import metrics  # noqa: E402
import plot_style  # noqa: E402


# Keep ACK-CDF baselines visually identical to expA_delaydriven/figA1dd_avg_fct.
ARM_COLORS = {
    "ops": "tab:gray",
    "reps": "tab:blue",
    "swift": "tab:pink",
    "mswift": "tab:olive",
    "mnscc": "tab:brown",
    "strack": "tab:orange",
    "v2": "tab:green",
}
MAIN_ACK_QDELAY_XMAX_US = 25.0
# Match expA_delaydriven/figA1dd_avg_fct, rendered by render_main_perf_split().
REFERENCE_FIGSIZE_IN = (5.2, 3.8)
REFERENCE_FONT_SIZE_PT = 24
CDF_ARMS = {
    "ops": "OPS",
    "reps": "REPS",
    "strack": "STrack",
    "v2": "Prism",
}


def color_for_arm(arm: str) -> str:
    """Return the shared evaluation colour for a named ACK-CDF arm."""
    try:
        return ARM_COLORS[arm]
    except KeyError as error:
        raise ValueError(f"no plotting colour configured for arm {arm!r}") from error


def apply_reference_figure_style() -> None:
    """Use the canvas and base typography of figA1dd_avg_fct."""
    plot_style.apply_style(REFERENCE_FONT_SIZE_PT)


def render_cdf_legend(figs_dir: Path, arms: dict[str, str] = CDF_ARMS) -> None:
    """Write the shared standalone legend used by all 1024-node CDF panels."""
    from matplotlib.lines import Line2D

    apply_reference_figure_style()
    handles = [
        Line2D([], [], color=color_for_arm(arm), linewidth=1.8, label=label)
        for arm, label in arms.items()
    ]
    figure = plt.figure(figsize=(5.2, 0.55))
    figure.legend(
        handles=handles,
        loc="center",
        ncol=len(handles),
        frameon=False,
        fontsize=16,
        handlelength=1.8,
        handletextpad=0.4,
        columnspacing=0.9,
    )
    figs_dir.mkdir(parents=True, exist_ok=True)
    figure.savefig(figs_dir / "figI_1024_cdf_legend.png", dpi=180,
                   bbox_inches="tight", pad_inches=0.04)
    figure.savefig(figs_dir / "figI_1024_cdf_legend.pdf",
                   bbox_inches="tight", pad_inches=0.04)
    plt.close(figure)


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


def nearest(values: list[float], percentile_value: float) -> float:
    """Return the nearest-rank percentile for a nonempty sequence."""
    return percentile(values, percentile_value)


def bootstrap_delta_band(
    reference_samples: list[list[float]],
    arm_samples: list[list[float]],
    grid: list[float],
    draws: int = 2000,
    seed: int = 20260725,
) -> tuple[list[float], list[float], list[float]]:
    """Return seed-resampled target-minus-reference ECDF bands.

    Corresponding seed lists are resampled together, preserving per-seed pairing
    while giving every seed one vote regardless of its trace length.
    """
    if len(reference_samples) != len(arm_samples):
        raise ValueError("reference and arm must have the same number of seeds")
    if not reference_samples or draws <= 0:
        raise ValueError("samples and draws must be nonempty")
    rng = random.Random(seed)
    draws_by_x = [[] for _ in grid]
    for _ in range(draws):
        picks = [rng.randrange(len(reference_samples)) for _ in reference_samples]
        reference = mean_seed_ecdf([reference_samples[index] for index in picks], grid)
        arm = mean_seed_ecdf([arm_samples[index] for index in picks], grid)
        for index, value in enumerate(arm):
            draws_by_x[index].append(value - reference[index])
    mean = [
        arm - reference
        for arm, reference in zip(
            mean_seed_ecdf(arm_samples, grid), mean_seed_ecdf(reference_samples, grid)
        )
    ]
    return (
        mean,
        [nearest(values, 0.025) for values in draws_by_x],
        [nearest(values, 0.975) for values in draws_by_x],
    )


def _trace_path(data_dir: Path, arm: str, seed: int) -> Path:
    return data_dir / f"{arm}_s{seed}.csv"


def ack_cdf_title(failure: int) -> str:
    return f"1024-node many2many, failed={failure}; equal-weight five-seed ECDF"


def plot_grid(values: list[float], upper: float, max_points: int = 4096) -> list[float]:
    """Bound plotting work while retaining evenly-spaced ECDF order statistics."""
    ordered = sorted(value for value in values if value <= upper)
    if not ordered:
        return [0.0, upper]
    stride = max(1, math.ceil(len(ordered) / max_points))
    return sorted({0.0, upper, *ordered[::stride]})


def render_ack_evidence(
    data_dir: Path, output_stem: Path, arms: dict[str, str], seeds: list[int]
) -> None:
    """Render seed-weighted full, low-delay, and relative ACK CDF evidence."""
    if not arms or not seeds:
        raise ValueError("arms and seeds must be nonempty")
    if "reps" not in arms:
        raise ValueError("arms must include REPS reference key 'reps'")

    samples_by_arm = {
        arm: [load_qdelay_us(_trace_path(data_dir, arm, seed)) for seed in seeds]
        for arm in arms
    }
    all_values = [
        value for arm_samples in samples_by_arm.values() for samples in arm_samples for value in samples
    ]
    full_grid = plot_grid(all_values, max(all_values))
    zoom_grid = plot_grid(all_values, upper=25.0)

    figure, axes = plt.subplots(1, 3, figsize=(13.0, 4.1), layout="constrained")
    full_axis, zoom_axis, delta_axis = axes
    for arm, label in arms.items():
        color = color_for_arm(arm)
        samples = samples_by_arm[arm]
        full_axis.plot(full_grid, mean_seed_ecdf(samples, full_grid), color=color, linewidth=1.8, label=label)
        zoom_axis.plot(zoom_grid, mean_seed_ecdf(samples, zoom_grid), color=color, linewidth=1.8, label=label)

    reference_samples = samples_by_arm["reps"]
    for arm, label in arms.items():
        if arm == "reps":
            continue
        color = color_for_arm(arm)
        mean, lower, upper = bootstrap_delta_band(reference_samples, samples_by_arm[arm], full_grid)
        delta_axis.fill_between(full_grid, [value * 100.0 for value in lower],
                                [value * 100.0 for value in upper], color=color, alpha=0.18)
        delta_axis.plot(full_grid, [value * 100.0 for value in mean], color=color, linewidth=1.8,
                        label=f"{label} − {arms['reps']}")

    full_axis.set_xlim(0.0, full_grid[-1])
    zoom_axis.set_xlim(0.0, 25.0)
    for axis in (full_axis, zoom_axis):
        axis.set_ylim(0.0, 1.01)
        axis.set_xlabel("ACK-derived end-to-end queuing delay (us)")
        axis.set_ylabel("Empirical CDF")
        axis.grid(alpha=0.25)
        axis.legend(fontsize=8)
    full_axis.set_title("full range")
    zoom_axis.set_title("low delay")
    delta_axis.axhline(0.0, color="black", linewidth=1.0, linestyle="--")
    delta_axis.set_xlim(0.0, full_grid[-1])
    delta_axis.set_xlabel("ACK-derived end-to-end queuing delay (us)")
    delta_axis.set_ylabel("Δ ECDF vs REPS+NSCC (percentage points)")
    delta_axis.grid(alpha=0.25)
    delta_axis.legend(fontsize=8)
    figure.suptitle("1024-node many2many, failed=16; five seed-local ECDFs equally weighted")
    output_stem.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_stem.with_suffix(".png"), dpi=180, bbox_inches="tight")
    figure.savefig(output_stem.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(figure)


def render(
    data_dir: Path, output_stem: Path, arms: dict[str, str], seeds: list[int], failure: int = 16
) -> None:
    if not arms or not seeds:
        raise ValueError("arms and seeds must be nonempty")

    samples_by_arm: dict[str, list[list[float]]] = {}
    for arm in arms:
        samples_by_arm[arm] = [load_qdelay_us(_trace_path(data_dir, arm, seed)) for seed in seeds]

    all_values = [value for samples in samples_by_arm.values() for seed in samples for value in seed]
    main_xmax = MAIN_ACK_QDELAY_XMAX_US
    full_xmax = max(all_values)
    grid = plot_grid(all_values, main_xmax)
    full_grid = plot_grid(all_values, full_xmax)

    apply_reference_figure_style()
    figure, axis = plt.subplots(figsize=REFERENCE_FIGSIZE_IN, layout="constrained")
    inset = inset_axes(
        axis,
        width="100%",
        height="100%",
        loc="lower left",
        bbox_to_anchor=(0.64, 0.08, 0.32, 0.32),
        bbox_transform=axis.transAxes,
        borderpad=0,
    )
    for arm, label in arms.items():
        color = color_for_arm(arm)
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
    axis.set_xlabel("Queueing delay (us)")
    axis.set_ylabel("CDF")
    axis.grid(alpha=0.25)
    inset.set_xlim(0.0, full_xmax)
    inset.set_ylim(0.0, 1.01)
    inset.set_title("full range", fontsize=14)
    inset.tick_params(labelsize=14)
    inset.grid(alpha=0.2)
    output_stem.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_stem.with_suffix(".png"), dpi=180, bbox_inches="tight", pad_inches=0.04)
    figure.savefig(output_stem.with_suffix(".pdf"), bbox_inches="tight", pad_inches=0.04)
    plt.close(figure)


def _mean_sem(values: list[float]) -> tuple[float, float]:
    """Return arithmetic mean and sample standard error for seed-local values."""
    if not values:
        raise ValueError("sample mean requires at least one value")
    if any(not math.isfinite(value) for value in values):
        raise ValueError("sample mean rejects non-finite seed metrics")
    mean = statistics.mean(values)
    sem = statistics.stdev(values) / math.sqrt(len(values)) if len(values) > 1 else 0.0
    return mean, sem


def _flow_path(data_dir: Path, arm: str, failure: int, seed: int) -> Path:
    return data_dir / f"double_{arm}_f{failure}_s{seed}.flow.txt"


def aggregate_failure_sweep(
    data_dir: Path, arms: dict[str, str], failures: list[int], seeds: list[int]
) -> dict[str, dict[int, dict[str, tuple[float, float]]]]:
    """Aggregate each arm/failure cell as equal-weight seed mean and sample SEM."""
    if not arms or not failures or not seeds:
        raise ValueError("arms, failures, and seeds must be nonempty")
    aggregate: dict[str, dict[int, dict[str, tuple[float, float]]]] = {}
    for arm in arms:
        aggregate[arm] = {}
        for failure in failures:
            seed_metrics = {
                "goodput_gbps": [],
                "mean_fct_us": [],
                "p99_fct_us": [],
                "completion_rate": [],
            }
            for seed in seeds:
                flow_path = _flow_path(data_dir, arm, failure, seed)
                stats = metrics.fct_stats(flow_path)
                seed_metrics["goodput_gbps"].append(
                    metrics.aggregate_goodput_gbps(flow_path)
                )
                seed_metrics["mean_fct_us"].append(stats["avg_s"] * 1e6)
                seed_metrics["p99_fct_us"].append(stats["p99_s"] * 1e6)
                seed_metrics["completion_rate"].append(stats["completion_rate"])
            aggregate[arm][failure] = {
                name: _mean_sem(values) for name, values in seed_metrics.items()
            }
    return aggregate


def engagement_fraction(path: Path) -> float:
    """Return the arithmetic mean of the Prism v2 engaged flag in CSV column 9."""
    engaged: list[int] = []
    with path.open(newline="", encoding="ascii") as stream:
        for line_number, row in enumerate(csv.reader(stream), start=1):
            if len(row) != 12:
                raise ValueError(f"{path}:{line_number}: expected twelve columns")
            try:
                value = int(row[9])
            except ValueError as error:
                raise ValueError(f"{path}:{line_number}: invalid engaged flag") from error
            if value not in (0, 1):
                raise ValueError(f"{path}:{line_number}: engaged flag must be zero or one")
            engaged.append(value)
    if not engaged:
        raise ValueError(f"{path}: no epoch rows")
    return statistics.mean(engaged)


def _flow_fcts_us(path: Path) -> list[float]:
    starts, finishes = metrics.parse_flow_events(path)
    return sorted(
        (finish_time - starts[key]) * 1e6
        for key, (finish_time, _bytes) in finishes.items()
        if key in starts
    )


def _save_figure(figure, figures_dir: Path, stem: str) -> None:
    figures_dir.mkdir(parents=True, exist_ok=True)
    figure.savefig(figures_dir / f"{stem}.png", dpi=180, bbox_inches="tight")
    figure.savefig(figures_dir / f"{stem}.pdf", bbox_inches="tight")
    plt.close(figure)


def render_failure_sweep(
    data_dir: Path,
    figs_dir: Path,
    arms: dict[str, str],
    failures: list[int],
    seeds: list[int],
    fct_cdf_failure: int = 32,
) -> None:
    """Render performance, selected FCT CDF, and Prism engagement evidence."""
    if "v2" not in arms:
        raise ValueError("arms must include Prism v2 key 'v2'")
    if fct_cdf_failure not in failures:
        raise ValueError("FCT CDF failure must be included in failure sweep")
    apply_reference_figure_style()
    aggregate = aggregate_failure_sweep(data_dir, arms, failures, seeds)

    performance, axes = plt.subplots(
        3, 1, figsize=(6.8, 9.0), sharex=True, layout="constrained"
    )
    panels = (
        ("goodput_gbps", "Goodput (Gbps)"),
        ("mean_fct_us", "Mean FCT (us)"),
        ("p99_fct_us", "P99 FCT (us)"),
    )
    for axis, (metric_name, y_label) in zip(axes, panels):
        for arm, label in arms.items():
            values = [aggregate[arm][failure][metric_name][0] for failure in failures]
            errors = [aggregate[arm][failure][metric_name][1] for failure in failures]
            axis.errorbar(
                failures,
                values,
                yerr=errors,
                marker="o",
                linewidth=1.8,
                capsize=3,
                color=color_for_arm(arm),
                label=label,
            )
            for failure, value in zip(failures, values):
                completion = aggregate[arm][failure]["completion_rate"][0]
                if completion < 0.999 and math.isfinite(value):
                    axis.annotate(
                        f"CR={completion:.3f}",
                        (failure, value),
                        xytext=(3, 4),
                        textcoords="offset points",
                        color="firebrick",
                        fontsize=6,
                    )
        axis.set_ylabel(y_label)
        axis.grid(alpha=0.25)
    axes[0].legend(fontsize=8)
    axes[-1].set_xlabel("Failed links")
    axes[-1].set_xticks(failures)
    performance.suptitle("1024-node many2many failure sweep; seed mean ± sample SEM")
    _save_figure(performance, figs_dir, "figI_1024_failure_sweep")

    fct_samples = {
        arm: [
            [value / 1000.0 for value in _flow_fcts_us(
                _flow_path(data_dir, arm, fct_cdf_failure, seed)
            )]
            for seed in seeds
        ]
        for arm in arms
    }
    all_fcts = [
        value
        for arm_samples in fct_samples.values()
        for seed_samples in arm_samples
        for value in seed_samples
    ]
    if not all_fcts:
        raise ValueError("selected failure flow logs contain no completed flows")
    fct_grid = plot_grid(all_fcts, max(all_fcts))
    fct_figure, fct_axis = plt.subplots(figsize=REFERENCE_FIGSIZE_IN, layout="constrained")
    for arm, label in arms.items():
        fct_axis.plot(
            fct_grid,
            mean_seed_ecdf(fct_samples[arm], fct_grid),
            linewidth=1.8,
            color=color_for_arm(arm),
            label=label,
        )
    fct_axis.set_xlim(0.0, fct_grid[-1])
    fct_axis.set_ylim(0.0, 1.01)
    fct_axis.set_xlabel("Avg FCT (ms)")
    fct_axis.set_ylabel("CDF")
    fct_axis.grid(alpha=0.25)
    _save_figure(fct_figure, figs_dir, f"figI_1024_f{fct_cdf_failure}_fct_cdf")
    render_cdf_legend(figs_dir, arms)

    engagement = {
        failure: _mean_sem(
            [
                engagement_fraction(
                    data_dir / f"double_v2_f{failure}_s{seed}.epoch.csv"
                )
                for seed in seeds
            ]
        )
        for failure in failures
    }
    engagement_figure, engagement_axis = plt.subplots(
        figsize=(6.8, 4.0), layout="constrained"
    )
    engagement_axis.errorbar(
        failures,
        [engagement[failure][0] for failure in failures],
        yerr=[engagement[failure][1] for failure in failures],
        marker="o",
        linewidth=1.8,
        capsize=3,
        color=color_for_arm("v2"),
        label=arms["v2"],
    )
    engagement_axis.set_ylim(0.0, 1.0)
    engagement_axis.set_xticks(failures)
    engagement_axis.set_xlabel("Failed links")
    engagement_axis.set_ylabel("Engaged epoch fraction")
    engagement_axis.set_title("Prism v2 engagement; seed mean ± sample SEM")
    engagement_axis.grid(alpha=0.25)
    engagement_axis.legend(fontsize=8)
    _save_figure(
        engagement_figure, figs_dir, "figI_1024_v2_engagement_sweep"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--output-stem", type=Path)
    parser.add_argument("--simple-cdf", action="store_true",
                        help="write the two-panel-compatible CDF with a full-range inset")
    parser.add_argument("--failure", type=int, default=16,
                        help="failed-link count to state on a simple CDF title")
    parser.add_argument("--sweep-data-dir", type=Path)
    parser.add_argument("--figs-dir", type=Path)
    parser.add_argument("--failures", type=int, nargs="+", default=[0, 8, 16, 24, 32])
    parser.add_argument("--seeds", type=int, nargs="+", default=[13, 14, 15, 16, 17])
    parser.add_argument("--fct-cdf-failure", type=int, default=32)
    args = parser.parse_args()
    arms = CDF_ARMS
    if args.sweep_data_dir is not None or args.figs_dir is not None:
        if args.sweep_data_dir is None or args.figs_dir is None:
            parser.error("--sweep-data-dir and --figs-dir must be provided together")
        if args.fct_cdf_failure not in args.failures:
            parser.error("--fct-cdf-failure must be present in --failures")
        render_failure_sweep(
            args.sweep_data_dir,
            args.figs_dir,
            arms,
            args.failures,
            args.seeds,
            args.fct_cdf_failure,
        )
    else:
        if args.data_dir is None or args.output_stem is None:
            parser.error("--data-dir and --output-stem must be provided together")
        if args.simple_cdf:
            render(args.data_dir, args.output_stem, arms, args.seeds, args.failure)
            render_cdf_legend(args.output_stem.parent, arms)
        else:
            render_ack_evidence(args.data_dir, args.output_stem, arms, args.seeds)


if __name__ == "__main__":
    main()
