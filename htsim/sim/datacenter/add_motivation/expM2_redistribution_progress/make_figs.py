#!/usr/bin/env python3
"""Render compact controlled-M2 diagnostics from aggregate CSV files."""

from __future__ import annotations

import argparse
import csv
import math
import os
from pathlib import Path


HERE = Path(__file__).resolve().parent
DATA_ROOT = HERE / "data" / "controlled"
FIGS = HERE / "figs" / "controlled"
_CACHE_DIR = DATA_ROOT / ".matplotlib-cache"
if "MPLCONFIGDIR" not in os.environ:
    os.environ["MPLCONFIGDIR"] = str(_CACHE_DIR)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def _read(path: Path, required: set[str]) -> list[dict]:
    with path.open(newline="", encoding="ascii") as stream:
        reader = csv.DictReader(stream)
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"{path} is missing columns: {sorted(missing)}")
        rows = list(reader)
    if not rows:
        raise ValueError(f"{path} has no data rows")
    return rows


def _float(row: dict, field: str) -> float:
    try:
        value = float(row[field])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field} in {row.get('run_id', row.get('cell_id', 'row'))}") from exc
    if not math.isfinite(value):
        raise ValueError(f"non-finite {field}")
    return value


def _float_or_nan(row: dict, field: str) -> float:
    try:
        return _float(row, field)
    except ValueError:
        return float("nan")


def _save(figure, stem: str) -> None:
    FIGS.mkdir(parents=True, exist_ok=True)
    figure.savefig(FIGS / f"{stem}.png", dpi=180, bbox_inches="tight")
    figure.savefig(FIGS / f"{stem}.pdf", bbox_inches="tight")
    plt.close(figure)


def _cell_label(row: dict) -> str:
    return f"f{row['foreground_flows']}\nc{row['degraded_capacity_gbps']}"


def render_smoke() -> None:
    rounds = _read(
        DATA_ROOT / "smoke" / "rounds.csv",
        {"round_index", "F_ps", "S_ps", "S_ref_ps", "complete"},
    )
    rows = sorted(rounds, key=lambda row: int(row["round_index"]))
    x = list(range(len(rows)))
    figure, axis = plt.subplots(figsize=(6.2, 3.4))
    axis.plot(x, [_float(row, "F_ps") / 1e6 for row in rows], label="floor")
    axis.plot(x, [_float(row, "S_ps") / 1e6 for row in rows], label="spread")
    axis.plot(x, [_float(row, "S_ref_ps") / 1e6 for row in rows], label="reference")
    axis.set_xlabel("shadow round")
    axis.set_ylabel("delay (us)")
    axis.legend(frameon=False)
    axis.grid(axis="y", alpha=0.25)
    _save(figure, "m2_controlled_smoke")


def render_calibration() -> None:
    summaries = _read(
        DATA_ROOT / "coarse" / "summary.csv",
        {"cell_id", "foreground_flows", "degraded_capacity_gbps", "C_healthy_gbps", "C_effective_residual_gbps", "L_foreground_gbps", "valid_completed_rounds", "median_delta_S"},
    )
    rows = sorted(summaries, key=lambda row: (int(row["foreground_flows"]), _float(row, "degraded_capacity_gbps")))
    labels = [_cell_label(row) for row in rows]
    x = list(range(len(rows)))
    width = 0.24
    figure, axes = plt.subplots(1, 3, figsize=(12.2, 3.4))
    axes[0].bar([item - width for item in x], [_float_or_nan(row, "C_healthy_gbps") for row in rows], width, label="healthy cut")
    axes[0].bar(x, [_float_or_nan(row, "L_foreground_gbps") for row in rows], width, label="foreground offered")
    axes[0].bar([item + width for item in x], [_float_or_nan(row, "C_effective_residual_gbps") for row in rows], width, label="effective cut")
    axes[0].set_ylabel("Gbps")
    axes[0].set_title("Capacity relation")
    axes[0].legend(frameon=False, fontsize=8)
    axes[1].bar(x, [int(row["valid_completed_rounds"]) for row in rows], color="#4c78a8")
    axes[1].set_title("Valid completed rounds")
    axes[1].set_ylabel("rounds")
    delta = [(_float(row, "median_delta_S")) if row["median_delta_S"] else float("nan") for row in rows]
    axes[2].bar(x, delta, color="#59a14f")
    axes[2].axhline(0, color="black", linewidth=0.8)
    axes[2].set_title("Median spread change")
    axes[2].set_ylabel("ps")
    for axis in axes:
        axis.set_xticks(x, labels)
        axis.grid(axis="y", alpha=0.25)
    figure.tight_layout()
    _save(figure, "m2_controlled_calibration")


def render_confirmation() -> None:
    summaries = _read(
        DATA_ROOT / "confirmation" / "summary.csv",
        {"scenario", "seed", "literal_no_progress_rate", "median_delta_S"},
    )
    rows = sorted(summaries, key=lambda row: (row["scenario"], int(row["seed"])))
    x = list(range(len(rows)))
    figure, axes = plt.subplots(1, 2, figsize=(10, 3.4))
    axes[0].bar(x, [_float(row, "literal_no_progress_rate") for row in rows])
    axes[0].axhline(0.5, color="#d62728", linestyle="--", linewidth=1)
    axes[0].set_ylabel("fraction")
    axes[0].set_title("No-progress rate")
    axes[1].bar(x, [_float(row, "median_delta_S") for row in rows])
    axes[1].axhline(0, color="black", linewidth=0.8)
    axes[1].set_ylabel("ps")
    axes[1].set_title("Median spread change")
    labels = [f"{row['scenario']}\ns{row['seed']}" for row in rows]
    for axis in axes:
        axis.set_xticks(x, labels, rotation=35, ha="right")
        axis.grid(axis="y", alpha=0.25)
    figure.tight_layout()
    _save(figure, "m2_controlled_confirmation")


def render_formal() -> None:
    summaries = _read(
        DATA_ROOT / "formal" / "summary.csv",
        {"scenario", "seed", "literal_no_progress_rate", "median_delta_S"},
    )
    by_scenario = {scenario: [] for scenario in ("recoverable", "persistent")}
    for row in summaries:
        by_scenario.setdefault(row["scenario"], []).append(row)
    figure, axes = plt.subplots(1, 2, figsize=(7.2, 3.4))
    scenarios = [name for name in ("recoverable", "persistent") if by_scenario[name]]
    axes[0].bar(scenarios, [sum(_float(row, "literal_no_progress_rate") for row in by_scenario[name]) / len(by_scenario[name]) for name in scenarios])
    axes[0].set_ylabel("fraction")
    axes[0].set_title("No-progress rate")
    axes[1].bar(scenarios, [sum(_float(row, "median_delta_S") for row in by_scenario[name]) / len(by_scenario[name]) for name in scenarios])
    axes[1].axhline(0, color="black", linewidth=0.8)
    axes[1].set_ylabel("ps")
    axes[1].set_title("Median spread change")
    for axis in axes:
        axis.grid(axis="y", alpha=0.25)
    figure.tight_layout()
    _save(figure, "m2_controlled")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--render-smoke", action="store_true")
    mode.add_argument("--render-calibration", action="store_true")
    mode.add_argument("--render-confirmation", action="store_true")
    mode.add_argument("--render", action="store_true")
    args = parser.parse_args(argv)
    if args.render_smoke:
        render_smoke()
    elif args.render_calibration:
        render_calibration()
    elif args.render_confirmation:
        render_confirmation()
    else:
        render_formal()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
