#!/usr/bin/env python3
"""Produce read-only M3 traffic-distribution evidence from trace bundles."""

from __future__ import annotations

import bisect
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import NamedTuple

from htsim.sim.datacenter.add_motivation.common.trace_schema import (
    SCHEMA_VERSION,
    TraceValidationError,
    _SCHEMAS,
)


WARMUP_PS = 1_000_000_000
MODES = ("original_prism", "prism_recycle")
SCENARIOS = ("recoverable", "persistent")
SEEDS = (13, 14, 15)
EXPERIMENT = "M3_residual_spread_coordination"
DEGRADED_LINKS = {"recoverable": 2, "persistent": 8}
DEGRADED_CAPACITY_GBPS = 25.0
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
_COORDINATION_ACTIONS = frozenset({
    "retain",
    "invalidate",
    "pending",
    "round_complete_progress",
    "round_complete_handoff",
    "round_complete_clean",
    "round_complete_retry",
})
_ADMISSION_OPERATIONS = frozenset({"enqueue_good_ack", "overwrite_good_ack"})
_NO_CACHE_SLOT = 2**16 - 1


class _AdmissionFact(NamedTuple):
    """The token fields needed for admission provenance and chain validation."""

    operation: str
    event_seq: int
    flow_id: int
    entropy: int
    cache_slot: int
    cache_generation: int
    related_ack_event_seq: int


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
        seed = manifest["seed"]
        analysis_seed = analysis["seed"]
        experiment = manifest["experiment"]
    except (KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid distribution manifest {manifest_path}: {exc}") from exc
    if not isinstance(run_id, str) or not run_id:
        raise ValueError(f"{manifest_path}: invalid run_id")
    if experiment != EXPERIMENT:
        raise ValueError(f"{manifest_path}: experiment must be {EXPERIMENT!r}")
    if mode not in MODES:
        raise ValueError(f"{manifest_path}: invalid distribution mode {mode!r}")
    if scenario not in SCENARIOS:
        raise ValueError(f"{manifest_path}: invalid distribution scenario {scenario!r}")
    if type(seed) is not int or type(analysis_seed) is not int or seed != analysis_seed:
        raise ValueError(f"{manifest_path}: manifest and analysis_config seeds must agree")
    if config.get("cc") != "prism":
        raise ValueError(f"{manifest_path}: config cc must be 'prism'")
    if config.get("load_balancing_algo") != "reps_actual":
        raise ValueError(f"{manifest_path}: config load_balancing_algo must be 'reps_actual'")
    expected_links = DEGRADED_LINKS[scenario]
    for section_name, section in (("config", config), ("analysis_config", analysis)):
        if section.get("degraded_links") != expected_links:
            raise ValueError(
                f"{manifest_path}: {scenario} requires {expected_links} degraded links in {section_name}"
            )
        capacity = section.get("degraded_capacity_gbps")
        if isinstance(capacity, bool) or not isinstance(capacity, (int, float)) or (
            float(capacity) != DEGRADED_CAPACITY_GBPS
        ):
            raise ValueError(
                f"{manifest_path}: {scenario} requires 25 Gbps degraded capacity in {section_name}"
            )
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


def _trace_error(path: Path, key: str, detail: str) -> TraceValidationError:
    return TraceValidationError(f"{path}: {key}: {detail}")


def _stream_rows(prefix: Path, kind: str, fields: tuple[str, ...], expected_run_id: str):
    """Yield validated rows, parsing only the fields this analysis consumes."""
    path = Path(f"{prefix}.{kind}.csv")
    schema = dict(_SCHEMAS[kind])
    expected_header = [name for name, _parser in _SCHEMAS[kind]]
    parse_fields = tuple(dict.fromkeys(("schema_version", "run_id", *fields)))
    try:
        stream = path.open("r", newline="", encoding="utf-8")
    except OSError as exc:
        raise _trace_error(path, "file", str(exc)) from exc

    with stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != expected_header:
            raise _trace_error(
                path,
                "header",
                f"expected {expected_header!r}, got {reader.fieldnames!r}",
            )
        previous_event_seq = None
        for line_number, raw_row in enumerate(reader, start=2):
            if set(raw_row) != set(expected_header) or any(
                raw_row[name] is None for name in expected_header
            ):
                raise _trace_error(path, "header", f"row {line_number} has missing or extra columns")
            row = {}
            for key in parse_fields:
                value = raw_row[key]
                try:
                    row[key] = schema[key](value)
                except (TypeError, ValueError, OverflowError) as exc:
                    raise _trace_error(
                        path,
                        key,
                        f"row {line_number} has invalid value {value!r}",
                    ) from exc
            if row["schema_version"] != SCHEMA_VERSION:
                raise _trace_error(
                    path,
                    "schema_version",
                    f"expected {SCHEMA_VERSION}, got {row['schema_version']}",
                )
            if row["run_id"] != expected_run_id:
                raise _trace_error(
                    path,
                    "run_id",
                    f"expected {expected_run_id!r}, got {row['run_id']!r}",
                )
            if "event_seq" in row:
                event_seq = row["event_seq"]
                if previous_event_seq is not None and event_seq <= previous_event_seq:
                    raise _trace_error(
                        path,
                        "event_seq",
                        f"row {line_number} value {event_seq} is not strictly increasing",
                    )
                previous_event_seq = event_seq
            yield row


def _load_attribution(prefix: Path, run_id: str) -> dict[tuple[int, int], tuple[bool, int]]:
    attribution = {}
    for row in _stream_rows(
        prefix,
        "pathmap",
        ("flow_id", "entropy", "physical_path_id", "resolution_status", "contains_reduced_link"),
        run_id,
    ):
        key = (row["flow_id"], row["entropy"])
        if row["resolution_status"] != "resolved":
            raise ValueError(f"{run_id}: unresolved pathmap attribution for {key}")
        if key in attribution:
            raise ValueError(f"{run_id}: duplicate pathmap mapping for {key}")
        attribution[key] = (row["contains_reduced_link"], row["physical_path_id"])
    return attribution


def _validate_coordination_row(path: Path, row: dict) -> None:
    if row["action"] not in _COORDINATION_ACTIONS:
        raise _trace_error(path, "action", f"unknown coordination action {row['action']!r}")
    if row["action"] == "invalidate" and row["refresh_complete"]:
        raise _trace_error(path, "refresh_complete", "invalidate action cannot mark refresh complete")
    if row["action"] in ("round_complete_clean", "round_complete_retry"):
        action = row["action"]
        if not row["refresh_complete"]:
            raise _trace_error(path, "refresh_complete", f"{action} requires completed refresh")
        if row["progress"]:
            raise _trace_error(path, "progress", f"{action} requires no progress")
        if row["handoff"]:
            raise _trace_error(path, "handoff", f"{action} requires no handoff")
    if row["handoff"] and row["action"] != "round_complete_handoff":
        raise _trace_error(path, "action", "handoff requires round_complete_handoff action")
    if row["action"] == "round_complete_handoff" and not row["handoff"]:
        if not row["refresh_complete"]:
            raise _trace_error(
                path,
                "refresh_complete",
                "no-op round_complete_handoff requires completed refresh",
            )
        if row["progress"]:
            raise _trace_error(
                path,
                "progress",
                "no-op round_complete_handoff requires no progress",
            )
    if row["action"] == "round_complete_progress" and not row["progress"]:
        raise _trace_error(path, "progress", "round_complete_progress action requires progress")
    if row["progress"] and row["action"] != "round_complete_progress":
        raise _trace_error(path, "action", "progress requires round_complete_progress action")


def _load_coordination(prefix: Path, run_id: str, mode: str) -> list[dict]:
    path = Path(f"{prefix}.coordination.csv")

    def records():
        for row in _stream_rows(
            prefix,
            "coordination",
            (
                "event_seq", "time_ps", "flow_id", "round_id", "cache_slot",
                "cache_generation", "action", "refresh_complete", "progress", "handoff",
            ),
            run_id,
        ):
            _validate_coordination_row(path, row)
            if (
                row["action"] == "invalidate"
                or row["action"] == "retain"
                or row["action"].startswith("round_complete_")
            ):
                yield row

    return _chain_specs(records(), mode)


def _chain_specs(records, mode: str) -> list[dict]:
    if mode != "prism_recycle":
        for _row in records:
            pass
        return []
    specs = []
    evidence_by_round = {}
    for row in records:
        identity = (row["flow_id"], row["round_id"])
        evidence = evidence_by_round.setdefault(identity, {
            "invalidations": {},
            "retains": [],
        })
        if row["action"] == "invalidate":
            invalidation_identity = (
                row["flow_id"], row["round_id"], row["cache_slot"], row["cache_generation"],
            )
            evidence["invalidations"].setdefault(invalidation_identity, row)
            continue
        if row["action"] == "retain":
            evidence["retains"].append(row)
            continue
        if not (
            row["action"].startswith("round_complete_")
            and row["time_ps"] >= WARMUP_PS
            and row["refresh_complete"]
            and evidence["invalidations"]
        ):
            continue
        specs.append({"terminal": row, "evidence": evidence})
    return specs


def _stream_candidate_admissions(prefix: Path, run_id: str, specs: list[dict]):
    specs_by_slot = defaultdict(list)
    for spec in specs:
        terminal_seq = spec["terminal"]["event_seq"]
        slots = {
            invalidation["cache_slot"]
            for invalidation in spec["evidence"]["invalidations"].values()
            if invalidation["event_seq"] < terminal_seq
        }
        for cache_slot in slots:
            specs_by_slot[(spec["terminal"]["flow_id"], cache_slot)].append(spec)
    admissions_by_slot = defaultdict(list)
    admissions_by_ack = defaultdict(list)
    token_path = Path(f"{prefix}.token.csv")
    for row in _stream_rows(
        prefix,
        "token",
        (
            "event_seq", "flow_id", "operation", "related_ack_event_seq", "cache_slot",
            "cache_generation", "admission_written", "entropy",
        ),
        run_id,
    ):
        if not row["admission_written"]:
            continue
        admission = _AdmissionFact(
            row["operation"],
            row["event_seq"],
            row["flow_id"],
            row["entropy"],
            row["cache_slot"],
            row["cache_generation"],
            row["related_ack_event_seq"],
        )
        if admission.operation not in _ADMISSION_OPERATIONS:
            raise _trace_error(
                token_path,
                "operation",
                f"value {admission.operation!r} cannot write an admission",
            )
        if admission.cache_slot == _NO_CACHE_SLOT:
            raise _trace_error(token_path, "cache_slot", "sentinel slot cannot write an admission")
        if admission.cache_generation == 0:
            raise _trace_error(
                token_path,
                "cache_generation",
                "written admission requires a positive generation",
            )
        admissions_by_ack[admission.related_ack_event_seq].append(admission)
        for spec in specs_by_slot.get((row["flow_id"], row["cache_slot"]), ()):
            terminal_seq = spec["terminal"]["event_seq"]
            if any(
                invalidation["event_seq"] < admission.event_seq < terminal_seq
                and admission.cache_generation > invalidation["cache_generation"]
                for invalidation in spec["evidence"]["invalidations"].values()
                if invalidation["event_seq"] < terminal_seq
                and invalidation["cache_slot"] == admission.cache_slot
            ):
                admissions_by_slot[(admission.flow_id, admission.cache_slot)].append(admission)
                break
    return admissions_by_slot, admissions_by_ack


def _ratio(healthy_bytes: int, throttled_bytes: int) -> float | str:
    total = healthy_bytes + throttled_bytes
    return throttled_bytes / total if total else ""


def _stream_ack_aggregates(prefix: Path, run_id: str, attribution, admissions_by_ack,
                           expected_seed: int, expected_scenario: str):
    selected_event_seqs = set(admissions_by_ack)
    selected_acks = {}
    base_rtt_ps = None
    last_ack_ps = None
    counts = defaultdict(lambda: [0, 0])
    for row in _stream_rows(
        prefix,
        "ack",
        (
            "event_seq", "time_ps", "flow_id", "entropy", "physical_path_id",
            "base_rtt_ps", "genuine_sample", "ecn", "newly_acked_bytes",
            "seed", "scenario",
        ),
        run_id,
    ):
        ack_path = Path(f"{prefix}.ack.csv")
        if row["seed"] != expected_seed:
            raise _trace_error(
                ack_path, "seed", f"expected {expected_seed}, got {row['seed']}"
            )
        if row["scenario"] != expected_scenario:
            raise _trace_error(
                ack_path, "scenario", f"expected {expected_scenario!r}, got {row['scenario']!r}"
            )
        if base_rtt_ps is None:
            base_rtt_ps = row["base_rtt_ps"]
        elif row["base_rtt_ps"] != base_rtt_ps:
            raise ValueError(f"{run_id}: require one identical ACK base RTT per run")
        key = (row["flow_id"], row["entropy"])
        if key not in attribution:
            raise ValueError(f"{run_id}: ACK lacks pathmap attribution for {key}")
        contains_reduced_link, physical_path_id = attribution[key]
        if row["physical_path_id"] != physical_path_id:
            raise ValueError(
                f"{run_id}: ACK physical path ID mismatch for {key}: "
                f"ACK has {row['physical_path_id']}, pathmap has {physical_path_id}"
            )
        if row["event_seq"] in selected_event_seqs:
            selected_acks[row["event_seq"]] = row
        if row["time_ps"] < WARMUP_PS:
            continue
        last_ack_ps = row["time_ps"] if last_ack_ps is None else max(last_ack_ps, row["time_ps"])
        bin_width_ps = 4 * base_rtt_ps
        index = (row["time_ps"] - WARMUP_PS) // bin_width_ps
        counts[index][int(contains_reduced_link)] += row["newly_acked_bytes"]
    if base_rtt_ps is None or base_rtt_ps <= 0:
        raise ValueError(f"{run_id}: ACK base RTT must be positive")
    if last_ack_ps is None:
        raise ValueError(f"{run_id}: no post-warm-up ACKs")
    return base_rtt_ps, last_ack_ps, counts, selected_acks


def _validate_admission_provenance(prefix: Path, admissions_by_ack, selected_acks: dict) -> None:
    token_path = Path(f"{prefix}.token.csv")
    ack_path = Path(f"{prefix}.ack.csv")
    for ack_event_seq, admissions in admissions_by_ack.items():
        if len(admissions) != 1:
            raise _trace_error(
                token_path,
                "related_ack_event_seq",
                f"ACK event {ack_event_seq} has duplicate written admissions",
            )
        ack = selected_acks.get(ack_event_seq)
        if ack is None:
            raise _trace_error(
                token_path,
                "related_ack_event_seq",
                f"ACK event {ack_event_seq} does not exist",
            )
        for admission in admissions:
            if admission.event_seq <= ack["event_seq"]:
                raise _trace_error(
                    token_path,
                    "event_seq",
                    f"value {admission.event_seq} must be after ACK event {ack_event_seq}",
                )
            if admission.flow_id != ack["flow_id"]:
                raise _trace_error(
                    token_path,
                    "flow_id",
                    f"value {admission.flow_id} differs from ACK flow {ack['flow_id']}",
                )
            if admission.entropy != ack["entropy"]:
                raise _trace_error(
                    token_path,
                    "entropy",
                    f"value {admission.entropy} differs from ACK entropy {ack['entropy']}",
                )
            if ack["ecn"]:
                raise _trace_error(
                    ack_path,
                    "ecn",
                    f"ACK event {ack_event_seq} must not be ECN-marked",
                )


def _replacement_chain_complete(spec: dict, admissions_by_slot, selected_acks: dict) -> bool:
    terminal = spec["terminal"]
    terminal_seq = terminal["event_seq"]
    for invalidation in spec["evidence"]["invalidations"].values():
        if invalidation["event_seq"] >= terminal_seq:
            continue
        for admission in admissions_by_slot[(terminal["flow_id"], invalidation["cache_slot"])]:
            if not (
                invalidation["event_seq"] < admission.event_seq < terminal_seq
                and admission.flow_id == terminal["flow_id"]
                and admission.cache_slot == invalidation["cache_slot"]
                and admission.cache_generation > invalidation["cache_generation"]
            ):
                continue
            ack = selected_acks.get(admission.related_ack_event_seq)
            if not (
                ack
                and invalidation["event_seq"] < ack["event_seq"] < admission.event_seq
                and ack["flow_id"] == terminal["flow_id"]
                and ack["genuine_sample"]
                and not ack["ecn"]
            ):
                continue
            if any(
                admission.event_seq < retain["event_seq"] < terminal_seq
                and retain["cache_slot"] == admission.cache_slot
                and retain["cache_generation"] == admission.cache_generation
                for retain in spec["evidence"]["retains"]
            ):
                break
        else:
            return False
    return True


def _distribution_bins(*, run_id: str, scenario: str, mode: str, seed: int,
                       base_rtt_ps: int, last_ack_ps: int, counts) -> list[dict]:
    bin_width_ps = 4 * base_rtt_ps
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


def _stream_effect_windows(prefix: Path, run_id: str, attribution, specs: list[dict],
                           base_rtt_ps: int) -> None:
    if not specs:
        return
    bin_width_ps = 4 * base_rtt_ps
    ordered_specs = sorted(specs, key=lambda spec: spec["terminal"]["time_ps"])
    terminal_times = [spec["terminal"]["time_ps"] for spec in ordered_specs]
    for spec in ordered_specs:
        spec["window_counts"] = [0, 0, 0, 0]
    for row in _stream_rows(
        prefix,
        "ack",
        ("time_ps", "flow_id", "entropy", "physical_path_id", "newly_acked_bytes"),
        run_id,
    ):
        if row["time_ps"] < WARMUP_PS:
            continue
        key = (row["flow_id"], row["entropy"])
        if key not in attribution:
            raise ValueError(f"{run_id}: ACK lacks pathmap attribution for {key}")
        contains_reduced_link, physical_path_id = attribution[key]
        if row["physical_path_id"] != physical_path_id:
            raise ValueError(
                f"{run_id}: ACK physical path ID mismatch for {key}: "
                f"ACK has {row['physical_path_id']}, pathmap has {physical_path_id}"
            )
        time_ps = row["time_ps"]
        byte_count = row["newly_acked_bytes"]
        value_index = int(contains_reduced_link)
        for index in range(
            bisect.bisect_right(terminal_times, time_ps),
            bisect.bisect_right(terminal_times, time_ps + bin_width_ps),
        ):
            ordered_specs[index]["window_counts"][value_index] += byte_count
        for index in range(
            bisect.bisect_right(terminal_times, time_ps - bin_width_ps),
            bisect.bisect_right(terminal_times, time_ps),
        ):
            ordered_specs[index]["window_counts"][2 + value_index] += byte_count


def _refresh_effects(*, specs: list[dict], run_id: str, scenario: str, mode: str, seed: int,
                     base_rtt_ps: int, last_ack_ps: int) -> list[dict]:
    bin_width_ps = 4 * base_rtt_ps
    rows = []
    for spec in specs:
        terminal = spec["terminal"]
        terminal_time_ps = terminal["time_ps"]
        pre_start_ps = terminal_time_ps - bin_width_ps
        pre_end_ps = terminal_time_ps
        post_start_ps = terminal_time_ps
        post_end_ps = terminal_time_ps + bin_width_ps
        pre_complete = pre_start_ps >= WARMUP_PS and pre_end_ps <= last_ack_ps
        post_complete = post_start_ps >= WARMUP_PS and post_end_ps <= last_ack_ps
        pre_healthy, pre_throttled, post_healthy, post_throttled = spec["window_counts"]
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
    run_id, scenario, seed, mode = _load_manifest(manifest_path)
    prefix = _trace_prefix(manifest_path)
    attribution = _load_attribution(prefix, run_id)
    specs = _load_coordination(prefix, run_id, mode)
    admissions_by_slot, admissions_by_ack = _stream_candidate_admissions(prefix, run_id, specs)
    base_rtt_ps, last_ack_ps, counts, selected_acks = _stream_ack_aggregates(
        prefix, run_id, attribution, admissions_by_ack, seed, EXPERIMENT
    )
    _validate_admission_provenance(prefix, admissions_by_ack, selected_acks)
    complete_specs = []
    for spec in specs:
        if not _replacement_chain_complete(spec, admissions_by_slot, selected_acks):
            terminal = spec["terminal"]
            raise ValueError(
                f"{run_id}: recycle terminal event {terminal['event_seq']} has incomplete replacement evidence"
            )
        complete_specs.append(spec)
    _stream_effect_windows(prefix, run_id, attribution, complete_specs, base_rtt_ps)
    bins = _distribution_bins(
        run_id=run_id,
        scenario=scenario,
        mode=mode,
        seed=seed,
        base_rtt_ps=base_rtt_ps,
        last_ack_ps=last_ack_ps,
        counts=counts,
    )
    effects = _refresh_effects(
        specs=complete_specs,
        run_id=run_id,
        scenario=scenario,
        mode=mode,
        seed=seed,
        base_rtt_ps=base_rtt_ps,
        last_ack_ps=last_ack_ps,
    )
    healthy_bytes = sum(row["healthy_acked_bytes"] for row in bins)
    throttled_bytes = sum(row["throttled_acked_bytes"] for row in bins)
    summary = {
        "run_id": run_id,
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
