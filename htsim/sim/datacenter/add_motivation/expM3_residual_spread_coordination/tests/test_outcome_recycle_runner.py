import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


class OutcomeRecycleRunnerTests(unittest.TestCase):
    def test_runner_uses_exactly_six_locked_recoverable_cases(self):
        from htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination import (
            run_outcome_recycle,
        )

        rows = run_outcome_recycle._outcome_recycle_rows()
        self.assertEqual(
            {
                (
                    row["mode"], row["scenario"], int(row["seed"]),
                    int(row["degraded_links"]), float(row["degraded_capacity_gbps"]),
                )
                for row in rows
            },
            {
                (mode, "recoverable", seed, 2, 25.0)
                for mode in ("prism_recycle", "outcome_recycle")
                for seed in (13, 14, 15)
            },
        )
        self.assertEqual(len(rows), 6)

    def test_runner_dispatches_only_the_locked_cases_to_its_output(self):
        from htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination import (
            run_outcome_recycle,
        )

        with TemporaryDirectory() as directory, patch.object(
            run_outcome_recycle, "OUTPUT", Path(directory)
        ), patch.object(run_outcome_recycle.run, "_run_one") as run_one:
            self.assertEqual(run_outcome_recycle.main([]), 0)

        self.assertEqual(run_one.call_count, 6)
        self.assertEqual(
            {
                (
                    call.kwargs["phase"], call.kwargs["output"], call.kwargs["mode"],
                    call.kwargs["scenario"], call.kwargs["seed"],
                    call.kwargs["degraded_links"], call.kwargs["degraded_capacity_gbps"],
                )
                for call in run_one.call_args_list
            },
            {
                ("outcome_recycle", Path(directory), mode, "recoverable", seed, 2, 25.0)
                for mode in ("prism_recycle", "outcome_recycle")
                for seed in (13, 14, 15)
            },
        )
