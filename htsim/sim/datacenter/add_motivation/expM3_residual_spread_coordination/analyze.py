#!/usr/bin/env python3
"""Aggregate fixed M3 residual-spread coordination trace bundles."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable

try:
    from htsim.sim.datacenter.add_motivation.common.trace_schema import load_trace_compact
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[5]))
    from htsim.sim.datacenter.add_motivation.common.trace_schema import load_trace_compact


HERE = Path(__file__).resolve().parent
DATA_ROOT = HERE / "data"
AGGREGATE = DATA_ROOT / "aggregate"
WARMUP_PS = 1_000_000_000
MODES = ("original_prism", "prism_recycle", "full_prism")
SCENARIOS = ("recoverable", "persistent")
SEEDS = (13, 14, 15)
TABLE_FIELDS = {
    "epoch_series": ("run_id", "scenario", "mode", "seed", "epoch_index", "floor_ps", "spread_ps", "cwnd_bytes", "hold_fraction"),
    "rounds": ("run_id", "scenario", "mode", "seed", "round_index", "epoch_id", "plot_epoch_index", "floor_ps", "spread_ps", "spread_ref_ps", "spread_change_ps", "refresh_complete", "replacement_chain_complete", "clean_scan_complete", "progress", "handoff", "cwnd_bytes", "control_state"),
    "per_seed_metrics": ("run_id", "scenario", "mode", "seed", "window_start_ps", "window_end_ps", "foreground_acked_bytes", "healthy_acked_bytes", "throttled_acked_bytes", "healthy_to_throttled_ratio", "throttled_traffic_ratio", "goodput_gbps", "p99_genuine_qdelay_ps", "completed_rounds", "progress_rounds", "handoff_rounds"),
    "summary": ("scenario", "mode", "seed_count", "mean_healthy_to_throttled_ratio", "mean_throttled_traffic_ratio", "mean_goodput_gbps", "mean_p99_genuine_qdelay_ps", "mean_progress_rounds", "mean_handoff_rounds"),
}

MATRIX_PREDICATE = (
    "fixed complete 18-run matrix (scenarios recoverable/persistent, "
    "modes original_prism/prism_recycle/full_prism, seeds 13/14/15)"
)
ROUND_MATRIX_PREDICATE = (
    "every round evidence row belongs to exactly one fixed matrix coordinate "
    "with matching run_id, scenario, mode, and seed"
)
CAUSAL_PREDICATES = (
    "at least two recoverable/prism_recycle seeds have a chain-backed progress round",
    "at least two recoverable/full_prism seeds have a chain-backed progress round and no applied handoff",
    "at least two persistent/full_prism seeds have an evidence-backed no-progress applied-handoff round",
    "no persistent/original_prism seed has a handoff round",
    "no persistent/prism_recycle seed has a handoff round",
)


def _percentile_99(values: Iterable[int]) -> int:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("no genuine ACK queueing-delay samples")
    return ordered[math.ceil(0.99 * len(ordered)) - 1]


def _mean(values: Iterable[float]) -> float:
    samples = list(values)
    if not samples:
        raise ValueError("cannot average an empty series")
    return statistics.fmean(samples)


def _trace_prefix(manifest_path: Path) -> Path:
    return manifest_path.with_suffix("").with_suffix("")


def _load_manifest(manifest_path: Path) -> dict:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid manifest {manifest_path}: {exc}") from exc
    config = manifest.get("config", {})
    analysis = manifest.get("analysis_config", {})
    mode = config.get("prism_coordination_mode")
    scenario = analysis.get("scenario")
    if mode not in MODES:
        raise ValueError(f"{manifest_path}: invalid prism coordination mode {mode!r}")
    if scenario not in SCENARIOS:
        raise ValueError(f"{manifest_path}: invalid M3 scenario {scenario!r}")
    if config.get("cc") != "prism" or config.get("load_balancing_algo") != "reps_actual":
        raise ValueError(f"{manifest_path}: M3 requires prism with reps_actual")
    if config.get("degraded_links") != 8 or float(config.get("degraded_capacity_gbps", 0)) != 25.0:
        raise ValueError(f"{manifest_path}: M3 requires eight 25 Gbps degraded links")
    return manifest


def _common_window(bundle, foreground_flows: int) -> tuple[int, int]:
    by_flow = defaultdict(list)
    for ack in bundle.ack:
        if ack["time_ps"] >= WARMUP_PS:
            by_flow[ack["flow_id"]].append(ack["time_ps"])
    expected_flow_ids = set(range(1, foreground_flows + 1))
    if set(by_flow) != expected_flow_ids:
        raise ValueError(
            f"{bundle.run_id}: foreground ACK coverage; foreground ACK flow IDs are {sorted(by_flow)}; "
            f"manifest requires {sorted(expected_flow_ids)}"
        )
    end_ps = min(max(times) for times in by_flow.values())
    if end_ps <= WARMUP_PS:
        # A one-sample-per-flow fixture still has a valid window anchored at warm-up.
        end_ps = max(max(times) for times in by_flow.values())
    if end_ps <= WARMUP_PS:
        raise ValueError(f"{bundle.run_id}: nonpositive post-warm-up window")
    return WARMUP_PS, end_ps


def _path_attribution(bundle) -> dict[tuple[int, int], tuple[bool, int]]:
    attribution = {}
    for row in bundle.pathmap:
        key = (row["flow_id"], row["entropy"])
        if row["resolution_status"] != "resolved":
            raise ValueError(f"{bundle.run_id}: unresolved pathmap attribution for {key}")
        if key in attribution:
            raise ValueError(f"{bundle.run_id}: duplicate pathmap mapping for {key}")
        attribution[key] = (row["contains_reduced_link"], row["physical_path_id"])
    return attribution


def _observer_epoch_index(bundle, coordination: dict, *, start_ps: int) -> int:
    candidates = [
        epoch for epoch in bundle.epoch
        if epoch["flow_id"] == coordination["flow_id"]
        and epoch["end_ps"] >= start_ps
        and epoch["end_ps"] <= coordination["time_ps"]
    ]
    if not candidates:
        raise ValueError(
            f"{bundle.run_id}: no completed observer epoch for flow {coordination['flow_id']} "
            f"at coordination time {coordination['time_ps']}"
        )
    latest_end_ps = max(epoch["end_ps"] for epoch in candidates)
    latest = [epoch for epoch in candidates if epoch["end_ps"] == latest_end_ps]
    if len(latest) != 1:
        raise ValueError(
            f"{bundle.run_id}: ambiguous completed observer epoch for flow {coordination['flow_id']} "
            f"at coordination time {coordination['time_ps']}"
        )
    return latest[0]["epoch_id"]


def _replacement_chain_complete(bundle, terminal: dict) -> bool:
    """Return whether every invalidated slot has an ordered replacement chain."""
    terminal_seq = terminal["event_seq"]
    if not terminal["refresh_complete"]:
        return False

    invalidations = [
        row for row in bundle.coordination
        if row["action"] == "invalidate"
        and row["flow_id"] == terminal["flow_id"]
        and row["round_id"] == terminal["round_id"]
        and row["event_seq"] < terminal_seq
    ]
    if not invalidations:
        return False

    ack_by_event_seq = {row["event_seq"]: row for row in bundle.ack}
    retains = [
        row for row in bundle.coordination
        if row["action"] == "retain"
        and row["flow_id"] == terminal["flow_id"]
        and row["round_id"] == terminal["round_id"]
        and row["event_seq"] < terminal_seq
    ]

    for invalidation in invalidations:
        replacement_found = False
        for admission in bundle.token:
            if not (
                invalidation["event_seq"] < admission["event_seq"] < terminal_seq
                and admission["flow_id"] == terminal["flow_id"]
                and admission["operation"] in {"enqueue_good_ack", "overwrite_good_ack"}
                and admission["admission_written"]
                and admission["cache_slot"] == invalidation["cache_slot"]
                and admission["cache_generation"] > invalidation["cache_generation"]
            ):
                continue
            ack = ack_by_event_seq.get(admission["related_ack_event_seq"])
            if not (
                ack
                and invalidation["event_seq"] < ack["event_seq"] < admission["event_seq"]
                and ack["flow_id"] == terminal["flow_id"]
                and ack["genuine_sample"]
                and not ack["ecn"]
            ):
                continue
            if any(
                admission["event_seq"] < retain["event_seq"] < terminal_seq
                and retain["cache_slot"] == admission["cache_slot"]
                and retain["cache_generation"] == admission["cache_generation"]
                for retain in retains
            ):
                replacement_found = True
                break
        if not replacement_found:
            return False
    return True


def _clean_scan_complete(bundle, terminal: dict) -> bool:
    """Return whether every physical cache slot was last retained before terminal."""
    terminal_seq = terminal["event_seq"]
    if not terminal["refresh_complete"]:
        return False

    round_records = [
        row for row in bundle.coordination
        if row["flow_id"] == terminal["flow_id"]
        and row["round_id"] == terminal["round_id"]
        and row["event_seq"] < terminal_seq
    ]
    if any(row["action"] == "invalidate" for row in round_records):
        return False

    slot_records = [row for row in round_records if 0 <= row["cache_slot"] < 8]

    latest_by_slot = {}
    for row in slot_records:
        slot = row["cache_slot"]
        previous = latest_by_slot.get(slot)
        if previous is None or row["event_seq"] > previous["event_seq"]:
            latest_by_slot[slot] = row
    return all(
        slot in latest_by_slot and latest_by_slot[slot]["action"] == "retain"
        for slot in range(8)
    )


def _validate_coordination(bundle, *, scenario: str, mode: str, start_ps: int) -> list[dict]:
    rounds = []
    completed = [row for row in bundle.coordination if row["action"].startswith("round_complete_")]
    for row in completed:
        if row["handoff"] and not row["refresh_complete"]:
            raise ValueError(f"{bundle.run_id}: handoff before refresh completion")
        if row["handoff"] and mode != "full_prism":
            raise ValueError(f"{bundle.run_id}: non-full mode handed off")
        if scenario == "recoverable" and mode == "full_prism" and row["handoff"]:
            raise ValueError(f"{bundle.run_id}: recoverable full_prism handed off")
        if mode == "full_prism" and row["handoff"] and row["spread_ps"] < row["spread_ref_ps"]:
            raise ValueError(f"{bundle.run_id}: handoff after positive spread progress")
        chain_complete = _replacement_chain_complete(bundle, row)
        clean_scan_complete = _clean_scan_complete(bundle, row)
        if not chain_complete and not clean_scan_complete:
            raise ValueError(
                f"{bundle.run_id}: terminal evidence incomplete for round {row['round_id']}"
            )
        rounds.append({
            "run_id": bundle.run_id,
            "scenario": scenario,
            "mode": mode,
            "seed": "",
            "round_index": row["round_id"],
            "epoch_id": row["epoch_id"],
            "plot_epoch_index": _observer_epoch_index(bundle, row, start_ps=start_ps),
            "floor_ps": row["floor_ps"],
            "spread_ps": row["spread_ps"],
            "spread_ref_ps": row["spread_ref_ps"],
            "spread_change_ps": row["spread_ref_ps"] - row["spread_ps"],
            "refresh_complete": row["refresh_complete"],
            "replacement_chain_complete": chain_complete,
            "clean_scan_complete": clean_scan_complete,
            "progress": row["progress"],
            "handoff": row["handoff"],
            "cwnd_bytes": row["cwnd_bytes"],
            "control_state": row["control_state"],
        })
    return rounds


def _analyze_bundle(manifest_path: Path) -> tuple[dict, list[dict], list[dict]]:
    manifest = _load_manifest(manifest_path)
    config = manifest["config"]
    analysis = manifest["analysis_config"]
    mode = config["prism_coordination_mode"]
    scenario = analysis["scenario"]
    seed = int(analysis.get("seed", manifest.get("seed")))
    try:
        foreground_flows = int(analysis["foreground_flows"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{manifest_path}: invalid analysis_config.foreground_flows") from exc
    if foreground_flows <= 0:
        raise ValueError(f"{manifest_path}: invalid analysis_config.foreground_flows")
    bundle = load_trace_compact(_trace_prefix(manifest_path))
    if bundle.run_id != manifest.get("run_id"):
        raise ValueError(f"{manifest_path}: manifest and trace run IDs differ")

    coordination_recycles = [row for row in bundle.coordination if row["action"] == "invalidate"]
    if mode == "original_prism" and coordination_recycles:
        raise ValueError(f"{bundle.run_id}: original_prism emitted recycle")

    start_ps, end_ps = _common_window(bundle, foreground_flows)
    path_reduced = _path_attribution(bundle)
    healthy_bytes = 0
    throttled_bytes = 0
    foreground_bytes = 0
    qdelays = []
    for ack in bundle.ack:
        if not start_ps <= ack["time_ps"] <= end_ps:
            continue
        key = (ack["flow_id"], ack["entropy"])
        if key not in path_reduced:
            raise ValueError(f"{bundle.run_id}: ACK lacks pathmap attribution for {key}")
        acked = ack["newly_acked_bytes"]
        foreground_bytes += acked
        contains_reduced_link, physical_path_id = path_reduced[key]
        if ack["physical_path_id"] != physical_path_id:
            raise ValueError(
                f"{bundle.run_id}: ACK physical path ID mismatch for {key}: "
                f"ACK has {ack['physical_path_id']}, pathmap has {physical_path_id}"
            )
        if contains_reduced_link:
            throttled_bytes += acked
        else:
            healthy_bytes += acked
        if ack["genuine_sample"]:
            qdelays.append(ack["qdelay_ps"])
    if foreground_bytes == 0:
        raise ValueError(f"{bundle.run_id}: no ACKed foreground bytes in common window")
    duration_ps = end_ps - start_ps
    goodput_gbps = foreground_bytes * 8_000 / duration_ps
    rounds = _validate_coordination(bundle, scenario=scenario, mode=mode, start_ps=start_ps)
    for row in rounds:
        row["seed"] = seed

    epoch_groups = defaultdict(list)
    for epoch in bundle.epoch:
        if epoch["end_ps"] >= start_ps:
            epoch_groups[epoch["epoch_id"]].append(epoch)
    epoch_rows = []
    for epoch_id, rows in sorted(epoch_groups.items()):
        epoch_rows.append({
            "run_id": bundle.run_id,
            "scenario": scenario,
            "mode": mode,
            "seed": seed,
            "epoch_index": epoch_id,
            "floor_ps": _mean(row["smooth_floor_ps"] for row in rows),
            "spread_ps": _mean(row["smooth_spread_ps"] for row in rows),
            "cwnd_bytes": _mean(row["cwnd_bytes"] for row in rows),
            "hold_fraction": _mean(row["actual_region"] == "hold" for row in rows),
        })

    metrics = {
        "run_id": bundle.run_id,
        "scenario": scenario,
        "mode": mode,
        "seed": seed,
        "window_start_ps": start_ps,
        "window_end_ps": end_ps,
        "foreground_acked_bytes": foreground_bytes,
        "healthy_acked_bytes": healthy_bytes,
        "throttled_acked_bytes": throttled_bytes,
        "healthy_to_throttled_ratio": healthy_bytes / throttled_bytes if throttled_bytes else "",
        "throttled_traffic_ratio": throttled_bytes / foreground_bytes,
        "goodput_gbps": goodput_gbps,
        "p99_genuine_qdelay_ps": _percentile_99(qdelays),
        "completed_rounds": len(rounds),
        "progress_rounds": sum(row["progress"] for row in rounds),
        "handoff_rounds": sum(row["handoff"] for row in rounds),
    }
    return metrics, rounds, epoch_rows


def _summary(rows: list[dict]) -> list[dict]:
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["scenario"], row["mode"])].append(row)
    summary = []
    for (scenario, mode), samples in sorted(grouped.items()):
        summary.append({
            "scenario": scenario,
            "mode": mode,
            "seed_count": len(samples),
            "mean_healthy_to_throttled_ratio": _mean(float(row["healthy_to_throttled_ratio"]) for row in samples if row["healthy_to_throttled_ratio"] != ""),
            "mean_throttled_traffic_ratio": _mean(float(row["throttled_traffic_ratio"]) for row in samples),
            "mean_goodput_gbps": _mean(float(row["goodput_gbps"]) for row in samples),
            "mean_p99_genuine_qdelay_ps": _mean(float(row["p99_genuine_qdelay_ps"]) for row in samples),
            "mean_progress_rounds": _mean(float(row["progress_rounds"]) for row in samples),
            "mean_handoff_rounds": _mean(float(row["handoff_rounds"]) for row in samples),
        })
    return summary


def analyze_data(data_root: Path | str = DATA_ROOT, *, write: bool = False) -> dict[str, list[dict]]:
    """Load M3 manifests/traces, validate causality, and return aggregate rows."""
    data_root = Path(data_root)
    manifests = sorted(path for path in data_root.rglob("*.manifest.json") if "aggregate" not in path.parts)
    if not manifests:
        raise ValueError(f"no M3 manifests below {data_root}")
    metrics, rounds, epochs = [], [], []
    for path in manifests:
        per_seed, run_rounds, run_epochs = _analyze_bundle(path)
        metrics.append(per_seed)
        rounds.extend(run_rounds)
        epochs.extend(run_epochs)
    result = {
        "epoch_series": sorted(epochs, key=lambda row: (row["scenario"], row["mode"], row["seed"], row["epoch_index"])),
        "rounds": sorted(rounds, key=lambda row: (row["scenario"], row["mode"], row["seed"], row["round_index"])),
        "per_seed_metrics": sorted(metrics, key=lambda row: (row["scenario"], row["mode"], row["seed"])),
        "summary": _summary(metrics),
    }
    if write:
        aggregate = data_root / "aggregate"
        aggregate.mkdir(parents=True, exist_ok=True)
        for name, rows in result.items():
            _write_csv(aggregate / f"{name}.csv", rows, TABLE_FIELDS[name])
    return result


def _write_csv(path: Path, rows: list[dict], fallback_fields: tuple[str, ...]) -> None:
    with path.open("w", newline="", encoding="ascii") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else fallback_fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _read_aggregate_csv(data_root: Path, name: str) -> list[dict] | None:
    path = data_root / "aggregate" / f"{name}.csv"
    try:
        with path.open(newline="", encoding="ascii") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None or not set(TABLE_FIELDS[name]).issubset(reader.fieldnames):
                return None
            return list(reader)
    except (OSError, UnicodeDecodeError, csv.Error):
        return None


def _matrix_rows(rows: list[dict] | None) -> dict[tuple[str, str, int], dict] | None:
    if rows is None or len(rows) != len(SCENARIOS) * len(MODES) * len(SEEDS):
        return None
    matrix = {}
    run_ids = set()
    try:
        for row in rows:
            run_id = row["run_id"]
            if not isinstance(run_id, str) or not run_id or run_id in run_ids:
                return None
            run_ids.add(run_id)
            key = (row["scenario"], row["mode"], int(row["seed"]))
            if key in matrix:
                return None
            matrix[key] = row
    except (KeyError, TypeError, ValueError):
        return None
    expected = {(scenario, mode, seed) for scenario in SCENARIOS for mode in MODES for seed in SEEDS}
    return matrix if set(matrix) == expected else None


def _is_true(row: dict, field: str) -> bool:
    value = row.get(field)
    return isinstance(value, str) and value.strip().lower() in {"1", "true"}


def _is_chain_backed_terminal(row: dict) -> bool:
    return _is_true(row, "refresh_complete") and _is_true(row, "replacement_chain_complete")


def _is_clean_scan_backed_terminal(row: dict) -> bool:
    return _is_true(row, "refresh_complete") and _is_true(row, "clean_scan_complete")


def _rounds_belong_to_matrix(rounds: list[dict], matrix: dict[tuple[str, str, int], dict]) -> bool:
    run_id_coordinates = defaultdict(list)
    for coordinate, row in matrix.items():
        run_id_coordinates[row["run_id"]].append(coordinate)
    for row in rounds:
        run_id = row.get("run_id")
        if not isinstance(run_id, str) or not run_id.strip():
            return False
        coordinates = run_id_coordinates.get(run_id, [])
        if len(coordinates) != 1:
            return False
        scenario, mode, seed = coordinates[0]
        if (
            row.get("scenario") != scenario
            or row.get("mode") != mode
            or row.get("seed") != str(seed)
        ):
            return False
    return True


def verify_aggregate(data_root: Path | str = DATA_ROOT) -> str:
    """Return the all-seed M3 causal verdict from existing aggregate CSVs."""
    data_root = Path(data_root)
    matrix = _matrix_rows(_read_aggregate_csv(data_root, "per_seed_metrics"))
    if matrix is None:
        return f"not_supported: {MATRIX_PREDICATE}"

    rounds = _read_aggregate_csv(data_root, "rounds")
    if rounds is None:
        rounds = []
    if not _rounds_belong_to_matrix(rounds, matrix):
        return f"not_supported: {ROUND_MATRIX_PREDICATE}"

    def selected_rounds(scenario: str, mode: str, seed: int) -> list[dict]:
        run_id = matrix[(scenario, mode, seed)]["run_id"]
        return [
            row for row in rounds
            if row.get("run_id") == run_id
            and row.get("scenario") == scenario
            and row.get("mode") == mode
            and row.get("seed") == str(seed)
        ]

    recoverable_full = {seed: selected_rounds("recoverable", "full_prism", seed) for seed in SEEDS}
    recoverable_recycle = {seed: selected_rounds("recoverable", "prism_recycle", seed) for seed in SEEDS}
    recoverable_recycle_successes = sum(
        any(
            _is_chain_backed_terminal(row)
            and _is_true(row, "progress")
            for row in seed_rounds
        )
        for seed_rounds in recoverable_recycle.values()
    )
    if recoverable_recycle_successes < 2:
        return f"not_supported: {CAUSAL_PREDICATES[0]}"
    recoverable_successes = sum(
        any(
            _is_chain_backed_terminal(row)
            and _is_true(row, "progress")
            for row in seed_rounds
        )
        and not any(_is_true(row, "handoff") for row in seed_rounds)
        for seed_rounds in recoverable_full.values()
    )
    if recoverable_successes < 2:
        return f"not_supported: {CAUSAL_PREDICATES[1]}"

    persistent_full = {seed: selected_rounds("persistent", "full_prism", seed) for seed in SEEDS}
    persistent_successes = sum(
        any(
            (_is_chain_backed_terminal(row) or _is_clean_scan_backed_terminal(row))
            and _is_true(row, "handoff")
            and not _is_true(row, "progress")
            for row in seed_rounds
        )
        for seed_rounds in persistent_full.values()
    )
    if persistent_successes < 2:
        return f"not_supported: {CAUSAL_PREDICATES[2]}"
    for mode, predicate in (("original_prism", CAUSAL_PREDICATES[3]), ("prism_recycle", CAUSAL_PREDICATES[4])):
        if any(
            _is_true(row, "handoff")
            for seed in SEEDS
            for row in selected_rounds("persistent", mode, seed)
        ):
            return f"not_supported: {predicate}"
    return "supported"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT)
    parser.add_argument("--verify-only", action="store_true", help="verify existing aggregate CSV causal evidence")
    args = parser.parse_args(argv)
    if args.verify_only:
        print(verify_aggregate(args.data_root))
        return 0
    analyze_data(args.data_root, write=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
