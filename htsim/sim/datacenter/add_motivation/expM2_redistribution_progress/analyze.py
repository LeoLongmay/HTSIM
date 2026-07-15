#!/usr/bin/env python3
"""Analyze M2 shadow validation rounds and lock deterministic formal cells."""

from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import math
import os
import re
import statistics
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Optional

try:
    from htsim.sim.datacenter.add_motivation.common.shadow_replay import replay_shadow
    from htsim.sim.datacenter.add_motivation.common.statistics import cluster_bootstrap
    from htsim.sim.datacenter.add_motivation.common.trace_schema import load_trace
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[5]))
    from htsim.sim.datacenter.add_motivation.common.shadow_replay import replay_shadow
    from htsim.sim.datacenter.add_motivation.common.statistics import cluster_bootstrap
    from htsim.sim.datacenter.add_motivation.common.trace_schema import load_trace


HERE = Path(__file__).resolve().parent
FORMAL_CONFIG = HERE / "configs" / "formal.csv"
CONFIG_FIELDS = (
    "cell_id", "scenario", "foreground_flows", "hot_path_groups",
    "background_utilization", "seed",
)
COARSE_SEEDS = (101,)
CONFIRMATION_SEEDS = (101, 102, 103)
FORMAL_SEEDS = (13, 14, 15, 16, 17)
TARGET_CUT_QUEUE = re.compile(r"^CS[0-9]+->US[0-9]+\([0-9]+\)$")
T_CC_PS = 14_000_000
DIAGNOSTIC_TOLERANCES_PS = (1_000_000, 2_000_000, 4_000_000)
DELIVERY_RELATIVE_TOLERANCE = 0.05
BOOTSTRAP_SAMPLES = 10_000
BOOTSTRAP_SEED = 20260714
MIN_VALID_COMPLETED_ROUNDS = 3


class EvidenceError(ValueError):
    """Raised when trace facts cannot support the requested M2 inference."""


@dataclasses.dataclass(frozen=True)
class CapacityWitness:
    c_healthy_gbps: float
    c_hot_residual_gbps: float
    c_effective_residual_gbps: float
    configured_background_gbps: float
    measured_background_gbps: float
    target_cut_queues: tuple[str, ...]
    hot_cut_queues: tuple[str, ...]

    def classify(self, l_foreground_gbps: float) -> str:
        if not _finite(l_foreground_gbps) or l_foreground_gbps < 0:
            return "invalid"
        if l_foreground_gbps < self.c_healthy_gbps:
            return "recoverable"
        if self.c_healthy_gbps < l_foreground_gbps < self.c_effective_residual_gbps:
            return "persistent"
        return "invalid"


@dataclasses.dataclass(frozen=True)
class OfferedLoadWitness:
    valid: bool
    rate_gbps: Optional[float]
    flow_count: int
    elapsed_ps_min: Optional[int]
    elapsed_ps_max: Optional[int]
    failed_predicates: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class BundleAnalysis:
    summary: dict
    rounds: tuple[dict, ...]
    epochs: tuple[dict, ...]


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _number(row: dict, key: str) -> Optional[float]:
    value = row.get(key)
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _integer(row: dict, key: str) -> Optional[int]:
    value = _number(row, key)
    return int(value) if value is not None and value.is_integer() else None


def _truth(row: dict, key: str) -> bool:
    return row.get(key) in (True, 1, 1.0, "1", "true", "True")


def _fingerprint_queues(fingerprint: str) -> tuple[str, ...]:
    if not isinstance(fingerprint, str) or not fingerprint:
        raise EvidenceError("empty queue_fingerprint")
    queues = tuple(fingerprint.split("|"))
    if any(not queue for queue in queues):
        raise EvidenceError(f"malformed queue_fingerprint {fingerprint!r}")
    return queues


