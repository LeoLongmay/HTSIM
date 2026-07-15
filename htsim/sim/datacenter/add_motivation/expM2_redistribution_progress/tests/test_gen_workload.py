import csv
import io
import random
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from htsim.sim.datacenter.add_motivation.expM2_redistribution_progress import (
    gen_workload,
)


BASE_RTT_PS = 13_945_000


def generate(seed=101):
    return gen_workload.generate_workload(
        foreground_flows=16,
        hot_path_groups=4,
        background_utilization=0.5,
        seed=seed,
        base_rtt_ps=BASE_RTT_PS,
    )


class WorkloadTests(unittest.TestCase):
    def test_timeline_size_ids_and_cross_pod_foreground(self):
        workload = generate()

        self.assertEqual(len(workload.foreground), 16)
        self.assertEqual(
            [flow.flow_id for flow in workload.foreground], list(range(1, 17))
        )
        self.assertEqual(
            {flow.start_ps for flow in workload.foreground},
            {gen_workload.FOREGROUND_START_PS},
        )
        self.assertEqual(
            {flow.size_bytes for flow in workload.foreground},
            {256_000_000},
        )
        sources = [flow.src for flow in workload.foreground]
        self.assertEqual(len(sources), len(set(sources)))
        for flow in workload.foreground:
            self.assertNotEqual(flow.src // gen_workload.HOSTS_PER_POD,
                                gen_workload.TARGET_POD)
            self.assertEqual(flow.dst // gen_workload.HOSTS_PER_POD,
                             gen_workload.TARGET_POD)
        self.assertEqual(
            [(flow.src, flow.dst) for flow in workload.foreground],
            sorted((flow.src, flow.dst) for flow in workload.foreground),
        )
        serialization_ps = 256_000_000 * 8 * 1_000 // 100
        self.assertGreater(1 + serialization_ps, 120 * BASE_RTT_PS)

    def test_exact_epoch_conversion_and_parser_header(self):
        workload = generate()
        rows = list(csv.DictReader(io.StringIO(workload.background_config_text)))

        self.assertEqual(tuple(rows[0]), gen_workload.BACKGROUND_FIELDS)
        self.assertEqual({int(row["start_ps"]) for row in rows}, {20 * BASE_RTT_PS})
        self.assertEqual({int(row["stop_ps"]) for row in rows}, {120 * BASE_RTT_PS})

    def test_background_endpoint_isolation_and_unique_routes(self):
        workload = generate()
        foreground_endpoints = {
            endpoint
            for flow in workload.foreground
            for endpoint in (flow.src, flow.dst)
        }
        sources = [flow.src for flow in workload.background]
        destinations = [flow.dst for flow in workload.background]
        routes = [flow.path_index for flow in workload.background]
        target_pods = {
            destination // gen_workload.HOSTS_PER_POD
            for destination in destinations
        }

        self.assertTrue(set(sources).isdisjoint(foreground_endpoints))
        self.assertEqual(len(sources), len(set(sources)))
        self.assertEqual(len(destinations), len(set(destinations)))
        self.assertEqual(routes, list(range(4)))
        self.assertEqual(target_pods, {gen_workload.TARGET_POD})
        self.assertEqual(
            [(flow.src, flow.dst) for flow in workload.background],
            sorted((flow.src, flow.dst) for flow in workload.background),
        )
        for flow in workload.background:
            self.assertNotEqual(flow.src // gen_workload.HOSTS_PER_POD,
                                gen_workload.TARGET_POD)
            self.assertEqual(flow.dst // gen_workload.HOSTS_PER_POD,
                             gen_workload.TARGET_POD)

    def test_32_foreground_flows_reuse_target_destinations_deterministically(self):
        parameters = dict(
            foreground_flows=32,
            hot_path_groups=6,
            background_utilization=0.75,
            seed=101,
            base_rtt_ps=BASE_RTT_PS,
        )
        first = gen_workload.generate_workload(**parameters)
        second = gen_workload.generate_workload(**parameters)
        sources = [flow.src for flow in first.foreground]
        destinations = [flow.dst for flow in first.foreground]

        self.assertEqual(len(sources), 32)
        self.assertEqual(len(set(sources)), 32)
        self.assertEqual(len(set(destinations)), gen_workload.HOSTS_PER_POD)
        self.assertEqual(
            {destinations.count(host) for host in set(destinations)}, {2}
        )
        self.assertTrue(all(
            source // gen_workload.HOSTS_PER_POD != gen_workload.TARGET_POD
            for source in sources
        ))
        self.assertTrue(all(
            destination // gen_workload.HOSTS_PER_POD == gen_workload.TARGET_POD
            for destination in destinations
        ))
        self.assertEqual(first.foreground_text, second.foreground_text)
        self.assertEqual(first.background_config_text,
                         second.background_config_text)

    def test_each_hot_group_aggregate_rate(self):
        workload = generate()
        rates_by_route = {}
        for flow in workload.background:
            rates_by_route.setdefault(flow.path_index, Decimal(0))
            rates_by_route[flow.path_index] += flow.rate_gbps

        self.assertEqual(len(rates_by_route), 4)
        self.assertEqual(set(rates_by_route.values()), {Decimal("50")})

    def test_same_parameters_are_byte_identical_and_do_not_touch_global_rng(self):
        state = random.getstate()
        first = generate()
        self.assertEqual(random.getstate(), state)
        second = generate()

        self.assertEqual(first.foreground_text.encode("ascii"),
                         second.foreground_text.encode("ascii"))
        self.assertEqual(first.background_config_text.encode("ascii"),
                         second.background_config_text.encode("ascii"))
        self.assertNotEqual(first.foreground_text, generate(seed=102).foreground_text)

    def test_cli_writes_semantic_background_config_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            foreground = root / "workload.cm"
            background = root / "workload.background-config.csv"
            args = [
                "--foreground", str(foreground),
                "--background-config", str(background),
                "--foreground-flows", "16",
                "--hot-path-groups", "4",
                "--background-utilization", "0.5",
                "--seed", "101",
                "--base-rtt-ps", str(BASE_RTT_PS),
            ]
            gen_workload.main(args)
            first = (foreground.read_bytes(), background.read_bytes())
            gen_workload.main(args)

            self.assertEqual(first, (foreground.read_bytes(), background.read_bytes()))
            self.assertEqual(first[0], generate().foreground_text.encode("ascii"))
            self.assertEqual(first[1], generate().background_config_text.encode("ascii"))

    def test_missing_and_nonpositive_base_rtt_are_rejected(self):
        common = dict(
            foreground_flows=16,
            hot_path_groups=4,
            background_utilization=0.5,
            seed=101,
        )
        for value in (0, -1, None, 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                gen_workload.generate_workload(base_rtt_ps=value, **common)

        with self.assertRaises(SystemExit):
            gen_workload.main([
                "--foreground", "x.cm",
                "--background-config", "x.background-config.csv",
                "--foreground-flows", "16",
                "--hot-path-groups", "4",
                "--background-utilization", "0.5",
                "--seed", "101",
            ])

    def test_background_trace_suffix_is_rejected_for_config(self):
        with self.assertRaises(ValueError):
            gen_workload.write_workload(
                Path("workload.cm"),
                Path("workload.background.csv"),
                foreground_flows=16,
                hot_path_groups=4,
                background_utilization=0.5,
                seed=101,
                base_rtt_ps=BASE_RTT_PS,
            )


class ConfigTests(unittest.TestCase):
    def test_coarse_grid_is_exactly_27_cells_and_formal_is_header_only(self):
        config_dir = Path(gen_workload.__file__).resolve().parent / "configs"
        with (config_dir / "calibration.csv").open(newline="", encoding="ascii") as source:
            rows = list(csv.DictReader(source))

        self.assertEqual(tuple(rows[0]), (
            "cell_id", "scenario", "foreground_flows", "hot_path_groups",
            "background_utilization", "seed",
        ))
        self.assertEqual(len(rows), 27)
        self.assertEqual(len({row["cell_id"] for row in rows}), 27)
        self.assertEqual({row["scenario"] for row in rows}, {""})
        self.assertEqual(
            {
                (int(row["foreground_flows"]), int(row["hot_path_groups"]),
                 Decimal(row["background_utilization"]), int(row["seed"]))
                for row in rows
            },
            {
                (foreground, groups, utilization, 101)
                for foreground in (8, 16, 32)
                for groups in (2, 4, 6)
                for utilization in (Decimal("0.25"), Decimal("0.50"), Decimal("0.75"))
            },
        )
        with (config_dir / "formal.csv").open(newline="", encoding="ascii") as source:
            self.assertEqual(len(list(csv.reader(source))), 1)


if __name__ == "__main__":
    unittest.main()
