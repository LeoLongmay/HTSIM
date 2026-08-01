"""Runner-contract tests for the locked ExpL rate-stability experiment."""

from __future__ import annotations

import os
import pytest
import subprocess
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


REPRO = DATACENTER / "prism_eval" / "expL_rate_stability" / "repro.sh"


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


def test_fixed_environment_clears_inherited_controller_trace_knobs(monkeypatch):
    case = Case(kind="primary", condition="asymmetric", arm="decmt", seed=13)
    names = ("PRISM_PATHRTT", "PRISM_EPOCH", "PRISM_LOSS", "MNSCC_MEDIAN")
    for name in names:
        monkeypatch.setenv(name, "inherited")

    env = fixed_environment(case)

    for name in names:
        assert name not in env


def test_workload_is_deterministic_and_rejects_conflicting_content(tmp_path):
    path = tmp_path / "m2m.cm"
    digest = ensure_workload(path)
    assert digest == ensure_workload(path)
    path.write_text("conflict\n", encoding="ascii")
    with pytest.raises(ValueError, match="conflicting"):
        ensure_workload(path)


@pytest.mark.parametrize("command", ("deterministic-check", "historical-check"))
def test_deterministic_gate_runs_the_representative_case_twice_in_isolated_outputs(tmp_path, command):
    """A one-seed reproducibility gate must compare twins, never invoke analysis."""
    calls = tmp_path / "python_calls.txt"
    fake_python = tmp_path / "python3"
    fake_python.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' \"$*\" >> \"$CALLS\"\n"
        "for ((i = 1; i <= $#; i++)); do\n"
        "  if [[ \"${!i}\" == --output-root ]]; then\n"
        "    j=$((i + 1))\n"
        "    output_root=${!j}\n"
        "    mkdir -p \"$output_root\"\n"
        "    printf 'identical sink trace\\n' > \"$output_root/rate_asymmetric_decmt_s13.sink.txt\"\n"
        "  fi\n"
        "done\n",
        encoding="ascii",
    )
    fake_python.chmod(0o755)

    result = subprocess.run(
        ["bash", str(REPRO), command],
        cwd=REPRO.parent,
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "CALLS": str(calls)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    invocations = calls.read_text(encoding="ascii").splitlines()
    assert len(invocations) == 2
    assert all("run.py --phase smoke --output-root" in invocation for invocation in invocations)
    roots = [invocation.split(" --output-root ", 1)[1] for invocation in invocations]
    assert roots[0] != roots[1]
    assert "analyze.py" not in "\n".join(invocations)
