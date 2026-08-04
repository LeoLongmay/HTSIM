"""Contract for the six-panel plotting-data archive."""

from pathlib import Path
import csv
import importlib.util


HERE = Path(__file__).resolve().parents[1]


def load_archive_renderer():
    """Load this experiment's renderer without sharing a global module name."""
    spec = importlib.util.spec_from_file_location(
        "expA_delaydriven_archive_fig_data", HERE / "archive_fig_data.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_archive_renderer_declares_six_panel_data_contract_and_type42():
    """Archive rendering must be independent of the removed simulation flow logs."""
    archive = load_archive_renderer()

    assert archive.ARCHIVE_FILES == {
        "failed": "figA1dd_failed_sweep.csv",
        "load": "figA3dd_load_sweep.csv",
    }
    assert archive.mpl.rcParams["pdf.fonttype"] == 42
    assert archive.mpl.rcParams["ps.fonttype"] == 42
    assert "Goodput (Tbps)" in archive.__doc__ or "Goodput (Tbps)" in Path(archive.__file__).read_text()
    assert "Goodput (Gbps)" in Path(archive.__file__).read_text()


def test_archive_keeps_all_six_panel_points_and_error_bars():
    """Both retained tables must contain every line-chart coordinate for five seeds."""
    archive = HERE / "archive_data"
    for filename, expected_rows in (("figA1dd_failed_sweep.csv", 49), ("figA3dd_load_sweep.csv", 35)):
        with (archive / filename).open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        assert len(rows) == expected_rows
        assert {row["n_seeds"] for row in rows} == {"5"}
