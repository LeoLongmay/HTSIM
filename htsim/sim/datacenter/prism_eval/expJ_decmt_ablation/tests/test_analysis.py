"""Behavioral tests for strict ExpJ formal-result aggregation."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import statistics
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest


EXPERIMENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXPERIMENT_DIR))

import analyze  # noqa: E402
import run  # noqa: E402


@contextmanager
def _patched_runner_inputs(root: Path):
    """Provide stable provenance inputs for full immutable-manifest fixtures."""
    assets = root / "runner-inputs"
    assets.mkdir()
    topology = assets / "fat_tree_128_1os.topo"
    binary = assets / "htsim_uec"
    decoder = assets / "parse_output"
    runner = assets / "run_lib.sh"
    for path in (topology, binary, decoder, runner):
        path.write_text("fixture\n", encoding="ascii")
    with patch.object(run, "TOPOLOGY", topology), patch.object(run, "HTSIM_UEC", binary), patch.object(
        run, "PARSE_OUTPUT", decoder
    ), patch.object(run, "RUN_LIB", runner):
        yield


def _write_case(root: Path, case: run.Case) -> None:
    """Write one complete runner-valid bundle with all 64 locked flows and idmap rows."""
    run_id = run.case_id(case)
    duration_s = (case.seed - 12) * 1e-6
    flow_path = root / f"{run_id}.flow.txt"
    idmap_path = root / f"{run_id}.idmap"
    flow_lines = []
    idmap_lines = []
    for index in range(run.FLOW_COUNT):
        src_id, flow_id = 1000 + index, 2000 + index
        src, dst = 16 + index, index % 16
        flow_lines.extend((
            f"1000 Type FLOW_EVENT SrcID {src_id} Ev START FlowID {flow_id} Flowsize {run.FLOW_SIZE_BYTES}",
            f"{1000 + duration_s} Type FLOW_EVENT SrcID {src_id} Ev FINISH FlowID {flow_id} Bytes {run.FLOW_SIZE_BYTES}",
        ))
        idmap_lines.extend((f"{src_id} Uec_{src}_{dst}", f"{flow_id} Uec_{src}_{dst}"))
    flow_path.write_text("\n".join(flow_lines) + "\n", encoding="ascii")
    idmap_path.write_text("\n".join(idmap_lines) + "\n", encoding="ascii")
    (root / f"{run_id}.stdout").write_text("simulator output\n", encoding="ascii")

    workload = root / "m2m.cm"
    if not workload.exists():
        workload.write_text(run._workload_text(), encoding="ascii")
    expected = run._expected_manifest(
        phase="formal",
        case=case,
        workload=workload,
        workload_hash=run._sha256(workload),
        output_root=root,
    )
    bindings = run._validate_flow(flow_path, idmap_path)
    expected["output_files"] = {
        name: {
            **metadata,
            "sha256": hashlib.sha256((root / metadata["filename"]).read_bytes()).hexdigest(),
        }
        for name, metadata in expected["output_files"].items()
    }
    (root / f"{run_id}.manifest.json").write_text(
        json.dumps(
            expected | {"flow_event_bindings": run._serialized_event_bindings(bindings)},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="ascii",
    )


def _write_formal_matrix(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for case in run.cases_for_phase("formal"):
        _write_case(root, case)


def test_summary_requires_ten_seeds_per_arm_and_condition(tmp_path):
    """Dropping one result must not silently reduce a condition's uncertainty."""
    with _patched_runner_inputs(tmp_path):
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
    with _patched_runner_inputs(tmp_path):
        formal = tmp_path / "formal"
        _write_formal_matrix(formal)

        result = analyze.analyze_formal(formal, tmp_path / "aggregate")

    assert len(result["per_seed"]) == 80
    assert len(result["summary"]) == 8
    decmt_8 = next(
        row for row in result["summary"] if row["arm"] == "decmt" and row["failed_links"] == 8
    )
    expected_goodputs = [1_024_000.0 / divisor for divisor in range(1, 11)]
    assert {name: decmt_8[name] for name in ("arm", "failed_links", "n_seeds")} == {
        "arm": "decmt", "failed_links": 8, "n_seeds": 10,
    }
    assert decmt_8["mean_goodput_gbps"] == pytest.approx(statistics.mean(expected_goodputs))
    assert decmt_8["std_goodput_gbps"] == pytest.approx(statistics.stdev(expected_goodputs))
    assert decmt_8["mean_avg_fct_us"] == pytest.approx(5.5)
    assert decmt_8["std_avg_fct_us"] == pytest.approx(statistics.stdev(range(1, 11)))
    assert decmt_8["mean_p99_fct_us"] == pytest.approx(5.5)
    assert decmt_8["std_p99_fct_us"] == pytest.approx(statistics.stdev(range(1, 11)))

    with (tmp_path / "aggregate" / "per_seed.csv").open(newline="") as stream:
        per_seed_rows = list(csv.DictReader(stream))
    with (tmp_path / "aggregate" / "summary.csv").open(newline="") as stream:
        summary_rows = list(csv.DictReader(stream))
    assert len(per_seed_rows) == 80
    assert len(summary_rows) == 8
    assert set(per_seed_rows[0]) == {
        "arm", "failed_links", "seed", "avg_fct_us", "p99_fct_us", "goodput_gbps"
    }


