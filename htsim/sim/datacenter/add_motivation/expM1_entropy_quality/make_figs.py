#!/usr/bin/env python3
"""Render the M1 three-panel figure from aggregate CSV tables only."""

from __future__ import annotations

import argparse
import csv
import math
import os
import shutil
import stat
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
        mode = os.lstat(path).st_mode
    except OSError as exc:
        raise ValueError(f"aggregate CSV is missing: {path}: {exc}") from exc
    if stat.S_ISLNK(mode):
        raise ValueError(f"aggregate CSV must not be a symlink: {path}")
    if not stat.S_ISREG(mode):
        raise ValueError(f"aggregate CSV must be a regular file: {path}")
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(HERE)
    except (OSError, ValueError) as exc:
        raise ValueError(f"aggregate CSV must resolve under {HERE}: {path}") from exc
    try:
        stream = resolved.open("r", newline="", encoding="ascii")
    except OSError as exc:
        raise ValueError(f"cannot read aggregate CSV {path}: {exc}") from exc
    with stream:
        reader = csv.DictReader(stream)
        fields = set(reader.fieldnames or ())
        missing = sorted(required - fields)
        if missing:
            raise ValueError(f"aggregate CSV {path} is missing columns: {missing}")
        return list(reader)


def _prepare_figure_directory(path: Path) -> Path:
    path = Path(path)
    if path.exists() or path.is_symlink():
        mode = os.lstat(path).st_mode
        if stat.S_ISLNK(mode):
            raise ValueError(f"figure directory must not be a symlink: {path}")
        if not stat.S_ISDIR(mode):
            raise ValueError(f"figure directory must be a directory: {path}")
        resolved = path.resolve(strict=True)
    else:
        try:
            parent = path.parent.resolve(strict=True)
            parent.relative_to(HERE)
        except (OSError, ValueError) as exc:
            raise ValueError(f"figure directory must resolve under {HERE}: {path}") from exc
        path.mkdir()
        resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(HERE)
    except ValueError as exc:
        raise ValueError(f"figure directory must resolve under {HERE}: {path}") from exc
    return resolved


def _validate_figure_output(path: Path) -> None:
    if path.exists() or path.is_symlink():
        mode = os.lstat(path).st_mode
        if stat.S_ISLNK(mode):
            raise ValueError(f"figure output must not be a symlink: {path}")
        if not stat.S_ISREG(mode):
            raise ValueError(f"figure output must be a regular file: {path}")
        try:
            path.resolve(strict=True).relative_to(HERE)
        except (OSError, ValueError) as exc:
            raise ValueError(f"figure output must resolve under {HERE}: {path}") from exc


def _atomic_save(fig, figure_dir: Path) -> tuple[Path, Path]:
    directory = _prepare_figure_directory(figure_dir)
    outputs = tuple(directory / f"{FIGURE_STEM}.{ext}" for ext in ("png", "pdf"))
    for output in outputs:
        _validate_figure_output(output)

    temporaries = []
    try:
        for output in outputs:
            with tempfile.NamedTemporaryFile(
                dir=directory, prefix=f".{output.name}.", suffix=".tmp", delete=False,
            ) as stream:
                temporary = Path(stream.name)
            temporaries.append(temporary)
            fig.savefig(temporary, format=output.suffix[1:], bbox_inches="tight", pad_inches=0.04)
            with temporary.open("rb") as stream:
                os.fsync(stream.fileno())
        for temporary, output in zip(temporaries, outputs):
            _validate_figure_output(output)
            os.replace(temporary, output)
        return outputs
    finally:
        for temporary in temporaries:
            temporary.unlink(missing_ok=True)


def _number(row: dict, key: str, source: str) -> float:
    try:
        value = float(row[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{source}: invalid {key} value {row.get(key)!r}") from exc
    if not math.isfinite(value):
        raise ValueError(f"{source}: non-finite {key} value")
    return value


def _nonnegative(row: dict, key: str, source: str) -> float:
    value = _number(row, key, source)
    if value < 0:
        raise ValueError(f"{source}: {key} must be nonnegative")
    return value


def _unit_interval(row: dict, key: str, source: str) -> float:
    value = _number(row, key, source)
    if not 0 <= value <= 1:
        raise ValueError(f"{source}: {key} must be in [0, 1]")
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
        if key[0] not in ARMS or key[1] not in ("low", "high"):
            raise ValueError(f"conditioning.csv has unknown arm/state row {key}")
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
        if arm not in ARMS:
            raise ValueError(f"tokens.csv has unknown arm {arm!r}")
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

    residual_values = {arm: [] for arm in ARMS}
    for row in residual_rows:
        arm = row["arm"]
        if arm not in ARMS:
            raise ValueError(f"ecdf.csv has unknown arm {arm!r}")
        residual_values[arm].append(
            _nonnegative(row, "residual_ps", "ecdf.csv") / 1e6
        )
    for arm in ARMS:
        if not residual_values[arm]:
            raise ValueError(f"ecdf.csv has no {arm} residual observations")

    conditioning_values = {}
    for arm in ARMS:
        for state in ("low", "high"):
            row = conditioning[(arm, state)]
            estimate = _unit_interval(row, "probability", "conditioning.csv")
            ci_low = _unit_interval(row, "ci_low", "conditioning.csv")
            ci_high = _unit_interval(row, "ci_high", "conditioning.csv")
            if not ci_low <= estimate <= ci_high:
                raise ValueError(
                    "conditioning.csv: CI must satisfy low <= estimate <= high"
                )
            conditioning_values[(arm, state)] = (estimate, ci_low, ci_high)

    token_values = {
        (arm, key): _unit_interval(tokens[arm], key, "tokens.csv")
        for arm in ARMS
        for key in ("shadow_rejection_exposure", "rejected_token_future_high_rate")
    }

    plot_style.apply_style(font_size=10)
    fig, axes = plt.subplots(1, 3, figsize=(11.2, 3.35))

    for arm in ARMS:
        values = residual_values[arm]
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
        values = [conditioning_values[(arm, state)][0] for state in states]
        lows = [conditioning_values[(arm, state)][1] for state in states]
        highs = [conditioning_values[(arm, state)][2] for state in states]
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
        values = [token_values[(arm, key)] for key, _label in measures]
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
    try:
        return _atomic_save(fig, figure_dir)
    finally:
        plt.close(fig)


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
