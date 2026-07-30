"""Behavioral tests for the ExpJ DecMT component-ablation figure."""

from __future__ import annotations

import sys
from pathlib import Path


EXPERIMENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXPERIMENT_DIR))

import make_figs  # noqa: E402
import run  # noqa: E402


def _summary_rows():
    return [
        {
            "arm": arm,
            "failed_links": failed,
            "n_seeds": 10,
            "mean_goodput_gbps": 1.0 + position,
            "std_goodput_gbps": 0.1,
            "mean_avg_fct_us": 2_000.0 + position,
            "std_avg_fct_us": 200.0,
            "mean_p99_fct_us": 3_000.0 + position,
            "std_p99_fct_us": 300.0,
        }
        for position, arm in enumerate(run.ARMS)
        for failed in run.FAILED_LINKS
    ]


def test_render_creates_three_panel_figure(tmp_path):
    """The paper artifact is emitted in both requested formats from summary rows."""
    make_figs.render(_summary_rows(), tmp_path)

    assert (tmp_path / "figJ1_decmt_ablation.pdf").is_file()
    assert (tmp_path / "figJ1_decmt_ablation.png").is_file()


def test_render_rejects_summary_without_the_failed_zero_control(tmp_path):
    """The compact control comparison is mandatory, not an optional annotation."""
    rows = [row for row in _summary_rows() if row["failed_links"] != 0]

    try:
        make_figs.render(rows, tmp_path)
    except ValueError as exc:
        assert "missing summary rows" in str(exc)
    else:
        raise AssertionError("renderer accepted a missing failed=0 control")
