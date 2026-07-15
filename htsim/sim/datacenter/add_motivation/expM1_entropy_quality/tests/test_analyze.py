import contextlib
import io
import json
import math
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from htsim.sim.datacenter.add_motivation.common.residual_join import ResidualAck
from htsim.sim.datacenter.add_motivation.common.trace_schema import TraceBundle
from htsim.sim.datacenter.add_motivation.expM1_entropy_quality import analyze
from htsim.sim.datacenter.add_motivation.expM1_entropy_quality import make_figs


def ack(event_seq, flow_id, entropy, residual_ps, *, ecn=False,
        source_token_id=analyze.UINT64_MAX, physical_path_id=None,
        retransmitted=False, selection_source=None):
    if selection_source is None:
        selection_source = (
            "recycled" if source_token_id != analyze.UINT64_MAX else "unknown"
        )
    return {
        "event_seq": event_seq,
        "time_ps": event_seq * 1_000,
        "flow_id": flow_id,
        "epoch_id": event_seq // 3,
        "entropy": entropy,
        "physical_path_id": entropy if physical_path_id is None else physical_path_id,
        "ecn": ecn,
        "genuine_sample": True,
        "retransmitted": retransmitted,
        "selection_source": selection_source,
        "source_token_id": source_token_id,
        "new_data_bytes_sent_total": event_seq * 4150,
        "newly_acked_bytes": 4150,
        "cwnd_bytes": 16600,
        "_residual_ps": residual_ps,
    }


def joined(rows, threshold_ps=14_000_000):
    return tuple(
        ResidualAck(
            row=row,
            floor_ps=1_000_000,
            spread_ps=max(row["_residual_ps"], threshold_ps),
            residual_ps=row["_residual_ps"],
            high_residual=row["_residual_ps"] >= threshold_ps,
        )
        for row in rows
    )


def bundle(rows, tokens=(), pathmap=()):
    return TraceBundle(
        run_id="fixture", ack=tuple(rows), token=tuple(tokens), epoch=(),
        pathmap=tuple(pathmap), linkmap=(), background=(), events=(),
    )


class RunMetricTests(unittest.TestCase):
    def test_flow_balanced_persistence_fixture(self):
        rows = [
            ack(1, 1, 10, 1_000_000),
            ack(2, 1, 10, 20_000_000, ecn=True),
            ack(3, 1, 20, 1_000_000),
            ack(4, 1, 20, 2_000_000, ecn=True),
            ack(5, 1, 30, 20_000_000),
            ack(6, 1, 30, 20_000_000, ecn=True),
            ack(7, 2, 10, 1_000_000),
            ack(8, 2, 10, 2_000_000, ecn=True),
            ack(9, 2, 30, 20_000_000),
        ]
        with mock.patch.object(analyze, "attach_same_epoch_residuals", return_value=joined(rows)):
            summary = analyze.summarize_run(bundle(rows), threshold_ps=14_000_000)

        self.assertEqual(summary.unmarked_high_ratio, 2 / 5)
        self.assertEqual(summary.next_high_given_current_high, 1.0)
        self.assertEqual(summary.next_high_given_current_low, 0.25)
        self.assertEqual(summary.risk_ratio, 4.0)
        self.assertEqual(summary.unmatched_next_use, 1)
        self.assertEqual(summary.matched_next_use, 4)

    def test_next_use_never_crosses_flow_and_has_no_interval_cap(self):
        rows = [
            ack(1, 1, 7, 20_000_000),
            ack(2, 2, 7, 1_000_000),
            ack(1_000_000, 1, 7, 20_000_000, ecn=True),
        ]
        with mock.patch.object(analyze, "attach_same_epoch_residuals", return_value=joined(rows)):
            result = analyze.analyze_bundle(bundle(rows))

        match = next(row for row in result.next_use_rows if row["flow_id"] == 1)
        self.assertEqual(match["next_event_seq"], 1_000_000)
        self.assertEqual(match["interval_ps"], 999_999_000)
        self.assertTrue(match["next_high"])

    def test_shadow_rejection_uses_exact_token_identity(self):
        rows = [
            ack(1, 1, 7, 20_000_000),
            ack(3, 1, 7, 1_000_000),
            ack(7, 1, 7, 1_000_000, ecn=True, source_token_id=42),
            ack(8, 1, 7, 20_000_000, ecn=True, source_token_id=41),
        ]
        tokens = [
            {"event_seq": 2, "flow_id": 1, "operation": "enqueue_good_ack",
             "token_id": 41, "entropy": 7, "related_ack_event_seq": 1},
            {"event_seq": 4, "flow_id": 1, "operation": "enqueue_good_ack",
             "token_id": 42, "entropy": 7, "related_ack_event_seq": 3},
            {"event_seq": 5, "flow_id": 1, "operation": "dequeue_recycle",
             "token_id": 41, "entropy": 7, "related_ack_event_seq": 0},
            {"event_seq": 6, "flow_id": 1, "operation": "dequeue_recycle",
             "token_id": 42, "entropy": 7, "related_ack_event_seq": 0},
        ]
        with mock.patch.object(analyze, "attach_same_epoch_residuals", return_value=joined(rows)):
            result = analyze.analyze_bundle(bundle(rows, tokens))

        summary = result.summary
        self.assertEqual(summary.legacy_token_count, 2)
        self.assertEqual(summary.shadow_rejection_count, 1)
        self.assertEqual(summary.shadow_rejection_exposure, 0.5)
        self.assertEqual(summary.rejected_token_selected_count, 1)
        self.assertEqual(summary.rejected_token_future_high_rate, 1.0)
        rejected = [row for row in result.token_rows if row["shadow_rejected"]]
        self.assertEqual([row["token_id"] for row in rejected], [41])
        self.assertEqual(rejected[0]["selected_ack_event_seq"], 8)

    def test_rejected_token_id_zero_matches_recycled_ack(self):
        rows = [
            ack(1, 1, 7, 20_000_000),
            ack(4, 1, 7, 20_000_000, ecn=True, source_token_id=0),
        ]
        tokens = [
            {"event_seq": 2, "flow_id": 1, "operation": "enqueue_good_ack",
             "token_id": 0, "entropy": 7, "related_ack_event_seq": 1},
            {"event_seq": 3, "flow_id": 1, "operation": "dequeue_recycle",
             "token_id": 0, "entropy": 7, "related_ack_event_seq": 0},
        ]
        with mock.patch.object(
            analyze, "attach_same_epoch_residuals", return_value=joined(rows)
        ):
            result = analyze.analyze_bundle(bundle(rows, tokens))

        self.assertEqual(result.summary.rejected_token_selected_count, 1)
        self.assertEqual(result.summary.rejected_token_future_high_rate, 1.0)
        self.assertEqual(result.token_rows[0]["selected_ack_event_seq"], 4)


