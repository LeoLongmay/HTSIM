#!/usr/bin/env python3
"""Validate and aggregate the fixed 24-case M4 finite-flow experiment."""

from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Sequence


HERE = Path(__file__).resolve().parent
if __package__ in (None, ""):
    sys.path.insert(0, str(HERE.parents[4]))
    from htsim.sim.datacenter.add_motivation.expM4_performance_ablation import run
else:
    from . import run

sys.path.insert(0, str(HERE.parents[1] / "prism_eval" / "common"))
from metrics import aggregate_goodput_gbps, fct_stats  # noqa: E402


PER_SEED_FIELDS = (
    "arm", "scenario", "seed", "avg_fct_us", "p99_fct_us", "goodput_gbps",
    "completion_rate", "completed", "total_started",
)
SUMMARY_FIELDS = (
    "arm", "scenario", "n_seeds", "mean_avg_fct_us", "mean_p99_fct_us",
    "mean_goodput_gbps", "mean_completion_rate", "min_avg_fct_us", "max_avg_fct_us",
    "min_p99_fct_us", "max_p99_fct_us", "min_goodput_gbps", "max_goodput_gbps",
)


def _number(value: float) -> str:
    return format(value, ".12g")


def _expected_manifest_paths(data_root: Path) -> dict[tuple[str, str, int], Path]:
    expected = {
        (case.arm, case.scenario, case.seed): data_root / f"formal_{case.arm}_{case.scenario}_s{case.seed}.manifest.json"
        for case in run.cases_for_phase("formal")
    }
    actual = set(data_root.glob("*.manifest.json"))
    if actual != set(expected.values()):
        missing = sorted(str(path.name) for path in set(expected.values()) - actual)
        unexpected = sorted(str(path.name) for path in actual - set(expected.values()))
        raise ValueError(f"formal data must contain exactly 24 manifests; missing={missing}, unexpected={unexpected}")
    return expected


def _load_case(manifest_path: Path, data_root: Path) -> dict:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid manifest: {manifest_path}") from exc
    try:
        case = run.Case(manifest["arm"], manifest["scenario"], int(manifest["seed"]))
        run._validate_case(case)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid M4 manifest identity: {manifest_path}") from exc
    run_id = f"formal_{case.arm}_{case.scenario}_s{case.seed}"
    scenario = run.SCENARIOS[case.scenario]
    workload = data_root / "workloads" / f"{case.scenario}_s{case.seed}.cm"
    if not workload.is_file() or workload.read_text(encoding="ascii") != run.workload_text(
        foreground_flows=scenario.foreground_flows, seed=case.seed
    ):
        raise ValueError(f"invalid workload for {run_id}")
    expected = run._expected_manifest(
        phase="formal",
        case=case,
        run_id=run_id,
        workload=workload,
        workload_hash=run._sha256(workload),
        dat_path=data_root / f"{run_id}.dat",
    )
    if manifest.get("scenario_config") != dataclasses.asdict(scenario):
        raise ValueError(f"invalid scenario_config for {run_id}")
    if manifest.get("flow_size_bytes") != run.FLOW_SIZE_BYTES or manifest.get("end_ms") != run.END_MS:
        raise ValueError(f"invalid finite-flow configuration for {run_id}")
    flow_path = data_root / f"{run_id}.flow.txt"
    stdout_path = data_root / f"{run_id}.stdout"
    run._reuse_or_reject(
        manifest_path=manifest_path,
        flow_path=flow_path,
        stdout_path=stdout_path,
        dat_path=data_root / f"{run_id}.dat",
        ascii_path=data_root / f"{run_id}.ascii.tmp",
        expected=expected,
        expected_flows=run.generate_workload(foreground_flows=scenario.foreground_flows, seed=case.seed),
    )
    stats = fct_stats(flow_path)
    if (
        stats["completion_rate"] != 1.0
        or stats["completed"] != scenario.foreground_flows
        or stats["total_started"] != scenario.foreground_flows
    ):
        raise ValueError(f"incomplete flow completion for {run_id}")
    metrics = {
        "avg_fct_us": stats["avg_s"] * 1_000_000,
        "p99_fct_us": stats["p99_s"] * 1_000_000,
        "goodput_gbps": aggregate_goodput_gbps(flow_path),
    }
    if not all(math.isfinite(value) and value > 0 for value in metrics.values()):
        raise ValueError(f"nonfinite or nonpositive metric for {run_id}")
    return {
        "arm": case.arm,
        "scenario": case.scenario,
        "seed": case.seed,
        **metrics,
        "completion_rate": stats["completion_rate"],
        "completed": stats["completed"],
        "total_started": stats["total_started"],
    }


def _summary(per_seed: list[dict]) -> list[dict]:
    summary = []
    for arm in run.ARMS:
        for scenario in run.SCENARIOS:
            rows = [row for row in per_seed if row["arm"] == arm and row["scenario"] == scenario]
            if len(rows) != len(run.SEEDS) or {row["seed"] for row in rows} != set(run.SEEDS):
                raise ValueError(f"missing seeds for {arm}/{scenario}")
            values = {field: [row[field] for row in rows] for field in (
                "avg_fct_us", "p99_fct_us", "goodput_gbps", "completion_rate"
            )}
            summary.append({
                "arm": arm,
                "scenario": scenario,
                "n_seeds": len(rows),
                "mean_avg_fct_us": statistics.mean(values["avg_fct_us"]),
                "mean_p99_fct_us": statistics.mean(values["p99_fct_us"]),
                "mean_goodput_gbps": statistics.mean(values["goodput_gbps"]),
                "mean_completion_rate": statistics.mean(values["completion_rate"]),
                "min_avg_fct_us": min(values["avg_fct_us"]),
                "max_avg_fct_us": max(values["avg_fct_us"]),
                "min_p99_fct_us": min(values["p99_fct_us"]),
                "max_p99_fct_us": max(values["p99_fct_us"]),
                "min_goodput_gbps": min(values["goodput_gbps"]),
                "max_goodput_gbps": max(values["goodput_gbps"]),
            })
    return summary


def _write_csv(path: Path, fields: Sequence[str], rows: Sequence[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="ascii") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _number(row[field]) if isinstance(row[field], float) else row[field] for field in fields})


def analyze_formal(data_root: Path, output_root: Path) -> dict[str, list[dict]]:
    data_root = Path(data_root)
    expected = _expected_manifest_paths(data_root)
    per_seed = [_load_case(expected[key], data_root) for key in sorted(expected)]
    summary = _summary(per_seed)
    _write_csv(Path(output_root) / "m4_per_seed.csv", PER_SEED_FIELDS, per_seed)
    _write_csv(Path(output_root) / "m4_summary.csv", SUMMARY_FIELDS, summary)
    return {"per_seed": per_seed, "summary": summary}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=HERE / "data" / "formal")
    parser.add_argument("--output-root", type=Path, default=HERE / "data" / "aggregate")
    args = parser.parse_args(argv)
    analyze_formal(args.data_root, args.output_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
