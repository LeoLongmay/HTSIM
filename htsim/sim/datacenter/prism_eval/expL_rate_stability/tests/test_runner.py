"""Runner-contract tests for the locked ExpL rate-stability experiment."""

from __future__ import annotations

import pytest
import sys
from pathlib import Path


DATACENTER = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(DATACENTER))

from prism_eval.expL_rate_stability.run import (
    BETA_VALUES,
    PRIMARY_ARMS,
    Case,
    cases_for_phase,
    ensure_workload,
    fixed_environment,
    run_lib_command,
)


def test_formal_matrix_has_exactly_sixty_unique_cases():
    cases = cases_for_phase("formal")
    assert len(cases) == 60
    assert len({case.case_id for case in cases}) == 60
    assert {case.arm for case in cases if case.kind == "primary"} == set(PRIMARY_ARMS)
    assert {case.beta for case in cases if case.kind == "beta"} == set(BETA_VALUES)


def test_primary_arm_commands_and_decmt_v2_flags_are_locked(tmp_path):
    case = Case(kind="primary", condition="asymmetric", arm="decmt", seed=13)
    env = fixed_environment(case)
    command = run_lib_command(case, tmp_path / "m2m.cm", tmp_path)
    assert command[2:7] == ["prism", "reps", "8", "fat_tree_128_1os.topo", "13"]
    assert "-disable_trim" in env["EXTRA_ARGS"]
    assert "-prism_smooth_beta 0.3" in env["EXTRA_ARGS"]
    assert env["LOGTIME_US"] == "10"


def test_workload_is_deterministic_and_rejects_conflicting_content(tmp_path):
    path = tmp_path / "m2m.cm"
    digest = ensure_workload(path)
    assert digest == ensure_workload(path)
    path.write_text("conflict\n", encoding="ascii")
    with pytest.raises(ValueError, match="conflicting"):
        ensure_workload(path)