class SelectionTests(unittest.TestCase):
    @staticmethod
    def passing(seed, arm, phi, *, degraded_links=0, capacity=100.0,
                offered_load=0.5):
        return {
            "run_id": f"calibration_{arm}_s{seed}", "seed": seed,
            "scenario_id": arm, "arm": "symmetric" if degraded_links == 0 else "gray",
            "offered_load": offered_load, "degraded_links": degraded_links,
            "degraded_capacity_gbps": capacity, "completion_rate": 1.0,
            "aux_valid": 1, "unmarked_count": 10, "unmarked_high_ratio": phi,
            "risk_ratio": 2.0, "coverage_adequate": 1,
            "loss_freezing_clear": 1,
        }

    def test_selects_calibration_cell_and_writes_only_five_formal_seed_pairs(self):
        rows = []
        for seed in (101, 102, 103):
            rows.append(self.passing(seed, "symmetric_l05", 0.1))
            rows.append(self.passing(
                seed, "gray_c50_d2_l05", 0.4,
                degraded_links=2, capacity=50.0,
            ))
        with tempfile.TemporaryDirectory() as directory:
            formal = Path(directory) / "formal.csv"
            result_path = Path(directory) / "selection.csv"
            result = analyze.select_formal(rows, formal, result_path)
            lines = formal.read_text(encoding="ascii").splitlines()

        self.assertTrue(result.selected)
        self.assertEqual(len(lines), 11)
        self.assertEqual({line.rsplit(",", 1)[1] for line in lines[1:]},
                         {"13", "14", "15", "16", "17"})

    def test_negative_selection_records_reasons_without_touching_formal(self):
        rows = [self.passing(101, "symmetric_l05", 0.2)]
        with tempfile.TemporaryDirectory() as directory:
            formal = Path(directory) / "formal.csv"
            formal.write_text("sentinel\n", encoding="ascii")
            result_path = Path(directory) / "selection.csv"
            result = analyze.select_formal(rows, formal, result_path)

            self.assertFalse(result.selected)
            self.assertEqual(formal.read_text(encoding="ascii"), "sentinel\n")
            self.assertIn("no_qualifying_cell", result_path.read_text(encoding="ascii"))

    def test_final_ranking_tie_break_is_scenario_id_not_offered_load(self):
        rows = []
        for seed in (101, 102, 103):
            rows.extend([
                self.passing(seed, "symmetric_l03", 0.1, offered_load=0.3),
                self.passing(seed, "symmetric_l07", 0.1, offered_load=0.7),
                self.passing(
                    seed, "zeta_l03", 0.4, degraded_links=2,
                    capacity=50.0, offered_load=0.3,
                ),
                self.passing(
                    seed, "alpha_l07", 0.4, degraded_links=2,
                    capacity=50.0, offered_load=0.7,
                ),
            ])
        with tempfile.TemporaryDirectory() as directory:
            result = analyze.select_formal(
                rows, Path(directory) / "formal.csv",
                Path(directory) / "selection.csv",
            )

        self.assertTrue(result.selected)
        self.assertEqual(result.scenario_id, "alpha_l07")
        self.assertEqual(result.control_scenario_id, "symmetric_l07")

    def test_duplicate_load_seed_controls_make_candidate_ineligible(self):
        rows = []
        for seed in analyze.CALIBRATION_SEEDS:
            rows.append(self.passing(seed, "symmetric_l05", 0.1))
            rows.append(self.passing(
                seed, "gray_l05", 0.4, degraded_links=2, capacity=50.0
            ))
        rows.append(self.passing(101, "symmetric_duplicate_l05", 0.1))
        with tempfile.TemporaryDirectory() as directory:
            result_path = Path(directory) / "selection.csv"
            result = analyze.select_formal(
                rows, Path(directory) / "formal.csv", result_path
            )
            report = result_path.read_text(encoding="ascii")

        self.assertFalse(result.selected)
        self.assertIn("duplicate_load_matched_control", report)

    def test_control_scenario_id_must_match_across_calibration_seeds(self):
        rows = []
        for seed, control_id in zip(
            analyze.CALIBRATION_SEEDS,
            ("symmetric_a_l05", "symmetric_b_l05", "symmetric_a_l05"),
        ):
            rows.append(self.passing(seed, control_id, 0.1))
            rows.append(self.passing(
                seed, "gray_l05", 0.4, degraded_links=2, capacity=50.0
            ))
        with tempfile.TemporaryDirectory() as directory:
            result_path = Path(directory) / "selection.csv"
            result = analyze.select_formal(
                rows, Path(directory) / "formal.csv", result_path
            )
            report = result_path.read_text(encoding="ascii")

        self.assertFalse(result.selected)
        self.assertIn("inconsistent_control_scenario_id", report)


