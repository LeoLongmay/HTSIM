#!/usr/bin/env python3
"""Strict aggregation for the locked ExpJ DecMT component ablation."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
COMMON = HERE.parent / "common"
if str(COMMON) not in sys.path:
    sys.path.insert(0, str(COMMON))

from metrics import aggregate_goodput_gbps, fct_stats  # noqa: E402
import run  # noqa: E402


PER_SEED_FIELDS = (
    "arm", "failed_links", "seed", "avg_fct_us", "p99_fct_us", "goodput_gbps",
)
SUMMARY_FIELDS = (
    "arm", "failed_links", "n_seeds", "mean_goodput_gbps", "std_goodput_gbps",
    "mean_avg_fct_us", "std_avg_fct_us", "mean_p99_fct_us", "std_p99_fct_us",
)


def _expected_cases() -> dict[str, run.Case]:
    return {run.case_id(case): case for case in run.cases_for_phase("formal")}


def _missing_seed_message(paths: set[Path], root: Path) -> str | None:
    missing = []
    for arm in run.ARMS:
        for failed in run.FAILED_LINKS:
            present = {
                case.seed
                for case in run.cases_for_phase("formal")
                if case.arm == arm
                and case.failed == failed
                and root / f"{run.case_id(case)}.manifest.json" in paths
            }
            expected = set(run.SEEDS)
            if present != expected:
                missing.append(f"{arm}/failed={failed}: {sorted(expected - present)}")
    if missing:
        return "missing seeds for " + "; ".join(missing)
    return None


def _load_manifest(path: Path, case: run.Case) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="ascii"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid manifest: {path.name}") from exc
    if not isinstance(manifest, dict):
        raise ValueError(f"invalid manifest: {path.name}")
    expected = {
        "schema": run.SCHEMA,
        "schema_version": run.SCHEMA_VERSION,
        "experiment": "ExpJ_decmt_ablation",
        "phase": "formal",
        "run_id": run.case_id(case),
        "arm": case.arm,
        "failed_links": case.failed,
        "seed": case.seed,
    }
    if any(manifest.get(name) != value for name, value in expected.items()):
        raise ValueError(f"formal manifest identity conflicts: {path.name}")
    output_files = manifest.get("output_files")
    expected_flow = f"{run.case_id(case)}.flow.txt"
    if not isinstance(output_files, dict) or output_files.get("flow") != expected_flow:
        raise ValueError(f"formal manifest flow output conflicts: {path.name}")
    return manifest


def _per_seed_row(root: Path, case: run.Case) -> dict[str, float | int | str]:
    path = root / f"{run.case_id(case)}.manifest.json"
    manifest = _load_manifest(path, case)
    flow_path = root / manifest["output_files"]["flow"]
    try:
        stats = fct_stats(flow_path)
        avg_fct_us = stats["avg_s"] * 1e6
        p99_fct_us = stats["p99_s"] * 1e6
        goodput_gbps = aggregate_goodput_gbps(flow_path)
    except (OSError, ValueError, IndexError) as exc:
        raise ValueError(f"unreadable flow output: {flow_path.name}") from exc
    metrics = (avg_fct_us, p99_fct_us, goodput_gbps)
    if not all(math.isfinite(value) for value in metrics):
        raise ValueError(f"non-finite flow metrics: {flow_path.name}")
    return {
        "arm": case.arm,
        "failed_links": case.failed,
        "seed": case.seed,
        "avg_fct_us": avg_fct_us,
        "p99_fct_us": p99_fct_us,
        "goodput_gbps": goodput_gbps,
    }


def _summary_row(rows: list[dict[str, float | int | str]], case: run.Case) -> dict[str, float | int | str]:
    values = {
        name: [float(row[name]) for row in rows]
        for name in ("goodput_gbps", "avg_fct_us", "p99_fct_us")
    }
    if len(rows) != len(run.SEEDS):
        raise ValueError(f"missing seeds for {case.arm}/failed={case.failed}")
    return {
        "arm": case.arm,
        "failed_links": case.failed,
        "n_seeds": len(rows),
        "mean_goodput_gbps": statistics.mean(values["goodput_gbps"]),
        "std_goodput_gbps": statistics.stdev(values["goodput_gbps"]),
        "mean_avg_fct_us": statistics.mean(values["avg_fct_us"]),
        "std_avg_fct_us": statistics.stdev(values["avg_fct_us"]),
        "mean_p99_fct_us": statistics.mean(values["p99_fct_us"]),
        "std_p99_fct_us": statistics.stdev(values["p99_fct_us"]),
    }


def _write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, float | int | str]]) -> None:
    with path.open("w", encoding="ascii", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def analyze_formal(data_root: Path, output_root: Path) -> dict[str, list[dict]]:
    """Validate all locked formal bundles and write per-seed and aggregate CSVs."""
    data_root = Path(data_root)
    output_root = Path(output_root)
    manifest_paths = set(data_root.glob("*.manifest.json"))
    expected_cases = _expected_cases()
    missing_message = _missing_seed_message(manifest_paths, data_root)
    if missing_message is not None:
        raise ValueError(missing_message)
    if len(manifest_paths) != len(expected_cases):
        raise ValueError("expected exactly 80 formal manifests")
    expected_paths = {data_root / f"{run_id}.manifest.json" for run_id in expected_cases}
    if manifest_paths != expected_paths:
        raise ValueError("expected exactly 80 formal manifests")

    per_seed = [_per_seed_row(data_root, case) for case in run.cases_for_phase("formal")]
    summary = []
    for arm in run.ARMS:
        for failed in run.FAILED_LINKS:
            rows = [
                row for row in per_seed if row["arm"] == arm and row["failed_links"] == failed
            ]
            summary.append(_summary_row(rows, run.Case(arm, failed, run.SEEDS[0])))

    output_root.mkdir(parents=True, exist_ok=True)
    _write_csv(output_root / "per_seed.csv", PER_SEED_FIELDS, per_seed)
    _write_csv(output_root / "summary.csv", SUMMARY_FIELDS, summary)
    return {"per_seed": per_seed, "summary": summary}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=HERE / "data" / "formal")
    parser.add_argument("--output", type=Path, default=HERE / "data" / "aggregate")
    args = parser.parse_args()
    analyze_formal(args.input, args.output)


if __name__ == "__main__":
    main()