def capacity_witness(bundle, start_ps: int, end_ps: int) -> CapacityWitness:
    """Construct the exact target-pod cut witness for one evaluated interval."""

    if isinstance(start_ps, bool) or isinstance(end_ps, bool) or start_ps < 0 or end_ps <= start_ps:
        raise EvidenceError("capacity interval must have 0 <= start_ps < end_ps")

    link_rates: dict[str, float] = {}
    for row in bundle.linkmap:
        name = row["queue_name"]
        rate = row["rate_gbps"]
        if not _finite(rate) or rate <= 0:
            raise EvidenceError(f"linkmap queue {name!r} has invalid rate_gbps")
        previous = link_rates.get(name)
        if previous is not None and previous != rate:
            raise EvidenceError(f"linkmap queue {name!r} has inconsistent capacities")
        link_rates[name] = float(rate)

    unresolved_paths = [
        row for row in bundle.pathmap if row["resolution_status"] != "resolved"
    ]
    if unresolved_paths:
        status = unresolved_paths[0]["resolution_status"]
        raise EvidenceError(
            f"foreground pathmap contains unresolved path row with status {status!r}"
        )

    cut_queues = set()
    for row in bundle.pathmap:
        for name in _fingerprint_queues(row["queue_fingerprint"]):
            if TARGET_CUT_QUEUE.fullmatch(name):
                if name not in link_rates:
                    raise EvidenceError(f"pathmap cut queue {name!r} is absent from linkmap")
                cut_queues.add(name)
    if not cut_queues:
        raise EvidenceError("pathmap/linkmap contain no resolved target-pod cut queues")

    by_background = defaultdict(list)
    for row in bundle.background:
        by_background[row["background_id"]].append(row)
    if not by_background:
        raise EvidenceError("capacity witness requires background start/finish records")

    configured_by_queue = defaultdict(float)
    measured_total = 0.0
    for background_id in sorted(by_background):
        records = by_background[background_id]
        starts = [row for row in records if row["operation"] == "start"]
        finishes = [row for row in records if row["operation"] in ("finish", "delivery")]
        if len(starts) != 1 or len(finishes) != 1:
            raise EvidenceError(
                f"background_id {background_id} must have exactly one start and finish/delivery"
            )
        start, finish = starts[0], finishes[0]
        if start["time_ps"] > start_ps or finish["time_ps"] < end_ps:
            raise EvidenceError(f"background_id {background_id} does not cover evaluated interval")
        if finish["time_ps"] <= start["time_ps"]:
            raise EvidenceError(f"background_id {background_id} has nonpositive delivery interval")
        if (
            start["configured_rate_gbps"] != finish["configured_rate_gbps"]
            or start["queue_fingerprint"] != finish["queue_fingerprint"]
        ):
            raise EvidenceError(f"background_id {background_id} start/finish metadata mismatch")
        matches = [
            name for name in _fingerprint_queues(start["queue_fingerprint"])
            if TARGET_CUT_QUEUE.fullmatch(name)
        ]
        if len(matches) != 1:
            raise EvidenceError(
                f"background_id {background_id} queue_fingerprint must contain exactly one "
                "target-pod cut queue"
            )
        queue = matches[0]
        if queue not in cut_queues:
            raise EvidenceError(f"background cut queue {queue!r} is absent from foreground cut")
        configured = float(start["configured_rate_gbps"])
        if not math.isfinite(configured) or configured <= 0:
            raise EvidenceError(f"background_id {background_id} has invalid configured rate")
        measured = (
            finish["delivered_bytes"] * 8.0 * 1000.0
            / (finish["time_ps"] - start["time_ps"])
        )
        if abs(measured - configured) > DELIVERY_RELATIVE_TOLERANCE * configured:
            raise EvidenceError(
                f"background_id {background_id} measured delivery {measured:g} Gbps "
                f"differs from configured {configured:g} Gbps by more than 5%"
            )
        configured_by_queue[queue] += configured
        measured_total += measured

    hot_queues = set(configured_by_queue)
    healthy = sum(link_rates[name] for name in cut_queues - hot_queues)
    hot_residual = sum(
        max(link_rates[name] - configured_by_queue[name], 0.0) for name in hot_queues
    )
    return CapacityWitness(
        c_healthy_gbps=healthy,
        c_hot_residual_gbps=hot_residual,
        c_effective_residual_gbps=healthy + hot_residual,
        configured_background_gbps=sum(configured_by_queue.values()),
        measured_background_gbps=measured_total,
        target_cut_queues=tuple(sorted(cut_queues)),
        hot_cut_queues=tuple(sorted(hot_queues)),
    )


