#!/usr/bin/env python3
"""Produce read-only M3 traffic-distribution evidence from trace bundles."""

from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path

from htsim.sim.datacenter.add_motivation.common.trace_schema import load_trace_compact
from htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.analyze import (
    _replacement_chain_complete,
)


WARMUP_PS = 1_000_000_000
MODES = ("original_prism", "prism_recycle")
SCENARIOS = ("recoverable", "persistent")
SEEDS = (13, 14, 15)
LOCKED_CASES = frozenset(
    (mode, scenario, seed)
    for mode in MODES
    for scenario in SCENARIOS
    for seed in SEEDS
)
BIN_FIELDS = (
    "run_id", "scenario", "mode", "seed", "base_rtt_ps", "bin_width_ps",
    "bin_start_ps", "bin_end_ps", "healthy_acked_bytes", "throttled_acked_bytes",
    "throttled_ratio",
)
EFFECT_FIELDS = (
    "run_id", "scenario", "mode", "seed", "flow_id", "round_id", "terminal_time_ps",
    "base_rtt_ps", "bin_width_ps", "pre_window_start_ps", "pre_window_end_ps",
    "post_window_start_ps", "post_window_end_ps", "pre_window_complete",
    "post_window_complete", "pre_healthy_acked_bytes", "pre_throttled_acked_bytes",
    "pre_throttled_ratio", "post_healthy_acked_bytes", "post_throttled_acked_bytes",
    "post_throttled_ratio", "throttled_ratio_change",
)
SUMMARY_FIELDS = (
    "run_id", "scenario", "mode", "seed", "base_rtt_ps", "bin_width_ps",
    "post_warmup_acked_bytes", "healthy_acked_bytes", "throttled_acked_bytes",
    "throttled_ratio", "bin_count", "refresh_effect_count",
    "mean_pre_throttled_ratio", "mean_post_throttled_ratio",
    "mean_throttled_ratio_change",
)


def _trace_prefix(manifest_path: Path) -> Path:
    return manifest_path.with_suffix("").with_suffix("")


def _load_manifest(manifest_path: Path) -> tuple[str, str, int, str]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="ascii"))
        config = manifest["config"]
        analysis = manifest["analysis_config"]
        run_id = manifest["run_id"]
        scenario = analysis["scenario"]
        mode = config["prism_coordination_mode"]
        seed = int(analysis.get("seed", manifest["seed"]))
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid distribution manifest {manifest_path}: {exc}") from exc
    if not isinstance(run_id, str) or not run_id:
        raise ValueError(f"{manifest_path}: invalid run_id")
    if mode not in MODES:
        raise ValueError(f"{manifest_path}: invalid distribution mode {mode!r}")
    if not isinstance(scenario, str) or not scenario:
        raise ValueError(f"{manifest_path}: invalid scenario")
    return run_id, scenario, seed, mode


def _validate_locked_manifest_set(manifest_paths: list[Path]) -> None:
    cases = []
    for manifest_path in manifest_paths:
        _run_id, scenario, seed, mode = _load_manifest(manifest_path)
        cases.append((mode, scenario, seed))
    actual_cases = set(cases)
    duplicates = sorted(case for case in actual_cases if cases.count(case) > 1)
    missing = sorted(LOCKED_CASES - actual_cases)
    unexpected = sorted(actual_cases - LOCKED_CASES)
    if len(cases) != len(LOCKED_CASES) or duplicates or missing or unexpected:
        raise ValueError(
            "require locked 12-case manifest set "
            f"(missing={missing}, duplicate={duplicates}, unexpected={unexpected})"
        )


def _resolved_attribution(bundle) -> dict[tuple[int, int], tuple[bool, int]]:
    attribution = {}
    for row in bundle.pathmap:
        key = (row["flow_id"], row["entropy"])
        if row["resolution_status"] != "resolved":
            raise ValueError(f"{bundle.run_id}: unresolved pathmap attribution for {key}")
        if key in attribution:
            raise ValueError(f"{bundle.run_id}: duplicate pathmap mapping for {key}")
        attribution[key] = (row["contains_reduced_link"], row["physical_path_id"])
    return attribution


def _base_rtt_ps(bundle) -> int:
    values = {ack["base_rtt_ps"] for ack in bundle.ack}
    if len(values) != 1:
        raise ValueError(f"{bundle.run_id}: require one identical ACK base RTT per run")
    value = next(iter(values))
    if value <= 0:
        raise ValueError(f"{bundle.run_id}: ACK base RTT must be positive")
    return value


def _ratio(healthy_bytes: int, throttled_bytes: int) -> float | str:
    total = healthy_bytes + throttled_bytes
    return throttled_bytes / total if total else ""


