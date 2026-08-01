import os
from pathlib import Path
import subprocess

import pytest


EXPL = Path(__file__).resolve().parents[1]
DATACENTER = EXPL.parents[1]
RUN_LIB = EXPL.parent / "common" / "run_lib.sh"
SCRIPT = RUN_LIB.read_text()


def test_run_lib_supports_opt_in_logtime_without_changing_default_callers():
    assert 'LOGTIME_ARG=""' in SCRIPT
    assert '[ -n "${LOGTIME_US:-}" ]' in SCRIPT
    assert 'LOGTIME_ARG="-logtime_us ${LOGTIME_US}"' in SCRIPT
    assert '${LOGTIME_ARG}' in SCRIPT


def test_rate_stability_runner_sets_ten_microsecond_logtime():
    assert '"LOGTIME_US": "10"' in (EXPL / "run.py").read_text()


def test_main_uec_clamps_logtime_against_the_ms_end_time_unit():
    """An 8-ms run must not reinterpret its end time as 8 us and shorten a 10-us logger."""
    source = (DATACENTER / "main_uec.cpp").read_text()

    assert "logtime >= timeFromMs((double)end_time)" in source
    assert "logtime = timeFromMs((double)end_time) - 1" in source


@pytest.mark.parametrize(
    "value", ["0", "00", "000", "-1", "1.5", "abc", "10 -end 0"]
)
def test_run_lib_rejects_invalid_logtime_us(value):
    result = subprocess.run(
        [
            "bash",
            str(RUN_LIB),
            "nscc",
            "reps",
            "0",
            "fat_tree_128_1os.topo",
            "13",
            "/tmp/nonexistent.cm",
            "sink",
            "invalid-logtime",
            "/tmp",
        ],
        env={**os.environ, "LOGTIME_US": value},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "ERROR: LOGTIME_US must be a decimal-free positive integer" in result.stderr
