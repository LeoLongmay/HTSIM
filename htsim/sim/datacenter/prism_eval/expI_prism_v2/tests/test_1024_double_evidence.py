import importlib.util
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
MODULE_PATH = HERE.parent / "make_1024_ack_qdelay_cdf.py"
SPEC = importlib.util.spec_from_file_location("ack_qdelay_cdf", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def write_ack_samples(path: Path, values_us: list[float]) -> None:
    path.write_text(
        "".join(
            f"1,1,0,{14000 + int(value * 1000)},14000,{int(value * 1000)},0,100\\n"
            for value in values_us
        ),
        encoding="ascii",
    )


def write_flow_log(path: Path, fcts_us: list[float], incomplete: bool = False) -> None:
    lines = []
    for flow_id, fct_us in enumerate(fcts_us, start=1):
        lines.append(
            f"0.000000000 Type FLOW_EVENT SrcID 1 Ev START FlowID {flow_id} "
            "Flowsize 100\n"
        )
        lines.append(
            f"{fct_us / 1e6:.9f} Type FLOW_EVENT SrcID 1 Ev FINISH FlowID {flow_id} "
            "Bytes 100 Pkts 1\n"
        )
    if incomplete:
        lines.append(
            "0.000000000 Type FLOW_EVENT SrcID 1 Ev START FlowID 99 Flowsize 100\n"
        )
    path.write_text("".join(lines), encoding="ascii")


def test_mean_seed_ecdf_weights_each_seed_equally():
    assert MODULE.mean_seed_ecdf([[1.0], [10.0, 10.0, 10.0]], [5.0]) == [0.5]


def test_delta_is_positive_when_prism_finishes_below_threshold():
    mean, lower, upper = MODULE.bootstrap_delta_band(
        [[10.0]], [[1.0]], [5.0], draws=200, seed=7
    )
    assert mean == [1.0]
    assert lower[0] <= mean[0] <= upper[0]


def test_bootstrap_delta_band_is_deterministic_and_contains_mean():
    first = MODULE.bootstrap_delta_band(
        [[1.0], [10.0, 10.0, 10.0]], [[1.0, 1.0], [20.0]], [5.0, 15.0],
        draws=200,
        seed=7,
    )
    second = MODULE.bootstrap_delta_band(
        [[1.0], [10.0, 10.0, 10.0]], [[1.0, 1.0], [20.0]], [5.0, 15.0],
        draws=200,
        seed=7,
    )
    assert first == second
    mean, lower, upper = first
    assert all(low <= value <= high for low, value, high in zip(lower, mean, upper))


def test_render_ack_evidence_writes_png_and_pdf(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    arms = {
        "ops": "OPS+NSCC",
        "reps": "REPS+NSCC",
        "strack": "REPS+STrack",
        "v2": "REPS+Prism v2-full",
    }
    seeds = [13, 14, 15, 16, 17]
    for arm_index, arm in enumerate(arms):
        for seed_index, seed in enumerate(seeds):
            write_ack_samples(data / f"{arm}_s{seed}.csv", [1.0 + arm_index + seed_index])

    output = tmp_path / "ack_evidence"
    MODULE.render_ack_evidence(data, output, arms, seeds)

    assert output.with_suffix(".png").is_file()
    assert output.with_suffix(".pdf").is_file()


def test_failure_sweep_aggregates_equal_weight_seed_means_and_sample_sem(tmp_path):
    write_flow_log(tmp_path / "double_ops_f0_s13.flow.txt", [1.0, 3.0])
    write_flow_log(tmp_path / "double_ops_f0_s14.flow.txt", [2.0, 4.0])

    aggregate = MODULE.aggregate_failure_sweep(
        tmp_path, {"ops": "OPS+NSCC"}, [0], [13, 14]
    )
    cell = aggregate["ops"][0]

    assert cell["goodput_gbps"] == pytest.approx((7.0 / 15.0, 1.0 / 15.0))
    assert cell["mean_fct_us"] == pytest.approx((2.5, 0.5))
    assert cell["p99_fct_us"] == pytest.approx((3.5, 0.5))
    assert cell["completion_rate"] == pytest.approx((1.0, 0.0))


def test_failure_sweep_preserves_incomplete_completion_rate(tmp_path):
    write_flow_log(
        tmp_path / "double_ops_f0_s13.flow.txt", [1.0, 3.0], incomplete=True
    )

    aggregate = MODULE.aggregate_failure_sweep(
        tmp_path, {"ops": "OPS+NSCC"}, [0], [13]
    )

    assert aggregate["ops"][0]["completion_rate"][0] < 0.999


def test_engagement_fraction_reads_column_nine(tmp_path):
    epoch = tmp_path / "double_v2_f32_s13.epoch.csv"
    epoch.write_text(
        "0,1,1,1,1,0,1,1,0,1,28,20\n"
        "1,1,1,1,1,0,1,1,0,0,28,20\n",
        encoding="ascii",
    )

    assert MODULE.engagement_fraction(epoch) == 0.5


@pytest.mark.parametrize("contents", ["", "0,1,1,1,1,0,1,1,0\n"])
def test_engagement_fraction_rejects_empty_or_malformed_rows(tmp_path, contents):
    epoch = tmp_path / "bad.epoch.csv"
    epoch.write_text(contents, encoding="ascii")

    with pytest.raises(ValueError):
        MODULE.engagement_fraction(epoch)


def test_render_failure_sweep_writes_all_png_and_pdf_targets(tmp_path):
    data = tmp_path / "data"
    figures = tmp_path / "figures"
    data.mkdir()
    arms = {
        "ops": "OPS+NSCC",
        "reps": "REPS+NSCC",
        "strack": "REPS+STrack",
        "v2": "REPS+Prism v2-full",
    }
    failures = [0, 32]
    seeds = [13, 14]
    for arm_index, arm in enumerate(arms):
        for failure in failures:
            for seed_index, seed in enumerate(seeds):
                write_flow_log(
                    data / f"double_{arm}_f{failure}_s{seed}.flow.txt",
                    [1.0 + arm_index + seed_index, 3.0 + arm_index + seed_index],
                    incomplete=(arm == "ops" and failure == 0 and seed == 13),
                )
    for failure in failures:
        for seed_index, seed in enumerate(seeds):
            engaged = (failure + seed_index) % 2
            (data / f"double_v2_f{failure}_s{seed}.epoch.csv").write_text(
                f"0,1,1,1,1,0,1,1,0,{engaged},28,20\n",
                encoding="ascii",
            )

    MODULE.render_failure_sweep(data, figures, arms, failures, seeds)

    for stem in (
        "figI_1024_failure_sweep",
        "figI_1024_f32_fct_cdf",
        "figI_1024_v2_engagement_sweep",
    ):
        assert (figures / f"{stem}.png").is_file()
        assert (figures / f"{stem}.pdf").is_file()
