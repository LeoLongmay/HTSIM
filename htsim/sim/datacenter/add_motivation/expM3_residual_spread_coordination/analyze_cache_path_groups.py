#!/usr/bin/env python3
"""Measure whether residual-targeted cache entries share reduced link groups."""

from __future__ import annotations

import csv
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.analyze_distribution import (
    _stream_rows,
    _trace_prefix,
)


EXPERIMENT = "M3_residual_spread_coordination"
TARGET_FIELDS = (
    "run_id", "mode", "scenario", "seed", "time_ps", "flow_id", "round_id",
    "cache_slot", "cache_generation", "entropy", "physical_path_id", "queue_group",
    "residual_ps", "target_reason", "cohort_slot_count",
    "additional_cohort_slot_count", "active_cache_slot_count",
)
SUMMARY_FIELDS = (
    "run_id", "mode", "scenario", "seed", "queue_group", "cache_admission_count",
    "high_residual_target_count", "cache_admission_share", "high_residual_target_share",
    "target_enrichment", "cohort_with_additional_count", "cohort_with_additional_fraction",
    "mean_additional_cohort_slot_count",
)
MATRIX_FIELDS = (
    "mode", "scenario", "queue_group", "seed_count", "mean_cache_admission_share",
    "mean_high_residual_target_share", "mean_target_enrichment",
)
TARGET_ACTIONS = frozenset({
    ("invalidate", "residual_threshold"),
    ("invalidate", "recycled_high_residual"),
    ("reserve", "consumed_high_residual"),
})


