import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination import (
    run_distribution,
)
from htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.analyze_distribution import (
    analyze_distribution,
)
from htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.tests.test_analyze import (
    _row,
    _write_bundle,
    _write_csv,
)


WARMUP_PS = 1_000_000_000
BASE_RTT_PS = 14_000_000
BIN_WIDTH_PS = 4 * BASE_RTT_PS


def _read_csv(path):
    with path.open(newline="", encoding="ascii") as stream:
        return list(csv.DictReader(stream))


def _write_distribution_bundle(root, *, mode="prism_recycle", complete_post_window=True):
    """Write one trace with terminal windows [t-width, t) and [t, t+width)."""
    _write_bundle(root, "recoverable", mode, replacement_chain="complete")
    run_id = f"fixture_recoverable_{mode}_s13"
    prefix = root / run_id

    with prefix.with_suffix(".ack.csv").open(newline="", encoding="ascii") as stream:
        ack_rows = list(csv.DictReader(stream))
    # Keep the replacement admission but make all observed base RTTs identical.
    ack_rows[0].update(time_ps=900_000_000, newly_acked_bytes=100)
    ack_rows[1].update(time_ps=WARMUP_PS + 10_000_000, newly_acked_bytes=900)
    ack_rows[2].update(time_ps=2_110_000_000, newly_acked_bytes=0)
    for row in ack_rows:
        row["base_rtt_ps"] = str(BASE_RTT_PS)
    ack_rows.extend([
        _row(
            "ack", run_id=run_id, seed=13, scenario="recoverable", event_seq=9,
            time_ps=2_150_000_000, flow_id=1, epoch_id=2, acked_psn=3, entropy=0,
            physical_path_id=10, raw_rtt_ps=18_000_000, base_rtt_ps=BASE_RTT_PS,
            qdelay_ps=4_000_000, ecn=0, genuine_sample=1, retransmitted=0,
            selection_source="fresh", newly_acked_bytes=100,
            new_data_bytes_sent_total=200, cwnd_bytes=12_000,
        ),
        _row(
            "ack", run_id=run_id, seed=13, scenario="recoverable", event_seq=10,
            time_ps=2_160_000_000, flow_id=2, epoch_id=2, acked_psn=2, entropy=0,
            physical_path_id=20, raw_rtt_ps=16_000_000, base_rtt_ps=BASE_RTT_PS,
            qdelay_ps=2_000_000, ecn=0, genuine_sample=1, retransmitted=0,
            selection_source="fresh", newly_acked_bytes=100,
            new_data_bytes_sent_total=1_000, cwnd_bytes=13_000,
        ),
        _row(
            "ack", run_id=run_id, seed=13, scenario="recoverable", event_seq=21,
            time_ps=2_220_000_000, flow_id=1, epoch_id=2, acked_psn=4, entropy=0,
            physical_path_id=10, raw_rtt_ps=18_000_000, base_rtt_ps=BASE_RTT_PS,
            qdelay_ps=4_000_000, ecn=0, genuine_sample=1, retransmitted=0,
            selection_source="fresh", newly_acked_bytes=80,
            new_data_bytes_sent_total=280, cwnd_bytes=12_000,
        ),
        _row(
            "ack", run_id=run_id, seed=13, scenario="recoverable", event_seq=22,
            time_ps=2_230_000_000, flow_id=2, epoch_id=2, acked_psn=3, entropy=0,
            physical_path_id=20, raw_rtt_ps=16_000_000, base_rtt_ps=BASE_RTT_PS,
            qdelay_ps=2_000_000, ecn=0, genuine_sample=1, retransmitted=0,
            selection_source="fresh", newly_acked_bytes=320,
            new_data_bytes_sent_total=1_320, cwnd_bytes=13_000,
        ),
    ])
    if complete_post_window:
        ack_rows.append(_row(
            "ack", run_id=run_id, seed=13, scenario="recoverable", event_seq=23,
            time_ps=2_256_000_000, flow_id=2, epoch_id=2, acked_psn=4, entropy=0,
            physical_path_id=20, raw_rtt_ps=16_000_000, base_rtt_ps=BASE_RTT_PS,
            qdelay_ps=2_000_000, ecn=0, genuine_sample=1, retransmitted=0,
            selection_source="fresh", newly_acked_bytes=0,
            new_data_bytes_sent_total=1_320, cwnd_bytes=13_000,
        ))
    _write_csv(prefix.with_suffix(".ack.csv"), "ack", ack_rows)

    with prefix.with_suffix(".coordination.csv").open(newline="", encoding="ascii") as stream:
        coordination_rows = list(csv.DictReader(stream))
    terminal = coordination_rows[-1]
    terminal.update(event_seq=20, time_ps=2_200_000_000)
    _write_csv(prefix.with_suffix(".coordination.csv"), "coordination", coordination_rows)

    with prefix.with_suffix(".pathmap.csv").open(newline="", encoding="ascii") as stream:
        pathmap_rows = list(csv.DictReader(stream))
    pathmap_rows.append(_row(
        "pathmap", run_id=run_id, flow_id=1, entropy=1, physical_path_id=10,
        resolution_status="resolved", queue_fingerprint="1", bottleneck_rate_gbps=25,
        contains_reduced_link=1, ordered_queue_ids="1",
    ))
    _write_csv(prefix.with_suffix(".pathmap.csv"), "pathmap", pathmap_rows)
    return prefix


