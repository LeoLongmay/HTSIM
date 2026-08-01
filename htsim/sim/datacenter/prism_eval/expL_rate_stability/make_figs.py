#!/usr/bin/env python3
"""Render ExpL aggregate delivery-rate stability publication figures."""

from __future__ import annotations

import argparse
import csv
import math
import statistics
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Sequence

import matplotlib as mpl

mpl.rcParams["pdf.fonttype"] = 42
mpl.rcParams["ps.fonttype"] = 42

import matplotlib.pyplot as plt


HERE = Path(__file__).resolve().parent
LABELS = {"ops": "OPS", "reps": "REPS", "strack": "STrack", "decmt": "DecMT"}
COLORS = {"ops": "tab:gray", "reps": "tab:blue", "strack": "tab:orange", "decmt": "tab:green"}
PRIMARY_ARMS = tuple(LABELS)
CONDITIONS = ("symmetric", "asymmetric")
BETA_ORDER = ("1.0", "0.5", "0.3", "0.15")
BETA_COLORS = ("tab:blue", "tab:orange", "tab:green", "tab:red")
RATE_SERIES_FIELDS = (
    "kind", "condition", "arm", "beta", "seed", "time_us", "rate_gbps",
    "display_rate_gbps",
)
STABILITY_SUMMARY_FIELDS = (
    "kind", "condition", "arm", "beta", "seed", "valid", "steady_samples",
    "steady_mean_gbps", "coefficient_of_variation", "normalized_p95_p5",
    "settling_time_us",
)


