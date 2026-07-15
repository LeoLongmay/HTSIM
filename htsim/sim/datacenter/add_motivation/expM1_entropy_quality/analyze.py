#!/usr/bin/env python3
"""Analyze M1 residual persistence and lock a calibration-selected formal cell."""

from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import math
import os
import re
import statistics
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Optional

try:
    from htsim.sim.datacenter.add_motivation.common.residual_join import (
        ResidualAck,
        attach_same_epoch_residuals,
    )
    from htsim.sim.datacenter.add_motivation.common.statistics import cluster_bootstrap
    from htsim.sim.datacenter.add_motivation.common.trace_schema import load_trace
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[5]))
    from htsim.sim.datacenter.add_motivation.common.residual_join import (
        ResidualAck,
        attach_same_epoch_residuals,
    )
    from htsim.sim.datacenter.add_motivation.common.statistics import cluster_bootstrap
    from htsim.sim.datacenter.add_motivation.common.trace_schema import load_trace


HERE = Path(__file__).resolve().parent
DATACENTER_DIR = HERE.parent.parent
DECODER = DATACENTER_DIR.parent / "build" / "parse_output"
FORMAL_CONFIG = HERE / "configs" / "formal.csv"

PRIMARY_THRESHOLD_PS = 14_000_000
FORMAL_SEEDS = (13, 14, 15, 16, 17)
CALIBRATION_SEEDS = (101, 102, 103)
MIN_COMPLETION_RATE = 0.99
MIN_COVERED_FLOW_FRACTION = 0.75
MIN_ENTROPY_COVERAGE = 6
MIN_PATH_COVERAGE = 2
MIN_FUTURE_HIGH = 0.10
MAX_UNMATCHED_RATE = 0.25
BOOTSTRAP_SAMPLES = 10_000
BOOTSTRAP_SEED = 20260714
BOOTSTRAP_CONFIDENCE_LEVEL = 0.95
BOOTSTRAP_LOWER_PERCENTILE = 0.025
BOOTSTRAP_UPPER_PERCENTILE = 0.975
RISK_RATIO_CI_LOWER_BOUND = 1.0
MIN_FUTURE_HIGH_CONTRIBUTING_FLOW_CLUSTERS = 2
MAX_HIGH_RETRANSMITTED_COUNT = 0
UINT64_MAX = 2**64 - 1


@dataclasses.dataclass(frozen=True)
class AuxiliaryMetrics:
    valid: bool
    completion_rate: Optional[float]
    goodput_gbps: Optional[float]
    p99_fct_us: Optional[float]
    total_started: int
    completed: int
    invalid_reason: str


@dataclasses.dataclass(frozen=True)
class RunSummary:
    run_id: str
    threshold_ps: int
    unmarked_count: int
    unmarked_high_count: int
    unmarked_high_ratio: Optional[float]
    matched_next_use: int
    unmatched_next_use: int
    unmatched_next_use_rate: Optional[float]
    next_high_given_current_high: Optional[float]
    next_high_given_current_low: Optional[float]
    risk_ratio: Optional[float]
    mean_interval_ps: Optional[float]
    mean_interval_epochs: Optional[float]
    entropy_direction: bool
    path_direction: bool
    covered_flow_count: int
    traced_flow_count: int
    covered_flow_fraction: Optional[float]
    coverage_adequate: bool
    legacy_token_count: int
    shadow_exposure_denominator: int
    shadow_rejection_count: int
    shadow_rejection_exposure: Optional[float]
    rejected_token_selected_count: int
    rejected_token_future_high_count: int
    rejected_token_future_high_rate: Optional[float]
    high_retransmitted_count: int
    aux_valid: bool
    aux_invalid_reason: str
    completion_rate: Optional[float]
    goodput_gbps: Optional[float]
    p99_fct_us: Optional[float]
    loss_freezing_clear: bool


@dataclasses.dataclass(frozen=True)
class BundleAnalysis:
    summary: RunSummary
    residual_rows: tuple[dict, ...]
    next_use_rows: tuple[dict, ...]
    token_rows: tuple[dict, ...]
    coverage_rows: tuple[dict, ...]
    group_rows: tuple[dict, ...]


@dataclasses.dataclass(frozen=True)
class SelectionResult:
    selected: bool
    scenario_id: str
    control_scenario_id: str
    reason: str


def _ratio(numerator: float, denominator: float) -> Optional[float]:
    return numerator / denominator if denominator else None


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _mean(values: Iterable[float]) -> Optional[float]:
    finite = [float(value) for value in values if _finite(value)]
    return statistics.fmean(finite) if finite else None


def _flow_condition_rows(next_rows: Iterable[dict]) -> list[dict]:
    counts = defaultdict(lambda: {"high_n": 0, "high_y": 0, "low_n": 0, "low_y": 0})
    for row in next_rows:
        if not row["matched"]:
            continue
        identity = row.get("cluster_id", row["flow_id"])
        state = "high" if row["current_high"] else "low"
        counts[identity][f"{state}_n"] += 1
        counts[identity][f"{state}_y"] += int(row["next_high"])
    result = []
    for identity in sorted(counts, key=str):
        values = counts[identity]
        result.append({
            "cluster_id": identity,
            "flow_id": identity,
            "high_probability": _ratio(values["high_y"], values["high_n"]),
            "low_probability": _ratio(values["low_y"], values["low_n"]),
            **values,
        })
    return result


def _condition_probability(flow_rows: Iterable[dict], state: str) -> Optional[float]:
    return _mean(row[f"{state}_probability"] for row in flow_rows)


def _risk_ratio_from_flow_rows(flow_rows: Iterable[dict]) -> Optional[float]:
    rows = list(flow_rows)
    high = _condition_probability(rows, "high")
    low = _condition_probability(rows, "low")
    if high is None or low is None or low <= 0:
        return None
    return high / low


