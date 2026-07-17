import unittest
from unittest.mock import patch

from htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination import (
    run_distribution,
)


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


if __name__ == "__main__":
    unittest.main()
