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
            f"1,1,0,{14000 + int(value * 1000)},14000,{int(value * 1000)},0,100\n"
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


def test_render_ack_evidence_writes_required_plot_semantics(tmp_path, monkeypatch):
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
            values = [1.0 + arm_index + seed_index]
            if arm == "ops" and seed == 13:
                values.append(1.25)
            write_ack_samples(data / f"{arm}_s{seed}.csv", values)

    closed_figures = []
    monkeypatch.setattr(MODULE.plt, "close", closed_figures.append)
    output = tmp_path / "ack_evidence"
    MODULE.render_ack_evidence(data, output, arms, seeds)

    assert output.with_suffix(".png").is_file()
    assert output.with_suffix(".pdf").is_file()
    assert len(closed_figures) == 1
    figure = closed_figures[0]
    full_axis, zoom_axis, delta_axis = figure.axes
    assert [axis.get_title() for axis in (full_axis, zoom_axis)] == [
        "full range",
        "low delay",
    ]
    assert all(axis.get_ylabel() == "Empirical CDF" for axis in (full_axis, zoom_axis))
    assert [text.get_text() for text in full_axis.get_legend().get_texts()] == list(
        arms.values()
    )
    assert delta_axis.get_ylabel() == "Δ ECDF vs REPS+NSCC (percentage points)"
    assert len(delta_axis.collections) == 3
    assert any(
        line.get_linestyle() == "--" and set(line.get_ydata()) == {0.0}
        for line in delta_axis.lines
    )
    assert [text.get_text() for text in delta_axis.get_legend().get_texts()] == [
        "OPS+NSCC − REPS+NSCC",
        "REPS+STrack − REPS+NSCC",
        "REPS+Prism v2-full − REPS+NSCC",
    ]
    assert "five seed-local ECDFs equally weighted" in figure._suptitle.get_text()


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


def test_failure_sweep_rejects_nonfinite_requested_seed_metric(tmp_path):
    write_flow_log(tmp_path / "double_ops_f0_s13.flow.txt", [1.0])
    write_flow_log(tmp_path / "double_ops_f0_s14.flow.txt", [])
    write_flow_log(tmp_path / "double_ops_f0_s15.flow.txt", [3.0])

    with pytest.raises(ValueError, match="non-finite"):
        MODULE.aggregate_failure_sweep(
            tmp_path, {"ops": "OPS+NSCC"}, [0], [13, 14, 15]
        )


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


def test_render_failure_sweep_writes_required_plot_semantics(tmp_path, monkeypatch):
    data = tmp_path / "data"
    figures = tmp_path / "figures"
    data.mkdir()
    arms = {
        "ops": "OPS+NSCC",
        "reps": "REPS+NSCC",
        "strack": "REPS+STrack",
        "v2": "REPS+Prism v2-full",
    }
    failures = [0, 8, 16, 24, 32]
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

    captured_figures = {}
    save_figure = MODULE._save_figure

    def capture_figure(figure, figures_dir, stem):
        captured_figures[stem] = figure
        save_figure(figure, figures_dir, stem)

    monkeypatch.setattr(MODULE, "_save_figure", capture_figure)
    MODULE.render_failure_sweep(data, figures, arms, failures, seeds)
    MODULE.render_failure_sweep(
        data, figures, arms, failures, seeds, fct_cdf_failure=16
    )

    for stem in (
        "figI_1024_failure_sweep",
        "figI_1024_f32_fct_cdf",
        "figI_1024_f16_fct_cdf",
        "figI_1024_v2_engagement_sweep",
    ):
        assert (figures / f"{stem}.png").is_file()
        assert (figures / f"{stem}.pdf").is_file()

    performance = captured_figures["figI_1024_failure_sweep"]
    assert [axis.get_ylabel() for axis in performance.axes] == [
        "Goodput (Gbps)",
        "Mean FCT (us)",
        "P99 FCT (us)",
    ]
    assert performance.axes[-1].get_xlabel() == "Failed links"
    assert all(
        len(axis.containers) == len(arms)
        and all(container.has_yerr for container in axis.containers)
        for axis in performance.axes
    )
    assert all(
        [text.get_text() for text in axis.texts] == ["CR=0.833"]
        for axis in performance.axes
    )
    assert "seed mean ± sample SEM" in performance._suptitle.get_text()

    fct_axis = captured_figures["figI_1024_f16_fct_cdf"].axes[0]
    assert fct_axis.get_xlabel() == "Avg FCT (ms)"
    assert fct_axis.get_ylabel() == "CDF"
    assert fct_axis.get_title() == ""
    assert len(fct_axis.lines) == len(arms)
    assert fct_axis.get_legend() is None
    assert max(fct_axis.lines[0].get_xdata()) < 0.01
    assert [line.get_color() for line in fct_axis.lines] == [
        MODULE.ARM_COLORS[arm] for arm in arms
    ]

    engagement_axis = captured_figures["figI_1024_v2_engagement_sweep"].axes[0]
    assert engagement_axis.get_ylim() == (0.0, 1.0)
    assert engagement_axis.get_xlabel() == "Failed links"
    assert engagement_axis.get_ylabel() == "Engaged epoch fraction"
    assert engagement_axis.get_title() == "Prism v2 engagement; seed mean ± sample SEM"
    assert len(engagement_axis.containers) == 1
    assert engagement_axis.containers[0].has_yerr
    assert [text.get_text() for text in engagement_axis.get_legend().get_texts()] == [
        arms["v2"]
    ]
