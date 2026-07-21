#!/usr/bin/env python3
"""Analyze M2 shadow validation rounds and lock deterministic formal cells."""

from __future__ import annotations

import argparse
import bisect
import copy
import csv
import dataclasses
import json
import math
import os
import re
import statistics
import sys
import tempfile
from collections import defaultdict, deque
from fractions import Fraction
from pathlib import Path
from typing import Iterable, Optional

try:
    from htsim.sim.datacenter.add_motivation.common.shadow_replay import replay_shadow
    from htsim.sim.datacenter.add_motivation.common.statistics import cluster_bootstrap
    from htsim.sim.datacenter.add_motivation.common.trace_schema import load_trace_compact
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[5]))
    from htsim.sim.datacenter.add_motivation.common.shadow_replay import replay_shadow
    from htsim.sim.datacenter.add_motivation.common.statistics import cluster_bootstrap
    from htsim.sim.datacenter.add_motivation.common.trace_schema import load_trace_compact


HERE = Path(__file__).resolve().parent
CALIBRATION_CONFIG = HERE / "configs" / "calibration.csv"
DATA_ROOT = HERE / "data" / "controlled"
CONFIRMATION_SELECTION = DATA_ROOT / "coarse" / "confirmation_selection.csv"
FORMAL_CONFIG = HERE / "configs" / "formal.csv"
CONFIG_FIELDS = (
    "cell_id", "scenario", "foreground_flows", "degraded_links",
    "degraded_capacity_gbps", "seed",
)
COARSE_SEEDS = (101,)
CONFIRMATION_SEEDS = (101, 102, 103)
FORMAL_SEEDS = (13, 14, 15, 16, 17)
TARGET_CUT_QUEUE = re.compile(r"CS[0-9]+->US[0-9]+\([0-9]+\)")
PATH_ENTROPIES = frozenset(range(8))
T_CC_PS = 14_000_000
CONTROLLED_WARMUP_PS = 1_000_000_000
DIAGNOSTIC_TOLERANCES_PS = (1_000_000, 2_000_000, 4_000_000)
BOOTSTRAP_SAMPLES = 10_000
BOOTSTRAP_SEED = 20260714
MIN_VALID_COMPLETED_ROUNDS = 3
PREFLIGHT_MIN_MATCH_RATIO = 0.95


class EvidenceError(ValueError):
    """Raised when trace facts cannot support the requested M2 inference."""


@dataclasses.dataclass(frozen=True)
class CapacityWitness:
    c_healthy_gbps: float
    c_hot_residual_gbps: float
    c_effective_residual_gbps: float
    target_cut_queues: tuple[str, ...]
    hot_cut_queues: tuple[str, ...]
    flow_cut_queues: tuple[tuple[int, tuple[str, ...]], ...] = ()
    healthy_queue_capacities_gbps: tuple[tuple[str, Fraction], ...] = ()
    effective_queue_capacities_gbps: tuple[tuple[str, Fraction], ...] = ()
    flow_queue_edge_count: int = 0
    unique_cut_queue_count: int = 0
    duplicate_entropy_edge_count: int = 0

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
    flow_demands_gbps: tuple[tuple[int, Fraction], ...] = ()


@dataclasses.dataclass(frozen=True)
class RoutingWitness:
    healthy_maxflow_gbps: Fraction
    effective_maxflow_gbps: Fraction
    healthy_feasible: bool
    effective_feasible: bool
    healthy_deficit_gbps: Fraction
    effective_deficit_gbps: Fraction


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


def _portable_trace_prefix(trace_prefix: Path | str) -> str:
    path = Path(trace_prefix)
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.resolve().relative_to(HERE.resolve()).as_posix()
    except ValueError:
        return str(path)


def preflight_base_rtt(bundle, trace_prefix: Path | str) -> dict:
    """Require one stable, positive base RTT across genuine ACK samples."""

    genuine = [ack for ack in bundle.ack if ack["genuine_sample"]]
    positive = [ack["base_rtt_ps"] for ack in genuine if ack["base_rtt_ps"] > 0]
    if not positive:
        raise EvidenceError("preflight has no genuine ACK with positive base_rtt_ps")
    minimum = min(positive)
    matching = sum(ack["base_rtt_ps"] == minimum for ack in genuine)
    count = len(genuine)
    ratio = matching / count
    if ratio < PREFLIGHT_MIN_MATCH_RATIO:
        raise EvidenceError(
            f"preflight base_rtt_ps match ratio {ratio:.6f} is below "
            f"{PREFLIGHT_MIN_MATCH_RATIO:.2f}"
        )
    return {
        "run_id": bundle.run_id,
        "min": minimum,
        "count": count,
        "matching": matching,
        "ratio": ratio,
        "trace_prefix": _portable_trace_prefix(trace_prefix),
    }


def _fingerprint_queues(fingerprint: str) -> tuple[str, ...]:
    if not isinstance(fingerprint, str) or not fingerprint:
        raise EvidenceError("empty queue_fingerprint")
    queues = tuple(fingerprint.split("|"))
    if any(not queue for queue in queues):
        raise EvidenceError(f"malformed queue_fingerprint {fingerprint!r}")
    return queues


def _logical_cut_suffix(queue_name: str) -> Optional[str]:
    if not isinstance(queue_name, str) or not queue_name:
        return None
    matches = tuple(TARGET_CUT_QUEUE.finditer(queue_name))
    if len(matches) != 1 or matches[0].end() != len(queue_name):
        return None
    return matches[0].group(0)


