#!/usr/bin/env python3
"""Render M2 evidence from aggregate CSV tables only."""

from __future__ import annotations

import argparse
import csv
import math
import os
import shutil
import statistics
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
FORMAL_DATA = HERE / "data" / "formal"
FIGS = HERE / "figs"
STEM = "m2_redistribution_progress"
SCENARIOS = ("recoverable", "persistent")
LABELS = {"recoverable": "Recoverable", "persistent": "Persistent"}
COLORS = {"F": "#2378b5", "S": "#d1495b", "S_ref": "#6f4e7c", "cwnd": "#218c74"}

_CACHE_DIR = HERE / "data" / ".matplotlib-cache"
_OWNS_CACHE = "MPLCONFIGDIR" not in os.environ
if _OWNS_CACHE:
    os.environ["MPLCONFIGDIR"] = str(_CACHE_DIR)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def _read(path: Path, required: set[str]) -> list[dict]:
    with path.open(newline="", encoding="ascii") as stream:
        reader = csv.DictReader(stream)
        missing = sorted(required - set(reader.fieldnames or ()))
        if missing:
            raise ValueError(f"aggregate CSV {path} is missing columns: {missing}")
        return list(reader)


def _float(row: dict, key: str) -> float:
    try:
        value = float(row[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid aggregate numeric field {key!r}") from exc
    if not math.isfinite(value):
        raise ValueError(f"non-finite aggregate numeric field {key!r}")
    return value


def _int(row: dict, key: str) -> int:
    value = _float(row, key)
    if not value.is_integer():
        raise ValueError(f"aggregate integer field {key!r} is not integral")
    return int(value)


def _representative(epochs: list[dict], rounds: list[dict], scenario: str):
    candidates = [
        row for row in rounds
        if row["scenario"] == scenario
        and row.get("complete") == "1"
        and row.get("valid_round") == "1"
    ]
    if not candidates:
        raise ValueError(f"no completed shadow validation round for {scenario}")
    seeds = sorted({_int(row, "seed") for row in candidates})
    seed = seeds[len(seeds) // 2]
    chosen = min(
        (row for row in candidates if _int(row, "seed") == seed),
        key=lambda row: (_int(row, "flow_id"), _int(row, "round_index")),
    )
    series = sorted(
        (
            row for row in epochs
            if row["scenario"] == scenario
            and _int(row, "seed") == seed
            and _int(row, "flow_id") == _int(chosen, "flow_id")
            and _int(row, "round_index") == _int(chosen, "round_index")
        ),
        key=lambda row: _int(row, "event_seq"),
    )
    if not series:
        raise ValueError(f"aggregate epochs are missing representative {scenario} round")
    return chosen, series


def _valid_seed_deltas(rounds: list[dict], scenario: str, seed: int) -> list[float]:
    return [
        _float(row, "delta_S") for row in rounds
        if row["scenario"] == scenario and _int(row, "seed") == seed
        and row.get("complete") == "1" and row.get("valid_round") == "1"
        and row.get("delta_S", "") != ""
    ]


def _hold_spans(ax, x: list[float], series: list[dict]) -> None:
    if len(x) > 1:
        step = statistics.median(b - a for a, b in zip(x, x[1:]))
    else:
        step = 1.0
    for index, row in enumerate(series):
        if row["hold"] != "1":
            continue
        right = x[index + 1] if index + 1 < len(x) else x[index] + step
        ax.axvspan(x[index], right, color="#d8d8d8", alpha=0.55, linewidth=0)


def _add_inset(ax, summaries: list[dict], rounds: list[dict], scenario: str) -> None:
    inset = ax.inset_axes([0.59, 0.51, 0.39, 0.43])
    seeds = sorted({_int(row, "seed") for row in summaries if row["scenario"] == scenario})
    delta = []
    completion = []
    censor = []
    for seed in seeds:
        values = _valid_seed_deltas(rounds, scenario, seed)
        if not values:
            raise ValueError(f"seed {seed} has no completed round delta_S")
        delta.append(statistics.median(values))
        summary = next(
            row for row in summaries
            if row["scenario"] == scenario and _int(row, "seed") == seed
        )
        completion.append(_float(summary, "completion_rate"))
        censor.append(_float(summary, "censor_rate"))
    positions = list(range(len(seeds)))
    inset.axhline(0, color="#555555", linewidth=0.7)
    inset.plot(positions, delta, "o-", color=COLORS["S"], linewidth=1, markersize=2.8)
    inset.bar([x - 0.15 for x in positions], completion, width=0.3,
              color="#5aa469", alpha=0.45)
    inset.bar([x + 0.15 for x in positions], [-value for value in censor], width=0.3,
              color="#777777", alpha=0.4)
    inset.set_xticks(positions, [str(seed) for seed in seeds], fontsize=6)
    inset.tick_params(axis="y", labelsize=6, length=2)
    inset.set_title("5-seed summary", fontsize=6, pad=1)
    inset.set_ylabel("fraction", fontsize=6)


def render(data_dir: Path = FORMAL_DATA, figure_dir: Path = FIGS) -> tuple[Path, Path]:
    data_dir = Path(data_dir)
    epochs = _read(data_dir / "epochs.csv", {
        "scenario", "seed", "flow_id", "round_index", "event_seq", "aligned_time_ps",
        "F_ps", "S_ps", "S_ref_ps", "actual_cwnd_bytes", "actual_state", "hold",
        "round_complete_marker",
    })
    rounds = _read(data_dir / "rounds.csv", {
        "scenario", "seed", "flow_id", "round_index", "complete", "valid_round",
        "delta_S",
    })
    summaries = _read(data_dir / "summary.csv", {
        "scenario", "seed", "completion_rate", "censor_rate",
    })

    fig, axes = plt.subplots(2, 2, figsize=(9.0, 5.3), sharex="col")
    for column, scenario in enumerate(SCENARIOS):
        _round, series = _representative(epochs, rounds, scenario)
        x = [_float(row, "aligned_time_ps") / 1e6 for row in series]
        floor = [_float(row, "F_ps") / 1e6 for row in series]
        spread = [_float(row, "S_ps") / 1e6 for row in series]
        reference = [_float(row, "S_ref_ps") / 1e6 for row in series]

        signal_ax = axes[0, column]
        _hold_spans(signal_ax, x, series)
        signal_ax.plot(x, floor, color=COLORS["F"], linewidth=1.4, label="F")
        signal_ax.plot(x, spread, color=COLORS["S"], linewidth=1.4, label="S")
        signal_ax.plot(x, reference, color=COLORS["S_ref"], linewidth=1.1,
                       linestyle="--", label="Sref")
        signal_ax.axhline(14, color="#222222", linewidth=0.8, linestyle=":", label="14 us")
        for value, row in zip(x, series):
            if row["round_complete_marker"] == "1":
                signal_ax.axvline(value, color="#111111", linewidth=0.9)
                signal_ax.scatter([value], [_float(row, "S_ps") / 1e6], marker="|",
                                  color="#111111", s=45, zorder=4)
        signal_ax.set_title(LABELS[scenario], fontsize=10)
        signal_ax.set_ylabel("Raw delay (us)")
        signal_ax.grid(axis="y", color="#e5e5e5", linewidth=0.6)
        _add_inset(signal_ax, summaries, rounds, scenario)

        control_ax = axes[1, column]
        _hold_spans(control_ax, x, series)
        cwnd = [_float(row, "actual_cwnd_bytes") / 1024 for row in series]
        control_ax.plot(x, cwnd, color=COLORS["cwnd"], linewidth=1.4, label="actual cwnd")
        control_ax.set_ylabel("Actual cwnd (KiB)")
        control_ax.set_xlabel("Time from shadow validation round start (us)")
        control_ax.grid(axis="y", color="#e5e5e5", linewidth=0.6)
        state_ax = control_ax.twinx()
        states = ["normal", "increase", "decrease", "hold"]
        observed = [row["actual_state"] for row in series]
        for state in observed:
            if state not in states:
                states.insert(-1, state)
        state_values = [states.index(state) for state in observed]
        state_ax.step(x, state_values, where="post", color="#555555", linewidth=0.9,
                      label="actual state")
        used = sorted(set(state_values))
        state_ax.set_yticks(used, [states[index].upper() for index in used], fontsize=7)
        state_ax.set_ylabel("Actual Prism state", fontsize=8)

    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=4, frameon=False, fontsize=8)
    fig.tight_layout(rect=(0, 0, 1, 0.95), w_pad=2.2)
    figure_dir = Path(figure_dir)
    figure_dir.mkdir(parents=True, exist_ok=True)
    outputs = tuple(figure_dir / f"{STEM}.{suffix}" for suffix in ("png", "pdf"))
    for output in outputs:
        temporary = output.with_name(f".{output.name}.tmp")
        fig.savefig(temporary, format=output.suffix[1:], dpi=180, bbox_inches="tight")
        os.replace(temporary, output)
    plt.close(fig)
    return outputs


def _write_fixture(directory: Path) -> None:
    epoch_fields = (
        "scenario", "seed", "flow_id", "round_index", "event_seq", "aligned_time_ps",
        "F_ps", "S_ps", "S_ref_ps", "actual_cwnd_bytes", "actual_state", "hold",
        "round_complete_marker",
    )
    round_fields = (
        "scenario", "seed", "flow_id", "round_index", "complete", "valid_round", "delta_S",
    )
    summary_fields = ("scenario", "seed", "completion_rate", "censor_rate")
    epochs, rounds, summaries = [], [], []
    event_seq = 0
    for scenario_index, scenario in enumerate(SCENARIOS):
        for seed in (13, 14, 15, 16, 17):
            progress = 0.18 if scenario == "recoverable" else -0.04
            rounds.append({"scenario": scenario, "seed": seed, "flow_id": 0,
                           "round_index": 0, "complete": 1, "valid_round": 1,
                           "delta_S": progress})
            summaries.append({"scenario": scenario, "seed": seed,
                              "completion_rate": 0.8 + 0.03 * (seed - 13),
                              "censor_rate": 0.2 - 0.03 * (seed - 13)})
            for index in range(7):
                epochs.append({
                    "scenario": scenario, "seed": seed, "flow_id": 0,
                    "round_index": 0, "event_seq": event_seq,
                    "aligned_time_ps": index * 3_000_000,
                    "F_ps": 7_000_000 + index * 400_000,
                    "S_ps": (24_000_000 - index * 1_200_000
                             if scenario == "recoverable" else 22_000_000 + index * 100_000),
                    "S_ref_ps": 24_000_000 if scenario == "recoverable" else 22_000_000,
                    "actual_cwnd_bytes": 64_000 + index * 2_000,
                    "actual_state": "hold" if index < 5 else "increase",
                    "hold": int(index < 5), "round_complete_marker": int(index == 6),
                })
                event_seq += 1
    for name, fields, rows in (
        ("epochs.csv", epoch_fields, epochs),
        ("rounds.csv", round_fields, rounds),
        ("summary.csv", summary_fields, summaries),
    ):
        with (directory / name).open("w", newline="", encoding="ascii") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)


def selftest() -> None:
    data_root = HERE / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    outputs = tuple(FIGS / f"{STEM}.{suffix}" for suffix in ("png", "pdf"))
    try:
        with tempfile.TemporaryDirectory(prefix=".m2_plot_selftest_", dir=data_root) as directory:
            fixture = Path(directory)
            _write_fixture(fixture)
            render(fixture, FIGS)
        if any(not path.is_file() or path.stat().st_size == 0 for path in outputs):
            raise AssertionError("M2 plot self-test did not create both figure formats")
    finally:
        for output in outputs:
            output.unlink(missing_ok=True)
        if _OWNS_CACHE:
            shutil.rmtree(_CACHE_DIR, ignore_errors=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--render", action="store_true")
    mode.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)
    try:
        selftest() if args.selftest else render()
        return 0
    except (OSError, ValueError, AssertionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        if _OWNS_CACHE:
            shutil.rmtree(_CACHE_DIR, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
