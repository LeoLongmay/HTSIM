import csv
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination import (
    run_distribution,
)
from htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination import (
    analyze_distribution as distribution_analysis,
)
from htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.analyze_distribution import (
    analyze_distribution,
)
from htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination import (
    make_distribution_fig,
)
from htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.tests.test_analyze import (
    _row,
    _write_bundle,
    _write_csv,
)


WARMUP_PS = 1_000_000_000
BASE_RTT_PS = 14_000_000
BIN_WIDTH_PS = 4 * BASE_RTT_PS
MODES = ("original_prism", "prism_recycle")
SCENARIOS = ("recoverable", "persistent")
SEEDS = (13, 14, 15)


def _read_csv(path):
    with path.open(newline="", encoding="ascii") as stream:
        return list(csv.DictReader(stream))


def _write_distribution_bundle(root, *, scenario="recoverable", mode="prism_recycle",
                               seed=13, complete_post_window=True):
    """Write one trace with terminal windows [t-width, t) and [t, t+width)."""
    _write_bundle(root, scenario, mode, seed=seed, replacement_chain="complete")
    run_id = f"fixture_{scenario}_{mode}_s{seed}"
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
            "ack", run_id=run_id, seed=seed, scenario=scenario, event_seq=9,
            time_ps=2_150_000_000, flow_id=1, epoch_id=2, acked_psn=3, entropy=0,
            physical_path_id=10, raw_rtt_ps=18_000_000, base_rtt_ps=BASE_RTT_PS,
            qdelay_ps=4_000_000, ecn=0, genuine_sample=1, retransmitted=0,
            selection_source="fresh", newly_acked_bytes=100,
            new_data_bytes_sent_total=200, cwnd_bytes=12_000,
        ),
        _row(
            "ack", run_id=run_id, seed=seed, scenario=scenario, event_seq=10,
            time_ps=2_160_000_000, flow_id=2, epoch_id=2, acked_psn=2, entropy=0,
            physical_path_id=20, raw_rtt_ps=16_000_000, base_rtt_ps=BASE_RTT_PS,
            qdelay_ps=2_000_000, ecn=0, genuine_sample=1, retransmitted=0,
            selection_source="fresh", newly_acked_bytes=100,
            new_data_bytes_sent_total=1_000, cwnd_bytes=13_000,
        ),
        _row(
            "ack", run_id=run_id, seed=seed, scenario=scenario, event_seq=21,
            time_ps=2_220_000_000, flow_id=1, epoch_id=2, acked_psn=4, entropy=0,
            physical_path_id=10, raw_rtt_ps=18_000_000, base_rtt_ps=BASE_RTT_PS,
            qdelay_ps=4_000_000, ecn=0, genuine_sample=1, retransmitted=0,
            selection_source="fresh", newly_acked_bytes=80,
            new_data_bytes_sent_total=280, cwnd_bytes=12_000,
        ),
        _row(
            "ack", run_id=run_id, seed=seed, scenario=scenario, event_seq=22,
            time_ps=2_230_000_000, flow_id=2, epoch_id=2, acked_psn=3, entropy=0,
            physical_path_id=20, raw_rtt_ps=16_000_000, base_rtt_ps=BASE_RTT_PS,
            qdelay_ps=2_000_000, ecn=0, genuine_sample=1, retransmitted=0,
            selection_source="fresh", newly_acked_bytes=320,
            new_data_bytes_sent_total=1_320, cwnd_bytes=13_000,
        ),
    ])
    if complete_post_window:
        ack_rows.append(_row(
            "ack", run_id=run_id, seed=seed, scenario=scenario, event_seq=23,
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


def _write_locked_distribution_matrix(root, *, complete_post_window=True):
    target = None
    for mode in MODES:
        for scenario in SCENARIOS:
            for seed in SEEDS:
                if (mode, scenario, seed) == ("prism_recycle", "recoverable", 13):
                    target = _write_distribution_bundle(
                        root, scenario=scenario, mode=mode, seed=seed,
                        complete_post_window=complete_post_window,
                    )
                else:
                    _write_bundle(root, scenario, mode, seed=seed)
    return target


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
    def _assert_rejects_written_admission_mutation(self, mutate, error):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prefix = _write_locked_distribution_matrix(root)
            with prefix.with_suffix(".token.csv").open(newline="", encoding="ascii") as stream:
                token_rows = list(csv.DictReader(stream))
            with prefix.with_suffix(".ack.csv").open(newline="", encoding="ascii") as stream:
                ack_rows = list(csv.DictReader(stream))
            mutate(token_rows, ack_rows)
            _write_csv(prefix.with_suffix(".token.csv"), "token", token_rows)
            _write_csv(prefix.with_suffix(".ack.csv"), "ack", ack_rows)

            with self.assertRaisesRegex(ValueError, error):
                analyze_distribution(root, root / "aggregate")

    def test_chain_specs_share_evidence_between_terminals_in_one_round(self):
        records = [
            {
                "action": "invalidate",
                "time_ps": 2_100_000_000,
                "event_seq": 5,
                "flow_id": 1,
                "round_id": 1,
                "cache_slot": 3,
                "cache_generation": 10,
                "refresh_complete": False,
            },
            {
                "action": "round_complete_progress",
                "time_ps": 2_200_000_000,
                "event_seq": 8,
                "flow_id": 1,
                "round_id": 1,
                "cache_slot": 0,
                "cache_generation": 0,
                "refresh_complete": True,
            },
            {
                "action": "round_complete_progress",
                "time_ps": 2_300_000_000,
                "event_seq": 9,
                "flow_id": 1,
                "round_id": 1,
                "cache_slot": 0,
                "cache_generation": 0,
                "refresh_complete": True,
            },
        ]

        specs = distribution_analysis._chain_specs(records, "prism_recycle")

        self.assertEqual(len(specs), 2)
        self.assertIs(specs[0]["evidence"], specs[1]["evidence"])
        self.assertNotIn("invalidations", specs[0])
        self.assertNotIn("retains", specs[0])
        self.assertNotIn("admissions", specs[0])

    def test_rejects_admission_entropy_that_differs_from_referenced_ack(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prefix = _write_locked_distribution_matrix(root)
            with prefix.with_suffix(".token.csv").open(newline="", encoding="ascii") as stream:
                token_rows = list(csv.DictReader(stream))
            token_rows[0]["entropy"] = "2"
            _write_csv(prefix.with_suffix(".token.csv"), "token", token_rows)

            with self.assertRaisesRegex(
                ValueError,
                r"token\.csv: entropy: value 2 differs from ACK entropy 1",
            ):
                analyze_distribution(root, root / "aggregate")

    def test_rejects_written_admission_not_after_its_referenced_ack(self):
        self._assert_rejects_written_admission_mutation(
            lambda tokens, _acks: tokens[0].update(event_seq="6"),
            r"token\.csv: event_seq: value 6 must be after ACK event 6",
        )

    def test_rejects_written_admission_with_mismatched_ack_flow(self):
        self._assert_rejects_written_admission_mutation(
            lambda tokens, _acks: tokens[0].update(flow_id="2"),
            r"token\.csv: flow_id: value 2 differs from ACK flow 1",
        )

    def test_rejects_written_admission_with_ecn_marked_ack(self):
        self._assert_rejects_written_admission_mutation(
            lambda _tokens, acks: acks[2].update(ecn="1"),
            r"ack\.csv: ecn: ACK event 6 must not be ECN-marked",
        )

    def test_accepts_written_admission_with_non_genuine_unmarked_ack(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prefix = _write_locked_distribution_matrix(root)
            with prefix.with_suffix(".ack.csv").open(newline="", encoding="ascii") as stream:
                ack_rows = list(csv.DictReader(stream))
            ack_rows[2].update(genuine_sample="0", ecn="0")
            _write_csv(prefix.with_suffix(".ack.csv"), "ack", ack_rows)

            analyze_distribution(root, root / "aggregate")
            summary = _read_csv(root / "aggregate" / "summary.csv")

        self.assertEqual(len(summary), 12)

    def test_rejects_written_admission_with_unsupported_operation(self):
        self._assert_rejects_written_admission_mutation(
            lambda tokens, _acks: tokens[0].update(operation="dequeue_bad_ack"),
            r"token\.csv: operation: value 'dequeue_bad_ack' cannot write an admission",
        )

    def test_rejects_written_admission_with_sentinel_cache_slot(self):
        self._assert_rejects_written_admission_mutation(
            lambda tokens, _acks: tokens[0].update(cache_slot="65535"),
            r"token\.csv: cache_slot: sentinel slot cannot write an admission",
        )

    def test_rejects_written_admission_with_zero_cache_generation(self):
        self._assert_rejects_written_admission_mutation(
            lambda tokens, _acks: tokens[0].update(cache_generation="0"),
            r"token\.csv: cache_generation: written admission requires a positive generation",
        )

    def test_rejects_original_prism_admission_entropy_that_differs_from_ack(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_locked_distribution_matrix(root)
            prefix = root / "fixture_recoverable_original_prism_s13"
            _write_csv(prefix.with_suffix(".token.csv"), "token", [_row(
                "token", run_id="fixture_recoverable_original_prism_s13", event_seq=3,
                time_ps=2_010_000_000, flow_id=1, operation="overwrite_good_ack",
                reason="admit", token_id=1, entropy=2, queue_depth_before=0,
                queue_depth_after=1, related_ack_event_seq=1, cache_slot=3,
                cache_generation=11, admission_written=1,
            )])

            with self.assertRaisesRegex(
                ValueError,
                r"token\.csv: entropy: value 2 differs from ACK entropy 0",
            ):
                analyze_distribution(root, root / "aggregate")

    def test_rejects_original_prism_admission_with_missing_referenced_ack(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_locked_distribution_matrix(root)
            prefix = root / "fixture_recoverable_original_prism_s13"
            _write_csv(prefix.with_suffix(".token.csv"), "token", [_row(
                "token", run_id="fixture_recoverable_original_prism_s13", event_seq=3,
                time_ps=2_010_000_000, flow_id=1, operation="enqueue_good_ack",
                reason="admit", token_id=1, entropy=0, queue_depth_before=0,
                queue_depth_after=1, related_ack_event_seq=999, cache_slot=3,
                cache_generation=11, admission_written=1,
            )])

            with self.assertRaisesRegex(
                ValueError,
                r"token\.csv: related_ack_event_seq: ACK event 999 does not exist",
            ):
                analyze_distribution(root, root / "aggregate")

    def test_validates_coordination_rows_for_original_prism_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_locked_distribution_matrix(root)
            prefix = root / "fixture_recoverable_original_prism_s13"
            with prefix.with_suffix(".coordination.csv").open(newline="", encoding="ascii") as stream:
                coordination_rows = list(csv.DictReader(stream))
            coordination_rows[0]["action"] = "invalid_action"
            _write_csv(prefix.with_suffix(".coordination.csv"), "coordination", coordination_rows)

            with self.assertRaisesRegex(ValueError, "unknown coordination action"):
                analyze_distribution(root, root / "aggregate")

    def test_streams_large_ack_trace_without_full_bundle_loader(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prefix = _write_locked_distribution_matrix(root)
            with prefix.with_suffix(".ack.csv").open(newline="", encoding="ascii") as stream:
                ack_rows = list(csv.DictReader(stream))
            for event_seq in range(24, 1_024):
                ack_rows.append(_row(
                    "ack", run_id="fixture_recoverable_prism_recycle_s13", seed=13,
                    scenario="recoverable", event_seq=event_seq,
                    time_ps=2_300_000_000 + event_seq, flow_id=1, epoch_id=2,
                    acked_psn=event_seq, entropy=0, physical_path_id=10,
                    raw_rtt_ps=18_000_000, base_rtt_ps=BASE_RTT_PS,
                    qdelay_ps=4_000_000, ecn=0, genuine_sample=1,
                    retransmitted=0, selection_source="fresh", newly_acked_bytes=7,
                    new_data_bytes_sent_total=7, cwnd_bytes=12_000,
                ))
            _write_csv(prefix.with_suffix(".ack.csv"), "ack", ack_rows)

            with patch(
                "htsim.sim.datacenter.add_motivation."
                "expM3_residual_spread_coordination.analyze_distribution."
                "load_trace_compact",
                side_effect=AssertionError("analyzer must stream trace rows"),
                create=True,
            ) as loader:
                analyze_distribution(root, root / "aggregate")
                loader.assert_not_called()
            summary = _read_csv(root / "aggregate" / "summary.csv")

        target = next(
            row for row in summary
            if row["run_id"] == "fixture_recoverable_prism_recycle_s13"
        )
        self.assertEqual(target["throttled_acked_bytes"], "7180")
        self.assertEqual(target["healthy_acked_bytes"], "1320")

    def test_writes_resolved_post_warmup_bins_and_terminal_anchored_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_locked_distribution_matrix(root)
            output = root / "aggregate"

            result = analyze_distribution(root, output)

            bins = _read_csv(output / "distribution_bins.csv")
            effects = _read_csv(output / "refresh_effects.csv")
            summary = _read_csv(output / "summary.csv")

        self.assertEqual(len(result["distribution_bins"]), len(bins))
        effect = next(row for row in effects if row["run_id"] == "fixture_recoverable_prism_recycle_s13")
        self.assertEqual(effect["terminal_time_ps"], "2200000000")
        self.assertEqual(effect["pre_window_start_ps"], "2144000000")
        self.assertEqual(effect["pre_window_end_ps"], "2200000000")
        self.assertEqual(effect["post_window_start_ps"], "2200000000")
        self.assertEqual(effect["post_window_end_ps"], "2256000000")
        self.assertEqual(effect["pre_throttled_ratio"], "0.5")
        self.assertEqual(effect["post_throttled_ratio"], "0.2")
        self.assertEqual(effect["throttled_ratio_change"], "-0.3")

        target_bins = [row for row in bins if row["run_id"] == "fixture_recoverable_prism_recycle_s13"]
        aligned_bin = next(row for row in target_bins if row["bin_start_ps"] == "2120000000")
        self.assertEqual(aligned_bin["bin_width_ps"], str(BIN_WIDTH_PS))
        self.assertEqual(aligned_bin["throttled_acked_bytes"], "100")
        self.assertEqual(aligned_bin["healthy_acked_bytes"], "100")
        self.assertEqual(aligned_bin["throttled_ratio"], "0.5")
        self.assertEqual(sum(int(row["throttled_acked_bytes"]) for row in target_bins), 180)
        self.assertEqual(sum(int(row["healthy_acked_bytes"]) for row in target_bins), 1_320)
        target_summary = next(row for row in summary if row["run_id"] == "fixture_recoverable_prism_recycle_s13")
        self.assertEqual(target_summary["base_rtt_ps"], str(BASE_RTT_PS))
        self.assertEqual(target_summary["bin_width_ps"], str(BIN_WIDTH_PS))
        self.assertEqual(target_summary["refresh_effect_count"], "1")

    def test_refresh_effect_blanks_ratio_for_partial_observation_window(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_locked_distribution_matrix(root, complete_post_window=False)

            analyze_distribution(root, root / "aggregate")
            effects = _read_csv(root / "aggregate" / "refresh_effects.csv")

        effect = next(row for row in effects if row["run_id"] == "fixture_recoverable_prism_recycle_s13")
        self.assertEqual(effect["pre_throttled_ratio"], "0.5")
        self.assertEqual(effect["post_window_complete"], "0")
        self.assertEqual(effect["post_throttled_ratio"], "")
        self.assertEqual(effect["throttled_ratio_change"], "")

    def test_rejects_mixed_ack_base_rtt_in_one_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prefix = _write_locked_distribution_matrix(root)
            with prefix.with_suffix(".ack.csv").open(newline="", encoding="ascii") as stream:
                rows = list(csv.DictReader(stream))
            rows[-1]["base_rtt_ps"] = "15000000"
            _write_csv(prefix.with_suffix(".ack.csv"), "ack", rows)

            with self.assertRaisesRegex(ValueError, "identical ACK base RTT"):
                analyze_distribution(root, root / "aggregate")

    def test_rejects_ack_path_that_disagrees_with_resolved_pathmap(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prefix = _write_locked_distribution_matrix(root)
            with prefix.with_suffix(".ack.csv").open(newline="", encoding="ascii") as stream:
                rows = list(csv.DictReader(stream))
            rows[-1]["physical_path_id"] = "99"
            _write_csv(prefix.with_suffix(".ack.csv"), "ack", rows)

            with self.assertRaisesRegex(ValueError, "physical path ID mismatch"):
                analyze_distribution(root, root / "aggregate")

    def test_rejects_missing_manifest_from_locked_trial_matrix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_distribution_bundle(root)

            with self.assertRaisesRegex(ValueError, "locked 12-case manifest set"):
                analyze_distribution(root, root / "aggregate")

    def test_rejects_duplicate_manifest_from_locked_trial_matrix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_locked_distribution_matrix(root)
            duplicate_root = root / "duplicate"
            duplicate_root.mkdir()
            for source in root.glob("fixture_recoverable_prism_recycle_s13.*"):
                shutil.copyfile(source, duplicate_root / source.name)

            with self.assertRaisesRegex(ValueError, "locked 12-case manifest set"):
                analyze_distribution(root, root / "aggregate")

    def test_rejects_unexpected_manifest_scenario_or_seed(self):
        for field, value in (("scenario", "unexpected"), ("seed", 16)):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                _write_locked_distribution_matrix(root)
                manifest_path = root / "fixture_recoverable_prism_recycle_s13.manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="ascii"))
                manifest["analysis_config"][field] = value
                manifest_path.write_text(json.dumps(manifest), encoding="ascii")

                with self.assertRaisesRegex(ValueError, "locked 12-case manifest set"):
                    analyze_distribution(root, root / "aggregate")

    def test_complete_zero_acked_byte_effect_windows_blank_ratios_and_change(self):
        windows = {
            "pre": (2_144_000_000, 2_200_000_000),
            "post": (2_200_000_000, 2_256_000_000),
        }
        for name, (start_ps, end_ps) in windows.items():
            with self.subTest(window=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                prefix = _write_locked_distribution_matrix(root)
                with prefix.with_suffix(".ack.csv").open(newline="", encoding="ascii") as stream:
                    rows = list(csv.DictReader(stream))
                for row in rows:
                    if start_ps <= int(row["time_ps"]) < end_ps:
                        row["newly_acked_bytes"] = "0"
                _write_csv(prefix.with_suffix(".ack.csv"), "ack", rows)

                analyze_distribution(root, root / "aggregate")
                effects = _read_csv(root / "aggregate" / "refresh_effects.csv")

            effect = next(row for row in effects if row["run_id"] == "fixture_recoverable_prism_recycle_s13")
            self.assertEqual(effect[f"{name}_window_complete"], "1")
            self.assertEqual(effect[f"{name}_throttled_ratio"], "")
            self.assertEqual(effect["throttled_ratio_change"], "")


class DistributionFigureTests(unittest.TestCase):
    def test_renders_pdf_and_png_from_minimal_aggregate_csvs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            aggregate = root / "aggregate"
            aggregate.mkdir()
            summary_rows = []
            for scenario in SCENARIOS:
                for mode in MODES:
                    for seed in SEEDS:
                        summary_rows.append({
                            "run_id": f"fixture_{scenario}_{mode}_s{seed}",
                            "scenario": scenario,
                            "mode": mode,
                            "seed": seed,
                            "throttled_ratio": {
                                "original_prism": "0.4",
                                "prism_recycle": "0.2",
                            }[mode],
                        })
            with (aggregate / "summary.csv").open("w", newline="", encoding="ascii") as stream:
                writer = csv.DictWriter(stream, fieldnames=(
                    "run_id", "scenario", "mode", "seed", "throttled_ratio",
                ))
                writer.writeheader()
                writer.writerows(summary_rows)
            with (aggregate / "refresh_effects.csv").open("w", newline="", encoding="ascii") as stream:
                writer = csv.DictWriter(stream, fieldnames=(
                    "scenario", "mode", "seed", "terminal_time_ps", "post_window_complete",
                    "post_throttled_ratio",
                ))
                writer.writeheader()
                writer.writerow({
                    "scenario": "recoverable",
                    "mode": "prism_recycle",
                    "seed": 13,
                    "terminal_time_ps": 2_200_000_000,
                    "post_window_complete": 1,
                    "post_throttled_ratio": 0.2,
                })

            make_distribution_fig.render_distribution_figure(aggregate, root / "figs")

            self.assertTrue((root / "figs" / "distribution.png").is_file())
            self.assertTrue((root / "figs" / "distribution.pdf").is_file())


if __name__ == "__main__":
    unittest.main()
