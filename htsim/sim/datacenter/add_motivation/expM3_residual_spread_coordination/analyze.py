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
TABLE_FIELDS = {
    "epoch_series": ("run_id", "scenario", "mode", "seed", "epoch_index", "floor_ps", "spread_ps", "cwnd_bytes", "hold_fraction"),
    "rounds": ("run_id", "scenario", "mode", "seed", "round_index", "epoch_id", "floor_ps", "spread_ps", "spread_ref_ps", "spread_change_ps", "refresh_complete", "progress", "handoff", "cwnd_bytes", "control_state"),
    "per_seed_metrics": ("run_id", "scenario", "mode", "seed", "window_start_ps", "window_end_ps", "foreground_acked_bytes", "healthy_acked_bytes", "throttled_acked_bytes", "healthy_to_throttled_ratio", "throttled_traffic_ratio", "goodput_gbps", "p99_genuine_qdelay_ps", "completed_rounds", "progress_rounds", "handoff_rounds"),
    "summary": ("scenario", "mode", "seed_count", "mean_healthy_to_throttled_ratio", "mean_throttled_traffic_ratio", "mean_goodput_gbps", "mean_p99_genuine_qdelay_ps", "mean_progress_rounds", "mean_handoff_rounds"),
}


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


def _common_window(bundle) -> tuple[int, int]:
    by_flow = defaultdict(list)
    for ack in bundle.ack:
        if ack["time_ps"] >= WARMUP_PS:
            by_flow[ack["flow_id"]].append(ack["time_ps"])
    if not by_flow:
        raise ValueError(f"{bundle.run_id}: no post-warm-up foreground ACKs")
    end_ps = min(max(times) for times in by_flow.values())
    if end_ps <= WARMUP_PS:
        # A one-sample-per-flow fixture still has a valid window anchored at warm-up.
        end_ps = max(max(times) for times in by_flow.values())
    if end_ps <= WARMUP_PS:
        raise ValueError(f"{bundle.run_id}: nonpositive post-warm-up window")
    return WARMUP_PS, end_ps


def _validate_coordination(bundle, *, scenario: str, mode: str) -> list[dict]:
    rounds = []
    completed = [row for row in bundle.coordination if row["action"].startswith("round_complete_")]
    for row in completed:
        if row["handoff"] and not row["refresh_complete"]:
            raise ValueError(f"{bundle.run_id}: handoff before refresh completion")
        if row["handoff"] and mode != "full_prism":
            raise ValueError(f"{bundle.run_id}: non-full mode handed off")
        if scenario == "recoverable" and mode == "full_prism" and row["handoff"]:
            raise ValueError(f"{bundle.run_id}: recoverable full_prism handed off")
        rounds.append({
            "run_id": bundle.run_id,
            "scenario": scenario,
            "mode": mode,
            "seed": "",
            "round_index": row["round_id"],
            "epoch_id": row["epoch_id"],
            "floor_ps": row["floor_ps"],
            "spread_ps": row["spread_ps"],
            "spread_ref_ps": row["spread_ref_ps"],
            "spread_change_ps": row["spread_ref_ps"] - row["spread_ps"],
            "refresh_complete": row["refresh_complete"],
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
    bundle = load_trace_compact(_trace_prefix(manifest_path))
    if bundle.run_id != manifest.get("run_id"):
        raise ValueError(f"{manifest_path}: manifest and trace run IDs differ")

    coordination_recycles = [row for row in bundle.coordination if row["action"] == "invalidate"]
    if mode == "original_prism" and coordination_recycles:
        raise ValueError(f"{bundle.run_id}: original_prism emitted recycle")

    start_ps, end_ps = _common_window(bundle)
    path_reduced = {
        (row["flow_id"], row["entropy"]): row["contains_reduced_link"]
        for row in bundle.pathmap
    }
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
        if path_reduced[key]:
            throttled_bytes += acked
        else:
            healthy_bytes += acked
        if ack["genuine_sample"]:
            qdelays.append(ack["qdelay_ps"])
    if foreground_bytes == 0:
        raise ValueError(f"{bundle.run_id}: no ACKed foreground bytes in common window")
    duration_ps = end_ps - start_ps
    goodput_gbps = foreground_bytes * 8_000 / duration_ps
    rounds = _validate_coordination(bundle, scenario=scenario, mode=mode)
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT)
    args = parser.parse_args(argv)
    analyze_data(args.data_root, write=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