def capacity_witness(
    bundle, start_ps: int, end_ps: int, expected_reduced_capacity_gbps: float,
) -> CapacityWitness:
    """Construct the exact target-pod cut witness for one evaluated interval."""

    if isinstance(start_ps, bool) or isinstance(end_ps, bool) or start_ps < 0 or end_ps <= start_ps:
        raise EvidenceError("capacity interval must have 0 <= start_ps < end_ps")

    link_rates: dict[str, float] = {}
    link_rates_exact: dict[str, Fraction] = {}
    reduced_by_queue: dict[str, bool] = {}
    for row in bundle.linkmap:
        name = row["queue_name"]
        rate = row["rate_gbps"]
        if not _finite(rate) or rate <= 0:
            raise EvidenceError(f"linkmap queue {name!r} has invalid rate_gbps")
        previous = link_rates.get(name)
        if previous is not None and previous != rate:
            raise EvidenceError(f"linkmap queue {name!r} has inconsistent capacities")
        previous_reduced = reduced_by_queue.get(name)
        if previous_reduced is not None and previous_reduced != bool(row["reduced_speed"]):
            raise EvidenceError(f"linkmap queue {name!r} has inconsistent reduced_speed")
        link_rates[name] = float(rate)
        link_rates_exact[name] = Fraction(str(rate))
        reduced_by_queue[name] = bool(row["reduced_speed"])

    paths_by_flow = defaultdict(list)
    for row in bundle.pathmap:
        paths_by_flow[row["flow_id"]].append(row)
    foreground_flow_ids = {row["flow_id"] for row in bundle.epoch}
    if not foreground_flow_ids:
        raise EvidenceError("capacity witness requires foreground epoch flows")
    if set(paths_by_flow) != foreground_flow_ids:
        raise EvidenceError(
            "foreground pathmap flow coverage differs from foreground epoch flows"
        )
    cut_queues = set()
    flow_cut_queues = {}
    raw_flow_queue_edges = 0
    for flow_id, rows in sorted(paths_by_flow.items()):
        entropies = [row["entropy"] for row in rows]
        if len(entropies) != len(PATH_ENTROPIES) or set(entropies) != PATH_ENTROPIES:
            raise EvidenceError(
                f"foreground flow {flow_id} pathmap must contain entropy 0 through 7 "
                "exactly once"
            )
        unresolved = [row for row in rows if row["resolution_status"] != "resolved"]
        if unresolved:
            status = unresolved[0]["resolution_status"]
            raise EvidenceError(
                f"foreground pathmap contains unresolved path row with status {status!r}"
            )
        reachable = []
        for row in rows:
            for name in _fingerprint_queues(row["queue_fingerprint"]):
                if _logical_cut_suffix(name) is None:
                    continue
                if name not in link_rates:
                    raise EvidenceError(f"pathmap cut queue {name!r} is absent from linkmap")
                reachable.append(name)
        unique_reachable = tuple(sorted(set(reachable)))
        flow_cut_queues[flow_id] = unique_reachable
        cut_queues.update(unique_reachable)
        raw_flow_queue_edges += len(reachable)
    if not cut_queues:
        raise EvidenceError("pathmap/linkmap contain no resolved target-pod cut queues")

    hot_queues = {name for name in cut_queues if reduced_by_queue[name]}
    if not hot_queues:
        raise EvidenceError("controlled M2 workload has no reduced target-pod cut queue")
    if any(
        not math.isclose(link_rates[name], expected_reduced_capacity_gbps,
                         rel_tol=0.0, abs_tol=1e-9)
        for name in hot_queues
    ):
        raise EvidenceError(
            "target-pod reduced queue rate differs from configured degradation"
        )
    healthy_queues = cut_queues - hot_queues
    healthy = sum(link_rates[name] for name in sorted(healthy_queues))
    hot_residual = sum(link_rates[name] for name in sorted(hot_queues))
    healthy_capacities = {
        name: link_rates_exact[name] for name in sorted(healthy_queues)
    }
    effective_capacities = dict(healthy_capacities)
    for name in sorted(hot_queues):
        effective_capacities[name] = link_rates_exact[name]
    flow_queue_edge_count = sum(len(queues) for queues in flow_cut_queues.values())
    return CapacityWitness(
        c_healthy_gbps=healthy,
        c_hot_residual_gbps=hot_residual,
        c_effective_residual_gbps=healthy + hot_residual,
        target_cut_queues=tuple(sorted(cut_queues)),
        hot_cut_queues=tuple(sorted(hot_queues)),
        flow_cut_queues=tuple(sorted(flow_cut_queues.items())),
        healthy_queue_capacities_gbps=tuple(healthy_capacities.items()),
        effective_queue_capacities_gbps=tuple(effective_capacities.items()),
        flow_queue_edge_count=flow_queue_edge_count,
        unique_cut_queue_count=len(cut_queues),
        duplicate_entropy_edge_count=raw_flow_queue_edges - flow_queue_edge_count,
    )


def foreground_offered_load(
    bundle, start_ps: int, end_ps: int,
    foreground_flow_ids: Optional[Iterable[int]] = None,
) -> OfferedLoadWitness:
    """Measure foreground injection from bracketing epoch send-counter snapshots."""

    if start_ps < 0 or end_ps <= start_ps:
        return OfferedLoadWitness(False, None, 0, None, None, ("invalid_interval",))
    index = _build_epoch_index(bundle.epoch)
    return _foreground_offered_load_indexed(
        index, start_ps, end_ps, foreground_flow_ids,
    )


def _build_epoch_index(epochs: Iterable[dict]) -> dict[int, tuple[tuple[dict, ...], tuple[int, ...]]]:
    by_flow = defaultdict(list)
    for epoch in epochs:
        by_flow[epoch["flow_id"]].append(epoch)
    index = {}
    for flow_id, rows in by_flow.items():
        ordered = tuple(sorted(rows, key=lambda row: (row["end_ps"], row["event_seq"])))
        index[flow_id] = (ordered, tuple(row["end_ps"] for row in ordered))
    return index


