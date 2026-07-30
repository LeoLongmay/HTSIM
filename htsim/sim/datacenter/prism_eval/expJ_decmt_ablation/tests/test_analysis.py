"""Behavioral tests for strict ExpJ formal-result aggregation."""

from __future__ import annotations

import csv
import json
import statistics
import sys
from pathlib import Path

import pytest


EXPERIMENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXPERIMENT_DIR))

import analyze  # noqa: E402
import run  # noqa: E402


def _write_case(root: Path, case: run.Case) -> None:
    """Write one complete, small flow log and its formal manifest fixture."""
    run_id = run.case_id(case)
    duration_s = (case.seed - 12) * 1e-6
    flow_path = root / f"{run_id}.flow.txt"
    flow_path.write_text(
        "\n".join(
            (
                "0 Type FLOW_EVENT SrcID 1 Ev START FlowID 11 Flowsize 1000",
                f"{duration_s} Type FLOW_EVENT SrcID 1 Ev FINISH FlowID 11 Bytes 1000",
                "0 Type FLOW_EVENT SrcID 2 Ev START FlowID 12 Flowsize 1000",
                f"{duration_s} Type FLOW_EVENT SrcID 2 Ev FINISH FlowID 12 Bytes 1000",
            )
        )
        + "\n",
        encoding="ascii",
    )
    (root / f"{run_id}.manifest.json").write_text(
        json.dumps(
            {
                "schema": run.SCHEMA,
                "schema_version": run.SCHEMA_VERSION,
                "experiment": "ExpJ_decmt_ablation",
                "phase": "formal",
                "run_id": run_id,
                "arm": case.arm,
                "failed_links": case.failed,
                "seed": case.seed,
                "output_files": {"flow": flow_path.name},
            }
        ),
        encoding="ascii",
    )


def _write_formal_matrix(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for case in run.cases_for_phase("formal"):
        _write_case(root, case)


def test_summary_requires_ten_seeds_per_arm_and_condition(tmp_path):
    """Dropping one result must not silently reduce a condition's uncertainty."""
    formal = tmp_path / "formal"
    formal.mkdir()
    cases = [
        case
        for case in run.cases_for_phase("formal")
        if not (case.arm == "decmt" and case.failed == 8 and case.seed == 22)
    ]
    for case in cases:
        _write_case(formal, case)

    with pytest.raises(ValueError, match="missing seeds"):
        analyze.analyze_formal(formal, tmp_path / "aggregate")


def test_aggregation_writes_per_seed_and_sample_standard_deviation(tmp_path):
    """A full locked matrix produces independently checkable seed and summary metrics."""
    formal = tmp_path / "formal"
    _write_formal_matrix(formal)

    result = analyze.analyze_formal(formal, tmp_path / "aggregate")

    assert len(result["per_seed"]) == 80
    assert len(result["summary"]) == 8
    decmt_8 = next(
        row for row in result["summary"] if row["arm"] == "decmt" and row["failed_links"] == 8
    )
    expected_goodputs = [16.0 / divisor for divisor in range(1, 11)]
    assert decmt_8 == {
        "arm": "decmt",
        "failed_links": 8,
        "n_seeds": 10,
        "mean_goodput_gbps": statistics.mean(expected_goodputs),
        "std_goodput_gbps": statistics.stdev(expected_goodputs),
        "mean_avg_fct_us": 5.5,
        "std_avg_fct_us": statistics.stdev(range(1, 11)),
        "mean_p99_fct_us": 5.5,
        "std_p99_fct_us": statistics.stdev(range(1, 11)),
    }

    with (tmp_path / "aggregate" / "per_seed.csv").open(newline="") as stream:
        per_seed_rows = list(csv.DictReader(stream))
    with (tmp_path / "aggregate" / "summary.csv").open(newline="") as stream:
        summary_rows = list(csv.DictReader(stream))
    assert len(per_seed_rows) == 80
    assert len(summary_rows) == 8
    assert set(per_seed_rows[0]) == {
        "arm", "failed_links", "seed", "avg_fct_us", "p99_fct_us", "goodput_gbps"
    }


def test_aggregation_rejects_unexpected_formal_manifest(tmp_path):
    """A stale or unrelated manifest cannot be folded into the locked 80-case study."""
    formal = tmp_path / "formal"
    _write_formal_matrix(formal)
    (formal / "stale.manifest.json").write_text("{}", encoding="ascii")

    with pytest.raises(ValueError, match="exactly 80 formal manifests"):
        analyze.analyze_formal(formal, tmp_path / "aggregate")