def _read_csv(path: Path, expected_fields: Sequence[str]) -> list[dict[str, str]]:
    """Read one exact analysis CSV contract without accepting partial output."""
    with path.open(encoding="ascii", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(expected_fields):
            raise ValueError(f"unexpected ExpL CSV schema in {path}")
        return list(reader)


def _curve(rows: Iterable[dict[str, str]], **match: str) -> tuple[list[float], list[float]]:
    """Select and validate one aggregate display trajectory, converted to milliseconds."""
    selected = [row for row in rows if row.get("seed") == "aggregate" and all(
        row.get(field) == value for field, value in match.items()
    )]
    if not selected:
        raise ValueError(f"missing aggregate ExpL trajectory for {match}")
    try:
        points = sorted((float(row["time_us"]) / 1000.0, float(row["display_rate_gbps"])) for row in selected)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid aggregate ExpL trajectory for {match}") from exc
    if any(not (math.isfinite(time_ms) and math.isfinite(rate)) for time_ms, rate in points):
        raise ValueError(f"non-finite aggregate ExpL trajectory for {match}")
    if len({time_ms for time_ms, _rate in points}) != len(points):
        raise ValueError(f"duplicate aggregate ExpL timestamp for {match}")
    return [time_ms for time_ms, _rate in points], [rate for _time_ms, rate in points]


def _decmt_iqr(rows: Iterable[dict[str, str]], condition: str) -> tuple[list[float], list[float], list[float]]:
    """Return pointwise inclusive 25th--75th percentiles for five DecMT seed traces."""
    samples: dict[float, list[float]] = defaultdict(list)
    seeds: set[str] = set()
    for row in rows:
        if not (
            row.get("kind") == "primary"
            and row.get("condition") == condition
            and row.get("arm") == "decmt"
            and row.get("seed") != "aggregate"
        ):
            continue
        try:
            time_ms = float(row["time_us"]) / 1000.0
            rate = float(row["rate_gbps"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid DecMT seed trajectory for {condition}") from exc
        if not (math.isfinite(time_ms) and math.isfinite(rate)):
            raise ValueError(f"non-finite DecMT seed trajectory for {condition}")
        samples[time_ms].append(rate)
        seeds.add(str(row["seed"]))
    if len(seeds) != 5 or not samples or any(len(values) != 5 for values in samples.values()):
        raise ValueError(f"expected five complete DecMT seed trajectories for {condition}")
    ordered = sorted(samples.items())
    lower, upper = [], []
    for _time_ms, values in ordered:
        quartiles = statistics.quantiles(values, n=4, method="inclusive")
        lower.append(quartiles[0])
        upper.append(quartiles[2])
    return [time_ms for time_ms, _values in ordered], lower, upper


def _save(fig: plt.Figure, output_dir: Path, stem: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_dir / f"{stem}.png", dpi=200, bbox_inches="tight")
    fig.savefig(output_dir / f"{stem}.pdf", bbox_inches="tight")
    plt.close(fig)


def _render_primary(rate_rows: list[dict[str, str]], output_dir: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.8), sharey=True)
    for axis, condition in zip(axes, CONDITIONS):
        band_x, lower, upper = _decmt_iqr(rate_rows, condition)
        axis.fill_between(band_x, lower, upper, color=COLORS["decmt"], alpha=0.20, linewidth=0, zorder=1)
        for arm in PRIMARY_ARMS:
            x, y = _curve(rate_rows, kind="primary", condition=condition, arm=arm, beta="")
            axis.plot(x, y, color=COLORS[arm], label=LABELS[arm], linewidth=1.8, zorder=2)
        axis.set_xlabel("Time (ms)")
        axis.grid(True, alpha=0.25)
    axes[0].set_ylabel("Aggregate delivery rate (Gbps)")
    axes[0].legend(frameon=False, loc="best")
    fig.tight_layout()
    _save(fig, output_dir, "figL1_rate_timeseries")


def _render_beta(rate_rows: list[dict[str, str]], output_dir: Path) -> None:
    fig, axis = plt.subplots(figsize=(3.6, 2.8))
    for beta, color in zip(BETA_ORDER, BETA_COLORS):
        x, y = _curve(rate_rows, kind="beta", condition="", arm="", beta=beta)
        axis.plot(x, y, color=color, label=f"β={beta}", linewidth=1.8)
    axis.set_xlabel("Time (ms)")
    axis.set_ylabel("Aggregate delivery rate (Gbps)")
    axis.grid(True, alpha=0.25)
    axis.legend(frameon=False, loc="best")
    fig.tight_layout()
    _save(fig, output_dir, "figL2_beta_timeseries")


def render(data_dir: Path, output_dir: Path) -> None:
    """Render both ExpL figures from the exact CSV contract written by ``analyze.py``."""
    data_dir = Path(data_dir)
    output_dir = Path(output_dir)
    rate_rows = _read_csv(data_dir / "rate_series.csv", RATE_SERIES_FIELDS)
    _read_csv(data_dir / "stability_summary.csv", STABILITY_SUMMARY_FIELDS)
    _render_primary(rate_rows, output_dir)
    _render_beta(rate_rows, output_dir)


def _write_selftest_csvs(data_dir: Path) -> None:
    """Create a complete tiny analysis bundle solely inside the caller's temporary directory."""
    data_dir.mkdir(parents=True)
    rows: list[dict[str, object]] = []
    for condition, baseline in (("symmetric", 80.0), ("asymmetric", 60.0)):
        for index, arm in enumerate(PRIMARY_ARMS):
            for time_us, rise in ((0.0, 0.0), (1000.0, 10.0)):
                rows.append({"kind": "primary", "condition": condition, "arm": arm, "beta": "",
                             "seed": "aggregate", "time_us": time_us, "rate_gbps": baseline + index + rise,
                             "display_rate_gbps": baseline + index + rise})
        for seed, offset in zip((13, 14, 15, 16, 17), (-4.0, -2.0, 0.0, 2.0, 8.0)):
            for time_us, rise in ((0.0, 0.0), (1000.0, 10.0)):
                rows.append({"kind": "primary", "condition": condition, "arm": "decmt", "beta": "",
                             "seed": seed, "time_us": time_us, "rate_gbps": baseline + 3.0 + offset + rise,
                             "display_rate_gbps": ""})
    for beta, offset in zip(BETA_ORDER, (6.0, 4.0, 2.0, 0.0)):
        for time_us, rise in ((0.0, 0.0), (1000.0, 8.0)):
            rows.append({"kind": "beta", "condition": "", "arm": "", "beta": beta,
                         "seed": "aggregate", "time_us": time_us, "rate_gbps": 50.0 + offset + rise,
                         "display_rate_gbps": 50.0 + offset + rise})
    with (data_dir / "rate_series.csv").open("w", encoding="ascii", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=RATE_SERIES_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    with (data_dir / "stability_summary.csv").open("w", encoding="ascii", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=STABILITY_SUMMARY_FIELDS, lineterminator="\n")
        writer.writeheader()


def _selftest() -> None:
    with tempfile.TemporaryDirectory(prefix="expL-make-figs-") as temporary_dir:
        root = Path(temporary_dir)
        _write_selftest_csvs(root / "data")
        render(root / "data", root / "figs")
        for stem in ("figL1_rate_timeseries", "figL2_beta_timeseries"):
            for extension in ("png", "pdf"):
                if not (root / "figs" / f"{stem}.{extension}").is_file():
                    raise RuntimeError(f"self-test failed to write {stem}.{extension}")
    print("make_figs self-test: PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=HERE / "data")
    parser.add_argument("--figs", type=Path, default=HERE / "figs")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        _selftest()
    else:
        render(args.data, args.figs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
