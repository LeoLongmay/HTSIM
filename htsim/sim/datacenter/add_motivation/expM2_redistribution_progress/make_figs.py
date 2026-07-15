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
SMOKE_DATA = HERE / "data" / "smoke"
COARSE_DATA = HERE / "data" / "coarse"
CONFIRMATION_DATA = HERE / "data" / "confirmation"
CONFIRMATION_SELECTION = COARSE_DATA / "confirmation_selection.csv"
FIGS = HERE / "figs"
STEM = "m2_redistribution_progress"
SMOKE_STEM = "m2_redistribution_progress_smoke"
CALIBRATION_STEM = "m2_coarse_diagnostics"
CONFIRMATION_STEM = "m2_confirmation_diagnostics"
SCENARIOS = ("recoverable", "persistent")
LABELS = {"recoverable": "Recoverable", "persistent": "Persistent"}
COLORS = {"F": "#2378b5", "S": "#d1495b", "S_ref": "#6f4e7c", "cwnd": "#218c74"}
COARSE_FOREGROUND = (8, 16, 32)
COARSE_HOT_GROUPS = (2, 4, 6)
COARSE_UTILIZATION = (0.25, 0.50, 0.75)
CAPACITY_CLASSES = ("recoverable", "persistent", "invalid")
CALIBRATION_COLORS = {
    "recoverable": "#65a765",
    "persistent": "#d36b5f",
    "mixed": "#d7a928",
    "invalid": "#a6a6a6",
}

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