class AuxiliaryTests(unittest.TestCase):
    def test_missing_flow_events_are_invalid_not_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.ascii"
            path.write_text("unrelated simulator output\n", encoding="ascii")
            auxiliary = analyze.parse_flow_output(path, already_ascii=True)

        self.assertFalse(auxiliary.valid)
        self.assertIsNone(auxiliary.completion_rate)
        self.assertIsNone(auxiliary.goodput_gbps)
        self.assertIsNone(auxiliary.p99_fct_us)
        self.assertIn("FLOW_EVENT", auxiliary.invalid_reason)


class RiskRatioBootstrapTests(unittest.TestCase):
    def test_infinite_rr_replicates_are_valid_and_retained_in_percentiles(self):
        rows = [
            {"cluster_id": 1, "high_probability": 1.0, "low_probability": 0.0},
            {"cluster_id": 2, "high_probability": 0.5, "low_probability": 0.0},
        ]
        result = analyze.risk_ratio_cluster_bootstrap(rows, samples=100, seed=7)

        self.assertEqual(result.point_status, "positive_over_zero")
        self.assertTrue(math.isinf(result.point_estimate))
        self.assertEqual(result.valid_replicates, 100)
        self.assertEqual(result.infinite_replicates, 100)
        self.assertEqual(result.undefined_replicates, 0)
        self.assertTrue(math.isinf(result.ci_low))
        self.assertTrue(result.adequate)

    def test_zero_over_zero_replicates_are_undefined_with_reason(self):
        rows = [
            {"cluster_id": 1, "high_probability": 0.0, "low_probability": 0.0},
        ]
        result = analyze.risk_ratio_cluster_bootstrap(rows, samples=20, seed=7)

        self.assertEqual(result.point_status, "undefined_zero_over_zero")
        self.assertIsNone(result.point_estimate)
        self.assertEqual(result.valid_replicates, 0)
        self.assertEqual(result.undefined_replicates, 20)
        self.assertEqual(result.undefined_reasons["zero_over_zero"], 20)
        self.assertIsNone(result.ci_low)
        self.assertFalse(result.adequate)

    def test_absent_conditioning_denominator_is_undefined(self):
        rows = [
            {"cluster_id": 1, "high_probability": None, "low_probability": 0.5},
        ]
        result = analyze.risk_ratio_cluster_bootstrap(rows, samples=20, seed=7)

        self.assertEqual(result.point_status, "undefined_missing_high_conditioning")
        self.assertEqual(result.undefined_reasons["missing_high_conditioning"], 20)


