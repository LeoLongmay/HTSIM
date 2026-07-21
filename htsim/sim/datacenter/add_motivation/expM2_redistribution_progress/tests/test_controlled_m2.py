import unittest
from types import SimpleNamespace

from htsim.sim.datacenter.add_motivation.expM2_redistribution_progress import analyze
from htsim.sim.datacenter.add_motivation.expM2_redistribution_progress.gen_workload import (
    generate_workload,
)


class ControlledM2Tests(unittest.TestCase):
    def test_workload_is_foreground_only_and_deterministic(self):
        first = generate_workload(foreground_flows=8, seed=101)
        second = generate_workload(foreground_flows=8, seed=101)
        self.assertEqual(first, second)
        self.assertEqual(len(first.foreground), 8)
        self.assertNotIn("background", first.foreground_text)
        self.assertTrue(all(flow.dst < 16 and flow.src >= 16 for flow in first.foreground))

    def test_capacity_witness_uses_reduced_linkmap_rate_not_delivery(self):
        queues = ("CS0->US0(0)", "CS1->US0(0)")
        pathmap = tuple(
            {
                "flow_id": flow_id,
                "entropy": entropy,
                "resolution_status": "resolved",
                "queue_fingerprint": "|".join(queues),
            }
            for flow_id in (1, 2) for entropy in range(8)
        )
        bundle = SimpleNamespace(
            linkmap=(
                {"queue_name": queues[0], "rate_gbps": 50.0, "reduced_speed": True},
                {"queue_name": queues[1], "rate_gbps": 100.0, "reduced_speed": False},
            ),
            pathmap=pathmap,
            epoch=({"flow_id": 1}, {"flow_id": 2}),
            background=(),
        )
        witness = analyze.capacity_witness(bundle, 0, 1, 50.0)
        self.assertEqual(witness.c_healthy_gbps, 100.0)
        self.assertEqual(witness.c_hot_residual_gbps, 50.0)
        self.assertEqual(witness.c_effective_residual_gbps, 150.0)

    def test_capacity_witness_rejects_wrong_reduced_rate(self):
        queues = ("CS0->US0(0)",)
        bundle = SimpleNamespace(
            linkmap=({"queue_name": queues[0], "rate_gbps": 75.0, "reduced_speed": True},),
            pathmap=tuple(
                {"flow_id": 1, "entropy": entropy, "resolution_status": "resolved", "queue_fingerprint": queues[0]}
                for entropy in range(8)
            ),
            epoch=({"flow_id": 1},),
            background=(),
        )
        with self.assertRaisesRegex(analyze.EvidenceError, "differs"):
            analyze.capacity_witness(bundle, 0, 1, 50.0)


if __name__ == "__main__":
    unittest.main()
