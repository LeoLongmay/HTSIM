import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from htsim.sim.datacenter.add_motivation.common.residual_join import ResidualAck
from htsim.sim.datacenter.add_motivation.common.trace_schema import TraceBundle
from htsim.sim.datacenter.add_motivation.expM1_entropy_quality import analyze


def ack(event_seq, flow_id, entropy, residual_ps, *, ecn=False,
        source_token_id=0, physical_path_id=None, retransmitted=False):
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


class SelectionTests(unittest.TestCase):
    @staticmethod
    def passing(seed, arm, phi, *, degraded_links=0, capacity=100.0):
        return {
            "run_id": f"calibration_{arm}_s{seed}", "seed": seed,
            "scenario_id": arm, "arm": "symmetric" if degraded_links == 0 else "gray",
            "offered_load": 0.5, "degraded_links": degraded_links,
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


class FormalPredicateTests(unittest.TestCase):
    def test_missing_formal_evidence_is_rejected_with_explicit_predicates(self):
        result = analyze._formal_result(
            [], [], [], min_future_high=0.10, max_unmatched_rate=0.25
        )

        self.assertEqual(result["accepted"], 0)
        self.assertIn("formal_seed_coverage", result["failed_predicates"])
        self.assertIn("risk_ratio_bootstrap_lower_above_1", result["failed_predicates"])
        self.assertEqual(result["min_future_high_threshold"], 0.10)


if __name__ == "__main__":
    unittest.main()