def _manifest(path: Path) -> tuple[str, str, str, int]:
    try:
        manifest = json.loads(path.read_text(encoding="ascii"))
        run_id = manifest["run_id"]
        mode = manifest["config"]["prism_coordination_mode"]
        scenario = manifest["analysis_config"]["scenario"]
        seed = manifest["seed"]
    except (KeyError, OSError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid M3 manifest {path}: {exc}") from exc
    if manifest.get("experiment") != EXPERIMENT:
        raise ValueError(f"{path}: experiment must be {EXPERIMENT!r}")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError(f"{path}: invalid run_id")
    if not isinstance(mode, str) or not mode:
        raise ValueError(f"{path}: invalid coordination mode")
    if not isinstance(scenario, str) or not scenario:
        raise ValueError(f"{path}: invalid scenario")
    if type(seed) is not int:
        raise ValueError(f"{path}: invalid seed")
    return run_id, mode, scenario, seed


def _queue_groups(prefix: Path, run_id: str) -> dict[tuple[int, int], tuple[int, str]]:
    reduced_queue_names = {
        row["queue_id"]: row["queue_name"].split(")", 1)[-1]
        for row in _stream_rows(prefix, "linkmap", ("queue_id", "queue_name", "reduced_speed"), run_id)
        if row["reduced_speed"]
    }
    if not reduced_queue_names:
        raise ValueError(f"{run_id}: linkmap has no reduced queues")

    mappings = {}
    for row in _stream_rows(
        prefix,
        "pathmap",
        ("flow_id", "entropy", "physical_path_id", "resolution_status", "contains_reduced_link",
         "ordered_queue_ids"),
        run_id,
    ):
        key = (row["flow_id"], row["entropy"])
        if row["resolution_status"] != "resolved":
            raise ValueError(f"{run_id}: unresolved pathmap mapping for {key}")
        if key in mappings:
            raise ValueError(f"{run_id}: duplicate pathmap mapping for {key}")
        queue_ids = tuple(int(value) for value in row["ordered_queue_ids"].split("|") if value)
        reduced_on_path = tuple(sorted(
            reduced_queue_names[queue_id]
            for queue_id in set(queue_ids).intersection(reduced_queue_names)
        ))
        if bool(reduced_on_path) != row["contains_reduced_link"]:
            raise ValueError(f"{run_id}: inconsistent reduced-link attribution for {key}")
        group = "healthy" if not reduced_on_path else "reduced:" + "+".join(reduced_on_path)
        mappings[key] = (row["physical_path_id"], group)
    return mappings


def _admissions(prefix: Path, run_id: str, mappings) -> dict[tuple[int, int, int], dict]:
    admissions = {}
    for row in _stream_rows(
        prefix,
        "token",
        ("event_seq", "time_ps", "flow_id", "entropy", "cache_slot", "cache_generation",
         "admission_written"),
        run_id,
    ):
        if not row["admission_written"]:
            continue
        key = (row["flow_id"], row["cache_slot"], row["cache_generation"])
        if key in admissions:
            raise ValueError(f"{run_id}: duplicate cache admission for {key}")
        path_key = (row["flow_id"], row["entropy"])
        if path_key not in mappings:
            raise ValueError(f"{run_id}: cache admission lacks pathmap mapping for {path_key}")
        physical_path_id, queue_group = mappings[path_key]
        admissions[key] = {
            "time_ps": row["time_ps"],
            "entropy": row["entropy"],
            "physical_path_id": physical_path_id,
            "queue_group": queue_group,
        }
    if not admissions:
        raise ValueError(f"{run_id}: trace has no written cache admissions")
    return admissions


def _cohort_counts(prefix: Path, run_id: str, admissions) -> dict[int, tuple[int, int, int]]:
    """Return cache cohort sizes immediately before each residual target action."""
    token_rows = iter(_stream_rows(
        prefix,
        "token",
        ("event_seq", "time_ps", "flow_id", "operation", "cache_slot", "cache_generation",
         "admission_written"),
        run_id,
    ))
    active = {}

    def advance_token(token):
        slot_key = (token["flow_id"], token["cache_slot"])
        admission_key = (token["flow_id"], token["cache_slot"], token["cache_generation"])
        if token["admission_written"]:
            if admission_key not in admissions:
                raise ValueError(f"{run_id}: missing admission for {admission_key}")
            active[slot_key] = admission_key
        elif token["operation"] == "dequeue_recycle":
            if active.get(slot_key) == admission_key:
                del active[slot_key]

    try:
        token = next(token_rows)
    except StopIteration:
        token = None

    cohorts = {}
    previous_coord_key = None
    for row in _stream_rows(
        prefix,
        "coordination",
        ("event_seq", "time_ps", "flow_id", "cache_slot", "cache_generation", "action", "reason"),
        run_id,
    ):
        coordination_key = (row["time_ps"], row["event_seq"])
        if previous_coord_key is not None and coordination_key < previous_coord_key:
            raise ValueError(f"{run_id}: coordination trace is not time ordered")
        previous_coord_key = coordination_key
        while token is not None and (token["time_ps"], token["event_seq"]) <= coordination_key:
            advance_token(token)
            try:
                token = next(token_rows)
            except StopIteration:
                token = None

        admission_key = (row["flow_id"], row["cache_slot"], row["cache_generation"])
        if (row["action"], row["reason"]) in TARGET_ACTIONS:
            try:
                target = admissions[admission_key]
            except KeyError as exc:
                raise ValueError(
                    f"{run_id}: residual target has no matching cache admission for {admission_key}"
                ) from exc
            active_entries = [
                entry_key
                for (flow_id, _slot), entry_key in active.items()
                if flow_id == row["flow_id"]
            ]
            matching_slots = sum(
                admissions[entry_key]["queue_group"] == target["queue_group"]
                for entry_key in active_entries
            )
            target_is_active = active.get((row["flow_id"], row["cache_slot"])) == admission_key
            cohort_slot_count = matching_slots if target_is_active else matching_slots + 1
            cohorts[row["event_seq"]] = (
                cohort_slot_count,
                cohort_slot_count - 1,
                len(active_entries),
            )

        if row["action"] == "invalidate" and active.get(
            (row["flow_id"], row["cache_slot"])
        ) == admission_key:
            del active[(row["flow_id"], row["cache_slot"])]
    return cohorts


def _targets(prefix: Path, run_id: str, admissions, cohorts) -> list[dict]:
    targets = []
    for row in _stream_rows(
        prefix,
        "coordination",
        ("event_seq", "time_ps", "flow_id", "round_id", "cache_slot", "cache_generation",
         "residual_ps", "action", "reason"),
        run_id,
    ):
        if (row["action"], row["reason"]) not in TARGET_ACTIONS:
            continue
        key = (row["flow_id"], row["cache_slot"], row["cache_generation"])
        try:
            admission = admissions[key]
        except KeyError as exc:
            raise ValueError(f"{run_id}: residual target has no matching cache admission for {key}") from exc
        if admission["time_ps"] > row["time_ps"]:
            raise ValueError(f"{run_id}: residual target predates its cache admission for {key}")
        if row["event_seq"] not in cohorts:
            raise ValueError(f"{run_id}: residual target has no cache cohort record")
        cohort_slot_count, additional_count, active_count = cohorts[row["event_seq"]]
        targets.append({
            "time_ps": row["time_ps"],
            "flow_id": row["flow_id"],
            "round_id": row["round_id"],
            "cache_slot": row["cache_slot"],
            "cache_generation": row["cache_generation"],
            "entropy": admission["entropy"],
            "physical_path_id": admission["physical_path_id"],
            "queue_group": admission["queue_group"],
            "residual_ps": row["residual_ps"],
            "target_reason": row["reason"],
            "cohort_slot_count": cohort_slot_count,
            "additional_cohort_slot_count": additional_count,
            "active_cache_slot_count": active_count,
        })
    return targets


def _summary_rows(*, run_id: str, mode: str, scenario: str, seed: int, admissions, targets):
    admission_counts = Counter(entry["queue_group"] for entry in admissions.values())
    target_counts = Counter(target["queue_group"] for target in targets)
    total_admissions = sum(admission_counts.values())
    total_targets = sum(target_counts.values())
    rows = []
    for queue_group in sorted(set(admission_counts) | set(target_counts)):
        group_targets = [target for target in targets if target["queue_group"] == queue_group]
        additional_count = sum(
            target["additional_cohort_slot_count"] > 0 for target in group_targets
        )
        admission_share = admission_counts[queue_group] / total_admissions
        target_share = target_counts[queue_group] / total_targets if total_targets else 0.0
        rows.append({
            "run_id": run_id,
            "mode": mode,
            "scenario": scenario,
            "seed": seed,
            "queue_group": queue_group,
            "cache_admission_count": admission_counts[queue_group],
            "high_residual_target_count": target_counts[queue_group],
            "cache_admission_share": admission_share,
            "high_residual_target_share": target_share,
            "target_enrichment": target_share / admission_share,
            "cohort_with_additional_count": additional_count,
            "cohort_with_additional_fraction": (
                additional_count / len(group_targets) if group_targets else 0.0
            ),
            "mean_additional_cohort_slot_count": (
                statistics.fmean(
                    target["additional_cohort_slot_count"] for target in group_targets
                ) if group_targets else 0.0
            ),
        })
    return rows


def _matrix_rows(summary_rows: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for row in summary_rows:
        groups[(row["mode"], row["scenario"], row["queue_group"])].append(row)
    return [{
        "mode": mode,
        "scenario": scenario,
        "queue_group": queue_group,
        "seed_count": len(rows),
        "mean_cache_admission_share": statistics.fmean(row["cache_admission_share"] for row in rows),
        "mean_high_residual_target_share": statistics.fmean(
            row["high_residual_target_share"] for row in rows
        ),
        "mean_target_enrichment": statistics.fmean(row["target_enrichment"] for row in rows),
    } for (mode, scenario, queue_group), rows in sorted(groups.items())]


def _write_csv(path: Path, fields: tuple[str, ...], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="ascii") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def analyze_cache_path_groups(data_root: Path | str, output_root: Path | str) -> dict[str, list[dict]]:
    """Write per-target physical queue attribution and cache-baseline enrichment."""
    data_root = Path(data_root)
    output_root = Path(output_root)
    manifests = sorted(path for path in data_root.glob("*.manifest.json"))
    if not manifests:
        raise ValueError(f"no M3 manifests in {data_root}")

    targets = []
    summaries = []
    for manifest_path in manifests:
        run_id, mode, scenario, seed = _manifest(manifest_path)
        prefix = _trace_prefix(manifest_path)
        mappings = _queue_groups(prefix, run_id)
        admissions = _admissions(prefix, run_id, mappings)
        cohorts = _cohort_counts(prefix, run_id, admissions)
        run_targets = _targets(prefix, run_id, admissions, cohorts)
        for target in run_targets:
            targets.append({"run_id": run_id, "mode": mode, "scenario": scenario, "seed": seed, **target})
        summaries.extend(_summary_rows(
            run_id=run_id,
            mode=mode,
            scenario=scenario,
            seed=seed,
            admissions=admissions,
            targets=run_targets,
        ))

    targets.sort(key=lambda row: (row["run_id"], row["time_ps"], row["flow_id"], row["cache_slot"]))
    summaries.sort(key=lambda row: (row["mode"], row["scenario"], row["seed"], row["queue_group"]))
    matrix = _matrix_rows(summaries)
    output_root.mkdir(parents=True, exist_ok=True)
    _write_csv(output_root / "cache_path_targets.csv", TARGET_FIELDS, targets)
    _write_csv(output_root / "cache_path_group_summary.csv", SUMMARY_FIELDS, summaries)
    _write_csv(output_root / "cache_path_matrix_summary.csv", MATRIX_FIELDS, matrix)
    return {"targets": targets, "summary": summaries, "matrix": matrix}


if __name__ == "__main__":
    HERE = Path(__file__).resolve().parent
    analyze_cache_path_groups(HERE / "data" / "outcome_recycle", HERE / "data" / "outcome_recycle" / "aggregate")