class DistributionRunnerTests(unittest.TestCase):
    def test_distribution_rows_are_the_locked_twelve_trial_matrix(self):
        rows = run_distribution._distribution_rows()

        expected = {
            (mode, scenario, seed, degraded_links, 25.0)
            for mode in ("original_prism", "prism_recycle")
            for scenario, degraded_links in (("recoverable", 2), ("persistent", 8))
            for seed in (13, 14, 15)
        }
        actual = {
            (
                row["mode"],
                row["scenario"],
                int(row["seed"]),
                int(row["degraded_links"]),
                float(row["degraded_capacity_gbps"]),
            )
            for row in rows
        }

        self.assertEqual(len(rows), 12)
        self.assertEqual(actual, expected)

    def test_distribution_rows_reject_a_matrix_with_full_prism(self):
        rows = list(run_distribution._distribution_rows())
        rows[0] = {**rows[0], "mode": "full_prism"}

        with self.assertRaisesRegex(ValueError, "locked 12 M3 distribution rows"):
            run_distribution._validate_distribution_rows(rows)

    def test_main_dispatches_each_locked_row_to_distribution_output(self):
        with patch.object(run_distribution.run, "_run_one") as run_one:
            result = run_distribution.main([])

        self.assertEqual(result, 0)
        self.assertEqual(run_one.call_count, 12)
        self.assertEqual(
            {
                (
                    call.kwargs["phase"],
                    call.kwargs["output"],
                    call.kwargs["mode"],
                    call.kwargs["scenario"],
                    call.kwargs["seed"],
                    call.kwargs["degraded_links"],
                    call.kwargs["degraded_capacity_gbps"],
                )
                for call in run_one.call_args_list
            },
            {
                (
                    "distribution",
                    run_distribution.OUTPUT,
                    mode,
                    scenario,
                    seed,
                    degraded_links,
                    25.0,
                )
                for mode in ("original_prism", "prism_recycle")
                for scenario, degraded_links in (("recoverable", 2), ("persistent", 8))
                for seed in (13, 14, 15)
            },
        )


class DistributionAnalysisTests(unittest.TestCase):
    def test_writes_resolved_post_warmup_bins_and_terminal_anchored_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_distribution_bundle(root)
            output = root / "aggregate"

            result = analyze_distribution(root, output)

            bins = _read_csv(output / "distribution_bins.csv")
            effects = _read_csv(output / "refresh_effects.csv")
            summary = _read_csv(output / "summary.csv")

        self.assertEqual(len(result["distribution_bins"]), len(bins))
        self.assertEqual(len(effects), 1)
        self.assertEqual(effects[0]["terminal_time_ps"], "2200000000")
        self.assertEqual(effects[0]["pre_window_start_ps"], "2144000000")
        self.assertEqual(effects[0]["pre_window_end_ps"], "2200000000")
        self.assertEqual(effects[0]["post_window_start_ps"], "2200000000")
        self.assertEqual(effects[0]["post_window_end_ps"], "2256000000")
        self.assertEqual(effects[0]["pre_throttled_ratio"], "0.5")
        self.assertEqual(effects[0]["post_throttled_ratio"], "0.2")
        self.assertEqual(effects[0]["throttled_ratio_change"], "-0.3")

        aligned_bin = next(row for row in bins if row["bin_start_ps"] == "2120000000")
        self.assertEqual(aligned_bin["bin_width_ps"], str(BIN_WIDTH_PS))
        self.assertEqual(aligned_bin["throttled_acked_bytes"], "100")
        self.assertEqual(aligned_bin["healthy_acked_bytes"], "100")
        self.assertEqual(aligned_bin["throttled_ratio"], "0.5")
        self.assertEqual(sum(int(row["throttled_acked_bytes"]) for row in bins), 180)
        self.assertEqual(sum(int(row["healthy_acked_bytes"]) for row in bins), 1_320)
        self.assertEqual(summary[0]["base_rtt_ps"], str(BASE_RTT_PS))
        self.assertEqual(summary[0]["bin_width_ps"], str(BIN_WIDTH_PS))
        self.assertEqual(summary[0]["refresh_effect_count"], "1")

    def test_refresh_effect_blanks_ratio_for_partial_observation_window(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_distribution_bundle(root, complete_post_window=False)

            analyze_distribution(root, root / "aggregate")
            effects = _read_csv(root / "aggregate" / "refresh_effects.csv")

        self.assertEqual(effects[0]["pre_throttled_ratio"], "0.5")
        self.assertEqual(effects[0]["post_window_complete"], "0")
        self.assertEqual(effects[0]["post_throttled_ratio"], "")
        self.assertEqual(effects[0]["throttled_ratio_change"], "")

    def test_rejects_mixed_ack_base_rtt_in_one_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prefix = _write_distribution_bundle(root)
            with prefix.with_suffix(".ack.csv").open(newline="", encoding="ascii") as stream:
                rows = list(csv.DictReader(stream))
            rows[-1]["base_rtt_ps"] = "15000000"
            _write_csv(prefix.with_suffix(".ack.csv"), "ack", rows)

            with self.assertRaisesRegex(ValueError, "identical ACK base RTT"):
                analyze_distribution(root, root / "aggregate")

    def test_rejects_ack_path_that_disagrees_with_resolved_pathmap(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prefix = _write_distribution_bundle(root)
            with prefix.with_suffix(".ack.csv").open(newline="", encoding="ascii") as stream:
                rows = list(csv.DictReader(stream))
            rows[-1]["physical_path_id"] = "99"
            _write_csv(prefix.with_suffix(".ack.csv"), "ack", rows)

            with self.assertRaisesRegex(ValueError, "physical path ID mismatch"):
                analyze_distribution(root, root / "aggregate")


if __name__ == "__main__":
    unittest.main()