def _common_evidence_end(
    epoch_index: dict[int, tuple[tuple[dict, ...], tuple[int, ...]]],
    coverage_end_ps: int,
) -> int:
    last_observed = []
    for flow_id, (_epochs, end_times) in sorted(epoch_index.items()):
        index = bisect.bisect_right(end_times, coverage_end_ps) - 1
        if index < 0:
            raise EvidenceError(
                f"foreground flow {flow_id} has no epoch snapshot at or before "
                "background coverage end"
            )
        last_observed.append(end_times[index])
    if not last_observed:
        raise EvidenceError("foreground epoch index is empty")
    return min(coverage_end_ps, *last_observed)


def _foreground_offered_load_indexed(
    index: dict[int, tuple[tuple[dict, ...], tuple[int, ...]]],
    start_ps: int,
    end_ps: int,
    foreground_flow_ids: Optional[Iterable[int]] = None,
    latest_snapshot_ps: Optional[int] = None,
) -> OfferedLoadWitness:
    if start_ps < 0 or end_ps <= start_ps:
        return OfferedLoadWitness(False, None, 0, None, None, ("invalid_interval",))
    flow_ids = sorted(index) if foreground_flow_ids is None else sorted(set(foreground_flow_ids))
    failures = []
    rates = []
    flow_demands = []
    elapsed_values = []
    for flow_id in flow_ids:
        epochs, end_times = index.get(flow_id, ((), ()))
        before_index = bisect.bisect_right(end_times, start_ps) - 1
        after_index = bisect.bisect_left(end_times, end_ps)
        if (
            before_index < 0 or after_index >= len(epochs)
            or (
                latest_snapshot_ps is not None
                and epochs[after_index]["end_ps"] > latest_snapshot_ps
            )
        ):
            failures.append(f"flow_{flow_id}:missing_bracketing_epoch")
            continue
        before = epochs[before_index]
        after = epochs[after_index]
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
        flow_demands.append((flow_id, Fraction(sent * 8_000, elapsed)))
    if failures or not flow_ids:
        if not flow_ids:
            failures.append("no_foreground_flows")
        return OfferedLoadWitness(
            False, None, len(flow_ids), min(elapsed_values, default=None),
            max(elapsed_values, default=None), tuple(failures),
        )
    return OfferedLoadWitness(
        True, sum(rates), len(flow_ids), min(elapsed_values), max(elapsed_values), (),
        tuple(flow_demands),
    )


def _bipartite_maxflow(
    flow_demands: tuple[tuple[int, Fraction], ...],
    flow_cut_queues: tuple[tuple[int, tuple[str, ...]], ...],
    queue_capacities: tuple[tuple[str, Fraction], ...],
) -> Fraction:
    """Return exact max flow for the fixed-size foreground-to-cut graph."""

    demands = dict(flow_demands)
    reachability = dict(flow_cut_queues)
    capacities = dict(queue_capacities)
    flow_ids = sorted(demands)
    queue_names = sorted(capacities)
    source = 0
    flow_offset = 1
    queue_offset = flow_offset + len(flow_ids)
    sink = queue_offset + len(queue_names)
    graph = [[] for _ in range(sink + 1)]

    def add_edge(start: int, finish: int, capacity: Fraction) -> None:
        if capacity <= 0:
            return
        graph[start].append([finish, len(graph[finish]), capacity])
        graph[finish].append([start, len(graph[start]) - 1, Fraction(0)])

    flow_nodes = {flow_id: flow_offset + index for index, flow_id in enumerate(flow_ids)}
    queue_nodes = {
        name: queue_offset + index for index, name in enumerate(queue_names)
    }
    for flow_id in flow_ids:
        demand = demands[flow_id]
        add_edge(source, flow_nodes[flow_id], demand)
        for name in sorted(set(reachability.get(flow_id, ()))):
            if name in queue_nodes:
                add_edge(flow_nodes[flow_id], queue_nodes[name], demand)
    for name in queue_names:
        add_edge(queue_nodes[name], sink, capacities[name])

    total = Fraction(0)
    while True:
        parent = [None] * len(graph)
        parent[source] = (-1, -1)
        pending = deque([source])
        while pending and parent[sink] is None:
            node = pending.popleft()
            for edge_index, edge in enumerate(graph[node]):
                neighbor, _reverse_index, residual = edge
                if residual > 0 and parent[neighbor] is None:
                    parent[neighbor] = (node, edge_index)
                    pending.append(neighbor)
                    if neighbor == sink:
                        break
        if parent[sink] is None:
            return total
        augment = None
        node = sink
        while node != source:
            previous, edge_index = parent[node]
            residual = graph[previous][edge_index][2]
            augment = residual if augment is None else min(augment, residual)
            node = previous
        node = sink
        while node != source:
            previous, edge_index = parent[node]
            edge = graph[previous][edge_index]
            reverse_index = edge[1]
            edge[2] -= augment
            graph[node][reverse_index][2] += augment
            node = previous
        total += augment


def _routing_witness(
    capacity: CapacityWitness, offered: OfferedLoadWitness,
) -> RoutingWitness:
    if not offered.valid or len(offered.flow_demands_gbps) != offered.flow_count:
        raise EvidenceError("routing witness requires every foreground flow demand")
    total_demand = sum(
        (demand for _flow_id, demand in offered.flow_demands_gbps), Fraction(0)
    )
    healthy_maxflow = _bipartite_maxflow(
        offered.flow_demands_gbps,
        capacity.flow_cut_queues,
        capacity.healthy_queue_capacities_gbps,
    )
    effective_maxflow = _bipartite_maxflow(
        offered.flow_demands_gbps,
        capacity.flow_cut_queues,
        capacity.effective_queue_capacities_gbps,
    )
    return RoutingWitness(
        healthy_maxflow_gbps=healthy_maxflow,
        effective_maxflow_gbps=effective_maxflow,
        healthy_feasible=healthy_maxflow == total_demand,
        effective_feasible=effective_maxflow == total_demand,
        healthy_deficit_gbps=total_demand - healthy_maxflow,
        effective_deficit_gbps=total_demand - effective_maxflow,
    )


