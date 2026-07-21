#!/usr/bin/env python3
"""Produce read-only per-refresh M3 traffic outcome evidence."""

from __future__ import annotations

import bisect
import csv
import statistics
from collections import defaultdict
from pathlib import Path

from htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.analyze_distribution import (
    EXPERIMENT,
    WARMUP_PS,
    _load_attribution,
    _load_coordination,
    _load_manifest,
    _ratio,
    _replacement_chain_complete,
    _stream_ack_aggregates,
    _stream_candidate_admissions,
    _stream_rows,
    _trace_prefix,
    _validate_admission_provenance,
    _validate_locked_manifest_set,
)


OUTCOME_FIELDS = (
    "run_id", "scenario", "mode", "seed", "flow_id", "round_id", "terminal_time_ps",
    "base_rtt_ps", "window_width_ps", "pre_start_ps", "pre_end_ps", "post1_start_ps",
    "post1_end_ps", "post2_start_ps", "post2_end_ps", "pre_complete", "post1_complete",
    "post2_complete", "pre_healthy_acked_bytes", "pre_throttled_acked_bytes",
    "pre_throttled_ratio", "post1_healthy_acked_bytes", "post1_throttled_acked_bytes",
    "post1_throttled_ratio", "post2_healthy_acked_bytes", "post2_throttled_acked_bytes",
    "post2_throttled_ratio", "pre_to_post1_throttled_ratio_change",
    "pre_to_post2_throttled_ratio_change", "sustained_decrease",
)
SUMMARY_FIELDS = (
    "scenario", "seed", "complete_outcome_count", "sustained_decrease_count",
    "sustained_decrease_fraction", "mean_pre_throttled_ratio",
    "mean_post1_throttled_ratio", "mean_post2_throttled_ratio",
    "mean_pre_to_post1_throttled_ratio_change", "mean_pre_to_post2_throttled_ratio_change",
)


def _stream_outcome_windows(prefix: Path, run_id: str, attribution, specs: list[dict],
                            base_rtt_ps: int) -> None:
    """Accumulate exactly three half-open windows for each terminal in one ACK pass."""
    if not specs:
        return
    width_ps = 4 * base_rtt_ps
    ordered_specs = sorted(specs, key=lambda spec: spec["terminal"]["time_ps"])
    terminal_times = [spec["terminal"]["time_ps"] for spec in ordered_specs]
    for spec in ordered_specs:
        spec["outcome_window_counts"] = [[0, 0], [0, 0], [0, 0]]
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
            bisect.bisect_right(terminal_times, time_ps + width_ps),
        ):
            ordered_specs[index]["outcome_window_counts"][0][value_index] += byte_count
        for index in range(
            bisect.bisect_right(terminal_times, time_ps - width_ps),
            bisect.bisect_right(terminal_times, time_ps),
        ):
            ordered_specs[index]["outcome_window_counts"][1][value_index] += byte_count
        for index in range(
            bisect.bisect_right(terminal_times, time_ps - 2 * width_ps),
            bisect.bisect_right(terminal_times, time_ps - width_ps),
        ):
            ordered_specs[index]["outcome_window_counts"][2][value_index] += byte_count


def _window_values(counts: list[int], complete: bool) -> tuple[int | str, int | str, float | str]:
    if not complete:
        return "", "", ""
    healthy_bytes, throttled_bytes = counts
    return healthy_bytes, throttled_bytes, _ratio(healthy_bytes, throttled_bytes)


def _refresh_outcomes(*, specs: list[dict], run_id: str, scenario: str, mode: str, seed: int,
                      base_rtt_ps: int, last_ack_ps: int) -> list[dict]:
    width_ps = 4 * base_rtt_ps
    rows = []
    for spec in specs:
        terminal = spec["terminal"]
        terminal_time_ps = terminal["time_ps"]
        windows = (
            (terminal_time_ps - width_ps, terminal_time_ps),
            (terminal_time_ps, terminal_time_ps + width_ps),
            (terminal_time_ps + width_ps, terminal_time_ps + 2 * width_ps),
        )
        complete = tuple(start_ps >= WARMUP_PS and end_ps <= last_ack_ps for start_ps, end_ps in windows)
        values = [
            _window_values(counts, is_complete)
            for counts, is_complete in zip(spec["outcome_window_counts"], complete)
        ]
        pre_ratio, post1_ratio, post2_ratio = (value[2] for value in values)
        pre_to_post1_change = (
            post1_ratio - pre_ratio if pre_ratio != "" and post1_ratio != "" else ""
        )
        pre_to_post2_change = (
            post2_ratio - pre_ratio if pre_ratio != "" and post2_ratio != "" else ""
        )
        sustained_decrease = ""
        if all(complete):
            sustained_decrease = int(
                pre_ratio != ""
                and post1_ratio != ""
                and post2_ratio != ""
                and post1_ratio < pre_ratio
                and post2_ratio < pre_ratio
            )
        rows.append({
            "run_id": run_id,
            "scenario": scenario,
            "mode": mode,
            "seed": seed,
            "flow_id": terminal["flow_id"],
            "round_id": terminal["round_id"],
            "terminal_time_ps": terminal_time_ps,
            "base_rtt_ps": base_rtt_ps,
            "window_width_ps": width_ps,
            "pre_start_ps": windows[0][0],
            "pre_end_ps": windows[0][1],
            "post1_start_ps": windows[1][0],
            "post1_end_ps": windows[1][1],
            "post2_start_ps": windows[2][0],
            "post2_end_ps": windows[2][1],
            "pre_complete": int(complete[0]),
            "post1_complete": int(complete[1]),
            "post2_complete": int(complete[2]),
            "pre_healthy_acked_bytes": values[0][0],
            "pre_throttled_acked_bytes": values[0][1],
            "pre_throttled_ratio": pre_ratio,
            "post1_healthy_acked_bytes": values[1][0],
            "post1_throttled_acked_bytes": values[1][1],
            "post1_throttled_ratio": post1_ratio,
            "post2_healthy_acked_bytes": values[2][0],
            "post2_throttled_acked_bytes": values[2][1],
            "post2_throttled_ratio": post2_ratio,
            "pre_to_post1_throttled_ratio_change": pre_to_post1_change,
            "pre_to_post2_throttled_ratio_change": pre_to_post2_change,
            "sustained_decrease": sustained_decrease,
        })
    return rows


