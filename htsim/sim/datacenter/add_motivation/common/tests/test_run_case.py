import csv
import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ADD_MOTIVATION = Path(__file__).resolve().parents[2]
RUN_CASE_PATH = ADD_MOTIVATION / "common" / "run_case.py"
TOPOLOGY = ADD_MOTIVATION.parent / "topologies" / "fat_tree_128_1os.topo"
M1_CONFIGS = ADD_MOTIVATION / "expM1_entropy_quality" / "configs"


def load_run_case_module():
    spec = importlib.util.spec_from_file_location("motivation_run_case", RUN_CASE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RunCaseTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(
            prefix=".test-run-case-", dir=ADD_MOTIVATION
        )
        self.root = Path(self.temp_dir.name)
        self.traffic = self.root / "traffic.cm"
        self.traffic.write_text(
            "Nodes 128\nConnections 1\n16->0 start 1 size 1000000\n",
            encoding="ascii",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def completed(argv, **kwargs):
        if argv[:3] == ["git", "rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(argv, 0, stdout="3318d33cafefeed\n")
        return subprocess.CompletedProcess(argv, 0)

    def invoke(self, module, **overrides):
        values = {
            "experiment": "M1_entropy_quality",
            "phase": "smoke",
            "run_id": "m1_smoke_s13",
            "cc": "nscc",
            "seed": 13,
            "topology": TOPOLOGY,
            "traffic": self.traffic,
            "out_dir": self.root / "output",
            "trace_prefix": self.root / "output" / "m1_smoke_s13",
            "degraded_links": 2,
            "degraded_capacity_gbps": 50.0,
        }
        values.update(overrides)
        return module.run_case(**values)

    def test_builds_fixed_legacy_reps_command_and_manifest(self):
        module = load_run_case_module()
        with mock.patch.object(module.subprocess, "run", side_effect=self.completed) as run:
            manifest_path = self.invoke(module)

        simulation = run.call_args_list[-1]
        argv = simulation.args[0]
        self.assertIsInstance(argv, list)
        self.assertTrue(simulation.kwargs["check"])
        self.assertNotIn("shell", simulation.kwargs)

        expected_pairs = {
            "-sender_cc_algo": "nscc",
            "-load_balancing_algo": "reps",
            "-paths": "8",
            "-mtu": "4150",
            "-q": "211",
            "-target_q_delay": "14",
            "-prism_t_spray": "14",
            "-prism_kappa": "1",
            "-prism_n_min": "3",
            "-degraded_links": "2",
            "-degraded_capacity_gbps": "50",
            "-motivation_run_id": "m1_smoke_s13",
            "-motivation_scenario": "M1_entropy_quality",
        }
        for flag, value in expected_pairs.items():
            index = argv.index(flag)
            self.assertEqual(argv[index + 1], value)
        self.assertIn("-disable_trim", argv)
        self.assertIn("-sender_cc_only", argv)
        self.assertNotIn("-receiver_cc", argv)
        self.assertNotIn("-ecn", argv)

        manifest = json.loads(manifest_path.read_text(encoding="ascii"))
        self.assertEqual(manifest_path, self.root / "output" / "m1_smoke_s13.manifest.json")
        self.assertEqual(manifest["git_commit"], "3318d33cafefeed")
        self.assertEqual(manifest["argv"], argv)
        self.assertEqual(manifest["seed"], 13)
        self.assertEqual(manifest["schema_version"], 2)
        self.assertEqual(manifest["phase"], "smoke")
        self.assertEqual(manifest["queue_bytes"], 875650)
        self.assertEqual(
            manifest["traffic_sha256"],
            hashlib.sha256(self.traffic.read_bytes()).hexdigest(),
        )
        self.assertEqual(manifest["config"]["load_balancing_algo"], "reps")
        self.assertEqual(manifest["config"]["degraded_links"], 2)
        self.assertEqual(manifest["config"]["degraded_capacity_gbps"], 50.0)
        self.assertEqual(
            set(manifest["output_filenames"]),
            {
                "simulation",
                "stdout",
                "ack",
                "token",
                "epoch",
                "background",
                "pathmap",
                "linkmap",
                "manifest",
            },
        )

    def test_does_not_publish_manifest_when_simulator_fails(self):
        module = load_run_case_module()

        def fail_simulation(argv, **kwargs):
            if argv[:3] == ["git", "rev-parse", "HEAD"]:
                return self.completed(argv, **kwargs)
            raise subprocess.CalledProcessError(1, argv)

        with mock.patch.object(module.subprocess, "run", side_effect=fail_simulation):
            with self.assertRaises(subprocess.CalledProcessError):
                self.invoke(module)

        self.assertFalse((self.root / "output" / "m1_smoke_s13.manifest.json").exists())
        self.assertEqual(list((self.root / "output").glob("*.tmp")), [])

    def test_rejects_output_and_trace_paths_outside_add_motivation(self):
        module = load_run_case_module()
        outside = ADD_MOTIVATION.parent / "escaped-task7-output"
        for field in ("out_dir", "trace_prefix"):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    self.invoke(module, **{field: outside})

    def test_rejects_invalid_values_before_running(self):
        module = load_run_case_module()
        invalid = (
            {"phase": "calibrate"},
            {"run_id": "../escape"},
            {"cc": "receiver"},
            {"seed": -1},
            {"degraded_links": -1},
            {"degraded_capacity_gbps": 0},
            {"degraded_capacity_gbps": 101},
            {"traffic": self.root / "missing.cm"},
        )
        for values in invalid:
            with self.subTest(values=values):
                with mock.patch.object(module.subprocess, "run") as run:
                    with self.assertRaises((TypeError, ValueError, FileNotFoundError)):
                        self.invoke(module, **values)
                    run.assert_not_called()


class M1ConfigTest(unittest.TestCase):
    def test_calibration_is_exact_product_and_formal_is_header_only(self):
        calibration = M1_CONFIGS / "calibration.csv"
        with calibration.open(newline="", encoding="ascii") as handle:
            reader = csv.DictReader(handle)
            self.assertEqual(
                reader.fieldnames,
                [
                    "scenario_id",
                    "degraded_links",
                    "degraded_capacity_gbps",
                    "offered_load",
                    "seed",
                ],
            )
            rows = list(reader)

        actual = {
            (
                int(row["degraded_links"]),
                int(row["degraded_capacity_gbps"]),
                float(row["offered_load"]),
                int(row["seed"]),
            )
            for row in rows
        }
        expected = {
            (links, capacity, load, seed)
            for capacity in (75, 50, 25)
            for links in (2, 4, 8)
            for load in (0.3, 0.5, 0.7)
            for seed in (101, 102, 103)
        }
        expected.update(
            (0, 100, load, seed)
            for load in (0.3, 0.5, 0.7)
            for seed in (101, 102, 103)
        )
        self.assertEqual(len(rows), 90)
        self.assertEqual(len({row["scenario_id"] for row in rows}), 90)
        self.assertEqual(actual, expected)

        formal = (M1_CONFIGS / "formal.csv").read_text(encoding="ascii")
        self.assertEqual(
            formal,
            "scenario_id,degraded_links,degraded_capacity_gbps,offered_load,seed\n",
        )


if __name__ == "__main__":
    unittest.main()