def foreground_offered_load(
    bundle, start_ps: int, end_ps: int,
    foreground_flow_ids: Optional[Iterable[int]] = None,
) -> OfferedLoadWitness:
    """Measure foreground injection from bracketing epoch send-counter snapshots."""

    if start_ps < 0 or end_ps <= start_ps:
        return OfferedLoadWitness(False, None, 0, None, None, ("invalid_interval",))
    by_flow = defaultdict(list)
    for epoch in bundle.epoch:
        by_flow[epoch["flow_id"]].append(epoch)
    flow_ids = sorted(by_flow) if foreground_flow_ids is None else sorted(set(foreground_flow_ids))
    failures = []
    rates = []
    elapsed_values = []
    for flow_id in flow_ids:
        epochs = sorted(by_flow.get(flow_id, ()), key=lambda row: (row["end_ps"], row["event_seq"]))
        before_rows = [row for row in epochs if row["end_ps"] <= start_ps]
        after_rows = [row for row in epochs if row["end_ps"] >= end_ps]
        if not before_rows or not after_rows:
            failures.append(f"flow_{flow_id}:missing_bracketing_epoch")
            continue
        before = before_rows[-1]
        after = after_rows[0]
        elapsed = after["end_ps"] - before["end_ps"]
        sent = after["new_data_bytes_sent_total"] - before["new_data_bytes_sent_total"]
        if elapsed <= 0:
            failures.append(f"flow_{flow_id}:nonpositive_counter_elapsed_ps")
            continue
        if sent < 0:
            failures.append(f"flow_{flow_id}:decreasing_new_data_counter")
            continue
        elapsed_values.append(elapsed)
        rates.append(sent * 8.0 * 1000.0 / elapsed)
    if failures or not flow_ids:
        if not flow_ids:
            failures.append("no_foreground_flows")
        return OfferedLoadWitness(
            False, None, len(flow_ids), min(elapsed_values, default=None),
            max(elapsed_values, default=None), tuple(failures),
        )
    return OfferedLoadWitness(
        True, sum(rates), len(flow_ids), min(elapsed_values), max(elapsed_values), (),
    )


def _median(values: Iterable[float]) -> Optional[float]:
    values = [float(value) for value in values if _finite(value)]
    return statistics.median(values) if values else None


def _mean(values: Iterable[float]) -> Optional[float]:
    values = [float(value) for value in values if _finite(value)]
    return statistics.fmean(values) if values else None


def _config(config: dict) -> dict:
    missing = [field for field in CONFIG_FIELDS if field not in config]
    if missing:
        raise ValueError(f"M2 config is missing fixed fields: {missing}")
    normalized = {
        "cell_id": str(config["cell_id"]),
        "scenario": str(config["scenario"]),
        "foreground_flows": int(config["foreground_flows"]),
        "hot_path_groups": int(config["hot_path_groups"]),
        "background_utilization": float(config["background_utilization"]),
        "seed": int(config["seed"]),
    }
    if normalized["scenario"] not in ("", "recoverable", "persistent"):
        raise ValueError("scenario must be empty, recoverable, or persistent")
    if (
        not normalized["cell_id"] or normalized["foreground_flows"] <= 0
        or normalized["hot_path_groups"] <= 0
        or not 0 < normalized["background_utilization"] < 1
    ):
        raise ValueError("M2 config contains invalid fixed-field values")
    return normalized


def _infer_coarse_scenario(round_rows: Iterable[dict]) -> tuple[str, str]:
    completed = [row for row in round_rows if _truth(row, "complete")]
    if not completed:
        return "invalid", "coarse_scenario_inference_no_completed_rounds"
    if any(
        not _truth(row, "capacity_valid")
        or not _truth(row, "offered_load_valid")
        or row.get("capacity_classification") not in ("recoverable", "persistent")
        for row in completed
    ):
        return "invalid", "coarse_scenario_inference_invalid_completed_evidence"
    classifications = {row["capacity_classification"] for row in completed}
    if len(classifications) != 1:
        return "invalid", "coarse_scenario_inference_mixed_capacity_classification"
    return classifications.pop(), ""


def _apply_coarse_scenario(
    metadata: dict, round_rows: list[dict], epoch_rows: list[dict],
) -> None:
    if metadata["scenario"]:
        return
    inferred_scenario, inference_failure = _infer_coarse_scenario(round_rows)
    metadata["scenario"] = inferred_scenario
    for row in round_rows:
        row["scenario"] = inferred_scenario
        if inference_failure:
            row["valid_round"] = 0
            row["failed_predicates"] = ";".join(filter(None, (
                row["failed_predicates"], inference_failure,
            )))
    for row in epoch_rows:
        row["scenario"] = inferred_scenario


