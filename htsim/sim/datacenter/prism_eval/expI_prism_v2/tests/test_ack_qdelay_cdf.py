import importlib.util
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
MODULE_PATH = HERE.parent / "make_1024_ack_qdelay_cdf.py"
SPEC = importlib.util.spec_from_file_location("ack_qdelay_cdf", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_load_qdelay_and_equal_seed_ecdf(tmp_path):
    first = tmp_path / "s13.csv"
    second = tmp_path / "s14.csv"
    first.write_text("1,1,0,15000,14000,1000,0,100\n", encoding="ascii")
    second.write_text(
        "1,1,0,15000,14000,1000,0,100\n" * 9
        + "1,1,0,24000,14000,10000,0,100\n",
        encoding="ascii",
    )

    assert MODULE.load_qdelay_us(first) == [1.0]
    assert MODULE.mean_seed_ecdf(
        [MODULE.load_qdelay_us(first), MODULE.load_qdelay_us(second)], [1.0, 10.0]
    ) == [0.95, 1.0]


def test_load_qdelay_rejects_bad_schema(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("1,2,3\n", encoding="ascii")

    with pytest.raises(ValueError, match="eight columns"):
        MODULE.load_qdelay_us(bad)


def test_render_writes_png_and_pdf(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    arms = {"reps": "REPS+NSCC", "v2": "REPS+Prism v2-full"}
    for arm in arms:
        for seed, value in ((13, 1000), (14, 2000)):
            (data / f"{arm}_s{seed}.csv").write_text(
                f"1,1,0,{14000 + value},14000,{value},0,100\n", encoding="ascii"
            )

    output = tmp_path / "ack_qdelay_cdf"
    MODULE.render(data, output, arms, [13, 14])

    assert output.with_suffix(".png").is_file()
    assert output.with_suffix(".pdf").is_file()


def test_main_ack_cdf_is_limited_to_low_delay_range():
    assert MODULE.MAIN_ACK_QDELAY_XMAX_US == 25.0


def test_ack_cdf_uses_the_reference_figure_canvas_and_base_font():
    assert MODULE.REFERENCE_FIGSIZE_IN == (5.2, 3.8)
    assert MODULE.REFERENCE_FONT_SIZE_PT == 24


def test_ack_cdf_title_names_failure_level():
    assert MODULE.ack_cdf_title(32) == "1024-node many2many, failed=32; equal-weight five-seed ECDF"


def test_ack_cdf_uses_the_delay_driven_baseline_palette():
    assert MODULE.ARM_COLORS == {
        "ops": "tab:gray",
        "reps": "tab:blue",
        "swift": "tab:pink",
        "mswift": "tab:olive",
        "mnscc": "tab:brown",
        "strack": "tab:orange",
        "v2": "tab:green",
    }
