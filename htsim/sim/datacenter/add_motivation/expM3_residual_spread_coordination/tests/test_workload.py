import unittest

from htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.gen_workload import (
    generate_workload,
)
from htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.run import (
    scenario_capacity,
)


class WorkloadCapacityTests(unittest.TestCase):
    def test_recoverable_capacity_is_strictly_below_healthy_ingress(self):
        recoverable = scenario_capacity("recoverable")

        self.assertEqual(recoverable.foreground_flows, 6)
        self.assertEqual(recoverable.source_offered_ceiling_gbps, 600.0)
        self.assertEqual(recoverable.healthy_capacity_gbps, 800.0)
        self.assertLess(
            recoverable.source_offered_ceiling_gbps,
            recoverable.healthy_capacity_gbps,
        )

    def test_persistent_capacity_is_strictly_above_healthy_ingress(self):
        persistent = scenario_capacity("persistent")

        self.assertEqual(persistent.foreground_flows, 12)
        self.assertEqual(persistent.source_offered_ceiling_gbps, 1200.0)
        self.assertEqual(persistent.healthy_capacity_gbps, 800.0)
        self.assertGreater(
            persistent.source_offered_ceiling_gbps,
            persistent.healthy_capacity_gbps,
        )

    def test_workloads_use_one_distinct_source_per_foreground_flow(self):
        for scenario in ("recoverable", "persistent"):
            capacity = scenario_capacity(scenario)
            for seed in (13, 14, 15):
                workload = generate_workload(
                    foreground_flows=capacity.foreground_flows,
                    seed=seed,
                )
                sources = {flow.src for flow in workload.foreground}

                self.assertEqual(len(sources), capacity.foreground_flows)


if __name__ == "__main__":
    unittest.main()