def analyze_bundle(bundle, config: dict) -> BundleAnalysis:
    """Replay one trace and emit only aggregate round and event-aligned epoch facts."""

    metadata = _config(config)
    rounds = replay_shadow(bundle)
    foreground_ids = sorted({row["flow_id"] for row in bundle.epoch})
    if len(foreground_ids) != metadata["foreground_flows"]:
        raise EvidenceError(
            f"trace has {len(foreground_ids)} foreground epoch flows; "
            f"config requires {metadata['foreground_flows']}"
        )
    epochs_by_flow = defaultdict(list)
    for epoch in bundle.epoch:
        epochs_by_flow[epoch["flow_id"]].append(epoch)

    round_rows = []
    epoch_rows = []
    for shadow in rounds:
        flow_epochs = sorted(
            epochs_by_flow[shadow.flow_id], key=lambda row: (row["end_ps"], row["event_seq"])
        )
        start_epoch = next(
            (row for row in flow_epochs if row["event_seq"] == shadow.start_event_seq), None
        )
        if start_epoch is None:
            raise EvidenceError(f"round start epoch {shadow.start_event_seq} is absent")
        interval_end = shadow.end_ps if shadow.complete else flow_epochs[-1]["end_ps"]
        interval_epochs = [
            row for row in flow_epochs
            if shadow.start_ps <= row["end_ps"] <= interval_end
        ]
        failures = []
        capacity = None
        offered = foreground_offered_load(bundle, shadow.start_ps, interval_end, foreground_ids)
        try:
            capacity = capacity_witness(bundle, shadow.start_ps, interval_end)
        except EvidenceError as exc:
            failures.append(f"capacity_witness_invalid:{exc}")
        if not offered.valid:
            failures.extend(offered.failed_predicates)
        classification = (
            capacity.classify(offered.rate_gbps)
            if capacity is not None and offered.valid and offered.rate_gbps is not None
            else "invalid"
        )
        if metadata["scenario"] and classification != metadata["scenario"]:
            failures.append("capacity_relation_mismatch")
        elif classification == "invalid":
            failures.append("capacity_classification_invalid")
        if not shadow.complete:
            failures.append("round_censored")

        low_floor_count = sum(row["raw_floor_ps"] < T_CC_PS for row in interval_epochs)
        high_spread_count = sum(row["raw_spread_ps"] >= T_CC_PS for row in interval_epochs)
        hold_epochs = [row for row in interval_epochs if row["actual_region"] == "hold"]
        hold_duration = sum(row["end_ps"] - row["start_ps"] for row in hold_epochs)
        round_qdelay = [
            ack["qdelay_ps"] for ack in bundle.ack
            if ack["flow_id"] == shadow.flow_id and ack["genuine_sample"]
            and shadow.start_ps <= ack["time_ps"] <= interval_end
        ]
        start_cwnd = start_epoch["cwnd_bytes"]
        row = {
            **metadata, "run_id": bundle.run_id, "flow_id": shadow.flow_id,
            "round_index": shadow.round_index, "start_event_seq": shadow.start_event_seq,
            "end_event_seq": shadow.end_event_seq if shadow.end_event_seq is not None else "",
            "start_ps": shadow.start_ps, "end_ps": shadow.end_ps if shadow.end_ps is not None else "",
            "duration_ps": shadow.end_ps - shadow.start_ps if shadow.complete else "",
            "complete": int(shadow.complete), "censored": int(shadow.censored),
            "censor_reason": shadow.censor_reason or "",
            "F_ps": start_epoch["raw_floor_ps"], "S_ps": start_epoch["raw_spread_ps"],
            "S_ref_ps": shadow.s_ref_ps,
            "S_end_ps": shadow.s_end_ps if shadow.s_end_ps is not None else "",
            "delta_S": shadow.delta_s if shadow.delta_s is not None else "",
            "literal_no_progress": int(shadow.no_progress) if shadow.complete else "",
            "no_progress_1us": (
                int(shadow.s_ref_ps - shadow.s_end_ps <= DIAGNOSTIC_TOLERANCES_PS[0])
                if shadow.complete else ""
            ),
            "no_progress_2us": (
                int(shadow.s_ref_ps - shadow.s_end_ps <= DIAGNOSTIC_TOLERANCES_PS[1])
                if shadow.complete else ""
            ),
            "no_progress_4us": (
                int(shadow.s_ref_ps - shadow.s_end_ps <= DIAGNOSTIC_TOLERANCES_PS[2])
                if shadow.complete else ""
            ),
            "hold_duration_ps": hold_duration, "hold_epoch_count": len(hold_epochs),
            "low_floor_epoch_count": low_floor_count,
            "round_epoch_count": len(interval_epochs),
            "low_floor_fraction": low_floor_count / len(interval_epochs) if interval_epochs else "",
            "high_spread_fraction": high_spread_count / len(interval_epochs) if interval_epochs else "",
            "actual_cwnd_bytes": start_cwnd, "actual_state": start_epoch["actual_region"],
            "fifo_depth": shadow.fifo_depth_at_start,
            "virtual_replacements": shadow.replacement_count,
            "seeded_admission_pass": shadow.seeded_pass_count,
            "seeded_admission_fail": shadow.seeded_fail_count,
            "replacement_admission_pass": shadow.admission_pass_count,
            "replacement_admission_fail": shadow.admission_fail_count,
            "entropy_coverage": min((item["entropy_coverage"] for item in interval_epochs), default=0),
            "physical_path_coverage": min(
                (item["physical_path_coverage"] for item in interval_epochs), default=0
            ),
            "mean_qdelay_ps": _mean(round_qdelay) if round_qdelay else "",
            "offered_load_valid": int(offered.valid),
            "L_foreground_gbps": offered.rate_gbps if offered.rate_gbps is not None else "",
            "offered_elapsed_ps_min": offered.elapsed_ps_min or "",
            "offered_elapsed_ps_max": offered.elapsed_ps_max or "",
            "capacity_valid": int(capacity is not None),
            "capacity_classification": classification,
            "C_healthy_gbps": capacity.c_healthy_gbps if capacity else "",
            "C_hot_residual_gbps": capacity.c_hot_residual_gbps if capacity else "",
            "C_effective_residual_gbps": capacity.c_effective_residual_gbps if capacity else "",
            "configured_background_gbps": capacity.configured_background_gbps if capacity else "",
            "measured_background_gbps": capacity.measured_background_gbps if capacity else "",
            "capacity_margin_gbps": (
                capacity.c_healthy_gbps - offered.rate_gbps
                if classification == "recoverable" else
                min(
                    offered.rate_gbps - capacity.c_healthy_gbps,
                    capacity.c_effective_residual_gbps - offered.rate_gbps,
                ) if classification == "persistent" else ""
            ),
            "valid_round": int(shadow.complete and not failures),
            "failed_predicates": ";".join(failures),
        }
        round_rows.append(row)

        for epoch in interval_epochs:
            epoch_rows.append({
                **metadata, "run_id": bundle.run_id, "flow_id": shadow.flow_id,
                "round_index": shadow.round_index, "event_seq": epoch["event_seq"],
                "event_time_ps": epoch["end_ps"],
                "aligned_time_ps": epoch["end_ps"] - shadow.start_ps,
                "F_ps": epoch["raw_floor_ps"], "S_ps": epoch["raw_spread_ps"],
                "S_ref_ps": shadow.s_ref_ps, "actual_cwnd_bytes": epoch["cwnd_bytes"],
                "actual_state": epoch["actual_region"],
                "hold": int(epoch["actual_region"] == "hold"),
                "round_complete_marker": int(
                    shadow.complete and epoch["event_seq"] == shadow.end_event_seq
                ),
            })

    _apply_coarse_scenario(metadata, round_rows, epoch_rows)

    complete = [row for row in round_rows if _truth(row, "complete")]
    valid = [row for row in round_rows if _truth(row, "valid_round")]
    valid_delta = [float(row["delta_S"]) for row in valid]
    literal = [int(row["literal_no_progress"]) for row in valid]
    total_round_epochs = sum(int(row["round_epoch_count"]) for row in round_rows)
    low_floor_high_spread_epochs = sum(
        sum(
            epoch["raw_floor_ps"] < T_CC_PS and epoch["raw_spread_ps"] >= T_CC_PS
            for epoch in epochs_by_flow[row["flow_id"]]
            if int(row["start_ps"]) <= epoch["end_ps"]
            <= (int(row["end_ps"]) if row["end_ps"] != "" else epochs_by_flow[row["flow_id"]][-1]["end_ps"])
        )
        for row in round_rows
    )
    summary = {
        **metadata, "run_id": bundle.run_id, "episode_count": len(round_rows),
        "round_count": len(round_rows), "completed_rounds": len(complete),
        "valid_completed_rounds": len(valid), "censored_rounds": len(round_rows) - len(complete),
        "completion_rate": len(complete) / len(round_rows) if round_rows else "",
        "censor_rate": (len(round_rows) - len(complete)) / len(round_rows) if round_rows else "",
        "median_delta_S": _median(valid_delta) if valid_delta else "",
        "literal_no_progress_count": sum(literal),
        "literal_no_progress_rate": sum(literal) / len(literal) if literal else "",
        "no_progress_rate_1us": _mean(row["no_progress_1us"] for row in valid) or 0.0,
        "no_progress_rate_2us": _mean(row["no_progress_2us"] for row in valid) or 0.0,
        "no_progress_rate_4us": _mean(row["no_progress_4us"] for row in valid) or 0.0,
        "low_floor_fraction": (
            sum(int(row["low_floor_epoch_count"]) for row in valid)
            / sum(int(row["round_epoch_count"]) for row in valid)
            if sum(int(row["round_epoch_count"]) for row in valid) else ""
        ),
        "completed_round_flow_count": len({row["flow_id"] for row in complete}),
        "all_valid_rounds_match_scenario": int(
            bool(complete)
            and metadata["scenario"] in ("recoverable", "persistent")
            and all(
                _truth(row, "capacity_valid")
                and _truth(row, "offered_load_valid")
                and row["capacity_classification"] == metadata["scenario"]
                for row in complete
            )
        ),
        "min_capacity_margin_gbps": _median([]) if not valid else min(
            float(row["capacity_margin_gbps"]) for row in valid
        ),
        "configured_background_gbps": _mean(
            row["configured_background_gbps"] for row in valid
        ) if valid else "",
        "measured_background_gbps": _mean(
            row["measured_background_gbps"] for row in valid
        ) if valid else "",
        "L_foreground_gbps": _mean(row["L_foreground_gbps"] for row in valid) if valid else "",
        "C_healthy_gbps": _mean(row["C_healthy_gbps"] for row in valid) if valid else "",
        "C_hot_residual_gbps": _mean(
            row["C_hot_residual_gbps"] for row in valid
        ) if valid else "",
        "C_effective_residual_gbps": _mean(
            row["C_effective_residual_gbps"] for row in valid
        ) if valid else "",
        "entropy_coverage": min((int(row["entropy_coverage"]) for row in valid), default=""),
        "physical_path_coverage": min(
            (int(row["physical_path_coverage"]) for row in valid), default=""
        ),
        "mean_qdelay_ps": _mean(row["mean_qdelay_ps"] for row in valid) if valid else "",
        "low_floor_high_spread_occupancy": (
            low_floor_high_spread_epochs / total_round_epochs if total_round_epochs else ""
        ),
        "mean_hold_duration_ps": _mean(row["hold_duration_ps"] for row in round_rows),
        "mean_actual_cwnd_bytes": _mean(row["actual_cwnd_bytes"] for row in round_rows),
        "mean_fifo_depth": _mean(row["fifo_depth"] for row in round_rows),
        "virtual_replacements": sum(int(row["virtual_replacements"]) for row in round_rows),
        "admission_pass": sum(
            int(row["seeded_admission_pass"]) + int(row["replacement_admission_pass"])
            for row in round_rows
        ),
        "admission_fail": sum(
            int(row["seeded_admission_fail"]) + int(row["replacement_admission_fail"])
            for row in round_rows
        ),
        "failed_predicates": ";".join(
            sorted({failure for row in round_rows for failure in str(row["failed_predicates"]).split(";") if failure})
        ),
    }
    return BundleAnalysis(summary, tuple(round_rows), tuple(epoch_rows))


