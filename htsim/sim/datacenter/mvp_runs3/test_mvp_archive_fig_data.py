"""Contract tests for the compact plotting-data archive of MVP paper figures."""

from pathlib import Path
import csv
import importlib.util


HERE = Path(__file__).resolve().parent


def load_archive_renderer():
    """Load this directory's renderer without sharing a global module name."""
    spec = importlib.util.spec_from_file_location(
        "mvp_runs3_archive_fig_data", HERE / "archive_fig_data.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_archive_renderer_declares_all_required_tables_and_type42_output():
    """The archive must be self-sufficient rather than silently reading simulation logs."""
    archive = load_archive_renderer()

    assert archive.ARCHIVE_FILES == {
        "figA": "figA_floor_vs_load.csv",
        "figC": "figC_lb_depends_on_bottleneck.csv",
        "figI2": "figI2_cc_lb_tuning_coupled.csv",
        "figS1_samples": "figS1_path_samples.csv",
        "figS1_markers": "figS1_markers.csv",
        "figS2": "figS2_load_sweep.csv",
    }
    assert archive.mpl.rcParams["pdf.fonttype"] == 42
    assert archive.mpl.rcParams["ps.fonttype"] == 42


def test_existing_archive_has_every_plotted_coordinate_and_error_bar():
    """The retained archive must cover all five figures without a raw simulation file."""
    archive = HERE / "archive_data"

    def rows(name):
        with (archive / name).open(newline="") as stream:
            return list(csv.DictReader(stream))

    assert len(rows("figA_floor_vs_load.csv")) == 6
    assert len(rows("figC_lb_depends_on_bottleneck.csv")) == 4
    assert len(rows("figI2_cc_lb_tuning_coupled.csv")) == 12
    assert len(rows("figS1_path_samples.csv")) == 5089
    assert {row["metric"] for row in rows("figS1_markers.csv")} == {"floor_us", "avg_delay_us", "target_us"}
    assert len(rows("figS2_load_sweep.csv")) == 5
