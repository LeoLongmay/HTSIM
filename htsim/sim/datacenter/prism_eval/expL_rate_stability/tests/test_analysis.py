"""Behavioral tests for ExpL delivery-rate aggregation and stability metrics."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


DATACENTER = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(DATACENTER))

from prism_eval.expL_rate_stability.analyze import (
    RateBin,
    aggregate_bins,
    centered_mean,
    median_trajectory,
    parse_sink_rate,
    stability_metrics,
    write_analysis,
)


def test_aggregate_bins_sums_all_sinks_at_the_same_time():
    """Dropping a sink would understate an aggregate delivery-rate bin."""
    records = [(0.000010, 1, 20.0), (0.000010, 2, 30.0), (0.000020, 1, 40.0)]

    bins = aggregate_bins(records, bin_us=10)

    assert [(bin_.time_us, bin_.rate_gbps) for bin_ in bins] == [(10.0, 50.0), (20.0, 40.0)]


def test_centered_mean_never_uses_samples_outside_the_half_width():
    """An overly wide display window would conceal short delivery-rate changes."""
    bins = [RateBin(10.0, 0.0), RateBin(20.0, 100.0), RateBin(30.0, 0.0)]

    assert [bin_.rate_gbps for bin_ in centered_mean(bins, width_us=20)] == [50.0, 100.0, 50.0]


def test_stability_metrics_use_unfiltered_steady_window_and_report_settling():
    """Using display smoothing for metrics would hide real steady-window variation."""
    bins = [RateBin(float(time_us), 100.0 if time_us >= 1000 else 20.0) for time_us in range(0, 6501, 10)]

    metrics = stability_metrics(bins, steady_us=(1000, 6000))

    assert metrics.coefficient_of_variation == pytest.approx(0.0)
    assert metrics.normalized_p95_p5 == pytest.approx(0.0)
    assert metrics.settling_time_us == pytest.approx(1000.0)


def test_settling_time_does_not_precede_the_steady_metric_window():
    """Pre-window samples must not make a 1--6 ms stability metric settle early."""
    bins = [RateBin(float(time_us), 100.0) for time_us in range(0, 6501, 10)]

    metrics = stability_metrics(bins, steady_us=(1000, 6000))

    assert metrics.settling_time_us == pytest.approx(1000.0)


def test_settling_time_does_not_use_samples_after_the_steady_metric_window():
    """A candidate without a complete 200-us in-window horizon is unavailable."""
    bins = [
        RateBin(float(time_us), 0.0 if time_us % 200 == 0 and time_us <= 5800 else 100.0)
        for time_us in range(1000, 6101, 10)
    ]

    metrics = stability_metrics(bins, steady_us=(1000, 6000))

    assert metrics.valid is True
    assert metrics.settling_time_us is None


def test_insufficient_nonzero_steady_samples_are_invalid():
    """A sparse trace cannot support a meaningful stability estimate."""
    metrics = stability_metrics([RateBin(1000.0, 0.0)], steady_us=(1000, 6000))

    assert metrics.valid is False


def test_parse_sink_rate_uses_only_sink_rate_records_and_converts_to_gbps(tmp_path):
    """Including another event type would contaminate the delivery-rate signal."""
    sink = tmp_path / "trace.sink.txt"
    sink.write_text(
        "0.000010 Type UEC_SINK ID 7 Ev RATE CAck 1 ReorderBuffer 0 Rate 25000000000\n"
        "0.000010 Type QUEUE ID 7 Ev RATE Rate 90000000000\n"
        "0.000020 Type UEC_SINK ID 8 Ev ACK CAck 1 ReorderBuffer 0\n",
        encoding="ascii",
    )

    assert parse_sink_rate(sink) == [(0.00001, 7, 25.0)]


def test_aggregate_bins_fills_only_the_gap_between_observed_bins():
    """Missing interior samples must be visible without inventing leading or trailing data."""
    bins = aggregate_bins([(0.000010, 1, 10.0), (0.000030, 1, 30.0)], bin_us=10)

    assert [(bin_.time_us, bin_.rate_gbps) for bin_ in bins] == [
        (10.0, 10.0),
        (20.0, 0.0),
        (30.0, 30.0),
    ]


def test_median_trajectory_keeps_aligned_timestamps_and_uses_pointwise_medians():
    """A mean or cross-time median would distort the five-seed plotted trajectory."""
    trajectory = median_trajectory([
        [RateBin(10.0, 10.0), RateBin(20.0, 100.0)],
        [RateBin(10.0, 30.0), RateBin(20.0, 50.0)],
        [RateBin(10.0, 20.0), RateBin(20.0, 75.0)],
    ])

    assert trajectory == [RateBin(10.0, 20.0), RateBin(20.0, 75.0)]


def test_write_analysis_emits_per_seed_and_median_aggregate_csv_rows(tmp_path):
    """Plotting must keep raw seed values distinct from the smoothed five-seed median."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    for seed in (13, 14, 15, 16, 17):
        case_id = f"symmetric_ops_s{seed}"
        (raw_dir / f"rate_{case_id}.sink.txt").write_text(
            "0.001000 Type UEC_SINK ID 1 Ev RATE CAck 1 ReorderBuffer 0 Rate 10000000000\n"
            "0.001010 Type UEC_SINK ID 1 Ev RATE CAck 1 ReorderBuffer 0 Rate 20000000000\n",
            encoding="ascii",
        )
        (raw_dir / f"{case_id}.manifest.json").write_text(
            "{\"kind\": \"primary\", \"condition\": \"symmetric\", "
            f"\"arm\": \"ops\", \"beta\": null, \"seed\": {seed}, "
            f"\"output_files\": {{\"sink\": {{\"filename\": \"rate_{case_id}.sink.txt\"}}}}}}",
            encoding="ascii",
        )

    write_analysis(raw_dir, tmp_path / "data")

    rate_rows = (tmp_path / "data" / "rate_series.csv").read_text(encoding="ascii").splitlines()
    summary_rows = (tmp_path / "data" / "stability_summary.csv").read_text(encoding="ascii").splitlines()
    assert rate_rows[0] == "kind,condition,arm,beta,seed,time_us,rate_gbps,display_rate_gbps"
    assert len(rate_rows) == 13
    assert any(",aggregate,1000.0,10.0,15.0" in row for row in rate_rows)
    assert summary_rows[0].startswith("kind,condition,arm,beta,seed,")
    assert len(summary_rows) == 7


def test_write_analysis_rejects_a_group_without_all_five_locked_seeds(tmp_path):
    """A four-seed median must not be mislabeled as the locked five-seed aggregate."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    for seed in (13, 14, 15, 16):
        case_id = f"symmetric_ops_s{seed}"
        (raw_dir / f"rate_{case_id}.sink.txt").write_text(
            "0.001000 Type UEC_SINK ID 1 Ev RATE CAck 1 ReorderBuffer 0 Rate 10000000000\n",
            encoding="ascii",
        )
        (raw_dir / f"{case_id}.manifest.json").write_text(
            "{\"kind\": \"primary\", \"condition\": \"symmetric\", "
            f"\"arm\": \"ops\", \"beta\": null, \"seed\": {seed}, "
            f"\"output_files\": {{\"sink\": {{\"filename\": \"rate_{case_id}.sink.txt\"}}}}}}",
            encoding="ascii",
        )

    with pytest.raises(ValueError, match="exactly seeds"):
        write_analysis(raw_dir, tmp_path / "data")