def _candidate_rank(rows: list[dict], scenario: str) -> tuple:
    if scenario == "recoverable":
        margins = [_number(row, "median_delta_S") for row in rows]
    else:
        margins = [
            (_number(row, "literal_no_progress_rate") - 0.5)
            if _number(row, "literal_no_progress_rate") is not None else None
            for row in rows
        ]
    capacities = [_number(row, "min_capacity_margin_gbps") for row in rows]
    if any(value is None for value in margins + capacities):
        return (math.inf, math.inf, math.inf, "")
    return (
        -min(margins), -min(capacities),
        float(rows[0]["background_utilization"]), str(rows[0]["cell_id"]),
    )


def _atomic_csv(path: Path | str, fields: Iterable[str], rows: Iterable[dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", newline="", encoding="ascii", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            writer = csv.DictWriter(stream, fieldnames=list(fields), extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _selection_evidence_adequate(row: dict) -> bool:
    return bool(
        (_integer(row, "valid_completed_rounds") or 0) >= MIN_VALID_COMPLETED_ROUNDS
        and (_number(row, "low_floor_high_spread_occupancy") or 0) > 0
    )


def select_confirmation(summary_rows: Iterable[dict], output_path: Path | str) -> list[dict]:
    """Select at most three seed-101 coarse cells per predeclared scenario."""

    rows = list(summary_rows)
    output = []
    for scenario in ("recoverable", "persistent"):
        eligible = [
            row for row in rows
            if row.get("scenario") == scenario and _integer(row, "seed") == 101
            and _truth(row, "all_valid_rounds_match_scenario")
            and _selection_evidence_adequate(row)
        ]
        for selected in sorted(eligible, key=lambda row: _candidate_rank([row], scenario))[:3]:
            for seed in CONFIRMATION_SEEDS:
                output.append({field: seed if field == "seed" else selected[field] for field in CONFIG_FIELDS})
    output.sort(key=lambda row: (row["scenario"], row["cell_id"], row["seed"]))
    _atomic_csv(output_path, CONFIG_FIELDS, output)
    return output


def select_formal(summary_rows: Iterable[dict], formal_path: Path | str = FORMAL_CONFIG) -> list[dict]:
    """Select only fully confirmed cells; write header-only formal CSV on failure."""

    grouped = defaultdict(list)
    for row in summary_rows:
        grouped[(row.get("scenario"), row.get("cell_id"))].append(row)
    selected = {}
    for scenario in ("recoverable", "persistent"):
        eligible = []
        for (candidate_scenario, _cell_id), rows in grouped.items():
            if candidate_scenario != scenario:
                continue
            seeds = {_integer(row, "seed") for row in rows}
            if seeds != set(CONFIRMATION_SEEDS) or len(rows) != len(CONFIRMATION_SEEDS):
                continue
            if not all(
                _truth(row, "all_valid_rounds_match_scenario")
                and _selection_evidence_adequate(row)
                for row in rows
            ):
                continue
            if scenario == "recoverable":
                if not all((_number(row, "median_delta_S") or 0) > 0 for row in rows):
                    continue
            else:
                if not all(
                    (_number(row, "literal_no_progress_rate") or 0) > 0.5
                    and (_number(row, "low_floor_fraction") or 0) >= 0.8
                    for row in rows
                ):
                    continue
            eligible.append(rows)
        if eligible:
            selected[scenario] = min(eligible, key=lambda rows: _candidate_rank(rows, scenario))[0]

    formal_rows = []
    if set(selected) == {"recoverable", "persistent"}:
        for scenario in ("recoverable", "persistent"):
            for seed in FORMAL_SEEDS:
                formal_rows.append({
                    field: seed if field == "seed" else selected[scenario][field]
                    for field in CONFIG_FIELDS
                })
    _atomic_csv(formal_path, CONFIG_FIELDS, formal_rows)
    return formal_rows


def formal_acceptance(
    summary_rows: Iterable[dict], round_rows: Iterable[dict], *, samples: int = BOOTSTRAP_SAMPLES,
) -> list[dict]:
    """Evaluate both formal claims without allowing censored rounds into outcome denominators."""

    summaries = list(summary_rows)
    rounds = list(round_rows)
    results = []
    for scenario in ("recoverable", "persistent"):
        scenario_summaries = [row for row in summaries if row.get("scenario") == scenario]
        scenario_rounds = [row for row in rounds if row.get("scenario") == scenario]
        completed_rounds = [row for row in scenario_rounds if _truth(row, "complete")]
        valid_rounds = [
            row for row in scenario_rounds
            if _truth(row, "complete") and _truth(row, "valid_round")
        ]
        failures = []
        seeds = {_integer(row, "seed") for row in scenario_summaries}
        if seeds != set(FORMAL_SEEDS) or len(scenario_summaries) != len(FORMAL_SEEDS):
            failures.append("formal_seed_coverage_not_exactly_13_through_17")
        sparse_seeds = [
            seed for seed in FORMAL_SEEDS
            if sum(_integer(row, "seed") == seed for row in valid_rounds)
            < MIN_VALID_COMPLETED_ROUNDS
        ]
        if sparse_seeds:
            failures.append("fewer_than_3_valid_completed_rounds_in_a_formal_seed")
        foreground = max(
            (_integer(row, "foreground_flows") or 0 for row in scenario_summaries),
            default=0,
        )
        valid_flows_by_seed = {
            seed: {
                _integer(row, "flow_id") for row in valid_rounds
                if _integer(row, "seed") == seed
            }
            for seed in FORMAL_SEEDS
        }
        required_flow_count = math.ceil(foreground / 2)
        if not foreground or any(
            len(flows) < required_flow_count for flows in valid_flows_by_seed.values()
        ):
            failures.append("valid_completed_round_flows_below_half_foreground_per_seed")

        bootstrap_low = None
        if scenario == "recoverable":
            positive_seed_count = sum(
                (_number(row, "median_delta_S") or 0) > 0 for row in scenario_summaries
            )
            if positive_seed_count < 4:
                failures.append("fewer_than_4_of_5_seed_medians_above_zero")
            if not completed_rounds or any(
                not _truth(row, "capacity_valid")
                or not _truth(row, "offered_load_valid")
                or row.get("capacity_classification") != "recoverable"
                for row in completed_rounds
            ):
                failures.append("recoverable_capacity_relation_not_in_every_completed_round")
            if valid_rounds:
                bootstrap_low, _high = cluster_bootstrap(
                    valid_rounds,
                    cluster_key=lambda row: (_integer(row, "seed"), _integer(row, "flow_id")),
                    statistic=lambda sample: statistics.median(float(row["delta_S"]) for row in sample),
                    samples=samples, seed=BOOTSTRAP_SEED,
                )
            if bootstrap_low is None or bootstrap_low <= 0:
                failures.append("flow_cluster_bootstrap_95pct_lower_not_above_zero")
        else:
            majority_seed_count = sum(
                (_number(row, "literal_no_progress_rate") or 0) > 0.5
                for row in scenario_summaries
            )
            if majority_seed_count < 4:
                failures.append("fewer_than_4_of_5_seeds_majority_literal_no_progress")
            if not completed_rounds or any(
                not _truth(row, "capacity_valid")
                or not _truth(row, "offered_load_valid")
                or row.get("capacity_classification") != "persistent"
                for row in completed_rounds
            ):
                failures.append("persistent_capacity_relation_not_in_every_valid_round")
            epoch_denominator = sum((_integer(row, "round_epoch_count") or 0) for row in valid_rounds)
            low_floor = sum((_integer(row, "low_floor_epoch_count") or 0) for row in valid_rounds)
            if not epoch_denominator or low_floor / epoch_denominator < 0.8:
                failures.append("low_floor_epoch_fraction_below_0.80")
            reversal = any(
                (_number(row, "no_progress_rate_1us") or 0) + 1e-15
                    < (_number(row, "literal_no_progress_rate") or 0)
                or (_number(row, "no_progress_rate_2us") or 0) + 1e-15
                    < (_number(row, "no_progress_rate_1us") or 0)
                or (_number(row, "no_progress_rate_4us") or 0) + 1e-15
                    < (_number(row, "no_progress_rate_2us") or 0)
                for row in scenario_summaries
            )
            if reversal:
                failures.append("tolerance_direction_reversal")
        results.append({
            "scenario": scenario, "accepted": int(not failures),
            "failed_predicates": ";".join(failures),
            "valid_completed_rounds": len(valid_rounds),
            "bootstrap_samples": samples if scenario == "recoverable" else "",
            "bootstrap_95pct_lower": bootstrap_low if bootstrap_low is not None else "",
        })
    return results


def _write_table(path: Path, rows: list[dict], fallback: Iterable[str]) -> None:
    _atomic_csv(path, list(rows[0]) if rows else list(fallback), rows)


def _read_manifest(path: Path, phase: str) -> tuple[dict, Path]:
    manifest = json.loads(path.read_text(encoding="ascii"))
    if manifest.get("phase") != phase or not isinstance(manifest.get("run_id"), str):
        raise ValueError(f"manifest {path} has wrong phase or run_id")
    source = manifest.get("analysis_config", manifest.get("config", {}))
    metadata = _config(source)
    if phase in ("confirmation", "formal") and not metadata["scenario"]:
        raise ValueError(f"manifest {path} must lock scenario for phase {phase}")
    if manifest.get("seed") != metadata["seed"]:
        raise ValueError(f"manifest {path} seed differs from M2 config seed")
    prefix = path.parent / manifest["run_id"]
    return metadata, prefix


def analyze_phase(phase: str, phase_dir: Path) -> tuple[list[dict], list[dict], list[dict]]:
    if phase not in ("coarse", "confirmation", "formal"):
        raise ValueError(f"unsupported M2 phase {phase!r}")
    manifests = sorted(phase_dir.glob("*.manifest.json"))
    if not manifests:
        raise ValueError(f"no manifests in {phase_dir}")
    summaries, rounds, epochs = [], [], []
    for manifest_path in manifests:
        metadata, prefix = _read_manifest(manifest_path, phase)
        analysis = analyze_bundle(load_trace(prefix), metadata)
        summaries.append(analysis.summary)
        rounds.extend(analysis.rounds)
        epochs.extend(analysis.epochs)
    if phase == "formal":
        acceptance = formal_acceptance(summaries, rounds)
        failed_by_scenario = {row["scenario"]: row for row in acceptance}
        for row in summaries:
            result = failed_by_scenario[row["scenario"]]
            row["formal_accepted"] = result["accepted"]
            row["formal_failed_predicates"] = result["failed_predicates"]
        _write_table(phase_dir / "formal_result.csv", acceptance, ("scenario",))
    _write_table(phase_dir / "summary.csv", summaries, ("run_id",))
    _write_table(phase_dir / "rounds.csv", rounds, ("run_id", "flow_id", "round_index"))
    _write_table(phase_dir / "epochs.csv", epochs, ("run_id", "flow_id", "round_index"))
    return summaries, rounds, epochs


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--coarse", action="store_true")
    mode.add_argument("--confirmation", action="store_true")
    mode.add_argument("--formal", action="store_true")
    parser.add_argument("--select-confirmation", action="store_true")
    parser.add_argument("--select-formal", action="store_true")
    args = parser.parse_args(argv)
    phase = "coarse" if args.coarse else "confirmation" if args.confirmation else "formal"
    if args.select_confirmation and phase != "coarse":
        parser.error("--select-confirmation requires --coarse")
    if args.select_formal and phase != "confirmation":
        parser.error("--select-formal requires --confirmation")
    try:
        summaries, _rounds, _epochs = analyze_phase(phase, HERE / "data" / phase)
        if args.select_confirmation:
            selected = select_confirmation(
                summaries, HERE / "data" / phase / "confirmation_selection.csv"
            )
            if not selected:
                return 1
        if args.select_formal and not select_formal(summaries, FORMAL_CONFIG):
            return 1
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
