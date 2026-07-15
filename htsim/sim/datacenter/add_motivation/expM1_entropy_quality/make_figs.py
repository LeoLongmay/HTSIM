#!/usr/bin/env python3
"""Render the M1 three-panel figure from aggregate CSV tables only."""

from __future__ import annotations

import argparse
import csv
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
_CACHE_DIR = HERE / "data" / ".matplotlib-cache"
_OWNS_CACHE = "MPLCONFIGDIR" not in os.environ
if _OWNS_CACHE:
    os.environ["MPLCONFIGDIR"] = str(_CACHE_DIR)

try:
    from htsim.sim.datacenter.prism_eval.common import plot_style
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[5]))
    from htsim.sim.datacenter.prism_eval.common import plot_style

import matplotlib.pyplot as plt


FORMAL_DATA = HERE / "data" / "formal"
FIGS = HERE / "figs"
FIGURE_STEM = "m1_entropy_quality"
THRESHOLD_US = 14.0
ARMS = ("symmetric", "gray")
ARM_LABELS = {"symmetric": "Symmetric", "gray": "Gray capacity"}
ARM_COLORS = {"symmetric": plot_style.COLORS["ops"], "gray": plot_style.COLORS["reps"]}


def _read_csv(path: Path, required: set[str]) -> list[dict]:
    try:
        stream = path.open("r", newline="", encoding="ascii")
    except OSError as exc:
        raise ValueError(f"cannot read aggregate CSV {path}: {exc}") from exc
    with stream:
        reader = csv.DictReader(stream)
        fields = set(reader.fieldnames or ())
        missing = sorted(required - fields)
        if missing:
            raise ValueError(f"aggregate CSV {path} is missing columns: {missing}")
        return list(reader)


