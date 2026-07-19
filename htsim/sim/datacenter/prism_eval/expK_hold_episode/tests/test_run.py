"""Contract tests for the fixed Prism Hold-episode experiment matrix."""

from __future__ import annotations

import json
import sys
from pathlib import Path


EXPERIMENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXPERIMENT_DIR))

import run  # noqa: E402


def test_locked_cases_are_exactly_the_four_approved_scenarios():
    cases = run.locked_cases()

    assert len(cases) == 12
    assert {(case.scenario, case.seed) for case in cases} == {
        (scenario, seed)
        for scenario in ("f0", "asymmetric", "incast", "trimming")
        for seed in (13, 14, 15)
    }
    assert next(case for case in cases if case.scenario == "f0").failed == 0
    assert next(case for case in cases if case.scenario == "asymmetric").failed == 8
    assert next(case for case in cases if case.scenario == "incast").fanin == 64
    assert next(case for case in cases if case.scenario == "trimming").disable_trim is False
    assert all(case.t_cc_us == 14 for case in cases)
    assert all(case.t_spray_us == 14 for case in cases)
    assert all(case.loss_decomp is False for case in cases)


def test_fixed_run_environment_ignores_ambient_runner_knobs(monkeypatch, tmp_path):
    monkeypatch.setenv("TQD", "99")
    monkeypatch.setenv("MTU", "9000")
    monkeypatch.setenv("NODES", "256")
    monkeypatch.setenv("KEEPDAT", "1")
    monkeypatch.setenv("PRISM_PATHRTT", "/tmp/unrelated.csv")

    env = run.fixed_run_environment(run.locked_cases()[0], tmp_path)

    assert env["PATHS"] == "8"
    assert env["END_MS"] == "8"
    assert env["MTU"] == "4150"
    assert env["NODES"] == "128"
    assert "TQD" not in env
    assert "KEEPDAT" not in env
    assert "PRISM_PATHRTT" not in env
    assert env["EXTRA_ARGS"] == "-disable_trim -target_q_delay 14"


def test_manifest_records_fixed_runner_settings(tmp_path):
    path = run.write_manifest(run.locked_cases()[0], tmp_path)
    manifest = json.loads(path.read_text())

    assert manifest["paths"] == 8
    assert manifest["mtu"] == 4150
    assert manifest["nodes"] == 128