def _make_next_use_rows(attached: tuple[ResidualAck, ...]) -> list[dict]:
    per_key = defaultdict(list)
    for item in sorted(attached, key=lambda value: (value.row["flow_id"], value.row["event_seq"])):
        per_key[(item.row["flow_id"], item.row["entropy"])].append(item)

    next_by_event = {}
    for values in per_key.values():
        for current, following in zip(values, values[1:]):
            next_by_event[current.row["event_seq"]] = following

    rows = []
    for current in sorted(attached, key=lambda value: (value.row["flow_id"], value.row["event_seq"])):
        row = current.row
        if row["ecn"]:
            continue
        following = next_by_event.get(row["event_seq"])
        output = {
            "flow_id": row["flow_id"],
            "entropy": row["entropy"],
            "physical_path_id": row["physical_path_id"],
            "current_event_seq": row["event_seq"],
            "current_epoch_id": row["epoch_id"],
            "current_residual_ps": current.residual_ps,
            "current_high": current.high_residual,
            "matched": following is not None,
            "next_event_seq": "",
            "next_epoch_id": "",
            "next_residual_ps": "",
            "next_high": "",
            "interval_ps": "",
            "interval_epochs": "",
            "unmatched_reason": "no_later_genuine_same_flow_entropy" if following is None else "",
        }
        if following is not None:
            output.update({
                "next_event_seq": following.row["event_seq"],
                "next_epoch_id": following.row["epoch_id"],
                "next_residual_ps": following.residual_ps,
                "next_high": following.high_residual,
                "interval_ps": following.row["time_ps"] - row["time_ps"],
                "interval_epochs": following.row["epoch_id"] - row["epoch_id"],
            })
        rows.append(output)
    return rows


def _group_direction_rows(next_rows: Iterable[dict]) -> list[dict]:
    matched = [row for row in next_rows if row["matched"]]
    output = []
    for grouping, key_name in (("entropy", "entropy"), ("physical_path", "physical_path_id")):
        grouped = defaultdict(list)
        for row in matched:
            key = row[key_name]
            if grouping == "physical_path" and key == UINT64_MAX:
                continue
            grouped[key].append(row)
        for key in sorted(grouped):
            values = grouped[key]
            high = [row for row in values if row["current_high"]]
            low = [row for row in values if not row["current_high"]]
            high_rate = _ratio(sum(bool(row["next_high"]) for row in high), len(high))
            low_rate = _ratio(sum(bool(row["next_high"]) for row in low), len(low))
            output.append({
                "grouping": grouping,
                "group_id": key,
                "current_high_count": len(high),
                "current_low_count": len(low),
                "next_high_given_current_high": high_rate,
                "next_high_given_current_low": low_rate,
                "comparable": high_rate is not None and low_rate is not None,
                "positive_direction": (
                    high_rate is not None and low_rate is not None and high_rate > low_rate
                ),
            })
    return output


def _overall_group_direction(group_rows: Iterable[dict], grouping: str) -> bool:
    comparable = [
        row for row in group_rows
        if row["grouping"] == grouping and row["comparable"]
    ]
    if not comparable:
        return False
    high = _mean(row["next_high_given_current_high"] for row in comparable)
    low = _mean(row["next_high_given_current_low"] for row in comparable)
    return high is not None and low is not None and high > low


def _coverage_rows(bundle, attached: tuple[ResidualAck, ...]) -> list[dict]:
    observations = defaultdict(lambda: {"entropies": set(), "paths": set()})
    resolved = {
        (row["flow_id"], row["entropy"], row["physical_path_id"])
        for row in bundle.pathmap
        if row["resolution_status"] == "resolved"
    }
    for item in attached:
        row = item.row
        observations[row["flow_id"]]["entropies"].add(row["entropy"])
        path_identity = (row["flow_id"], row["entropy"], row["physical_path_id"])
        if row["physical_path_id"] != UINT64_MAX and (not bundle.pathmap or path_identity in resolved):
            observations[row["flow_id"]]["paths"].add(row["physical_path_id"])

    epoch_max = defaultdict(lambda: {"entropy": 0, "path": 0})
    for row in bundle.epoch:
        epoch_max[row["flow_id"]]["entropy"] = max(
            epoch_max[row["flow_id"]]["entropy"], row["entropy_coverage"]
        )
        epoch_max[row["flow_id"]]["path"] = max(
            epoch_max[row["flow_id"]]["path"], row["physical_path_coverage"]
        )

    rows = []
    for flow_id in sorted(observations):
        entropy_count = len(observations[flow_id]["entropies"])
        path_count = len(observations[flow_id]["paths"])
        rows.append({
            "flow_id": flow_id,
            "entropy_coverage": entropy_count,
            "physical_path_coverage": path_count,
            "max_epoch_entropy_coverage": epoch_max[flow_id]["entropy"],
            "max_epoch_path_coverage": epoch_max[flow_id]["path"],
            "adequate": entropy_count >= MIN_ENTROPY_COVERAGE and path_count >= MIN_PATH_COVERAGE,
        })
    return rows


