import math
import unittest

from htsim.sim.datacenter.add_motivation.common.statistics import cluster_bootstrap


class ClusterBootstrapTests(unittest.TestCase):
    def test_is_deterministic_for_a_fixed_seed(self):
        rows = [
            {"flow": 2, "value": 10.0},
            {"flow": 1, "value": 1.0},
            {"flow": 2, "value": 20.0},
        ]
        statistic = lambda sample: sum(row["value"] for row in sample) / len(sample)

        first = cluster_bootstrap(
            rows, lambda row: row["flow"], statistic, samples=200, seed=7
        )
        second = cluster_bootstrap(
            list(reversed(rows)), lambda row: row["flow"], statistic,
            samples=200, seed=7,
        )

        self.assertEqual(first, second)

    def test_resamples_whole_clusters_with_replacement(self):
        rows = [
            {"flow": 1, "value": 1},
            {"flow": 1, "value": 2},
            {"flow": 2, "value": 10},
        ]
        observed_samples = []

        def statistic(sample):
            by_flow = {}
            for row in sample:
                by_flow.setdefault(row["flow"], []).append(row["value"])
            observed_samples.append(by_flow)
            return float(sum(row["value"] for row in sample))

        cluster_bootstrap(
            rows, lambda row: row["flow"], statistic, samples=30, seed=11
        )

        self.assertTrue(observed_samples)
        for sample in observed_samples:
            self.assertNotIn([1], sample.values())
            self.assertNotIn([2], sample.values())
            for values in sample.values():
                self.assertIn(values, ([1, 2], [1, 2, 1, 2], [10], [10, 10]))

    def test_rejects_empty_rows(self):
        with self.assertRaisesRegex(ValueError, "empty clusters"):
            cluster_bootstrap([], lambda row: row, len, samples=10)

    def test_rejects_nonpositive_sample_count(self):
        with self.assertRaisesRegex(ValueError, "samples"):
            cluster_bootstrap([1], lambda row: row, len, samples=0)

    def test_rejects_any_nonfinite_statistic(self):
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value), self.assertRaisesRegex(
                ValueError, "non-finite statistic"
            ):
                cluster_bootstrap(
                    [{"flow": 1}], lambda row: row["flow"],
                    lambda _sample, result=value: result, samples=3,
                )


if __name__ == "__main__":
    unittest.main()
