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
    arms = {"reps": "REPS+NSCC", "prism": "REPS+Prism v2-full"}
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