def _token_rows(bundle, attached: tuple[ResidualAck, ...]) -> list[dict]:
    residual_by_event = {item.row["event_seq"]: item for item in attached}
    all_ack_by_event = {row["event_seq"]: row for row in bundle.ack}
    dequeues = defaultdict(list)
    for token in bundle.token:
        if token["operation"] == "dequeue_recycle":
            dequeues[(token["flow_id"], token["token_id"])].append(token)
    selected = defaultdict(list)
    for ack_row in bundle.ack:
        token_id = ack_row.get("source_token_id", 0)
        if token_id:
            selected[(ack_row["flow_id"], token_id)].append(ack_row)

    output = []
    for token in bundle.token:
        if token["operation"] != "enqueue_good_ack":
            continue
        identity = (token["flow_id"], token["token_id"])
        admission = residual_by_event.get(token["related_ack_event_seq"])
        exposure_eligible = admission is not None and not admission.row["ecn"]
        rejected = exposure_eligible and admission.high_residual
        reason = ""
        dequeue = None
        selected_ack = None
        selected_residual = None
        if admission is None:
            reason = "admission_ack_not_genuine"
        elif not rejected:
            reason = "not_shadow_rejected"
        else:
            dequeue = next(
                (row for row in dequeues[identity] if row["event_seq"] > token["event_seq"]),
                None,
            )
            if dequeue is None:
                reason = "not_dequeued_recycle"
            else:
                selected_ack = next(
                    (row for row in selected[identity] if row["event_seq"] > dequeue["event_seq"]),
                    None,
                )
                if selected_ack is None:
                    reason = "no_selected_ack_for_token_id"
                else:
                    selected_residual = residual_by_event.get(selected_ack["event_seq"])
                    if selected_residual is None:
                        reason = "selected_ack_not_genuine"

        output.append({
            "flow_id": token["flow_id"],
            "token_id": token["token_id"],
            "entropy": token["entropy"],
            "enqueue_event_seq": token["event_seq"],
            "admission_ack_event_seq": token["related_ack_event_seq"],
            "admission_ack_present": token["related_ack_event_seq"] in all_ack_by_event,
            "exposure_eligible": exposure_eligible,
            "admission_high": admission.high_residual if admission is not None else "",
            "shadow_rejected": rejected,
            "dequeue_event_seq": dequeue["event_seq"] if dequeue is not None else "",
            "selected_ack_event_seq": selected_ack["event_seq"] if selected_ack is not None else "",
            "selected_ack_matched": selected_residual is not None,
            "selected_ack_future_high": (
                selected_residual.high_residual if selected_residual is not None else ""
            ),
            "unmatched_reason": reason,
        })
    return output


def analyze_bundle(
    bundle,
    threshold_ps: int = PRIMARY_THRESHOLD_PS,
    auxiliary: Optional[AuxiliaryMetrics] = None,
) -> BundleAnalysis:
    """Compute auditable M1 rows and a compact per-run summary."""

    if threshold_ps < 0:
        raise ValueError("threshold_ps must be nonnegative")
    if auxiliary is None:
        auxiliary = AuxiliaryMetrics(False, None, None, None, 0, 0, "auxiliary_not_requested")

    attached = tuple(attach_same_epoch_residuals(bundle, threshold_ps=threshold_ps))
    unmarked = [item for item in attached if not item.row["ecn"]]
    residual_rows = tuple({
        "flow_id": item.row["flow_id"],
        "event_seq": item.row["event_seq"],
        "entropy": item.row["entropy"],
        "physical_path_id": item.row["physical_path_id"],
        "epoch_id": item.row["epoch_id"],
        "residual_ps": item.residual_ps,
        "high_residual": item.high_residual,
        "ecn": item.row["ecn"],
    } for item in unmarked)
    next_rows = _make_next_use_rows(attached)
    flow_rows = _flow_condition_rows(next_rows)
    high_probability = _condition_probability(flow_rows, "high")
    low_probability = _condition_probability(flow_rows, "low")
    risk_ratio = _risk_ratio_from_flow_rows(flow_rows)
    group_rows = _group_direction_rows(next_rows)
    coverage_rows = _coverage_rows(bundle, attached)
    token_rows = _token_rows(bundle, attached)

    matched = [row for row in next_rows if row["matched"]]
    rejected = [row for row in token_rows if row["shadow_rejected"]]
    rejected_selected = [row for row in rejected if row["selected_ack_matched"]]
    exposure = [row for row in token_rows if row["exposure_eligible"]]
    covered = sum(row["adequate"] for row in coverage_rows)
    covered_fraction = _ratio(covered, len(coverage_rows))
    unmarked_high = sum(item.high_residual for item in unmarked)
    high_retransmitted = sum(
        item.high_residual and bool(item.row.get("retransmitted", False)) for item in unmarked
    )
    loss_freezing_clear = bool(
        auxiliary.valid
        and auxiliary.completion_rate is not None
        and auxiliary.completion_rate >= MIN_COMPLETION_RATE
        and high_retransmitted <= MAX_HIGH_RETRANSMITTED_COUNT
    )

    summary = RunSummary(
        run_id=bundle.run_id,
        threshold_ps=threshold_ps,
        unmarked_count=len(unmarked),
        unmarked_high_count=unmarked_high,
        unmarked_high_ratio=_ratio(unmarked_high, len(unmarked)),
        matched_next_use=len(matched),
        unmatched_next_use=len(next_rows) - len(matched),
        unmatched_next_use_rate=_ratio(len(next_rows) - len(matched), len(next_rows)),
        next_high_given_current_high=high_probability,
        next_high_given_current_low=low_probability,
        risk_ratio=risk_ratio,
        mean_interval_ps=_mean(row["interval_ps"] for row in matched),
        mean_interval_epochs=_mean(row["interval_epochs"] for row in matched),
        entropy_direction=_overall_group_direction(group_rows, "entropy"),
        path_direction=_overall_group_direction(group_rows, "physical_path"),
        covered_flow_count=covered,
        traced_flow_count=len(coverage_rows),
        covered_flow_fraction=covered_fraction,
        coverage_adequate=covered_fraction is not None and covered_fraction >= MIN_COVERED_FLOW_FRACTION,
        legacy_token_count=len(token_rows),
        shadow_exposure_denominator=len(exposure),
        shadow_rejection_count=len(rejected),
        shadow_rejection_exposure=_ratio(len(rejected), len(exposure)),
        rejected_token_selected_count=len(rejected_selected),
        rejected_token_future_high_count=sum(
            bool(row["selected_ack_future_high"]) for row in rejected_selected
        ),
        rejected_token_future_high_rate=_ratio(
            sum(bool(row["selected_ack_future_high"]) for row in rejected_selected),
            len(rejected_selected),
        ),
        high_retransmitted_count=high_retransmitted,
        aux_valid=auxiliary.valid,
        aux_invalid_reason=auxiliary.invalid_reason,
        completion_rate=auxiliary.completion_rate,
        goodput_gbps=auxiliary.goodput_gbps,
        p99_fct_us=auxiliary.p99_fct_us,
        loss_freezing_clear=loss_freezing_clear,
    )
    return BundleAnalysis(
        summary=summary,
        residual_rows=residual_rows,
        next_use_rows=tuple(next_rows),
        token_rows=tuple(token_rows),
        coverage_rows=tuple(coverage_rows),
        group_rows=tuple(group_rows),
    )


