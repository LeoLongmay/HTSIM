import importlib.util
import pathlib
import unittest


HERE = pathlib.Path(__file__).resolve().parent
REPORT = HERE.parent / "report.py"
SPEC = importlib.util.spec_from_file_location("prime_smoke_report", REPORT)
report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report)
FIGS = HERE.parent / "make_figs.py"
FIGS_SPEC = importlib.util.spec_from_file_location("prime_smoke_figs", FIGS)
figs = importlib.util.module_from_spec(FIGS_SPEC)
FIGS_SPEC.loader.exec_module(figs)


class PrimeSmokeReportTest(unittest.TestCase):
    def test_summary_row_keeps_censoring_bytes_and_tier_share(self):
        """A reporter that drops unfinished flows, sink bytes, or selections is incorrect."""
        row = report.build_summary_row(HERE / "fixture", arm="Prime", failed=8,
                                       seed=13, end_ms=8)
        self.assertEqual(row["completion_count"], 2)
        self.assertEqual(row["censored_count"], 1)
        self.assertEqual(row["fct_mean_us"], 200.0)
        self.assertEqual(row["fct_p50_us"], 100.0)
        self.assertEqual(row["fct_p95_us"], 300.0)
        self.assertEqual(row["delivered_bytes"], 4_000_000)
        self.assertEqual(row["tier0_share_0"], 0.5)

    def test_aggregate_reconstructs_flow_fcts_and_uses_total_seed_duration(self):
        """Averaging cell means or summing independent run rates is mathematically wrong."""
        rows = []
        for _, arm in report.ARMS:
            for failed in report.FAILEDS:
                rows.append({"arm": arm, "failed": failed, "end_ms": 8,
                             "started_count": 1, "completion_count": 1,
                             "censored_count": 0, "fct_mean_us": 10.0,
                             "fct_p99_us": 10.0, "_fct_samples_us": [10.0],
                             "delivered_bytes": 1_000_000_000,
                             "delivered_goodput_gbps": 1000.0,
                             "feedback_count": 0, "selection_count": 0})
        first = next(row for row in rows if row["arm"] == "Prime" and row["failed"] == 8)
        first.update(completion_count=100, started_count=100, fct_mean_us=1.0,
                     fct_p99_us=1.0, _fct_samples_us=[1.0] * 100,
                     delivered_bytes=1_000_000_000)
        rows.append({**first, "completion_count": 1, "started_count": 1,
                     "fct_mean_us": 1000.0, "fct_p99_us": 1000.0,
                     "_fct_samples_us": [1000.0], "delivered_bytes": 2_000_000_000})

        aggregate = next(row for row in report._aggregate(rows)
                         if row["arm"] == "Prime" and row["failed"] == 8)
        self.assertEqual(aggregate["completion_count"], 101)
        self.assertAlmostEqual(aggregate["fct_mean_us"], 1100.0 / 101.0)
        self.assertEqual(aggregate["fct_p50_us"], 1.0)
        self.assertEqual(aggregate["fct_p95_us"], 1.0)
        self.assertEqual(aggregate["fct_p99_us"], 1.0)
        self.assertEqual(aggregate["end_ms"], 16)
        self.assertEqual(aggregate["delivered_bytes"], 3_000_000_000)
        self.assertEqual(aggregate["delivered_goodput_gbps"], 1500.0)
        self.assertEqual(aggregate["delivered_goodput_gbps"],
                         aggregate["delivered_bytes"] * 8.0 / (aggregate["end_ms"] * 1e6))

    def test_tier_figure_discovers_every_observed_tuple_tier(self):
        """Dropping a nonzero tuple tier hides an applicable part of Prime's selection."""
        self.assertEqual(figs.tier_numbers([
            {"tier0_share_0": 0.5, "tier1_share_2": 0.5, "tier2_share_1": 1.0}
        ]), [0, 1, 2])

    def test_tier_figure_weights_shares_by_selection_count(self):
        """A sparse cell must not contribute as much as a cell with ten selections."""
        rows = [{"selection_count": 10, "tier0_share_0": 0.9},
                {"selection_count": 1, "tier0_share_0": 0.0}]
        self.assertAlmostEqual(figs.weighted_tier_share(rows, 0, 0), 9.0 / 11.0)


if __name__ == "__main__":
    unittest.main()