class FormalPredicateTests(unittest.TestCase):
    @staticmethod
    def summary(seed, arm):
        return {
            "run_id": f"formal_{arm}_s{seed}", "seed": seed, "arm": arm,
            "offered_load": 0.5, "unmarked_high_ratio": 0.4 if arm == "gray" else 0.1,
            "unmarked_count": 10, "coverage_adequate": 1,
            "unmatched_next_use_rate": 0.1, "aux_valid": 1,
            "completion_rate": 1.0, "loss_freezing_clear": 1,
        }

    @staticmethod
    def evidence():
        summaries = []
        next_rows = []
        group_rows = []
        for seed in analyze.FORMAL_SEEDS:
            summaries.extend([
                FormalPredicateTests.summary(seed, "symmetric"),
                FormalPredicateTests.summary(seed, "gray"),
            ])
            for flow_id, low_future_high in ((1, False), (2, True)):
                common = {
                    "run_id": f"formal_gray_s{seed}", "seed": seed,
                    "arm": "gray", "flow_id": flow_id, "matched": True,
                }
                next_rows.extend([
                    {**common, "current_high": True, "next_high": True},
                    {**common, "current_high": False,
                     "next_high": low_future_high},
                ])
            for grouping in ("entropy", "physical_path"):
                group_rows.append({
                    "arm": "gray", "grouping": grouping, "group_id": seed,
                    "comparable": True,
                    "next_high_given_current_high": 1.0,
                    "next_high_given_current_low": 0.5,
                })
        return summaries, next_rows, group_rows

    def test_missing_formal_evidence_is_rejected_with_explicit_predicates(self):
        result = analyze._formal_result([], [], [])

        self.assertEqual(result["accepted"], 0)
        self.assertIn("formal_seed_coverage", result["failed_predicates"])
        self.assertIn("risk_ratio_bootstrap_lower_above_1", result["failed_predicates"])
        self.assertEqual(result["min_future_high_threshold"], 0.10)

    def test_invalid_load_matched_controls_fail_every_control_gate(self):
        summaries, next_rows, group_rows = self.evidence()
        for row in summaries:
            if row["arm"] == "symmetric" and row["seed"] == 13:
                row.update({
                    "completion_rate": 0.5,
                    "unmarked_count": 0,
                    "coverage_adequate": 0,
                    "unmatched_next_use_rate": 0.9,
                    "loss_freezing_clear": 0,
                })
        with mock.patch.object(
            analyze, "cluster_bootstrap", return_value=(1.5, 2.5)
        ):
            result = analyze._formal_result(summaries, next_rows, group_rows)

        self.assertEqual(result["accepted"], 0)
        failed = set(result["failed_predicates"].split(";"))
        self.assertTrue({
            "control_completion_adequate",
            "control_nonzero_unmarked_denominator",
            "control_flow_coverage_adequate",
            "control_matching_adequate",
            "control_no_hard_loss_or_freezing_explanation",
        }.issubset(failed))

    def test_formal_result_emits_complete_fixed_evidence_contract(self):
        summaries, next_rows, group_rows = self.evidence()
        result = analyze._formal_result(summaries, next_rows, group_rows)

        self.assertEqual(result["accepted"], 1)
        self.assertEqual(result["residual_threshold_ps"], 14_000_000)
        self.assertEqual(result["completion_rate_threshold"], 0.99)
        self.assertEqual(result["flow_coverage_fraction_threshold"], 0.75)
        self.assertEqual(result["entropy_coverage_count_threshold"], 6)
        self.assertEqual(result["physical_path_coverage_count_threshold"], 2)
        self.assertEqual(result["bootstrap_samples"], 10_000)
        self.assertEqual(result["bootstrap_confidence_level"], 0.95)
        self.assertEqual(result["risk_ratio_bootstrap_valid_replicates"], 10_000)
        self.assertGreater(result["risk_ratio_bootstrap_infinite_replicates"], 0)
        self.assertEqual(result["risk_ratio_bootstrap_undefined_replicates"], 0)
        self.assertEqual(result["risk_ratio_bootstrap_min_valid_fraction"], 0.95)
        self.assertEqual(result["risk_ratio_bootstrap_min_valid_replicates"], 9_500)
        self.assertEqual(result["risk_ratio_ci_lower_bound_threshold"], 1.0)
        self.assertEqual(result["risk_ratio_ci_lower_bound_rule"], ">1")
        self.assertEqual(result["min_future_high_threshold"], 0.10)
        self.assertEqual(result["min_future_high_contributing_flow_clusters"], 2)
        self.assertEqual(result["max_unmatched_rate_threshold"], 0.25)
        self.assertEqual(result["required_formal_seeds"], "13;14;15;16;17")
        self.assertEqual(result["evidence_required_for_arms"],
                         "gray;load-matched symmetric control")
        self.assertEqual(result["loss_freezing_max_high_retransmitted_count"], 0)
        self.assertIn("retransmitted", result["loss_freezing_criterion"])