def summarize_run(bundle, threshold_ps: int = PRIMARY_THRESHOLD_PS) -> RunSummary:
    """Return the per-run M1 summary used by tests and calibration."""

    return analyze_bundle(bundle, threshold_ps=threshold_ps).summary


def _invalid_auxiliary(reason: str) -> AuxiliaryMetrics:
    return AuxiliaryMetrics(False, None, None, None, 0, 0, reason)


def parse_flow_output(path: Path | str, *, already_ascii: bool = False) -> AuxiliaryMetrics:
    """Decode and parse simulator FLOW_EVENT records without temporary output files."""

    source = Path(path)
    if not source.is_file():
        return _invalid_auxiliary(f"simulator output is missing: {source}")
    if already_ascii:
        try:
            text = source.read_text(encoding="ascii")
        except (OSError, UnicodeError) as exc:
            return _invalid_auxiliary(f"cannot read ASCII simulator output: {exc}")
    else:
        if not DECODER.is_file() or not os.access(DECODER, os.X_OK):
            return _invalid_auxiliary(f"parse_output decoder is unavailable: {DECODER}")
        try:
            decoded = subprocess.run(
                [str(DECODER), str(source), "-ascii"],
                check=True,
                capture_output=True,
                text=True,
                encoding="ascii",
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
            return _invalid_auxiliary(f"simulator output decode failed: {exc}")
        text = decoded.stdout

    starts = {}
    finishes = {}
    try:
        for line_number, line in enumerate(text.splitlines(), start=1):
            fields = line.split()
            if "FLOW_EVENT" not in fields:
                continue
            event = fields[fields.index("Ev") + 1]
            key = (
                int(fields[fields.index("SrcID") + 1]),
                int(fields[fields.index("FlowID") + 1]),
            )
            timestamp = float(fields[0])
            if not math.isfinite(timestamp):
                raise ValueError("non-finite timestamp")
            if event == "START":
                if key in starts:
                    raise ValueError(f"duplicate START for flow {key}")
                starts[key] = timestamp
            elif event == "FINISH":
                if key in finishes:
                    raise ValueError(f"duplicate FINISH for flow {key}")
                finishes[key] = (timestamp, int(fields[fields.index("Bytes") + 1]))
    except (ValueError, IndexError) as exc:
        return _invalid_auxiliary(f"malformed FLOW_EVENT at line {line_number}: {exc}")

    if not starts:
        return _invalid_auxiliary("no FLOW_EVENT START records")
    unknown_finishes = sorted(set(finishes) - set(starts))
    if unknown_finishes:
        return _invalid_auxiliary(f"FLOW_EVENT FINISH without START: {unknown_finishes[0]}")
    completed_keys = sorted(set(starts) & set(finishes))
    if not completed_keys:
        return _invalid_auxiliary("no completed FLOW_EVENT records")
    fcts = sorted(finishes[key][0] - starts[key] for key in completed_keys)
    if any(not math.isfinite(value) or value < 0 for value in fcts):
        return _invalid_auxiliary("FLOW_EVENT has invalid finish-before-start timing")
    first_start = min(starts[key] for key in completed_keys)
    last_finish = max(finishes[key][0] for key in completed_keys)
    span = last_finish - first_start
    if span <= 0:
        return _invalid_auxiliary("completed FLOW_EVENT makespan is not positive")
    total_bytes = sum(finishes[key][1] for key in completed_keys)
    p99 = fcts[int(round(0.99 * (len(fcts) - 1)))]
    return AuxiliaryMetrics(
        valid=True,
        completion_rate=len(completed_keys) / len(starts),
        goodput_gbps=total_bytes * 8.0 / span / 1e9,
        p99_fct_us=p99 * 1e6,
        total_started=len(starts),
        completed=len(completed_keys),
        invalid_reason="",
    )


def _as_float(row: dict, key: str) -> Optional[float]:
    value = row.get(key)
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _as_int(row: dict, key: str) -> Optional[int]:
    value = _as_float(row, key)
    return int(value) if value is not None and value.is_integer() else None


def _truth(row: dict, key: str) -> bool:
    return row.get(key) in (True, 1, 1.0, "1", "true", "True")


def _atomic_csv(path: Path, fieldnames: list[str], rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", newline="", encoding="ascii", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _base_scenario_id(value: str, seed: int) -> str:
    suffix = f"_s{seed}"
    return value[:-len(suffix)] if value.endswith(suffix) else value


def _candidate_failures(gray_rows: list[dict], controls: dict[tuple[float, int], dict]) -> list[str]:
    failures = []
    by_seed = {_as_int(row, "seed"): row for row in gray_rows}
    if set(by_seed) != set(CALIBRATION_SEEDS):
        failures.append("missing_calibration_seed")
    for seed in CALIBRATION_SEEDS:
        gray = by_seed.get(seed)
        if gray is None:
            continue
        load = _as_float(gray, "offered_load")
        control = controls.get((load, seed)) if load is not None else None
        prefix = f"seed_{seed}:"
        if control is None:
            failures.append(prefix + "missing_load_matched_control")
            continue
        completion = _as_float(gray, "completion_rate")
        if not _truth(gray, "aux_valid") or completion is None or completion < MIN_COMPLETION_RATE:
            failures.append(prefix + "completion_below_0.99_or_invalid")
        if (_as_int(gray, "unmarked_count") or 0) <= 0:
            failures.append(prefix + "zero_unmarked_denominator")
        if not _truth(gray, "coverage_adequate"):
            failures.append(prefix + "coverage_below_75pct_6_entropy_2_path")
        gray_phi = _as_float(gray, "unmarked_high_ratio")
        control_phi = _as_float(control, "unmarked_high_ratio")
        if gray_phi is None or control_phi is None or gray_phi <= control_phi:
            failures.append(prefix + "gray_phi_not_above_control")
        risk = _as_float(gray, "risk_ratio")
        if risk is None or risk <= 1:
            failures.append(prefix + "risk_ratio_not_above_1")
        if not _truth(gray, "loss_freezing_clear"):
            failures.append(prefix + "loss_or_freezing_signature")
    return failures


def select_formal(
    summary_rows: Iterable[dict],
    formal_path: Path | str = FORMAL_CONFIG,
    result_path: Path | str = HERE / "data" / "calibration" / "calibration_selection.csv",
) -> SelectionResult:
    """Select a calibration cell without weakening criteria or touching formal on failure."""

    rows = list(summary_rows)
    controls = {}
    candidates = defaultdict(list)
    for row in rows:
        seed = _as_int(row, "seed")
        load = _as_float(row, "offered_load")
        if seed is None or load is None:
            continue
        if row.get("arm") == "symmetric" or (_as_int(row, "degraded_links") == 0):
            controls[(load, seed)] = row
        else:
            key = (
                _base_scenario_id(str(row.get("scenario_id", "")), seed),
                _as_int(row, "degraded_links"),
                _as_float(row, "degraded_capacity_gbps"),
                load,
            )
            candidates[key].append(row)

    evaluations = []
    for key in sorted(candidates, key=str):
        scenario_id, degraded_links, capacity, load = key
        gray_rows = candidates[key]
        failures = _candidate_failures(gray_rows, controls)
        increases = []
        for gray in gray_rows:
            seed = _as_int(gray, "seed")
            control = controls.get((load, seed))
            gray_phi = _as_float(gray, "unmarked_high_ratio")
            control_phi = _as_float(control, "unmarked_high_ratio") if control else None
            if gray_phi is not None and control_phi is not None:
                increases.append(gray_phi - control_phi)
        control_ids = {
            _base_scenario_id(str(row.get("scenario_id", "")), _as_int(row, "seed"))
            for (control_load, _seed), row in controls.items() if control_load == load
        }
        evaluations.append({
            "scenario_id": scenario_id,
            "control_scenario_id": min(control_ids) if control_ids else "",
            "degraded_links": degraded_links,
            "degraded_capacity_gbps": capacity,
            "offered_load": load,
            "eligible": not failures,
            "minimum_phi_increase": min(increases) if len(increases) == len(CALIBRATION_SEEDS) else "",
            "failed_predicates": ";".join(failures),
        })

    eligible = [row for row in evaluations if row["eligible"]]
    result_file = Path(result_path)
    fields = [
        "selection_status", "scenario_id", "control_scenario_id", "degraded_links",
        "degraded_capacity_gbps", "offered_load", "eligible",
        "minimum_phi_increase", "failed_predicates",
    ]
    if not eligible:
        if not evaluations:
            evaluations = [{
                "scenario_id": "", "control_scenario_id": "", "degraded_links": "",
                "degraded_capacity_gbps": "", "offered_load": "", "eligible": False,
                "minimum_phi_increase": "", "failed_predicates": "no_candidate_cells",
            }]
        result_rows = [{"selection_status": "no_qualifying_cell", **row} for row in evaluations]
        _atomic_csv(result_file, fields, result_rows)
        return SelectionResult(False, "", "", "no_qualifying_cell")

    selected = min(
        eligible,
        key=lambda row: (
            -float(row["minimum_phi_increase"]),
            int(row["degraded_links"]),
            -float(row["degraded_capacity_gbps"]),
            str(row["scenario_id"]),
        ),
    )
    result_rows = [
        {"selection_status": "selected" if row is selected else "eligible_not_selected", **row}
        for row in evaluations
    ]
    _atomic_csv(result_file, fields, result_rows)

    formal_rows = []
    for seed in FORMAL_SEEDS:
        formal_rows.append({
            "scenario_id": selected["control_scenario_id"], "degraded_links": 0,
            "degraded_capacity_gbps": 100, "offered_load": selected["offered_load"],
            "seed": seed,
        })
        formal_rows.append({
            "scenario_id": selected["scenario_id"],
            "degraded_links": selected["degraded_links"],
            "degraded_capacity_gbps": selected["degraded_capacity_gbps"],
            "offered_load": selected["offered_load"], "seed": seed,
        })
    _atomic_csv(
        Path(formal_path),
        ["scenario_id", "degraded_links", "degraded_capacity_gbps", "offered_load", "seed"],
        formal_rows,
    )
    return SelectionResult(
        True, str(selected["scenario_id"]), str(selected["control_scenario_id"]), ""
    )


def _scenario_from_run_id(run_id: str, phase: str, seed: int) -> str:
    prefix = f"{phase}_"
    if not run_id.startswith(prefix):
        raise ValueError(f"run_id {run_id!r} does not belong to phase {phase!r}")
    return _base_scenario_id(run_id[len(prefix):], seed)


def _offered_load(scenario_id: str) -> float:
    match = re.search(r"(?:^|_)l(\d{2})(?:_|$)", scenario_id)
    if match is None:
        raise ValueError(f"scenario_id {scenario_id!r} has no offered-load token")
    return int(match.group(1)) / 10.0


def _manifest_metadata(path: Path, phase: str) -> dict:
    try:
        manifest = json.loads(path.read_text(encoding="ascii"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid manifest {path}: {exc}") from exc
    required = ("schema_version", "run_id", "seed", "phase", "config")
    missing = [key for key in required if key not in manifest]
    if missing:
        raise ValueError(f"manifest {path} is missing keys: {missing}")
    if manifest["schema_version"] != 2 or manifest["phase"] != phase:
        raise ValueError(f"manifest {path} has wrong schema_version or phase")
    run_id = manifest["run_id"]
    seed = manifest["seed"]
    if not isinstance(run_id, str) or not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError(f"manifest {path} has invalid run_id or seed")
    if path.name != f"{run_id}.manifest.json":
        raise ValueError(f"manifest filename {path.name!r} does not match run_id {run_id!r}")
    scenario_id = _scenario_from_run_id(run_id, phase, seed)
    config = manifest["config"]
    if not isinstance(config, dict) or not {
        "degraded_links", "degraded_capacity_gbps"
    }.issubset(config):
        raise ValueError(f"manifest {path} has incomplete config")
    if (
        not isinstance(config["degraded_links"], int)
        or isinstance(config["degraded_links"], bool)
        or not _finite(config["degraded_capacity_gbps"])
    ):
        raise ValueError(f"manifest {path} has invalid degraded-capacity config")
    return {
        "run_id": run_id,
        "seed": seed,
        "scenario_id": scenario_id,
        "arm": "symmetric" if config["degraded_links"] == 0 else "gray",
        "offered_load": _offered_load(scenario_id),
        "degraded_links": config["degraded_links"],
        "degraded_capacity_gbps": config["degraded_capacity_gbps"],
    }


def _enrich(rows: Iterable[dict], metadata: dict) -> list[dict]:
    return [{**metadata, **row} for row in rows]


def _csv_value(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return int(value)
    return value


def _summary_dict(summary: RunSummary, metadata: dict) -> dict:
    values = dataclasses.asdict(summary)
    return {**metadata, **{key: _csv_value(value) for key, value in values.items()}}


def _write_table(path: Path, rows: list[dict], fallback_fields: list[str]) -> None:
    fields = list(rows[0]) if rows else fallback_fields
    _atomic_csv(path, fields, rows)


def _conditioning_table(next_rows: list[dict]) -> list[dict]:
    output = []
    for arm in ("symmetric", "gray"):
        arm_rows = [row for row in next_rows if row["arm"] == arm and row["matched"]]
        flow_rows = _flow_condition_rows([
            {**row, "cluster_id": (row["run_id"], row["flow_id"])} for row in arm_rows
        ])
        for state in ("low", "high"):
            usable = [
                {"cluster_id": row["cluster_id"], "probability": row[f"{state}_probability"]}
                for row in flow_rows if row[f"{state}_probability"] is not None
            ]
            probability = _mean(row["probability"] for row in usable)
            low_ci = high_ci = None
            if usable:
                low_ci, high_ci = cluster_bootstrap(
                    usable,
                    lambda row: row["cluster_id"],
                    lambda sample: statistics.fmean(row["probability"] for row in sample),
                    samples=BOOTSTRAP_SAMPLES,
                    seed=BOOTSTRAP_SEED,
                )
            output.append({
                "arm": arm, "current_state": state, "probability": _csv_value(probability),
                "ci_low": _csv_value(low_ci), "ci_high": _csv_value(high_ci),
                "flow_clusters": len(usable), "bootstrap_samples": BOOTSTRAP_SAMPLES,
                "bootstrap_seed": BOOTSTRAP_SEED,
            })
    return output


def _token_aggregate(token_rows: list[dict]) -> list[dict]:
    output = []
    for arm in ("symmetric", "gray"):
        rows = [row for row in token_rows if row["arm"] == arm]
        exposure = [row for row in rows if row["exposure_eligible"]]
        rejected = [row for row in rows if row["shadow_rejected"]]
        selected = [row for row in rejected if row["selected_ack_matched"]]
        output.append({
            "arm": arm,
            "legacy_token_count": len(rows),
            "exposure_denominator": len(exposure),
            "shadow_rejection_count": len(rejected),
            "shadow_rejection_exposure": _csv_value(_ratio(len(rejected), len(exposure))),
            "matched_selected_ack_denominator": len(selected),
            "rejected_token_future_high_count": sum(
                bool(row["selected_ack_future_high"]) for row in selected
            ),
            "rejected_token_future_high_rate": _csv_value(_ratio(
                sum(bool(row["selected_ack_future_high"]) for row in selected), len(selected)
            )),
            "unmatched_reasons": json.dumps(
                {reason: sum(row["unmatched_reason"] == reason for row in rejected)
                 for reason in sorted({row["unmatched_reason"] for row in rejected if row["unmatched_reason"]})},
                sort_keys=True,
            ),
        })
    return output


def _formal_result(
    summaries: list[dict], next_rows: list[dict], group_rows: list[dict],
) -> dict:
    gray = [row for row in summaries if row["arm"] == "gray"]
    symmetric = [row for row in summaries if row["arm"] == "symmetric"]
    controls_by_key = defaultdict(list)
    for row in symmetric:
        controls_by_key[(row["seed"], row["offered_load"])].append(row)
    paired_controls = [
        controls_by_key[(row["seed"], row["offered_load"])][0]
        for row in gray
        if len(controls_by_key[(row["seed"], row["offered_load"])]) == 1
    ]
    predicates = {}
    predicates["formal_seed_coverage"] = (
        len(gray) == len(FORMAL_SEEDS)
        and len(symmetric) == len(FORMAL_SEEDS)
        and {row["seed"] for row in gray} == set(FORMAL_SEEDS)
        and {row["seed"] for row in symmetric} == set(FORMAL_SEEDS)
        and len({row["offered_load"] for row in gray}) == 1
        and len(paired_controls) == len(gray)
    )
    predicates["gray_phi_above_control_every_seed"] = predicates["formal_seed_coverage"] and all(
        _finite(row["unmarked_high_ratio"])
        and _finite(control["unmarked_high_ratio"])
        and row["unmarked_high_ratio"] > control["unmarked_high_ratio"]
        for row, control in zip(gray, paired_controls)
    )

    predicates["gray_completion_adequate"] = bool(gray) and all(
        _truth(row, "aux_valid")
        and _finite(row["completion_rate"])
        and row["completion_rate"] >= MIN_COMPLETION_RATE
        for row in gray
    )
    complete_controls = len(paired_controls) == len(FORMAL_SEEDS)
    predicates["control_completion_adequate"] = complete_controls and all(
        _truth(row, "aux_valid")
        and _finite(row["completion_rate"])
        and row["completion_rate"] >= MIN_COMPLETION_RATE
        for row in paired_controls
    )
    predicates["gray_nonzero_unmarked_denominator"] = bool(gray) and all(
        (_as_int(row, "unmarked_count") or 0) > 0 for row in gray
    )
    predicates["control_nonzero_unmarked_denominator"] = complete_controls and all(
        (_as_int(row, "unmarked_count") or 0) > 0 for row in paired_controls
    )
    predicates["gray_flow_coverage_adequate"] = bool(gray) and all(
        _truth(row, "coverage_adequate") for row in gray
    )
    predicates["control_flow_coverage_adequate"] = complete_controls and all(
        _truth(row, "coverage_adequate") for row in paired_controls
    )
    predicates["gray_matching_adequate"] = bool(gray) and all(
        _finite(row["unmatched_next_use_rate"])
        and row["unmatched_next_use_rate"] <= MAX_UNMATCHED_RATE
        for row in gray
    )
    predicates["control_matching_adequate"] = complete_controls and all(
        _finite(row["unmatched_next_use_rate"])
        and row["unmatched_next_use_rate"] <= MAX_UNMATCHED_RATE
        for row in paired_controls
    )
    predicates["gray_no_hard_loss_or_freezing_explanation"] = bool(gray) and all(
        _truth(row, "loss_freezing_clear") for row in gray
    )
    predicates["control_no_hard_loss_or_freezing_explanation"] = (
        complete_controls
        and all(_truth(row, "loss_freezing_clear") for row in paired_controls)
    )

    gray_next = [
        {**row, "cluster_id": (row["run_id"], row["flow_id"])}
        for row in next_rows if row["arm"] == "gray" and row["matched"]
    ]
    flow_rows = _flow_condition_rows(gray_next)
    risk = _risk_ratio_from_flow_rows(flow_rows)
    risk_low = risk_high = None
    if flow_rows and risk is not None:
        try:
            risk_low, risk_high = cluster_bootstrap(
                flow_rows,
                lambda row: row["cluster_id"],
                lambda sample: _risk_ratio_from_flow_rows(sample),
                samples=BOOTSTRAP_SAMPLES,
                seed=BOOTSTRAP_SEED,
            )
        except ValueError:
            risk_low = risk_high = None
    predicates["risk_ratio_bootstrap_lower_above_1"] = (
        risk_low is not None and risk_low > RISK_RATIO_CI_LOWER_BOUND
    )

    high_probability = _condition_probability(flow_rows, "high")
    by_seed_high = []
    for row in gray:
        seed_next = [
            {**item, "cluster_id": (item["run_id"], item["flow_id"])}
            for item in gray_next if item["seed"] == row["seed"]
        ]
        by_seed_high.append(_condition_probability(_flow_condition_rows(seed_next), "high"))
    high_contributors = sum(
        row["high_n"] > 0 and row["high_y"] > 0 for row in flow_rows
    )
    predicates["future_high_probability_nontrivial"] = bool(
        high_probability is not None
        and high_probability >= MIN_FUTURE_HIGH
        and len(by_seed_high) == len(FORMAL_SEEDS)
        and all(value is not None and value >= MIN_FUTURE_HIGH for value in by_seed_high)
        and high_contributors >= MIN_FUTURE_HIGH_CONTRIBUTING_FLOW_CLUSTERS
    )

    gray_groups = [row for row in group_rows if row["arm"] == "gray"]
    predicates["entropy_persistence_positive"] = _overall_group_direction(gray_groups, "entropy")
    predicates["deduplicated_path_persistence_positive"] = _overall_group_direction(
        gray_groups, "physical_path"
    )
    failed = [name for name, passed in predicates.items() if not passed]
    return {
        "accepted": int(not failed),
        "failed_predicates": ";".join(failed),
        "risk_ratio": _csv_value(risk),
        "risk_ratio_ci_low": _csv_value(risk_low),
        "risk_ratio_ci_high": _csv_value(risk_high),
        "future_high_given_current_high": _csv_value(high_probability),
        "residual_threshold_ps": PRIMARY_THRESHOLD_PS,
        "residual_threshold_rule": ">=",
        "completion_rate_threshold": MIN_COMPLETION_RATE,
        "flow_coverage_fraction_threshold": MIN_COVERED_FLOW_FRACTION,
        "entropy_coverage_count_threshold": MIN_ENTROPY_COVERAGE,
        "physical_path_coverage_count_threshold": MIN_PATH_COVERAGE,
        "min_future_high_threshold": MIN_FUTURE_HIGH,
        "max_unmatched_rate_threshold": MAX_UNMATCHED_RATE,
        "bootstrap_samples": BOOTSTRAP_SAMPLES,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "bootstrap_confidence_level": BOOTSTRAP_CONFIDENCE_LEVEL,
        "bootstrap_lower_percentile": BOOTSTRAP_LOWER_PERCENTILE,
        "bootstrap_upper_percentile": BOOTSTRAP_UPPER_PERCENTILE,
        "bootstrap_cluster_unit": "run_id,flow_id",
        "risk_ratio_ci_lower_bound_threshold": RISK_RATIO_CI_LOWER_BOUND,
        "risk_ratio_ci_lower_bound_rule": ">1",
        "min_future_high_contributing_flow_clusters": (
            MIN_FUTURE_HIGH_CONTRIBUTING_FLOW_CLUSTERS
        ),
        "required_formal_seeds": ";".join(str(seed) for seed in FORMAL_SEEDS),
        "required_formal_seed_count": len(FORMAL_SEEDS),
        "evidence_required_for_arms": "gray;load-matched symmetric control",
        "phi_control_rule": "gray>load-matched symmetric in every formal seed",
        "loss_freezing_max_high_retransmitted_count": MAX_HIGH_RETRANSMITTED_COUNT,
        "loss_freezing_criterion": (
            "valid auxiliary completion>=0.99 and zero retransmitted genuine "
            "ECN-unmarked high-residual ACKs"
        ),
        "predicates_json": json.dumps(predicates, sort_keys=True),
    }


def analyze_phase(
    phase: str,
    phase_dir: Path,
) -> tuple[list[dict], Optional[dict]]:
    """Read one phase directory and atomically replace its aggregate CSV tables."""

    if phase not in ("calibration", "formal"):
        raise ValueError(f"unsupported M1 analysis phase: {phase!r}")
    phase_dir = phase_dir.resolve()
    try:
        phase_dir.relative_to(HERE)
    except ValueError as exc:
        raise ValueError(f"phase directory must remain inside {HERE}: {phase_dir}") from exc
    manifests = sorted(phase_dir.glob("*.manifest.json"))
    if not manifests:
        raise ValueError(f"no manifests found in requested phase directory: {phase_dir}")
    summary_rows = []
    residual_rows = []
    next_rows = []
    token_rows = []
    coverage_rows = []
    group_rows = []
    for manifest_path in manifests:
        metadata = _manifest_metadata(manifest_path, phase)
        run_id = metadata["run_id"]
        prefix = phase_dir / run_id
        analysis = analyze_bundle(
            load_trace(prefix), threshold_ps=PRIMARY_THRESHOLD_PS,
            auxiliary=parse_flow_output(phase_dir / f"{run_id}.dat"),
        )
        summary_rows.append(_summary_dict(analysis.summary, metadata))
        residual_rows.extend(_enrich(analysis.residual_rows, metadata))
        next_rows.extend(_enrich(analysis.next_use_rows, metadata))
        token_rows.extend(_enrich(analysis.token_rows, metadata))
        coverage_rows.extend(_enrich(analysis.coverage_rows, metadata))
        group_rows.extend(_enrich(analysis.group_rows, metadata))

    _write_table(phase_dir / "summary.csv", summary_rows, ["run_id"])
    _write_table(phase_dir / "ecdf.csv", residual_rows, ["run_id", "residual_ps"])
    _write_table(phase_dir / "next_use.csv", next_rows, ["run_id", "flow_id"])
    _write_table(phase_dir / "token_detail.csv", token_rows, ["run_id", "token_id"])
    _write_table(phase_dir / "coverage.csv", coverage_rows, ["run_id", "flow_id"])
    _write_table(phase_dir / "group_direction.csv", group_rows, ["run_id", "grouping"])
    conditioning = _conditioning_table(next_rows)
    tokens = _token_aggregate(token_rows)
    _write_table(phase_dir / "conditioning.csv", conditioning, ["arm", "current_state"])
    _write_table(phase_dir / "tokens.csv", tokens, ["arm"])

    formal = None
    if phase == "formal":
        formal = _formal_result(summary_rows, next_rows, group_rows)
        _write_table(phase_dir / "formal_result.csv", [formal], list(formal))
    return summary_rows, formal


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--calibration", action="store_true")
    mode.add_argument("--formal", action="store_true")
    parser.add_argument("--select-formal", action="store_true")
    args = parser.parse_args(argv)
    if args.select_formal and not args.calibration:
        parser.error("--select-formal requires --calibration")
    phase = "calibration" if args.calibration else "formal"
    phase_dir = HERE / "data" / phase
    try:
        summaries, formal = analyze_phase(phase, phase_dir)
        if args.select_formal:
            selection = select_formal(
                summaries, FORMAL_CONFIG, phase_dir / "calibration_selection.csv"
            )
            if not selection.selected:
                print("calibration selection failed: no qualifying cell", file=sys.stderr)
                return 1
            print(f"selected {selection.scenario_id} with control {selection.control_scenario_id}")
        elif formal is not None:
            print(f"formal accepted={formal['accepted']} failed={formal['failed_predicates']}")
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