def _mean(rows: list[dict], field: str) -> float | str:
    values = [float(row[field]) for row in rows if row[field] != ""]
    return statistics.fmean(values) if values else ""


def _summaries(rows: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for row in rows:
        if row["pre_complete"] == 1 and row["post1_complete"] == 1 and row["post2_complete"] == 1:
            groups[(row["scenario"], row["seed"])].append(row)
    summaries = []
    for (scenario, seed), complete_rows in sorted(groups.items()):
        sustained_count = sum(row["sustained_decrease"] == 1 for row in complete_rows)
        summaries.append({
            "scenario": scenario,
            "seed": seed,
            "complete_outcome_count": len(complete_rows),
            "sustained_decrease_count": sustained_count,
            "sustained_decrease_fraction": sustained_count / len(complete_rows),
            "mean_pre_throttled_ratio": _mean(complete_rows, "pre_throttled_ratio"),
            "mean_post1_throttled_ratio": _mean(complete_rows, "post1_throttled_ratio"),
            "mean_post2_throttled_ratio": _mean(complete_rows, "post2_throttled_ratio"),
            "mean_pre_to_post1_throttled_ratio_change": _mean(
                complete_rows, "pre_to_post1_throttled_ratio_change"
            ),
            "mean_pre_to_post2_throttled_ratio_change": _mean(
                complete_rows, "pre_to_post2_throttled_ratio_change"
            ),
        })
    return summaries


def _analyze_bundle(manifest_path: Path) -> list[dict]:
    run_id, scenario, seed, mode = _load_manifest(manifest_path)
    prefix = _trace_prefix(manifest_path)
    attribution = _load_attribution(prefix, run_id)
    specs = _load_coordination(prefix, run_id, mode)
    admissions_by_slot, admissions_by_ack = _stream_candidate_admissions(prefix, run_id, specs)
    base_rtt_ps, last_ack_ps, _counts, selected_acks = _stream_ack_aggregates(
        prefix, run_id, attribution, admissions_by_ack, seed, EXPERIMENT
    )
    _validate_admission_provenance(prefix, admissions_by_ack, selected_acks)
    complete_specs = []
    for spec in specs:
        if not _replacement_chain_complete(spec, admissions_by_slot, selected_acks):
            terminal = spec["terminal"]
            raise ValueError(
                f"{run_id}: recycle terminal event {terminal['event_seq']} "
                "has incomplete replacement evidence"
            )
        complete_specs.append(spec)
    _stream_outcome_windows(prefix, run_id, attribution, complete_specs, base_rtt_ps)
    return _refresh_outcomes(
        specs=complete_specs,
        run_id=run_id,
        scenario=scenario,
        mode=mode,
        seed=seed,
        base_rtt_ps=base_rtt_ps,
        last_ack_ps=last_ack_ps,
    )


def _write_csv(path: Path, rows: list[dict], fields: tuple[str, ...]) -> None:
    with path.open("w", newline="", encoding="ascii") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def analyze_refresh_outcomes(data_root: Path | str, output_root: Path | str) -> dict[str, list[dict]]:
    """Write chain-backed three-window recycle outcomes and per-seed summaries."""
    data_root = Path(data_root)
    output_root = Path(output_root)
    manifests = sorted(
        path for path in data_root.rglob("*.manifest.json") if output_root not in path.parents
    )
    if not manifests:
        raise ValueError(f"no distribution manifests below {data_root}")
    _validate_locked_manifest_set(manifests)
    outcomes = []
    for manifest_path in manifests:
        outcomes.extend(_analyze_bundle(manifest_path))
    outcomes.sort(
        key=lambda row: (
            row["scenario"], row["seed"], row["terminal_time_ps"], row["flow_id"], row["round_id"]
        )
    )
    summaries = _summaries(outcomes)
    output_root.mkdir(parents=True, exist_ok=True)
    _write_csv(output_root / "refresh_outcomes.csv", outcomes, OUTCOME_FIELDS)
    _write_csv(output_root / "refresh_outcome_summary.csv", summaries, SUMMARY_FIELDS)
    return {"refresh_outcomes": outcomes, "refresh_outcome_summary": summaries}


def main() -> int:
    here = Path(__file__).resolve().parent
    data_root = here / "data" / "distribution"
    analyze_refresh_outcomes(data_root, data_root / "aggregate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
