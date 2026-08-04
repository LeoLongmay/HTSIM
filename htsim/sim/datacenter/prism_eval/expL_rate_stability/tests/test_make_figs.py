"""Behavioral tests for ExpL's publication figure renderer."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest


DATACENTER = Path(__file__).resolve().parents[3]
MAKE_FIGS = DATACENTER / "prism_eval" / "expL_rate_stability" / "make_figs.py"
sys.path.insert(0, str(DATACENTER))

from prism_eval.expL_rate_stability.make_figs import render


RATE_FIELDS = (
    "kind", "condition", "arm", "beta", "seed", "time_us", "rate_gbps",
    "display_rate_gbps",
)
SUMMARY_FIELDS = (
    "kind", "condition", "arm", "beta", "seed", "valid", "steady_samples",
    "steady_mean_gbps", "coefficient_of_variation", "normalized_p95_p5",
    "settling_time_us",
)


def write_fixture_csvs(data_dir: Path, *, invalid_aggregate: bool = False) -> None:
    """Write a complete, deliberately unordered minimal rendering fixture."""
    data_dir.mkdir(parents=True)
    rate_rows: list[dict[str, object]] = []
    for condition, baseline in (("symmetric", 80.0), ("asymmetric", 60.0)):
        for index, arm in enumerate(("ops", "reps", "strack", "decmt")):
            for time_us, offset in ((0.0, 0.0), (1000.0, 10.0)):
                rate_rows.append({
                    "kind": "primary", "condition": condition, "arm": arm,
                    "beta": "", "seed": "aggregate", "time_us": time_us,
                    "rate_gbps": baseline + index + offset,
                    "display_rate_gbps": baseline + index + offset,
                })
        for seed, seed_offset in zip((13, 14, 15, 16, 17), (-4.0, -2.0, 0.0, 2.0, 8.0)):
            for time_us, offset in ((0.0, 0.0), (1000.0, 10.0)):
                rate_rows.append({
                    "kind": "primary", "condition": condition, "arm": "decmt",
                    "beta": "", "seed": seed, "time_us": time_us,
                    "rate_gbps": baseline + 3.0 + seed_offset + offset,
                    "display_rate_gbps": "",
                })
    for beta, offset in (("0.15", 0.0), ("0.3", 2.0), ("0.5", 4.0), ("1.0", 6.0)):
        for time_us, rise in ((0.0, 0.0), (1000.0, 8.0)):
            rate_rows.append({
                "kind": "beta", "condition": "", "arm": "",
                "beta": beta, "seed": "aggregate", "time_us": time_us,
                "rate_gbps": 50.0 + offset + rise,
                "display_rate_gbps": 50.0 + offset + rise,
            })
    with (data_dir / "rate_series.csv").open("w", encoding="ascii", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=RATE_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rate_rows)
    with (data_dir / "stability_summary.csv").open("w", encoding="ascii", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=SUMMARY_FIELDS, lineterminator="\n")
        writer.writeheader()
        summary_rows = [
            {
                "kind": "primary", "condition": condition, "arm": arm, "beta": "",
                "seed": "aggregate", "valid": "True", "steady_samples": "500",
                "steady_mean_gbps": "100.0", "coefficient_of_variation": "0.1",
                "normalized_p95_p5": "0.2", "settling_time_us": "1000.0",
            }
            for condition in ("symmetric", "asymmetric")
            for arm in ("ops", "reps", "strack", "decmt")
        ] + [
            {
                "kind": "beta", "condition": "", "arm": "", "beta": beta,
                "seed": "aggregate", "valid": "True", "steady_samples": "500",
                "steady_mean_gbps": "100.0", "coefficient_of_variation": "0.1",
                "normalized_p95_p5": "0.2", "settling_time_us": "1000.0",
            }
            for beta in ("1.0", "0.5", "0.3", "0.15")
        ]
        if invalid_aggregate:
            summary_rows[0]["valid"] = "False"
            summary_rows[0]["settling_time_us"] = ""
        writer.writerows(summary_rows)


def test_renderer_uses_required_labels_and_type42_embedding():
    """Non-embedded fonts or renamed arms would make the paper artifact unusable."""
    source = MAKE_FIGS.read_text()
    for label in ("OPS", "REPS", "STrack", "DecMT"):
        assert label in source
    assert 'mpl.rcParams["pdf.fonttype"] = 42' in source
    assert 'mpl.rcParams["ps.fonttype"] = 42' in source


def test_renderer_writes_both_figures_from_minimal_csv_fixture(tmp_path):
    """Missing a primary or beta figure would break the locked publication interface."""
    write_fixture_csvs(tmp_path / "data")

    render(tmp_path / "data", tmp_path / "figs")

    for stem in ("figL1_rate_timeseries", "figL2_beta_timeseries"):
        assert (tmp_path / "figs" / f"{stem}.png").is_file()
        assert (tmp_path / "figs" / f"{stem}.pdf").is_file()


def test_renderer_writes_legend_free_type42_primary_panels_in_tbps(tmp_path):
    """Split primary panels must retain a publication-ready independent interface."""
    write_fixture_csvs(tmp_path / "data")

    render(tmp_path / "data", tmp_path / "figs")

    for stem in ("figL1_rate_symmetric", "figL1_rate_asymmetric"):
        for extension in ("png", "pdf"):
            assert (tmp_path / "figs" / f"{stem}.{extension}").is_file()
    source = MAKE_FIGS.read_text()
    assert "Sending rate (Tbps)" in source
    assert 'SPLIT_PRIMARY_LABEL_COORDS = {"symmetric": (-0.18, 0.40), "asymmetric": (-0.19, 0.38)}' in source
    assert "SPLIT_PANEL_FONT_SIZE = 18" in source
    assert "(0.2, 2.0)" in source
    assert "(0.0, 1.2)" in source


def test_renderer_rejects_an_invalid_or_unsettled_aggregate_before_writing_figures(tmp_path):
    """Calling the renderer directly must not bypass the formal publication gate."""
    write_fixture_csvs(tmp_path / "data", invalid_aggregate=True)

    with pytest.raises(ValueError, match="invalid or unsettled"):
        render(tmp_path / "data", tmp_path / "figs")

    assert not (tmp_path / "figs").exists()


def test_renderer_draws_only_the_decmt_interquartile_bands_in_each_primary_view(tmp_path, monkeypatch):
    """Standalone panels retain only DecMT's band and convert it from Gbps to Tbps."""
    write_fixture_csvs(tmp_path / "data")
    import matplotlib.axes

    calls: list[tuple[object, object, object]] = []
    original = matplotlib.axes.Axes.fill_between

    def capture_band(self, x, y1, y2, *args, **kwargs):
        calls.append((tuple(x), tuple(y1), tuple(y2)))
        return original(self, x, y1, y2, *args, **kwargs)

    monkeypatch.setattr(matplotlib.axes.Axes, "fill_between", capture_band)
    render(tmp_path / "data", tmp_path / "figs")

    assert calls == [
        ((0.0, 1.0), (81.0, 91.0), (85.0, 95.0)),
        ((0.0, 1.0), (61.0, 71.0), (65.0, 75.0)),
        ((0.0, 1.0), (0.081, 0.091), (0.085, 0.095)),
        ((0.0, 1.0), (0.061, 0.071), (0.065, 0.075)),
    ]


def test_renderer_draws_beta_curves_in_locked_order(tmp_path, monkeypatch):
    """CSV iteration order must not silently change the beta sensitivity comparison."""
    write_fixture_csvs(tmp_path / "data")
    import matplotlib.axes

    labels: list[str] = []
    original = matplotlib.axes.Axes.plot

    def capture_plot(self, *args, **kwargs):
        label = kwargs.get("label")
        if isinstance(label, str) and label.startswith("β="):
            labels.append(label)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(matplotlib.axes.Axes, "plot", capture_plot)
    render(tmp_path / "data", tmp_path / "figs")

    assert labels == ["β=1.0", "β=0.5", "β=0.3", "β=0.15"]