def _classify_capacity_and_routing(
    capacity: CapacityWitness, offered: OfferedLoadWitness,
) -> tuple[str, RoutingWitness, tuple[str, ...]]:
    routing = _routing_witness(capacity, offered)
    demand = sum(
        (rate for _flow_id, rate in offered.flow_demands_gbps), Fraction(0)
    )
    healthy_capacity = sum(
        (rate for _queue, rate in capacity.healthy_queue_capacities_gbps),
        Fraction(0),
    )
    effective_capacity = sum(
        (rate for _queue, rate in capacity.effective_queue_capacities_gbps),
        Fraction(0),
    )
    if demand < healthy_capacity:
        aggregate = "recoverable"
    elif healthy_capacity < demand < effective_capacity:
        aggregate = "persistent"
    else:
        aggregate = "invalid"
    if aggregate == "recoverable":
        if routing.healthy_feasible:
            return "recoverable", routing, ()
        return "invalid", routing, ("healthy_routing_infeasible",)
    if aggregate == "persistent":
        if routing.healthy_feasible:
            return "invalid", routing, ("healthy_routing_feasible",)
        if routing.effective_feasible:
            return "persistent", routing, ()
        return "invalid", routing, ("effective_routing_infeasible",)
    return "invalid", routing, ()


def _background_common_coverage(bundle) -> tuple[int, int, tuple[tuple[int, int, int], ...]]:
    by_background = defaultdict(list)
    for row in bundle.background:
        by_background[row["background_id"]].append(row)
    if not by_background:
        raise EvidenceError("capacity witness requires background start/finish records")
    intervals = []
    for background_id in sorted(by_background):
        records = by_background[background_id]
        starts = [row for row in records if row["operation"] == "start"]
        finishes = [row for row in records if row["operation"] in ("finish", "delivery")]
        if len(starts) != 1 or len(finishes) != 1:
            raise EvidenceError(
                f"background_id {background_id} must have exactly one start and finish/delivery"
            )
        start_ps = starts[0]["time_ps"]
        finish_ps = finishes[0]["time_ps"]
        if finish_ps <= start_ps:
            raise EvidenceError(f"background_id {background_id} has nonpositive delivery interval")
        intervals.append((background_id, start_ps, finish_ps))
    return (
        max(start_ps for _background_id, start_ps, _finish_ps in intervals),
        min(finish_ps for _background_id, _start_ps, finish_ps in intervals),
        tuple(intervals),
    )


def _background_interval_error(
    intervals: Iterable[tuple[int, int, int]], start_ps: int, end_ps: int,
) -> Optional[str]:
    for background_id, background_start, background_finish in intervals:
        if background_start > start_ps or background_finish < end_ps:
            return f"background_id {background_id} does not cover evaluated interval"
    return None


def _observation_bundle(bundle, end_ps: int):
    updates = {}
    for name, time_field in (
        ("ack", "time_ps"),
        ("token", "time_ps"),
        ("epoch", "end_ps"),
        ("background", "time_ps"),
    ):
        if hasattr(bundle, name):
            updates[name] = tuple(
                row for row in getattr(bundle, name) if row[time_field] <= end_ps
            )
    if hasattr(bundle, "events"):
        updates["events"] = tuple(
            event for event in bundle.events
            if event.row["end_ps" if event.kind == "epoch" else "time_ps"] <= end_ps
        )
    if dataclasses.is_dataclass(bundle):
        return dataclasses.replace(bundle, **updates)
    limited = copy.copy(bundle)
    for name, rows in updates.items():
        setattr(limited, name, rows)
    return limited


def _build_genuine_ack_index(
    acknowledgements: Iterable[dict],
) -> dict[int, tuple[tuple[int, ...], tuple[int, ...]]]:
    by_flow = defaultdict(list)
    for ack in acknowledgements:
        if ack["genuine_sample"]:
            by_flow[ack["flow_id"]].append(ack)
    index = {}
    for flow_id, rows in by_flow.items():
        ordered = sorted(rows, key=lambda row: (row["time_ps"], row["event_seq"]))
        times = tuple(row["time_ps"] for row in ordered)
        prefix_sums = [0]
        for row in ordered:
            prefix_sums.append(prefix_sums[-1] + int(float(row["qdelay_ps"])))
        index[flow_id] = (times, tuple(prefix_sums))
    return index