class FixedThresholdCliTests(unittest.TestCase):
    def test_evidence_threshold_override_flags_are_rejected(self):
        attempts = (
            ("--threshold-ps", "13000000"),
            ("--min-future-high", "0"),
            ("--max-unmatched-rate", "1"),
        )
        for flag, value in attempts:
            with self.subTest(flag=flag):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as raised:
                        analyze.main(["--formal", flag, value])
                self.assertEqual(raised.exception.code, 2)


class InputBindingTests(unittest.TestCase):
    def test_trace_bundle_identity_seed_and_scenario_are_bound_to_manifest(self):
        manifest = {
            "run_id": "formal_gray_s13", "seed": 13,
            "experiment": "M1_entropy_quality", "phase": "formal",
        }
        valid_ack = {"seed": 13, "scenario": "M1_entropy_quality"}
        cases = (
            (TraceBundle("copied", (), (), (), (), (), (), ()), "run_id"),
            (TraceBundle("formal_gray_s13", ({**valid_ack, "seed": 14},), (), (),
                         (), (), (), ()), "ACK seed"),
            (TraceBundle("formal_gray_s13", ({**valid_ack, "scenario": "other"},),
                         (), (), (), (), (), ()), "ACK scenario"),
        )
        for trace, reason in cases:
            with self.subTest(reason=reason), self.assertRaisesRegex(ValueError, reason):
                analyze._validate_bundle_binding(trace, manifest)

    def test_run_inputs_reject_symlink_and_copied_manifest_output(self):
        data_root = analyze.HERE / "data"
        data_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".m1_input_test_", dir=data_root) as directory:
            phase_dir = Path(directory)
            run_id = "formal_gray_s13"
            manifest_path = phase_dir / f"{run_id}.manifest.json"
            expected = {
                "manifest": manifest_path,
                "simulation": phase_dir / f"{run_id}.dat",
                **{kind: phase_dir / f"{run_id}.{kind}.csv"
                   for kind in analyze.TRACE_SUFFIXES},
            }
            for path in expected.values():
                path.write_text("fixture\n", encoding="ascii")
            manifest = {
                "output_filenames": {key: str(path) for key, path in expected.items()}
            }

            copied = phase_dir / "copied.ack.csv"
            copied.write_text("fixture\n", encoding="ascii")
            manifest["output_filenames"]["ack"] = str(copied)
            with self.assertRaisesRegex(ValueError, "output_filenames.*ack"):
                analyze._validate_run_inputs(manifest_path, manifest, phase_dir, run_id)

            manifest["output_filenames"]["ack"] = str(expected["ack"])
            expected["token"].unlink()
            os.symlink(expected["ack"], expected["token"])
            with self.assertRaisesRegex(ValueError, "token.*symlink"):
                analyze._validate_run_inputs(manifest_path, manifest, phase_dir, run_id)


class PlotValidationTests(unittest.TestCase):
    def _assert_fixture_rejected(self, filename, old, new, reason):
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            make_figs._write_fixture(data_dir)
            path = data_dir / filename
            path.write_text(
                path.read_text(encoding="ascii").replace(old, new, 1),
                encoding="ascii",
            )
            with self.assertRaisesRegex(ValueError, reason):
                make_figs.render(data_dir, data_dir / "figs")

    def test_rejects_negative_residual(self):
        self._assert_fixture_rejected(
            "ecdf.csv", "symmetric,0", "symmetric,-1", "nonnegative"
        )

    def test_rejects_probability_outside_unit_interval(self):
        self._assert_fixture_rejected(
            "conditioning.csv", "symmetric,low,0.18", "symmetric,low,1.2",
            "\[0, 1\]",
        )

    def test_rejects_ci_that_does_not_contain_estimate(self):
        self._assert_fixture_rejected(
            "conditioning.csv", "0.18,0.12,0.25", "0.18,0.19,0.25",
            "CI.*estimate",
        )


if __name__ == "__main__":
    unittest.main()