def _number(row: dict, key: str, source: str) -> float:
    try:
        value = float(row[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{source}: invalid {key} value {row.get(key)!r}") from exc
    if not math.isfinite(value):
        raise ValueError(f"{source}: non-finite {key} value")
    return value


def _ecdf(values: list[float]) -> tuple[list[float], list[float]]:
    ordered = sorted(values)
    if not ordered:
        return [], []
    return ordered, [(index + 1) / len(ordered) for index in range(len(ordered))]


def _conditioning_by_arm(rows: list[dict]) -> dict[tuple[str, str], dict]:
    indexed = {}
    for row in rows:
        key = (row["arm"], row["current_state"])
        if key in indexed:
            raise ValueError(f"conditioning.csv has duplicate row {key}")
        indexed[key] = row
    missing = [(arm, state) for arm in ARMS for state in ("low", "high") if (arm, state) not in indexed]
    if missing:
        raise ValueError(f"conditioning.csv is missing rows: {missing}")
    return indexed


def _tokens_by_arm(rows: list[dict]) -> dict[str, dict]:
    indexed = {}
    for row in rows:
        arm = row["arm"]
        if arm in indexed:
            raise ValueError(f"tokens.csv has duplicate arm {arm!r}")
        indexed[arm] = row
    missing = [arm for arm in ARMS if arm not in indexed]
    if missing:
        raise ValueError(f"tokens.csv is missing arms: {missing}")
    return indexed


def render(data_dir: Path = FORMAL_DATA, figure_dir: Path = FIGS) -> tuple[Path, Path]:
    """Render the final figure without opening manifests or trace CSVs."""

    residual_rows = _read_csv(data_dir / "ecdf.csv", {"arm", "residual_ps"})
    conditioning = _conditioning_by_arm(_read_csv(
        data_dir / "conditioning.csv",
        {"arm", "current_state", "probability", "ci_low", "ci_high"},
    ))
    tokens = _tokens_by_arm(_read_csv(
        data_dir / "tokens.csv",
        {"arm", "shadow_rejection_exposure", "rejected_token_future_high_rate"},
    ))

    plot_style.apply_style(font_size=10)
    fig, axes = plt.subplots(1, 3, figsize=(11.2, 3.35))

    for arm in ARMS:
        values = [
            _number(row, "residual_ps", "ecdf.csv") / 1e6
            for row in residual_rows if row["arm"] == arm
        ]
        if not values:
            raise ValueError(f"ecdf.csv has no {arm} residual observations")
        x_values, y_values = _ecdf(values)
        axes[0].step(
            x_values, y_values, where="post", color=ARM_COLORS[arm],
            linewidth=1.8, label=ARM_LABELS[arm],
        )
    axes[0].axvline(THRESHOLD_US, color="tab:red", linestyle="--", linewidth=1.3,
                    label="14 us threshold")
    axes[0].set_xlabel("ECN-unmarked residual (us)")
    axes[0].set_ylabel("ECDF")
    axes[0].set_ylim(0, 1.02)
    axes[0].set_title("Unmarked residual")
    axes[0].legend(frameon=False, fontsize=8)

    states = ("low", "high")
    centers = range(len(states))
    width = 0.34
    for arm_index, arm in enumerate(ARMS):
        positions = [center + (arm_index - 0.5) * width for center in centers]
        values = [_number(conditioning[(arm, state)], "probability", "conditioning.csv") for state in states]
        lows = [_number(conditioning[(arm, state)], "ci_low", "conditioning.csv") for state in states]
        highs = [_number(conditioning[(arm, state)], "ci_high", "conditioning.csv") for state in states]
        errors = [[value - low for value, low in zip(values, lows)],
                  [high - value for value, high in zip(values, highs)]]
        axes[1].bar(
            positions, values, width=width, color=ARM_COLORS[arm], label=ARM_LABELS[arm],
            yerr=errors, capsize=3, edgecolor="white", linewidth=0.5,
        )
    axes[1].set_xticks(list(centers), ["Current low", "Current high"])
    axes[1].set_ylabel("Future-high probability")
    axes[1].set_ylim(0, 1.02)
    axes[1].set_title("Same-entropy next use")
    axes[1].legend(frameon=False, fontsize=8)

    measures = (
        ("shadow_rejection_exposure", "Shadow reject\nclassification"),
        ("rejected_token_future_high_rate", "Rejected-token\nfuture high"),
    )
    centers = range(len(measures))
    for arm_index, arm in enumerate(ARMS):
        positions = [center + (arm_index - 0.5) * width for center in centers]
        values = [_number(tokens[arm], key, "tokens.csv") for key, _label in measures]
        axes[2].bar(
            positions, values, width=width, color=ARM_COLORS[arm], label=ARM_LABELS[arm],
            edgecolor="white", linewidth=0.5,
        )
    axes[2].set_xticks(list(centers), [label for _key, label in measures])
    axes[2].set_ylabel("Observed fraction")
    axes[2].set_ylim(0, 1.02)
    axes[2].set_title("Shadow token classification")
    axes[2].legend(frameon=False, fontsize=8)

    for label, axis in zip("abc", axes):
        axis.text(-0.14, 1.04, f"({label})", transform=axis.transAxes,
                  fontweight="bold", va="bottom")
    fig.tight_layout(w_pad=1.2)
    plot_style.save(fig, FIGURE_STEM, str(figure_dir))
    plt.close(fig)
    return figure_dir / f"{FIGURE_STEM}.png", figure_dir / f"{FIGURE_STEM}.pdf"


def _write_fixture(directory: Path) -> None:
    tables = {
        "ecdf.csv": (
            ["arm", "residual_ps"],
            [
                {"arm": arm, "residual_ps": value * 1_000_000}
                for arm, values in (("symmetric", (0, 2, 5, 9, 13, 16)),
                                    ("gray", (0, 4, 12, 16, 22, 30)))
                for value in values
            ],
        ),
        "conditioning.csv": (
            ["arm", "current_state", "probability", "ci_low", "ci_high"],
            [
                {"arm": "symmetric", "current_state": "low", "probability": 0.18,
                 "ci_low": 0.12, "ci_high": 0.25},
                {"arm": "symmetric", "current_state": "high", "probability": 0.35,
                 "ci_low": 0.27, "ci_high": 0.44},
                {"arm": "gray", "current_state": "low", "probability": 0.22,
                 "ci_low": 0.16, "ci_high": 0.29},
                {"arm": "gray", "current_state": "high", "probability": 0.68,
                 "ci_low": 0.58, "ci_high": 0.77},
            ],
        ),
        "tokens.csv": (
            ["arm", "shadow_rejection_exposure", "rejected_token_future_high_rate"],
            [
                {"arm": "symmetric", "shadow_rejection_exposure": 0.12,
                 "rejected_token_future_high_rate": 0.31},
                {"arm": "gray", "shadow_rejection_exposure": 0.39,
                 "rejected_token_future_high_rate": 0.72},
            ],
        ),
    }
    for name, (fields, rows) in tables.items():
        with (directory / name).open("w", newline="", encoding="ascii") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)


def selftest() -> None:
    data_root = HERE / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".m1_plot_selftest_", dir=data_root) as directory:
        fixture_dir = Path(directory)
        _write_fixture(fixture_dir)
        outputs = render(fixture_dir, FIGS)
    for output in outputs:
        if not output.is_file() or output.stat().st_size == 0:
            raise AssertionError(f"plot self-test did not create {output}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--render", action="store_true")
    mode.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.selftest:
            selftest()
        else:
            render()
        return 0
    except (OSError, ValueError, AssertionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        if _OWNS_CACHE:
            shutil.rmtree(_CACHE_DIR, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
