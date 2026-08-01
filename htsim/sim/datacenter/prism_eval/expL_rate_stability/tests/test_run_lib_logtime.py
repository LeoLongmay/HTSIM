import os
from pathlib import Path
import subprocess

import pytest


SCRIPT = Path("htsim/sim/datacenter/prism_eval/common/run_lib.sh").read_text()


def test_run_lib_supports_opt_in_logtime_without_changing_default_callers():
    assert 'LOGTIME_ARG=""' in SCRIPT
    assert '[ -n "${LOGTIME_US:-}" ]' in SCRIPT
    assert 'LOGTIME_ARG="-logtime_us ${LOGTIME_US}"' in SCRIPT
    assert '${LOGTIME_ARG}' in SCRIPT


def test_rate_stability_runner_sets_ten_microsecond_logtime():
    assert '"LOGTIME_US": "10"' in Path(
        "htsim/sim/datacenter/prism_eval/expL_rate_stability/run.py"
    ).read_text()


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "abc", "10 -end 0"])
def test_run_lib_rejects_invalid_logtime_us(value):
    result = subprocess.run(
        [
            "bash",
            "htsim/sim/datacenter/prism_eval/common/run_lib.sh",
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