def _window_bytes(acks, start_ps: int, end_ps: int) -> tuple[int, int]:
    healthy_bytes = 0
    throttled_bytes = 0
    for ack, contains_reduced_link in acks:
        if start_ps <= ack["time_ps"] < end_ps:
            if contains_reduced_link:
                throttled_bytes += ack["newly_acked_bytes"]
            else:
                healthy_bytes += ack["newly_acked_bytes"]
    return healthy_bytes, throttled_bytes


def _complete_window(start_ps: int, end_ps: int, last_ack_ps: int) -> bool:
    return start_ps >= WARMUP_PS and end_ps <= last_ack_ps


def _distribution_bins(*, run_id: str, scenario: str, mode: str, seed: int,
                       base_rtt_ps: int, acks) -> list[dict]:
    bin_width_ps = 4 * base_rtt_ps
    last_ack_ps = max(ack["time_ps"] for ack, _reduced in acks)
    counts = defaultdict(lambda: [0, 0])
    for ack, contains_reduced_link in acks:
        index = (ack["time_ps"] - WARMUP_PS) // bin_width_ps
        counts[index][int(contains_reduced_link)] += ack["newly_acked_bytes"]
    rows = []
    for index in range((last_ack_ps - WARMUP_PS) // bin_width_ps + 1):
        healthy_bytes, throttled_bytes = counts[index]
        start_ps = WARMUP_PS + index * bin_width_ps
        rows.append({
            "run_id": run_id,
            "scenario": scenario,
            "mode": mode,
            "seed": seed,
            "base_rtt_ps": base_rtt_ps,
            "bin_width_ps": bin_width_ps,
            "bin_start_ps": start_ps,
            "bin_end_ps": start_ps + bin_width_ps,
            "healthy_acked_bytes": healthy_bytes,
            "throttled_acked_bytes": throttled_bytes,
            "throttled_ratio": _ratio(healthy_bytes, throttled_bytes),
        })
    return rows


def _refresh_effects(*, bundle, run_id: str, scenario: str, mode: str, seed: int,
                     base_rtt_ps: int, acks) -> list[dict]:
    if mode != "prism_recycle":
        return []
    bin_width_ps = 4 * base_rtt_ps
    last_ack_ps = max(ack["time_ps"] for ack, _reduced in acks)
    rows = []
    for terminal in bundle.coordination:
        if not terminal["action"].startswith("round_complete_"):
            continue
        terminal_time_ps = terminal["time_ps"]
        if terminal_time_ps < WARMUP_PS or not _replacement_chain_complete(bundle, terminal):
            continue

        # Effects are terminal-anchored, non-overlapping windows: [t-width, t), [t, t+width).
        pre_start_ps = terminal_time_ps - bin_width_ps
        pre_end_ps = terminal_time_ps
        post_start_ps = terminal_time_ps
        post_end_ps = terminal_time_ps + bin_width_ps
        pre_complete = _complete_window(pre_start_ps, pre_end_ps, last_ack_ps)
        post_complete = _complete_window(post_start_ps, post_end_ps, last_ack_ps)
        pre_healthy, pre_throttled = _window_bytes(acks, pre_start_ps, pre_end_ps)
        post_healthy, post_throttled = _window_bytes(acks, post_start_ps, post_end_ps)
        pre_ratio = _ratio(pre_healthy, pre_throttled) if pre_complete else ""
        post_ratio = _ratio(post_healthy, post_throttled) if post_complete else ""
        change = post_ratio - pre_ratio if pre_ratio != "" and post_ratio != "" else ""
        rows.append({
            "run_id": run_id,
            "scenario": scenario,
            "mode": mode,
            "seed": seed,
            "flow_id": terminal["flow_id"],
            "round_id": terminal["round_id"],
            "terminal_time_ps": terminal_time_ps,
            "base_rtt_ps": base_rtt_ps,
            "bin_width_ps": bin_width_ps,
            "pre_window_start_ps": pre_start_ps,
            "pre_window_end_ps": pre_end_ps,
            "post_window_start_ps": post_start_ps,
            "post_window_end_ps": post_end_ps,
            "pre_window_complete": int(pre_complete),
            "post_window_complete": int(post_complete),
            "pre_healthy_acked_bytes": pre_healthy,
            "pre_throttled_acked_bytes": pre_throttled,
            "pre_throttled_ratio": pre_ratio,
            "post_healthy_acked_bytes": post_healthy,
            "post_throttled_acked_bytes": post_throttled,
            "post_throttled_ratio": post_ratio,
            "throttled_ratio_change": change,
        })
    return rows


def _mean_or_blank(rows: list[dict], field: str) -> float | str:
    values = [float(row[field]) for row in rows if row[field] != ""]
    return statistics.fmean(values) if values else ""


def _analyze_bundle(manifest_path: Path) -> tuple[list[dict], list[dict], dict]:
    expected_run_id, scenario, seed, mode = _load_manifest(manifest_path)
    bundle = load_trace_compact(_trace_prefix(manifest_path))
    if bundle.run_id != expected_run_id:
        raise ValueError(f"{manifest_path}: manifest and trace run IDs differ")
    base_rtt_ps = _base_rtt_ps(bundle)
    attribution = _resolved_attribution(bundle)
    post_warmup_acks = []
    for ack in bundle.ack:
        key = (ack["flow_id"], ack["entropy"])
        if key not in attribution:
            raise ValueError(f"{bundle.run_id}: ACK lacks pathmap attribution for {key}")
        contains_reduced_link, physical_path_id = attribution[key]
        if ack["physical_path_id"] != physical_path_id:
            raise ValueError(
                f"{bundle.run_id}: ACK physical path ID mismatch for {key}: "
                f"ACK has {ack['physical_path_id']}, pathmap has {physical_path_id}"
            )
        if ack["time_ps"] >= WARMUP_PS:
            post_warmup_acks.append((ack, contains_reduced_link))
    if not post_warmup_acks:
        raise ValueError(f"{bundle.run_id}: no post-warm-up ACKs")

    bins = _distribution_bins(
        run_id=bundle.run_id, scenario=scenario, mode=mode, seed=seed,
        base_rtt_ps=base_rtt_ps, acks=post_warmup_acks,
    )
    effects = _refresh_effects(
        bundle=bundle, run_id=bundle.run_id, scenario=scenario, mode=mode, seed=seed,
        base_rtt_ps=base_rtt_ps, acks=post_warmup_acks,
    )
    healthy_bytes = sum(row["healthy_acked_bytes"] for row in bins)
    throttled_bytes = sum(row["throttled_acked_bytes"] for row in bins)
    summary = {
        "run_id": bundle.run_id,
        "scenario": scenario,
        "mode": mode,
        "seed": seed,
        "base_rtt_ps": base_rtt_ps,
        "bin_width_ps": 4 * base_rtt_ps,
        "post_warmup_acked_bytes": healthy_bytes + throttled_bytes,
        "healthy_acked_bytes": healthy_bytes,
        "throttled_acked_bytes": throttled_bytes,
        "throttled_ratio": _ratio(healthy_bytes, throttled_bytes),
        "bin_count": len(bins),
        "refresh_effect_count": len(effects),
        "mean_pre_throttled_ratio": _mean_or_blank(effects, "pre_throttled_ratio"),
        "mean_post_throttled_ratio": _mean_or_blank(effects, "post_throttled_ratio"),
        "mean_throttled_ratio_change": _mean_or_blank(effects, "throttled_ratio_change"),
    }
    return bins, effects, summary


def _write_csv(path: Path, rows: list[dict], fields: tuple[str, ...]) -> None:
    with path.open("w", newline="", encoding="ascii") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def analyze_distribution(data_root: Path | str, output_root: Path | str) -> dict[str, list[dict]]:
    """Write per-run distribution bins, chain-backed refresh effects, and figure summary."""
    data_root = Path(data_root)
    output_root = Path(output_root)
    manifests = sorted(
        path for path in data_root.rglob("*.manifest.json") if output_root not in path.parents
    )
    if not manifests:
        raise ValueError(f"no distribution manifests below {data_root}")
    _validate_locked_manifest_set(manifests)
    bins, effects, summaries = [], [], []
    for manifest_path in manifests:
        run_bins, run_effects, summary = _analyze_bundle(manifest_path)
        bins.extend(run_bins)
        effects.extend(run_effects)
        summaries.append(summary)
    bins.sort(key=lambda row: (row["scenario"], row["mode"], row["seed"], row["bin_start_ps"]))
    effects.sort(key=lambda row: (row["scenario"], row["mode"], row["seed"], row["terminal_time_ps"], row["flow_id"], row["round_id"]))
    summaries.sort(key=lambda row: (row["scenario"], row["mode"], row["seed"], row["run_id"]))
    output_root.mkdir(parents=True, exist_ok=True)
    _write_csv(output_root / "distribution_bins.csv", bins, BIN_FIELDS)
    _write_csv(output_root / "refresh_effects.csv", effects, EFFECT_FIELDS)
    _write_csv(output_root / "summary.csv", summaries, SUMMARY_FIELDS)
    return {"distribution_bins": bins, "refresh_effects": effects, "summary": summaries}
