"""Contract tests for the locked ExpJ DecMT component-ablation runner."""

from __future__ import annotations

import json
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest


EXPERIMENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXPERIMENT_DIR))

import run  # noqa: E402


def test_repro_script_lists_smoke_then_formal_then_render():
    script = (EXPERIMENT_DIR / "repro.sh").read_text(encoding="utf-8")

    assert script.index("run.py smoke") < script.index("run.py formal")
    assert script.index("run.py formal") < script.index("analyze.py") < script.index("make_figs.py")


@contextmanager
def patched_inputs(root: Path):
    topology = root / "fat_tree_128_1os.topo"
    binary = root / "htsim_uec"
    decoder = root / "parse_output"
    runner = root / "run_lib.sh"
    for path in (topology, binary, decoder, runner):
        path.write_text("fixture\n", encoding="ascii")
    with patch.object(run, "TOPOLOGY", topology), patch.object(run, "HTSIM_UEC", binary), patch.object(
        run, "PARSE_OUTPUT", decoder
    ), patch.object(run, "RUN_LIB", runner):
        yield


def run_lib_with_flow(*, completed: int = 64):
    def invoke(command, *, cwd, env, check):
        del cwd, env, check
        tag = command[-2]
        output = Path(command[-1])
        output.mkdir(parents=True, exist_ok=True)
        flow = []
        idmap = []
        for index in range(run.FLOW_COUNT):
            src_id = 1000 + index
            flow_id = 2000 + index
            src, dst = 16 + index, index % 16
            idmap.extend((f"{src_id} Uec_{src}_{dst}", f"{flow_id} Uec_{src}_{dst}"))
            flow.append(
                f"1000 Type FLOW_EVENT SrcID {src_id} Ev START FlowID {flow_id} Flowsize {run.FLOW_SIZE_BYTES}"
            )
            if index < completed:
                flow.append(
                    f"2000 Type FLOW_EVENT SrcID {src_id} Ev FINISH FlowID {flow_id} Bytes {run.FLOW_SIZE_BYTES}"
                )
        (output / f"{tag}.flow.txt").write_text("\n".join(flow) + "\n", encoding="ascii")
        (output / f"{tag}.idmap").write_text("\n".join(idmap) + "\n", encoding="ascii")
        (output / f"{tag}.stdout").write_text("simulator output\n", encoding="ascii")
    return invoke


def test_formal_matrix_and_locked_arm_arguments():
    cases = run.cases_for_phase("formal")

    assert len(cases) == 80
    assert set(cases) == {
        run.Case(arm, failed, seed)
        for arm in run.ARMS
        for failed in (0, 8)
        for seed in range(13, 23)
    }
    assert run.fixed_environment(run.Case("matched_nscc", 8, 13))["TQD"] == "14"
    assert run.fixed_environment(run.Case("floor_only", 8, 13))["EXTRA_ARGS"] == "-disable_trim -prism_floor_only"
    assert "TQD" not in run.fixed_environment(run.Case("original_nscc", 8, 13))
    assert run.run_lib_command(run.Case("floor_only", 8, 13), Path("m2m.cm"), Path("data"))[2:6] == [
        "prism", "reps", "8", "fat_tree_128_1os.topo",
    ]


def test_fixed_environment_clears_ambient_run_and_trace_knobs(monkeypatch):
    for name in (
        "TQD", "EXTRA_ARGS", "KEEPDAT", "PRISM_EPOCH", "PRISM_PATHRTT", "PRISM_HOLD_TRACE",
        "PRISM_LOSS", "TMPDIR", "TMP", "TEMP",
    ):
        monkeypatch.setenv(name, "inherited")

    env = run.fixed_environment(run.Case("floor_only", 8, 13))

    assert {name: env[name] for name in ("PATHS", "END_MS", "MTU", "NODES")} == {
        "PATHS": "8", "END_MS": "8", "MTU": "4150", "NODES": "128",
    }
    assert env["TQD"] == "14"
    assert env["EXTRA_ARGS"] == "-disable_trim -prism_floor_only"
    for name in (
        "KEEPDAT", "PRISM_EPOCH", "PRISM_PATHRTT", "PRISM_HOLD_TRACE", "PRISM_LOSS",
        "TMPDIR", "TMP", "TEMP",
    ):
        assert name not in env


def test_workload_is_fixed_and_formal_run_rejects_incomplete_flow():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        case = run.Case("original_nscc", 8, 13)
        with patched_inputs(root), patch.object(
            run.subprocess, "run", side_effect=run_lib_with_flow(completed=63)
        ), pytest.raises(RuntimeError, match="incomplete flow"):
            run.run_one(case, phase="smoke", output_root=root / "smoke")

        assert (root / "smoke" / "m2m.cm").read_text(encoding="ascii") == run._workload_text()


def test_successful_case_writes_immutable_manifest_and_rejects_conflict():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        case = run.Case("decmt", 8, 13)
        with patched_inputs(root), patch.object(run.subprocess, "run", side_effect=run_lib_with_flow()):
            manifest_path = run.run_one(case, phase="smoke", output_root=root / "smoke")

        manifest = json.loads(manifest_path.read_text(encoding="ascii"))
        assert manifest["arm"] == "decmt"
        assert manifest["fixed_parameters"]["flow_count"] == 64
        assert len(manifest["flow_event_bindings"]) == 64

        manifest["seed"] = 99
        manifest_path.write_text(json.dumps(manifest), encoding="ascii")
        with patched_inputs(root), pytest.raises(ValueError, match="identity conflicts"):
            run.run_one(case, phase="smoke", output_root=root / "smoke")
