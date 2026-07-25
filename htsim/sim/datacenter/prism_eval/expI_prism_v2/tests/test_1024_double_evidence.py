import importlib.util
from pathlib import Path


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