def _atomic_csv(path: Path, fieldnames: tuple[str, ...], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("w", newline="", encoding="ascii") as stream:
            writer = csv.DictWriter(
                stream, fieldnames=fieldnames, lineterminator="\n"
            )
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _coarse_key(row: dict) -> tuple[int, int, float]:
    return (
        _int(row, "foreground_flows"),
        _int(row, "hot_path_groups"),
        _float(row, "background_utilization"),
    )


def _expected_coarse_cells() -> set[tuple[int, int, float]]:
    return {
        (foreground, hot_groups, utilization)
        for foreground in COARSE_FOREGROUND
        for hot_groups in COARSE_HOT_GROUPS
        for utilization in COARSE_UTILIZATION
    }


def _validate_coarse_rows(
    summaries: list[dict], rounds: list[dict],
) -> tuple[dict[tuple[int, int, float], dict], dict[tuple[int, int, float], list[dict]]]:
    expected = _expected_coarse_cells()
    by_summary = {}
    for row in summaries:
        key = _coarse_key(row)
        if key in by_summary:
            raise ValueError(f"duplicate coarse summary cell {key}")
        by_summary[key] = row
    actual = set(by_summary)
    if actual != expected:
        raise ValueError(
            "coarse summary must contain exactly the 27 preregistered cells; "
            f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )

    by_round = defaultdict(list)
    for row in rounds:
        key = _coarse_key(row)
        if key not in expected:
            raise ValueError(f"round belongs to non-preregistered coarse cell {key}")
        by_round[key].append(row)
    round_cells = set(by_round)
    if round_cells != expected:
        raise ValueError(
            "coarse rounds must cover exactly the 27 preregistered cells; "
            f"missing={sorted(expected - round_cells)}"
        )

    for key, summary in by_summary.items():
        expected_cell_id = (
            f"coarse-f{key[0]}-h{key[1]}-u{int(round(key[2] * 100))}"
        )
        if summary["cell_id"] != expected_cell_id or _int(summary, "seed") != 101:
            raise ValueError(f"coarse summary metadata does not match cell {key}")
        for row in by_round[key]:
            if row["cell_id"] != expected_cell_id or _int(row, "seed") != 101:
                raise ValueError(f"coarse round metadata does not match cell {key}")
    return by_summary, by_round


def _failure_category(predicate: str) -> str | None:
    if not predicate or predicate in {
        "capacity_classification_invalid",
        "coarse_scenario_inference_invalid_completed_evidence",
    }:
        return None
    if "capacity_witness_invalid" in predicate:
        return "capacity_witness_invalid"
    if "missing_bracketing_epoch" in predicate:
        return "missing_bracketing_epoch"
    if predicate == "round_censored":
        return "round_censored"
    return predicate.split(":", 1)[0]


def _main_failure(rows: list[dict]) -> tuple[str, str]:
    counts = defaultdict(int)
    for row in rows:
        categories = {
            category
            for predicate in row.get("failed_predicates", "").split(";")
            if (category := _failure_category(predicate)) is not None
        }
        for category in categories:
            counts[category] += 1
    if not counts:
        return "none", ""
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return ordered[0][0], ";".join(f"{key}={value}" for key, value in ordered)


def _calibration_rows(summaries: list[dict], rounds: list[dict]) -> list[dict]:
    by_summary, by_round = _validate_coarse_rows(summaries, rounds)
    diagnostics = []
    for key in sorted(by_summary):
        summary = by_summary[key]
        cell_rounds = by_round[key]
        completed = [row for row in cell_rounds if _int(row, "complete") == 1]
        valid_completed = [row for row in completed if _int(row, "valid_round") == 1]
        counts = {name: 0 for name in CAPACITY_CLASSES}
        for row in completed:
            classification = row["capacity_classification"]
            if classification not in counts:
                raise ValueError(f"unknown capacity classification {classification!r}")
            counts[classification] += 1

        episode_count = _int(summary, "episode_count")
        summary_completed = _int(summary, "completed_rounds")
        summary_valid = _int(summary, "valid_completed_rounds")
        if episode_count != len(cell_rounds):
            raise ValueError(f"episode count mismatch for coarse cell {key}")
        if summary_completed != len(completed):
            raise ValueError(f"completed round count mismatch for coarse cell {key}")
        if summary_valid != len(valid_completed):
            raise ValueError(f"valid completed round count mismatch for coarse cell {key}")
        completion_rate = _float(summary, "completion_rate")
        expected_completion = len(completed) / episode_count
        if not math.isclose(completion_rate, expected_completion, rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError(f"completion rate mismatch for coarse cell {key}")

        observed = {name for name, count in counts.items() if count}
        if observed == {"recoverable"}:
            profile = "recoverable"
        elif observed == {"persistent"}:
            profile = "persistent"
        elif not observed or observed == {"invalid"}:
            profile = "invalid"
        else:
            profile = "mixed"
        denominator = len(completed)
        primary_failure, failure_counts = _main_failure(cell_rounds)
        diagnostics.append({
            "cell_id": summary["cell_id"],
            "foreground_flows": key[0],
            "hot_path_groups": key[1],
            "background_utilization": f"{key[2]:.2f}",
            "episode_count": episode_count,
            "completed_rounds": len(completed),
            "completion_rate": f"{completion_rate:.9g}",
            "low_floor_high_spread_occupancy":
                f"{_float(summary, 'low_floor_high_spread_occupancy'):.9g}",
            "valid_completed_rounds": len(valid_completed),
            "valid_evidence_fraction":
                f"{(len(valid_completed) / denominator if denominator else 0.0):.9g}",
            "recoverable_completed_rounds": counts["recoverable"],
            "recoverable_fraction":
                f"{(counts['recoverable'] / denominator if denominator else 0.0):.9g}",
            "persistent_completed_rounds": counts["persistent"],
            "persistent_fraction":
                f"{(counts['persistent'] / denominator if denominator else 0.0):.9g}",
            "invalid_completed_rounds": counts["invalid"],
            "invalid_fraction":
                f"{(counts['invalid'] / denominator if denominator else 0.0):.9g}",
            "capacity_profile": profile,
            "main_failure_category": primary_failure,
            "failure_category_counts": failure_counts,
        })
    return diagnostics


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

    epoch_series = defaultdict(list)
    for row in epochs:
        if row["scenario"] != scenario or _int(row, "seed") != seed:
            continue
        key = (_int(row, "flow_id"), _int(row, "round_index"))
        epoch_series[key].append(row)
    for series in epoch_series.values():
        series.sort(key=lambda row: _int(row, "event_seq"))

    def evidence_key(row: dict) -> tuple[int, float, int, int]:
        key = (_int(row, "flow_id"), _int(row, "round_index"))
        series = epoch_series.get(key, ())
        if series:
            times = [_float(epoch, "aligned_time_ps") for epoch in series]
            coverage_ps = max(times) - min(times)
        else:
            coverage_ps = 0.0
        return (-len(series), -coverage_ps, key[0], key[1])

    chosen = min(
        (row for row in candidates if _int(row, "seed") == seed),
        key=evidence_key,
    )
    chosen_key = (_int(chosen, "flow_id"), _int(chosen, "round_index"))
    series = epoch_series.get(chosen_key, [])
    if len(series) < 2:
        raise ValueError(
            f"representative {scenario} round has fewer than 2 aggregate epoch points"
        )
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


def _add_inset(
    ax, summaries: list[dict], rounds: list[dict], scenario: str,
    title: str = "5-seed summary",
) -> None:
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
    inset.set_title(title, fontsize=6, pad=1)
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


def render_smoke(
    data_dir: Path = SMOKE_DATA, figure_dir: Path = FIGS / "smoke",
) -> tuple[Path, Path]:
    """Render one real smoke scenario from aggregate CSVs only."""

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

    aggregate_rows = epochs + rounds + summaries
    if any(row.get("scenario") == "invalid" for row in aggregate_rows):
        raise ValueError("smoke aggregate has invalid inferred scenario")
    valid_completed = [
        row for row in rounds
        if row.get("complete") == "1" and row.get("valid_round") == "1"
    ]
    if not valid_completed:
        raise ValueError("smoke aggregate has no valid completed shadow validation round")
    scenarios = {row["scenario"] for row in valid_completed}
    if len(scenarios) != 1 or not scenarios.issubset(SCENARIOS):
        raise ValueError("smoke aggregate must contain exactly one valid inferred scenario")
    scenario = scenarios.pop()
    valid_seeds = {_int(row, "seed") for row in valid_completed}
    smoke_summaries = [
        row for row in summaries
        if row["scenario"] == scenario and _int(row, "seed") in valid_seeds
    ]
    if len(smoke_summaries) != len(valid_seeds) or {
        _int(row, "seed") for row in smoke_summaries
    } != valid_seeds:
        raise ValueError("smoke aggregate must have one summary for every valid seed")

    _round, series = _representative(epochs, valid_completed, scenario)
    x = [_float(row, "aligned_time_ps") / 1e6 for row in series]
    floor = [_float(row, "F_ps") / 1e6 for row in series]
    spread = [_float(row, "S_ps") / 1e6 for row in series]
    reference = [_float(row, "S_ref_ps") / 1e6 for row in series]

    fig, axes = plt.subplots(2, 1, figsize=(5.2, 5.3), sharex=True)
    signal_ax, control_ax = axes
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
    signal_ax.set_title(f"Smoke: {LABELS[scenario]}", fontsize=10)
    signal_ax.set_ylabel("Raw delay (us)")
    signal_ax.grid(axis="y", color="#e5e5e5", linewidth=0.6)
    _add_inset(signal_ax, smoke_summaries, valid_completed, scenario, "Smoke seed summary")

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

    handles, labels = signal_ax.get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=4, frameon=False, fontsize=8)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    figure_dir = Path(figure_dir)
    figure_dir.mkdir(parents=True, exist_ok=True)
    outputs = tuple(figure_dir / f"{SMOKE_STEM}.{suffix}" for suffix in ("png", "pdf"))
    for output in outputs:
        temporary = output.with_name(f".{output.name}.tmp")
        fig.savefig(temporary, format=output.suffix[1:], dpi=180, bbox_inches="tight")
        os.replace(temporary, output)
    plt.close(fig)
    return outputs


CALIBRATION_FIELDS = (
    "cell_id", "foreground_flows", "hot_path_groups", "background_utilization",
    "episode_count", "completed_rounds", "completion_rate",
    "low_floor_high_spread_occupancy", "valid_completed_rounds",
    "valid_evidence_fraction", "recoverable_completed_rounds", "recoverable_fraction",
    "persistent_completed_rounds", "persistent_fraction", "invalid_completed_rounds",
    "invalid_fraction", "capacity_profile", "main_failure_category",
    "failure_category_counts",
)

CONFIRMATION_FIELDS = (
    "cell_id", "scenario", "seed", "completed_rounds", "valid_completed_rounds",
    "completion_rate", "median_delta_S", "literal_no_progress_rate",
    "low_floor_fraction", "L_foreground_gbps", "C_healthy_gbps",
    "C_effective_residual_gbps", "outcome_pass", "capacity_pass",
)


def _confirmation_rows(
    summaries: list[dict], selections: list[dict],
) -> list[dict]:
    expected_seeds = {101, 102, 103}
    if len(selections) != 3:
        raise ValueError("confirmation selection must contain exactly seeds 101/102/103")

    selection_by_seed = {}
    selection_cells = set()
    for row in selections:
        seed = _int(row, "seed")
        if seed in selection_by_seed:
            raise ValueError(f"duplicate confirmation selection seed {seed}")
        selection_by_seed[seed] = row
        selection_cells.add((
            row["cell_id"], row["scenario"], _int(row, "foreground_flows"),
            _int(row, "hot_path_groups"), _float(row, "background_utilization"),
        ))
    if set(selection_by_seed) != expected_seeds:
        raise ValueError("confirmation selection must contain exactly seeds 101/102/103")
    if len(selection_cells) != 1:
        raise ValueError("confirmation selection must describe one identical cell")
    selected_cell = next(iter(selection_cells))
    if selected_cell[1] != "persistent":
        raise ValueError("confirmation diagnostic requires scenario=persistent")

    if len(summaries) != 3:
        raise ValueError("confirmation summary must contain exactly seeds 101/102/103")
    summary_by_seed = {}
    for row in summaries:
        seed = _int(row, "seed")
        if seed in summary_by_seed:
            raise ValueError(f"duplicate confirmation summary seed {seed}")
        summary_by_seed[seed] = row
    if set(summary_by_seed) != expected_seeds:
        raise ValueError("confirmation summary must contain exactly seeds 101/102/103")

    diagnostics = []
    for seed in sorted(expected_seeds):
        row = summary_by_seed[seed]
        summary_cell = (
            row["cell_id"], row["scenario"], _int(row, "foreground_flows"),
            _int(row, "hot_path_groups"), _float(row, "background_utilization"),
        )
        if summary_cell != selected_cell:
            raise ValueError(
                f"confirmation summary seed {seed} does not match current selection"
            )

        completed = _int(row, "completed_rounds")
        valid = _int(row, "valid_completed_rounds")
        round_count = _int(row, "round_count")
        completion = _float(row, "completion_rate")
        if not (0 <= valid <= completed <= round_count):
            raise ValueError(f"invalid confirmation round counts for seed {seed}")
        expected_completion = completed / round_count if round_count else 0.0
        if not math.isclose(completion, expected_completion, rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError(f"confirmation completion rate mismatch for seed {seed}")

        delta_s = _float(row, "median_delta_S")
        literal_rate = _float(row, "literal_no_progress_rate")
        low_floor = _float(row, "low_floor_fraction")
        load = _float(row, "L_foreground_gbps")
        healthy = _float(row, "C_healthy_gbps")
        effective = _float(row, "C_effective_residual_gbps")
        if not (0.0 <= completion <= 1.0 and 0.0 <= literal_rate <= 1.0
                and 0.0 <= low_floor <= 1.0):
            raise ValueError(f"invalid confirmation rate for seed {seed}")

        outcome_pass = literal_rate > 0.5 and low_floor >= 0.8
        capacity_pass = healthy < load < effective
        diagnostics.append({
            "cell_id": row["cell_id"],
            "scenario": row["scenario"],
            "seed": seed,
            "completed_rounds": completed,
            "valid_completed_rounds": valid,
            "completion_rate": f"{completion:.9g}",
            "median_delta_S": f"{delta_s:.9g}",
            "literal_no_progress_rate": f"{literal_rate:.9g}",
            "low_floor_fraction": f"{low_floor:.9g}",
            "L_foreground_gbps": f"{load:.9g}",
            "C_healthy_gbps": f"{healthy:.9g}",
            "C_effective_residual_gbps": f"{effective:.9g}",
            "outcome_pass": int(outcome_pass),
            "capacity_pass": int(capacity_pass),
        })
    return diagnostics


def render_confirmation(
    data_dir: Path = CONFIRMATION_DATA,
    selection_path: Path = CONFIRMATION_SELECTION,
    figure_dir: Path = FIGS / "calibration",
) -> tuple[Path, Path, Path]:
    """Render the fixed three-seed persistent confirmation diagnostic."""

    data_dir = Path(data_dir)
    summaries = _read(data_dir / "summary.csv", {
        "cell_id", "scenario", "foreground_flows", "hot_path_groups",
        "background_utilization", "seed", "round_count", "completed_rounds",
        "valid_completed_rounds", "completion_rate", "median_delta_S",
        "literal_no_progress_rate", "low_floor_fraction", "L_foreground_gbps",
        "C_healthy_gbps", "C_effective_residual_gbps",
    })
    selections = _read(Path(selection_path), {
        "cell_id", "scenario", "foreground_flows", "hot_path_groups",
        "background_utilization", "seed",
    })
    diagnostics = _confirmation_rows(summaries, selections)

    seeds = [int(row["seed"]) for row in diagnostics]
    x = list(range(len(seeds)))
    fig, axes = plt.subplots(1, 3, figsize=(10.2, 3.8))
    try:
        delta = [float(row["median_delta_S"]) for row in diagnostics]
        axes[0].bar(x, delta, color="#6f7782", width=0.62)
        axes[0].axhline(0.0, color="#222222", linewidth=1.0)
        axes[0].set_title("Median redistribution progress", fontsize=9)
        axes[0].set_ylabel("median delta_S")

        literal = [float(row["literal_no_progress_rate"]) for row in diagnostics]
        low_floor = [float(row["low_floor_fraction"]) for row in diagnostics]
        width = 0.34
        axes[1].bar([value - width / 2 for value in x], literal, width=width,
                    color="#4c78a8", label="Literal no-progress")
        axes[1].bar([value + width / 2 for value in x], low_floor, width=width,
                    color="#8f8f8f", label="Low-floor fraction")
        axes[1].axhline(0.5, color="#4c78a8", linestyle="--", linewidth=1.0,
                        label="Literal threshold > 0.5")
        axes[1].axhline(0.8, color="#555555", linestyle=":", linewidth=1.0,
                        label="Low-floor threshold >= 0.8")
        for index, row in enumerate(diagnostics):
            passed = bool(int(row["outcome_pass"]))
            axes[1].text(
                index - width / 2, literal[index] + 0.025,
                "PASS" if passed else "FAIL", ha="center", va="bottom",
                fontsize=6.5, fontweight="bold",
                color="#2f6b3f" if passed else "#b33f40",
            )
        axes[1].set_ylim(0.0, 1.05)
        axes[1].set_title("Persistent outcome predicates", fontsize=9)
        axes[1].set_ylabel("Fraction")
        axes[1].legend(frameon=False, fontsize=6.6, loc="lower left")

        healthy = [float(row["C_healthy_gbps"]) for row in diagnostics]
        load = [float(row["L_foreground_gbps"]) for row in diagnostics]
        effective = [float(row["C_effective_residual_gbps"]) for row in diagnostics]
        for index in x:
            axes[2].plot([index, index], [healthy[index], effective[index]],
                         color="#999999", linewidth=5, solid_capstyle="butt")
        axes[2].scatter(x, healthy, marker="v", color="#2f6b3f", label="C healthy", zorder=3)
        axes[2].scatter(x, load, marker="o", color="#c44e52", label="L foreground", zorder=4)
        axes[2].scatter(x, effective, marker="^", color="#7a5195",
                        label="C effective", zorder=3)
        axes[2].set_title("Independent capacity predicate", fontsize=9)
        axes[2].set_ylabel("Gbps")
        axes[2].legend(frameon=False, fontsize=7, loc="best")

        for ax in axes:
            ax.set_xticks(x, [str(seed) for seed in seeds])
            ax.set_xlabel("Seed")
            ax.grid(axis="y", color="#e5e5e5", linewidth=0.6)
        cell_id = diagnostics[0]["cell_id"]
        failures = sum(not int(row["outcome_pass"]) for row in diagnostics)
        fig.suptitle(
            f"Confirmation diagnostic: {cell_id} persistent outcome "
            f"({failures}/3 seeds fail)",
            fontsize=10,
        )
        fig.tight_layout(rect=(0, 0, 1, 0.92), w_pad=1.2)

        csv_output = data_dir / "confirmation_diagnostics.csv"
        figure_dir = Path(figure_dir)
        figure_outputs = tuple(
            figure_dir / f"{CONFIRMATION_STEM}.{suffix}"
            for suffix in ("png", "pdf")
        )
        outputs = (csv_output, *figure_outputs)
        temporaries = tuple(path.with_name(f".{path.name}.tmp") for path in outputs)
        data_dir.mkdir(parents=True, exist_ok=True)
        figure_dir.mkdir(parents=True, exist_ok=True)
        try:
            with temporaries[0].open("w", newline="", encoding="ascii") as stream:
                writer = csv.DictWriter(
                    stream,
                    fieldnames=CONFIRMATION_FIELDS,
                    lineterminator="\n",
                )
                writer.writeheader()
                writer.writerows(diagnostics)
            for temporary, suffix in zip(temporaries[1:], ("png", "pdf")):
                fig.savefig(temporary, format=suffix, dpi=180, bbox_inches="tight")
            for temporary, output in zip(temporaries, outputs):
                os.replace(temporary, output)
        finally:
            for temporary in temporaries:
                temporary.unlink(missing_ok=True)
    finally:
        plt.close(fig)
    return csv_output, *figure_outputs


def render_calibration(
    data_dir: Path = COARSE_DATA, figure_dir: Path = FIGS / "calibration",
) -> tuple[Path, Path, Path]:
    """Render preregistered coarse-grid diagnostics from aggregate CSVs only."""

    data_dir = Path(data_dir)
    summaries = _read(data_dir / "summary.csv", {
        "cell_id", "foreground_flows", "hot_path_groups", "background_utilization",
        "seed", "episode_count", "completed_rounds", "valid_completed_rounds",
        "completion_rate", "low_floor_high_spread_occupancy",
    })
    rounds = _read(data_dir / "rounds.csv", {
        "cell_id", "foreground_flows", "hot_path_groups", "background_utilization",
        "seed", "complete", "valid_round", "capacity_classification",
        "failed_predicates",
    })
    diagnostics = _calibration_rows(summaries, rounds)
    csv_output = data_dir / "calibration_diagnostics.csv"
    _atomic_csv(csv_output, CALIBRATION_FIELDS, diagnostics)

    by_key = {
        (
            int(row["foreground_flows"]), int(row["hot_path_groups"]),
            float(row["background_utilization"]),
        ): row
        for row in diagnostics
    }
    fig, axes = plt.subplots(1, 3, figsize=(9.4, 3.9), sharex=True, sharey=True)
    class_labels = {
        "recoverable": "R", "persistent": "P", "mixed": "M", "invalid": "I",
    }
    try:
        for ax, foreground in zip(axes, COARSE_FOREGROUND):
            for row_index, hot_groups in enumerate(reversed(COARSE_HOT_GROUPS)):
                for column, utilization in enumerate(COARSE_UTILIZATION):
                    row = by_key[(foreground, hot_groups, utilization)]
                    profile = row["capacity_profile"]
                    ax.add_patch(plt.Rectangle(
                        (column - 0.5, row_index - 0.5), 1, 1,
                        facecolor=CALIBRATION_COLORS[profile], edgecolor="white",
                        linewidth=2,
                    ))
                    ax.text(
                        column, row_index - 0.22, class_labels[profile],
                        ha="center", va="center", fontsize=11, fontweight="bold",
                    )
                    ax.text(
                        column, row_index + 0.12,
                        f"V {float(row['valid_evidence_fraction']):.2f}  "
                        f"C {float(row['completion_rate']):.2f}\n"
                        f"O {float(row['low_floor_high_spread_occupancy']):.2f}",
                        ha="center", va="center", fontsize=6.8, linespacing=1.15,
                    )
            ax.set_title(f"Foreground flows = {foreground}", fontsize=9)
            ax.set_xlim(-0.5, 2.5)
            ax.set_ylim(-0.5, 2.5)
            ax.set_xticks(range(3), [f"{value:.2f}" for value in COARSE_UTILIZATION])
            ax.set_xlabel("Background utilization")
            ax.set_yticks(range(3), ["6", "4", "2"])
            ax.tick_params(length=0)
        axes[0].set_ylabel("Hot path groups")
        legend_handles = [
            plt.Rectangle((0, 0), 1, 1, color=CALIBRATION_COLORS[name], label=label)
            for name, label in (
                ("recoverable", "Stable recoverable"),
                ("persistent", "Stable persistent"),
                ("mixed", "Mixed"),
                ("invalid", "Invalid"),
            )
        ]
        fig.legend(
            handles=legend_handles, loc="upper center", ncol=4, frameon=False,
            fontsize=7.5, bbox_to_anchor=(0.5, 0.99),
        )
        fig.suptitle(
            "Coarse calibration: capacity profile and evidence quality",
            fontsize=10, y=1.04,
        )
        fig.text(
            0.5, 0.01, "V: valid evidence / completed   C: completion   O: occupancy",
            ha="center", fontsize=7.5,
        )
        fig.tight_layout(rect=(0, 0.05, 1, 0.91), w_pad=1.2)
        figure_dir = Path(figure_dir)
        figure_dir.mkdir(parents=True, exist_ok=True)
        figure_outputs = tuple(
            figure_dir / f"{CALIBRATION_STEM}.{suffix}" for suffix in ("png", "pdf")
        )
        for output in figure_outputs:
            temporary = output.with_name(f".{output.name}.tmp")
            try:
                fig.savefig(
                    temporary, format=output.suffix[1:], dpi=180, bbox_inches="tight",
                )
                os.replace(temporary, output)
            finally:
                temporary.unlink(missing_ok=True)
    finally:
        plt.close(fig)
    return csv_output, *figure_outputs


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
            writer = csv.DictWriter(
                stream, fieldnames=fields, lineterminator="\n"
            )
            writer.writeheader()
            writer.writerows(rows)


def _write_calibration_fixture(directory: Path) -> None:
    summaries, rounds = [], []
    for foreground, hot_groups, utilization in sorted(_expected_coarse_cells()):
        cell_id = f"coarse-f{foreground}-h{hot_groups}-u{int(utilization * 100)}"
        summaries.append({
            "cell_id": cell_id, "foreground_flows": foreground,
            "hot_path_groups": hot_groups, "background_utilization": utilization,
            "seed": 101, "episode_count": 1, "completed_rounds": 1,
            "valid_completed_rounds": 0, "completion_rate": 1,
            "low_floor_high_spread_occupancy": 0.5,
        })
        rounds.append({
            "cell_id": cell_id, "foreground_flows": foreground,
            "hot_path_groups": hot_groups, "background_utilization": utilization,
            "seed": 101, "complete": 1, "valid_round": 0,
            "capacity_classification": "invalid",
            "failed_predicates": "capacity_witness_invalid:selftest",
        })
    _atomic_csv(directory / "summary.csv", tuple(summaries[0]), summaries)
    _atomic_csv(directory / "rounds.csv", tuple(rounds[0]), rounds)


def _write_confirmation_fixture(data_dir: Path, selection_path: Path) -> None:
    summaries = []
    selections = []
    for seed, literal in zip((101, 102, 103), (0.51, 0.50, 0.49)):
        common = {
            "cell_id": "coarse-f16-h6-u25", "scenario": "persistent",
            "foreground_flows": 16, "hot_path_groups": 6,
            "background_utilization": 0.25, "seed": seed,
        }
        selections.append(common)
        summaries.append({
            **common, "round_count": 10, "completed_rounds": 9,
            "valid_completed_rounds": 9, "completion_rate": 0.9,
            "median_delta_S": (seed - 102) * 0.01,
            "literal_no_progress_rate": literal, "low_floor_fraction": 0.8,
            "L_foreground_gbps": 1300, "C_healthy_gbps": 1000,
            "C_effective_residual_gbps": 1450,
        })
    _atomic_csv(data_dir / "summary.csv", tuple(summaries[0]), summaries)
    _atomic_csv(selection_path, tuple(selections[0]), selections)


def selftest() -> None:
    data_root = HERE / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".m2_plot_selftest_", dir=data_root) as directory:
        fixture = Path(directory)
        formal_data = fixture / "formal"
        formal_figs = fixture / "formal_figs"
        formal_data.mkdir()
        _write_fixture(formal_data)
        outputs = render(formal_data, formal_figs)
        if any(not path.is_file() or path.stat().st_size == 0 for path in outputs):
            raise AssertionError("M2 plot self-test did not create both figure formats")
        coarse_data = fixture / "coarse"
        coarse_figs = fixture / "coarse_figs"
        coarse_data.mkdir()
        _write_calibration_fixture(coarse_data)
        calibration_outputs = render_calibration(coarse_data, coarse_figs)
        if any(
            not path.is_file() or path.stat().st_size == 0
            for path in calibration_outputs
        ):
            raise AssertionError(
                "M2 calibration plot self-test did not create CSV, PNG, and PDF"
            )
        confirmation_data = fixture / "confirmation"
        confirmation_figs = fixture / "confirmation_figs"
        confirmation_data.mkdir()
        selection_path = fixture / "confirmation_selection.csv"
        _write_confirmation_fixture(confirmation_data, selection_path)
        confirmation_outputs = render_confirmation(
            confirmation_data, selection_path, confirmation_figs,
        )
        if any(
            not path.is_file() or path.stat().st_size == 0
            for path in confirmation_outputs
        ):
            raise AssertionError(
                "M2 confirmation plot self-test did not create CSV, PNG, and PDF"
            )
    if _OWNS_CACHE:
        shutil.rmtree(_CACHE_DIR, ignore_errors=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--render", action="store_true")
    mode.add_argument("--render-smoke", action="store_true")
    mode.add_argument("--render-calibration", action="store_true")
    mode.add_argument("--render-confirmation", action="store_true")
    mode.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.selftest:
            selftest()
        elif args.render_confirmation:
            render_confirmation()
        elif args.render_calibration:
            render_calibration()
        elif args.render_smoke:
            render_smoke()
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