def test_aggregation_writes_lf_terminated_csvs(tmp_path):
    """Generated tables must not add CRLF noise to the committed result package."""
    with _patched_runner_inputs(tmp_path):
        formal = tmp_path / "formal"
        _write_formal_matrix(formal)
        aggregate = tmp_path / "aggregate"
        analyze.analyze_formal(formal, aggregate)

    for name in ("per_seed.csv", "summary.csv"):
        assert b"\r\n" not in (aggregate / name).read_bytes()


def test_aggregation_rejects_partial_flow_output(tmp_path):
    """A 63-of-64 completion log is not allowed to become a formal measurement."""
    with _patched_runner_inputs(tmp_path):
        formal = tmp_path / "formal"
        _write_formal_matrix(formal)
        case = run.Case("decmt", 8, 13)
        flow_path = formal / f"{run.case_id(case)}.flow.txt"
        lines = flow_path.read_text(encoding="ascii").splitlines()
        flow_path.write_text("\n".join(lines[:-1]) + "\n", encoding="ascii")
        manifest_path = formal / f"{run.case_id(case)}.manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="ascii"))
        manifest["output_files"]["flow"]["sha256"] = hashlib.sha256(
            flow_path.read_bytes()
        ).hexdigest()
        manifest_path.write_text(json.dumps(manifest), encoding="ascii")

        with pytest.raises(ValueError, match="incomplete flow output"):
            analyze.analyze_formal(formal, tmp_path / "aggregate")


def test_aggregation_rejects_retained_artifact_hash_mismatch(tmp_path):
    """Strict analysis must authenticate even retained artifacts it does not parse."""
    with _patched_runner_inputs(tmp_path):
        formal = tmp_path / "formal"
        _write_formal_matrix(formal)
        case = run.Case("decmt", 8, 13)
        stdout_path = formal / f"{run.case_id(case)}.stdout"
        stdout_path.write_text("tampered but nonempty\n", encoding="ascii")

        with pytest.raises(ValueError, match="artifact SHA-256 mismatch: stdout"):
            analyze.analyze_formal(formal, tmp_path / "aggregate")


def test_aggregation_validates_a_relocated_formal_bundle(tmp_path):
    """Manifest identity must remain strict without depending on checkout location."""
    with _patched_runner_inputs(tmp_path):
        source = tmp_path / "source" / "formal"
        _write_formal_matrix(source)
        relocated = tmp_path / "relocated" / "formal"
        shutil.copytree(source, relocated)

        result = analyze.analyze_formal(relocated, tmp_path / "aggregate")

    assert len(result["per_seed"]) == 80
    assert len(result["summary"]) == 8


def test_aggregation_rejects_mutated_immutable_manifest_field(tmp_path):
    """A changed fixed runner environment cannot be mistaken for the locked experiment."""
    with _patched_runner_inputs(tmp_path):
        formal = tmp_path / "formal"
        _write_formal_matrix(formal)
        case = run.Case("floor_only", 8, 13)
        manifest_path = formal / f"{run.case_id(case)}.manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="ascii"))
        manifest["config"]["environment"]["PATHS"] = "99"
        manifest_path.write_text(json.dumps(manifest), encoding="ascii")

        with pytest.raises(ValueError, match="identity conflicts"):
            analyze.analyze_formal(formal, tmp_path / "aggregate")


def test_aggregation_rejects_unexpected_formal_manifest(tmp_path):
    """A stale or unrelated manifest cannot be folded into the locked 80-case study."""
    with _patched_runner_inputs(tmp_path):
        formal = tmp_path / "formal"
        _write_formal_matrix(formal)
        (formal / "stale.manifest.json").write_text("{}", encoding="ascii")

        with pytest.raises(ValueError, match="exactly 80 formal manifests"):
            analyze.analyze_formal(formal, tmp_path / "aggregate")