def _indexed_mean_qdelay(
    index: dict[int, tuple[tuple[int, ...], tuple[int, ...]]],
    flow_id: int,
    start_ps: int,
    end_ps: int,
) -> Optional[float]:
    times, prefix_sums = index.get(flow_id, ((), (0,)))
    start_index = bisect.bisect_left(times, start_ps)
    end_index = bisect.bisect_right(times, end_ps)
    count = end_index - start_index
    if count == 0:
        return None
    total = prefix_sums[end_index] - prefix_sums[start_index]
    return float(total) / count


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
        "degraded_links": int(config["degraded_links"]),
        "degraded_capacity_gbps": float(config["degraded_capacity_gbps"]),
        "seed": int(config["seed"]),
    }
    if normalized["scenario"] not in ("", "recoverable", "persistent"):
        raise ValueError("scenario must be empty, recoverable, or persistent")
    if (
        not normalized["cell_id"] or normalized["foreground_flows"] <= 0
        or normalized["degraded_links"] <= 0
        or not 0 < normalized["degraded_capacity_gbps"] < 100
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
    foreground_ids = sorted({row["flow_id"] for row in bundle.epoch})
    if len(foreground_ids) != metadata["foreground_flows"]:
        raise EvidenceError(
            f"trace has {len(foreground_ids)} foreground epoch flows; "
            f"config requires {metadata['foreground_flows']}"
        )
    epoch_index = _build_epoch_index(bundle.epoch)
    first_epoch_start_ps = min(
        epoch["start_ps"]
        for epochs, _end_times in epoch_index.values()
        for epoch in epochs
    )
    shadow_injection_ps = max(first_epoch_start_ps, CONTROLLED_WARMUP_PS)
    capacity_base = None
    capacity_failure = None
    coverage_start = 0
    coverage_end = min(end_times[-1] for _epochs, end_times in epoch_index.values())
    evidence_end = coverage_end
    try:
        capacity_base = capacity_witness(
            bundle, coverage_start, coverage_end,
            metadata["degraded_capacity_gbps"],
        )
    except EvidenceError as exc:
        capacity_failure = str(exc)
    replay_bundle = (
        _observation_bundle(bundle, evidence_end)
    )
    rounds = replay_shadow(replay_bundle, injection_time_ps=shadow_injection_ps)
    epochs_by_flow = {
        flow_id: epochs for flow_id, (epochs, _end_times) in epoch_index.items()
    }
    epochs_by_event = {
        flow_id: {epoch["event_seq"]: epoch for epoch in epochs}
        for flow_id, epochs in epochs_by_flow.items()
    }
    genuine_ack_index = _build_genuine_ack_index(bundle.ack)

    round_rows = []
    epoch_rows = []
    low_floor_high_spread_epochs = 0
    for shadow in rounds:
        if (
            coverage_start is not None and evidence_end is not None
            and (shadow.start_ps < coverage_start or shadow.start_ps >= evidence_end)
        ):
            continue
        flow_epochs, flow_end_times = epoch_index[shadow.flow_id]
        start_epoch = epochs_by_event[shadow.flow_id].get(shadow.start_event_seq)
        if start_epoch is None:
            raise EvidenceError(f"round start epoch {shadow.start_event_seq} is absent")
        if shadow.complete:
            natural_interval_end = shadow.end_ps
        elif shadow.censor_reason == "hold_exit_before_slot_completion":
            natural_interval_end = next(
                (
                    epoch["end_ps"] for epoch in flow_epochs
                    if epoch["end_ps"] > shadow.start_ps
                    and epoch["actual_region"] != "hold"
                ),
                flow_epochs[-1]["end_ps"],
            )
        else:
            natural_interval_end = flow_epochs[-1]["end_ps"]
        observation_end_censored = bool(
            evidence_end is not None and natural_interval_end > evidence_end
        )
        interval_end = evidence_end if observation_end_censored else natural_interval_end
        round_complete = bool(shadow.complete and not observation_end_censored)
        round_censored = bool(shadow.censored or observation_end_censored)
        censor_reason = (
            "observation_end_right_censored"
            if observation_end_censored else shadow.censor_reason
        )
        interval_start_index = bisect.bisect_right(flow_end_times, shadow.start_ps)
        interval_end_index = bisect.bisect_right(flow_end_times, interval_end)
        interval_epochs = flow_epochs[interval_start_index:interval_end_index]
        failures = []
        offered = _foreground_offered_load_indexed(
            epoch_index, shadow.start_ps, interval_end, foreground_ids,
        )
        capacity = capacity_base
        if shadow.start_ps < 0 or interval_end <= shadow.start_ps:
            capacity = None
            failures.append(
                "capacity_witness_invalid:capacity interval must have "
                "0 <= start_ps < end_ps"
            )
        elif capacity_failure is not None:
            capacity = None
            failures.append(f"capacity_witness_invalid:{capacity_failure}")
        if not offered.valid:
            failures.extend(offered.failed_predicates)
        routing = None
        if capacity is not None and offered.valid and offered.rate_gbps is not None:
            classification, routing, routing_failures = _classify_capacity_and_routing(
                capacity, offered,
            )
            failures.extend(routing_failures)
        else:
            classification = "invalid"
        if metadata["scenario"] and classification != metadata["scenario"]:
            failures.append("capacity_relation_mismatch")
        elif classification == "invalid":
            failures.append("capacity_classification_invalid")
        if not round_complete:
            failures.append("round_censored")

        low_floor_count = sum(row["raw_floor_ps"] < T_CC_PS for row in interval_epochs)
        high_spread_count = sum(row["raw_spread_ps"] >= T_CC_PS for row in interval_epochs)
        low_floor_high_spread_epochs += sum(
            row["raw_floor_ps"] < T_CC_PS and row["raw_spread_ps"] >= T_CC_PS
            for row in interval_epochs
        )
        hold_epochs = [row for row in interval_epochs if row["actual_region"] == "hold"]
        hold_duration = sum(row["end_ps"] - row["start_ps"] for row in hold_epochs)
        mean_qdelay = _indexed_mean_qdelay(
            genuine_ack_index, shadow.flow_id, shadow.start_ps, interval_end,
        )
        start_cwnd = start_epoch["cwnd_bytes"]
        row = {
            **metadata, "run_id": bundle.run_id, "flow_id": shadow.flow_id,
            "round_index": shadow.round_index, "start_event_seq": shadow.start_event_seq,
            "end_event_seq": shadow.end_event_seq if round_complete else "",
            "start_ps": shadow.start_ps, "end_ps": shadow.end_ps if round_complete else "",
            "duration_ps": shadow.end_ps - shadow.start_ps if round_complete else "",
            "complete": int(round_complete), "censored": int(round_censored),
            "censor_reason": censor_reason or "",
            "F_ps": start_epoch["raw_floor_ps"], "S_ps": start_epoch["raw_spread_ps"],
            "S_ref_ps": shadow.s_ref_ps,
            "S_end_ps": shadow.s_end_ps if round_complete else "",
            "delta_S": shadow.delta_s if round_complete else "",
            "literal_no_progress": int(shadow.no_progress) if round_complete else "",
            "no_progress_1us": (
                int(shadow.s_ref_ps - shadow.s_end_ps <= DIAGNOSTIC_TOLERANCES_PS[0])
                if round_complete else ""
            ),
            "no_progress_2us": (
                int(shadow.s_ref_ps - shadow.s_end_ps <= DIAGNOSTIC_TOLERANCES_PS[1])
                if round_complete else ""
            ),
            "no_progress_4us": (
                int(shadow.s_ref_ps - shadow.s_end_ps <= DIAGNOSTIC_TOLERANCES_PS[2])
                if round_complete else ""
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
            "mean_qdelay_ps": mean_qdelay if mean_qdelay is not None else "",
            "offered_load_valid": int(offered.valid),
            "L_foreground_gbps": offered.rate_gbps if offered.rate_gbps is not None else "",
            "offered_elapsed_ps_min": offered.elapsed_ps_min or "",
            "offered_elapsed_ps_max": offered.elapsed_ps_max or "",
            "capacity_valid": int(capacity is not None),
            "capacity_classification": classification,
            "C_healthy_gbps": capacity.c_healthy_gbps if capacity else "",
            "C_reduced_gbps": capacity.c_hot_residual_gbps if capacity else "",
            "C_effective_residual_gbps": capacity.c_effective_residual_gbps if capacity else "",
            "healthy_maxflow_gbps": (
                float(routing.healthy_maxflow_gbps) if routing else ""
            ),
            "effective_maxflow_gbps": (
                float(routing.effective_maxflow_gbps) if routing else ""
            ),
            "healthy_feasible": int(routing.healthy_feasible) if routing else "",
            "effective_feasible": int(routing.effective_feasible) if routing else "",
            "healthy_deficit_gbps": (
                float(routing.healthy_deficit_gbps) if routing else ""
            ),
            "effective_deficit_gbps": (
                float(routing.effective_deficit_gbps) if routing else ""
            ),
            "flow_queue_edge_count": capacity.flow_queue_edge_count if capacity else "",
            "unique_cut_queue_count": capacity.unique_cut_queue_count if capacity else "",
            "duplicate_entropy_edge_count": (
                capacity.duplicate_entropy_edge_count if capacity else ""
            ),
            "capacity_margin_gbps": (
                capacity.c_healthy_gbps - offered.rate_gbps
                if classification == "recoverable" else
                min(
                    offered.rate_gbps - capacity.c_healthy_gbps,
                    capacity.c_effective_residual_gbps - offered.rate_gbps,
                ) if classification == "persistent" else ""
            ),
            "valid_round": int(round_complete and not failures),
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
                    round_complete and epoch["event_seq"] == shadow.end_event_seq
                ),
            })

    _apply_coarse_scenario(metadata, round_rows, epoch_rows)

    complete = [row for row in round_rows if _truth(row, "complete")]
    valid = [row for row in round_rows if _truth(row, "valid_round")]
    valid_delta = [float(row["delta_S"]) for row in valid]
    literal = [int(row["literal_no_progress"]) for row in valid]
    total_round_epochs = sum(int(row["round_epoch_count"]) for row in round_rows)
    summary = {
        **metadata, "run_id": bundle.run_id,
        "shadow_injection_ps": shadow_injection_ps,
        "controlled_warmup_ps": CONTROLLED_WARMUP_PS,
        "episode_count": len(round_rows),
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
        "L_foreground_gbps": _mean(row["L_foreground_gbps"] for row in valid) if valid else "",
        "C_healthy_gbps": _mean(row["C_healthy_gbps"] for row in valid) if valid else "",
        "C_reduced_gbps": _mean(
            row["C_reduced_gbps"] for row in valid
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
    evidence = [_integer(row, "valid_completed_rounds") or 0 for row in rows]
    if scenario == "recoverable":
        return (
            -min(evidence), -min(margins), -min(capacities),
            float(rows[0]["degraded_capacity_gbps"]), str(rows[0]["cell_id"]),
        )
    return (
        -min(margins), -min(capacities),
        float(rows[0]["degraded_capacity_gbps"]), str(rows[0]["cell_id"]),
    )


def _atomic_csv(
    path: Path | str,
    fields: Iterable[str],
    rows: Iterable[dict],
    *,
    lineterminator: str = "\n",
) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", newline="", encoding="ascii", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            writer_options = {
                "fieldnames": list(fields),
                "extrasaction": "ignore",
                "lineterminator": lineterminator,
            }
            writer = csv.DictWriter(stream, **writer_options)
            writer.writeheader()
            writer.writerows(rows)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _atomic_text(path: Path | str, content: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="ascii", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_preflight_outputs(
    report: dict, base_rtt_output: Path | str, preflight_manifest: Path | str,
) -> None:
    """Atomically publish the validated base RTT and its evidence manifest."""

    if Path(base_rtt_output).resolve(strict=False) == Path(preflight_manifest).resolve(
        strict=False
    ):
        raise ValueError("base RTT output and preflight manifest must differ")
    _atomic_text(base_rtt_output, f"{report['min']}\n")
    payload = json.dumps(
        report, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False,
    ) + "\n"
    _atomic_text(preflight_manifest, payload)


def _selection_evidence_adequate(row: dict) -> bool:
    return bool(
        (_integer(row, "valid_completed_rounds") or 0) >= MIN_VALID_COMPLETED_ROUNDS
        and (_number(row, "low_floor_high_spread_occupancy") or 0) > 0
    )


def select_confirmation(summary_rows: Iterable[dict], output_path: Path | str) -> list[dict]:
    """Select one seed-101 coarse cell per predeclared scenario."""

    rows = list(summary_rows)
    output = []
    for scenario in ("recoverable", "persistent"):
        eligible = [
            row for row in rows
            if row.get("scenario") == scenario and _integer(row, "seed") == 101
            and _truth(row, "all_valid_rounds_match_scenario")
            and _selection_evidence_adequate(row)
        ]
        for selected in sorted(eligible, key=lambda row: _candidate_rank([row], scenario))[:1]:
            for seed in CONFIRMATION_SEEDS:
                output.append({field: seed if field == "seed" else selected[field] for field in CONFIG_FIELDS})
    output.sort(key=lambda row: (row["scenario"], row["cell_id"], row["seed"]))
    _atomic_csv(output_path, CONFIG_FIELDS, output, lineterminator="\n")
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
    _atomic_csv(formal_path, CONFIG_FIELDS, formal_rows, lineterminator="\n")
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
        summary_cells = {
            str(row["cell_id"]) for row in scenario_summaries if row.get("cell_id")
        }
        round_cells = {
            str(row["cell_id"]) for row in scenario_rounds if row.get("cell_id")
        }
        if (
            len(summary_cells) != 1 or len(round_cells) > 1
            or bool(round_cells and round_cells != summary_cells)
        ):
            failures.append("formal_mixed_cell_ids_within_scenario")
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
    source = manifest.get("analysis_config")
    if not isinstance(source, dict):
        raise ValueError(f"manifest {path} is missing analysis_config")
    if set(source) != set(CONFIG_FIELDS):
        raise ValueError(f"manifest {path} analysis_config has wrong fields")
    metadata = _config(source)
    if phase in ("confirmation", "formal") and not metadata["scenario"]:
        raise ValueError(f"manifest {path} must lock scenario for phase {phase}")
    if manifest.get("seed") != metadata["seed"]:
        raise ValueError(f"manifest {path} seed differs from M2 config seed")
    prefix = path.parent / manifest["run_id"]
    return metadata, prefix


def _read_formal_config(path: Path | str) -> tuple[dict, ...]:
    path = Path(path)
    with path.open(newline="", encoding="ascii") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != CONFIG_FIELDS:
            raise ValueError(f"formal config {path} has wrong header")
        raw_rows = list(reader)
    if len(raw_rows) != 10:
        raise ValueError(f"formal config {path} must contain exactly 10 rows")

    rows = []
    for index, raw in enumerate(raw_rows, start=2):
        if set(raw) != set(CONFIG_FIELDS) or any(
            raw[field] is None for field in CONFIG_FIELDS
        ):
            raise ValueError(f"formal config {path} row {index} is malformed")
        rows.append(_config(raw))

    for scenario in ("recoverable", "persistent"):
        scenario_rows = [row for row in rows if row["scenario"] == scenario]
        seeds = {row["seed"] for row in scenario_rows}
        if len(scenario_rows) != len(FORMAL_SEEDS) or seeds != set(FORMAL_SEEDS):
            raise ValueError(
                f"formal config {path} scenario {scenario} must contain seeds 13 through 17"
            )
        locked_cells = {
            tuple(row[field] for field in CONFIG_FIELDS if field != "seed")
            for row in scenario_rows
        }
        if len(locked_cells) != 1:
            raise ValueError(
                f"formal config {path} scenario {scenario} must lock one stable cell"
            )
    if len({row["cell_id"] for row in rows}) != 2:
        raise ValueError(f"formal config {path} must lock one distinct cell per scenario")
    return tuple(rows)


def _read_locked_config_rows(path: Path | str, label: str) -> tuple[dict, ...]:
    path = Path(path)
    with path.open(newline="", encoding="ascii") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != CONFIG_FIELDS:
            raise ValueError(f"{label} config {path} has wrong header")
        raw_rows = list(reader)
    rows = []
    for index, raw in enumerate(raw_rows, start=2):
        if set(raw) != set(CONFIG_FIELDS) or any(
            raw[field] is None for field in CONFIG_FIELDS
        ):
            raise ValueError(f"{label} config {path} row {index} is malformed")
        rows.append(_config(raw))
    return tuple(rows)


def _read_coarse_config(path: Path | str) -> tuple[dict, ...]:
    rows = _read_locked_config_rows(path, "coarse")
    if len(rows) != 6:
        raise ValueError(f"coarse config {path} must contain exactly 6 rows")
    if any(row["scenario"] or row["seed"] != COARSE_SEEDS[0] for row in rows):
        raise ValueError("coarse config must use empty scenario and seed 101")
    if len({row["cell_id"] for row in rows}) != len(rows):
        raise ValueError("coarse config must contain 6 unique cells")
    return rows


def _read_confirmation_config(path: Path | str) -> tuple[dict, ...]:
    rows = _read_locked_config_rows(path, "confirmation")
    if not 1 <= len(rows) <= 6:
        raise ValueError("confirmation config must contain between 1 and 6 rows")
    by_cell = defaultdict(list)
    for row in rows:
        if row["scenario"] not in ("recoverable", "persistent"):
            raise ValueError("confirmation config must lock every scenario")
        by_cell[row["cell_id"]].append(row)
    for cell_id, cell_rows in sorted(by_cell.items()):
        if (
            len(cell_rows) != len(CONFIRMATION_SEEDS)
            or {row["seed"] for row in cell_rows} != set(CONFIRMATION_SEEDS)
        ):
            raise ValueError(
                f"confirmation config cell {cell_id} must contain seeds 101 through 103"
            )
        locked = {
            tuple(row[field] for field in CONFIG_FIELDS if field != "seed")
            for row in cell_rows
        }
        if len(locked) != 1:
            raise ValueError(
                f"confirmation config cell {cell_id} has inconsistent locked fields"
            )
    return rows


def _validate_locked_manifests(
    records: list[tuple[Path, dict, Path]], locked_rows: Iterable[dict], phase: str,
) -> None:
    def signature(row: dict) -> tuple:
        return tuple(row[field] for field in CONFIG_FIELDS)

    locked_rows = tuple(locked_rows)
    locked = {signature(row): row for row in locked_rows}
    if len(locked) != len(locked_rows):
        raise ValueError(f"current {phase} config contains duplicate locked rows")
    if len(records) != len(locked):
        raise ValueError(
            f"{phase} manifests must exactly cover current {phase} config: "
            f"expected {len(locked)}, found {len(records)}"
        )
    seen = set()
    for manifest_path, metadata, _prefix in records:
        key = signature(metadata)
        if key in seen:
            raise ValueError(f"{phase} manifest {manifest_path} duplicates a locked row")
        if key not in locked:
            raise ValueError(
                f"{phase} manifest {manifest_path} differs from current {phase} config"
            )
        seen.add(key)
    if seen != set(locked):
        raise ValueError(f"{phase} manifests do not exactly cover current {phase} config")


def _validate_formal_manifests(
    records: list[tuple[Path, dict, Path]], locked_rows: Iterable[dict],
) -> None:
    locked = {(row["scenario"], row["seed"]): row for row in locked_rows}
    if len(records) != len(locked):
        raise ValueError("formal manifests must contain exactly the 10 locked runs")
    seen = set()
    for manifest_path, metadata, _prefix in records:
        key = (metadata["scenario"], metadata["seed"])
        if key in seen:
            raise ValueError(f"formal manifest {manifest_path} duplicates locked row {key}")
        if key not in locked:
            raise ValueError(f"formal manifest {manifest_path} is not a locked formal row")
        if metadata != locked[key]:
            raise ValueError(
                f"formal manifest {manifest_path} differs from current formal config"
            )
        seen.add(key)
    if seen != set(locked):
        raise ValueError("formal manifests do not exactly cover current formal config")


def analyze_phase(phase: str, phase_dir: Path) -> tuple[list[dict], list[dict], list[dict]]:
    if phase not in ("smoke", "coarse", "confirmation", "formal"):
        raise ValueError(f"unsupported M2 phase {phase!r}")
    manifests = sorted(phase_dir.glob("*.manifest.json"))
    if not manifests:
        raise ValueError(f"no manifests in {phase_dir}")
    if phase == "coarse":
        locked_rows = _read_coarse_config(CALIBRATION_CONFIG)
    elif phase == "confirmation":
        locked_rows = _read_confirmation_config(CONFIRMATION_SELECTION)
    elif phase == "formal":
        locked_rows = _read_formal_config(FORMAL_CONFIG)
    else:
        locked_rows = ()
    records = [
        (manifest_path, *_read_manifest(manifest_path, phase))
        for manifest_path in manifests
    ]
    if phase == "formal":
        _validate_formal_manifests(records, locked_rows)
    elif phase in ("coarse", "confirmation"):
        _validate_locked_manifests(records, locked_rows, phase)
    summaries, rounds, epochs = [], [], []
    for _manifest_path, metadata, prefix in records:
        analysis = analyze_bundle(load_trace_compact(prefix), metadata)
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
    mode.add_argument("--smoke", action="store_true")
    mode.add_argument("--coarse", action="store_true")
    mode.add_argument("--confirmation", action="store_true")
    mode.add_argument("--formal", action="store_true")
    mode.add_argument("--preflight-prefix", type=Path)
    parser.add_argument("--select-confirmation", action="store_true")
    parser.add_argument("--select-formal", action="store_true")
    parser.add_argument("--base-rtt-output", type=Path)
    parser.add_argument("--preflight-manifest", type=Path)
    args = parser.parse_args(argv)
    if args.preflight_prefix is not None:
        if args.base_rtt_output is None or args.preflight_manifest is None:
            parser.error(
                "--preflight-prefix requires --base-rtt-output and --preflight-manifest"
            )
        if args.select_confirmation or args.select_formal:
            parser.error("selection options cannot be used with --preflight-prefix")
        try:
            report = preflight_base_rtt(
                load_trace_compact(args.preflight_prefix), args.preflight_prefix,
            )
            write_preflight_outputs(
                report, args.base_rtt_output, args.preflight_manifest,
            )
            return 0
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    if args.base_rtt_output is not None or args.preflight_manifest is not None:
        parser.error(
            "--base-rtt-output and --preflight-manifest require --preflight-prefix"
        )
    phase = (
        "smoke" if args.smoke else "coarse" if args.coarse
        else "confirmation" if args.confirmation else "formal"
    )
    if args.select_confirmation and phase != "coarse":
        parser.error("--select-confirmation requires --coarse")
    if args.select_formal and phase != "confirmation":
        parser.error("--select-formal requires --confirmation")
    try:
        summaries, _rounds, _epochs = analyze_phase(phase, DATA_ROOT / phase)
        if args.select_confirmation:
            selected = select_confirmation(
                summaries, DATA_ROOT / phase / "confirmation_selection.csv"
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
