from pathlib import Path


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
