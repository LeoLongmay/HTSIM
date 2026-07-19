"""Contract tests for the fixed Prism Hold-episode experiment matrix."""

from __future__ import annotations

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
