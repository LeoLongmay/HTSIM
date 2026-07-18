import csv
import hashlib
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ADD_MOTIVATION = Path(__file__).resolve().parents[2]
RUN_CASE_PATH = ADD_MOTIVATION / "common" / "run_case.py"
TOPOLOGY = ADD_MOTIVATION.parent / "topologies" / "fat_tree_128_1os.topo"
M1_CONFIGS = ADD_MOTIVATION / "expM1_entropy_quality" / "configs"
TRACE_HEADERS = {
    "ack": (
        "schema_version", "run_id", "seed", "scenario", "event_seq", "time_ps",
        "flow_id", "epoch_id", "acked_psn", "entropy", "physical_path_id",
        "raw_rtt_ps", "base_rtt_ps", "qdelay_ps", "ecn", "genuine_sample",
        "retransmitted", "forward_path_backlog_ps", "selection_source",
        "source_token_id", "newly_acked_bytes", "new_data_bytes_sent_total",
        "cwnd_bytes",
    ),
    "token": (
        "schema_version", "run_id", "event_seq", "time_ps", "flow_id", "operation",
        "reason", "token_id", "entropy", "queue_depth_before", "queue_depth_after",
        "related_ack_event_seq", "cache_slot", "cache_generation", "admission_written",
    ),
    "epoch": (
        "schema_version", "run_id", "event_seq", "flow_id", "epoch_id", "start_ps",
        "end_ps", "sample_count", "raw_floor_ps", "raw_spread_ps", "smooth_floor_ps",
        "smooth_spread_ps", "observed_region", "actual_region", "engaged",
        "entropy_coverage", "physical_path_coverage", "new_data_bytes_sent_total",
        "acked_bytes_total", "cwnd_bytes",
    ),
    "background": (
        "schema_version", "run_id", "event_seq", "time_ps", "background_id",
        "operation", "src", "dst", "path_index", "configured_rate_gbps",
        "delivered_bytes", "queue_fingerprint",
    ),
    "pathmap": (
        "schema_version", "run_id", "flow_id", "entropy", "physical_path_id",
        "resolution_status", "queue_fingerprint", "bottleneck_rate_gbps",
        "contains_reduced_link", "ordered_queue_ids",
    ),
    "linkmap": (
        "schema_version", "run_id", "queue_id", "queue_name", "rate_gbps",
        "reduced_speed",
    ),
    "coordination": (
        "schema_version", "run_id", "event_seq", "time_ps", "flow_id", "epoch_id",
        "round_id", "cache_slot", "cache_generation", "floor_ps", "spread_ps",
        "spread_ref_ps", "residual_ps", "action", "reason", "refresh_complete",
        "progress", "handoff", "cwnd_bytes", "control_state",
    ),
}


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

    def write_valid_outputs(self, argv):
        simulation = Path(argv[argv.index("-o") + 1])
        simulation.write_bytes(b"nonempty simulator output\n")
        prefix = Path(argv[argv.index("-motivation_trace_prefix") + 1])
        run_id = argv[argv.index("-motivation_run_id") + 1]
        for kind, header in TRACE_HEADERS.items():
            path = Path(f"{prefix}.{kind}.csv")
            path.write_text(",".join(header) + "\n", encoding="ascii")
        with Path(f"{prefix}.linkmap.csv").open("a", encoding="ascii") as stream:
            stream.write(f"2,{run_id},1,queue-1,100,0\n")

    def completed(self, argv, **kwargs):
        if argv[:3] == ["git", "rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(argv, 0, stdout="3318d33cafefeed\n")
        kwargs["stdout"].write("simulator stdout\n")
        kwargs["stdout"].flush()
        self.write_valid_outputs(argv)
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
        self.assertNotIn("-queue_type", argv)
        self.assertNotIn("-host_queue_type", argv)
        self.assertNotIn("-motivation_background_config", argv)
        self.assertNotIn("-prism_coordination_mode", argv)
        for flag in (
            "-prism_smooth_beta", "-prism_hysteresis",
            "-prism_engage_spread", "-prism_engage_mult",
        ):
            self.assertNotIn(flag, argv)

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
        self.assertEqual(
            manifest["topology_sha256"],
            hashlib.sha256(TOPOLOGY.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            manifest["binary_sha256"],
            hashlib.sha256(module.BINARY.read_bytes()).hexdigest(),
        )
        self.assertEqual(manifest["config"]["load_balancing_algo"], "reps")
        self.assertEqual(manifest["config"]["degraded_links"], 2)
        self.assertEqual(manifest["config"]["degraded_capacity_gbps"], 50.0)
        self.assertIsNone(manifest["config"]["background_config"])
        self.assertEqual(manifest["config"]["prism_coordination_mode"], "disabled")
        self.assertNotIn("network_queue_type", manifest["config"])
        self.assertNotIn("host_queue_type", manifest["config"])
        self.assertNotIn("background_config_sha256", manifest)
        self.assertNotIn("background_safety_contract", manifest)
        self.assertNotIn("analysis_config", manifest)
        self.assertNotIn("prism_smooth_beta", manifest["config"])
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
                "coordination",
                "manifest",
            },
        )

    def test_laps_is_accepted_on_both_axes_and_preserved_in_command(self):
        module = load_run_case_module()
        self.assertIn("laps", module.VALID_CCS)
        self.assertIn("laps", module.VALID_LOAD_BALANCERS)

        with mock.patch.object(module.subprocess, "run", side_effect=self.completed) as run:
            self.invoke(module, cc="laps", load_balancing_algo="laps")

        argv = run.call_args_list[-1].args[0]
        self.assertEqual(argv[argv.index("-sender_cc_algo") + 1], "laps")
        self.assertEqual(argv[argv.index("-load_balancing_algo") + 1], "laps")

    def test_m2_phases_round_trip_analysis_config(self):
        module = load_run_case_module()
        self.assertTrue({"coarse", "confirmation"}.issubset(module.VALID_PHASES))
        for phase, scenario in (("coarse", ""), ("confirmation", "recoverable")):
            with self.subTest(phase=phase):
                run_id = f"m2_{phase}_s101"
                config = {
                    "cell_id": "coarse-f8-d8-c50",
                    "scenario": scenario,
                    "foreground_flows": 8,
                    "degraded_links": 8,
                    "degraded_capacity_gbps": 50.0,
                    "seed": 101,
                }
                with mock.patch.object(
                    module.subprocess, "run", side_effect=self.completed
                ):
                    manifest_path = self.invoke(
                        module,
                        experiment="M2_redistribution_progress",
                        phase=phase,
                        run_id=run_id,
                        seed=101,
                        out_dir=self.root / phase,
                        trace_prefix=self.root / phase / run_id,
                        degraded_links=8,
                        degraded_capacity_gbps=50.0,
                        analysis_config=config,
                    )
                manifest = json.loads(manifest_path.read_text(encoding="ascii"))
                self.assertEqual(manifest["phase"], phase)
                self.assertEqual(manifest["analysis_config"], config)

    def test_prism_has_explicit_stability_parameters_and_manifest_config(self):
        module = load_run_case_module()
        with mock.patch.object(module.subprocess, "run", side_effect=self.completed) as run:
            manifest_path = self.invoke(module, cc="prism")

        argv = run.call_args_list[-1].args[0]
        expected = {
            "-prism_smooth_beta": "1",
            "-prism_hysteresis": "0",
            "-prism_engage_spread": "0",
            "-prism_engage_mult": "0",
        }
        for flag, value in expected.items():
            self.assertEqual(argv.count(flag), 1)
            self.assertEqual(argv[argv.index(flag) + 1], value)
        manifest = json.loads(manifest_path.read_text(encoding="ascii"))
        self.assertEqual(
            {key: manifest["config"][key.removeprefix("-")] for key in expected},
            {key: int(value) for key, value in expected.items()},
        )

    def test_prism_coordination_mode_is_opt_in_and_recorded(self):
        module = load_run_case_module()
        with mock.patch.object(module.subprocess, "run", side_effect=self.completed) as run:
            manifest_path = self.invoke(
                module,
                cc="prism",
                load_balancing_algo="reps_actual",
                prism_coordination_mode="full_prism",
            )

        argv = run.call_args_list[-1].args[0]
        self.assertEqual(argv[argv.index("-prism_coordination_mode") + 1], "full_prism")
        manifest = json.loads(manifest_path.read_text(encoding="ascii"))
        self.assertEqual(manifest["config"]["prism_coordination_mode"], "full_prism")

    def test_rejects_invalid_prism_coordination_mode_before_running(self):
        module = load_run_case_module()
        with mock.patch.object(module.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "invalid prism_coordination_mode"):
                self.invoke(module, prism_coordination_mode="unknown")
        run.assert_not_called()

    def test_outcome_recycle_requires_prism_and_reps_actual(self):
        module = load_run_case_module()
        with mock.patch.object(module.subprocess, "run", side_effect=self.completed) as run:
            manifest_path = self.invoke(
                module,
                cc="prism",
                load_balancing_algo="reps_actual",
                prism_coordination_mode="outcome_recycle",
            )

        argv = run.call_args_list[-1].args[0]
        self.assertEqual(argv[argv.index("-prism_coordination_mode") + 1], "outcome_recycle")
        manifest = json.loads(manifest_path.read_text(encoding="ascii"))
        self.assertEqual(manifest["config"]["prism_coordination_mode"], "outcome_recycle")

        for overrides in (
            {"cc": "nscc", "load_balancing_algo": "reps_actual"},
            {"cc": "prism", "load_balancing_algo": "reps"},
        ):
            with self.subTest(overrides=overrides), mock.patch.object(module.subprocess, "run") as run:
                with self.assertRaisesRegex(ValueError, "outcome_recycle requires"):
                    self.invoke(module, prism_coordination_mode="outcome_recycle", **overrides)
                run.assert_not_called()

    def test_m2_rejects_missing_fields_and_seed_mismatch_before_running(self):
        module = load_run_case_module()
        valid = {
            "cell_id": "coarse-f8-d8-c50",
            "scenario": "",
            "foreground_flows": 8,
            "degraded_links": 8,
            "degraded_capacity_gbps": 50.0,
            "seed": 101,
        }
        invalid = [None, {key: value for key, value in valid.items() if key != "cell_id"}]
        invalid.append({**valid, "seed": 102})
        for config in invalid:
            with self.subTest(config=config):
                with mock.patch.object(module.subprocess, "run") as run:
                    with self.assertRaises((TypeError, ValueError)):
                        self.invoke(
                            module,
                            experiment="M2_redistribution_progress",
                            phase="coarse",
                            seed=101,
                            analysis_config=config,
                        )
                    run.assert_not_called()

    def test_cli_accepts_empty_m2_scenario_and_builds_complete_config(self):
        module = load_run_case_module()
        argv = [
            "--experiment", "M2_redistribution_progress",
            "--phase", "coarse",
            "--run-id", "m2_coarse_s101",
            "--cc", "prism",
            "--seed", "101",
            "--topology", str(TOPOLOGY),
            "--traffic", str(self.traffic),
            "--out-dir", str(self.root / "output"),
            "--trace-prefix", str(self.root / "output" / "m2_coarse_s101"),
            "--m2-cell-id", "coarse-f8-d8-c50",
            "--m2-scenario", "",
            "--m2-foreground-flows", "8",
            "--m2-degraded-links", "8",
            "--m2-degraded-capacity-gbps", "50",
        ]
        with mock.patch.object(
            module, "run_case", return_value=Path("manifest.json")
        ) as run:
            module.main(argv)
        self.assertEqual(
            run.call_args.kwargs["analysis_config"],
            {
                "cell_id": "coarse-f8-d8-c50",
                "scenario": "",
                "foreground_flows": 8,
                "degraded_links": 8,
                "degraded_capacity_gbps": 50.0,
                "seed": 101,
            },
        )

    def test_background_uses_drain_safe_queues_and_records_safety_contract(self):
        module = load_run_case_module()
        background = self.root / "background.csv"
        background.write_text(
            "background_id,src,dst,path_index,rate_gbps,start_ps,stop_ps\n"
            "0,32,0,3,25,200000000,1200000000\n",
            encoding="ascii",
        )

        with mock.patch.object(module.subprocess, "run", side_effect=self.completed) as run:
            manifest_path = self.invoke(module, background_config=background)

        argv = run.call_args_list[-1].args[0]
        self.assertEqual(argv.count("-queue_type"), 1)
        self.assertEqual(argv[argv.index("-queue_type") + 1], "ecn")
        self.assertEqual(argv.count("-host_queue_type"), 1)
        self.assertEqual(argv[argv.index("-host_queue_type") + 1], "fair_prio")
        self.assertEqual(argv.count("-disable_trim"), 1)
        self.assertNotIn("-ecn", argv)
        self.assertEqual(argv.count("-motivation_background_config"), 1)
        self.assertEqual(
            argv[argv.index("-motivation_background_config") + 1],
            str(background.resolve()),
        )

        manifest = json.loads(manifest_path.read_text(encoding="ascii"))
        self.assertEqual(manifest["argv"], argv)
        self.assertEqual(manifest["config"]["background_config"], str(background.resolve()))
        self.assertEqual(manifest["config"]["network_queue_type"], "ecn")
        self.assertEqual(manifest["config"]["host_queue_type"], "fair_prio")
        self.assertEqual(
            manifest["background_config_sha256"],
            hashlib.sha256(background.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            manifest["background_safety_contract"],
            {
                "enforced_by": "main_uec",
                "rate_lte_host_queue_bitrate": True,
                "source_distinct_from_all_foreground_endpoints": True,
                "source_unique_across_background_streams": True,
                "stop_plus_route_drain_bound_lt_simulation_end": True,
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

    def test_rejects_stale_manifest_before_running_any_subprocess(self):
        module = load_run_case_module()
        output = self.root / "output"
        output.mkdir()
        (output / "m1_smoke_s13.manifest.json").write_text("stale\n", encoding="ascii")

        with mock.patch.object(module.subprocess, "run") as run:
            with self.assertRaises(FileExistsError):
                self.invoke(module)
            run.assert_not_called()

    def test_rejects_output_symlink_before_running_any_subprocess(self):
        module = load_run_case_module()
        output = self.root / "output"
        output.mkdir()
        os.symlink(self.traffic, output / "m1_smoke_s13.stdout")

        with mock.patch.object(module.subprocess, "run") as run:
            with self.assertRaises(FileExistsError):
                self.invoke(module)
            run.assert_not_called()

    def test_does_not_publish_manifest_for_invalid_trace_outputs(self):
        module = load_run_case_module()

        def malformed_trace(argv, **kwargs):
            result = self.completed(argv, **kwargs)
            if argv[:3] != ["git", "rev-parse", "HEAD"]:
                prefix = Path(argv[argv.index("-motivation_trace_prefix") + 1])
                Path(f"{prefix}.ack.csv").write_text("wrong,header\n", encoding="ascii")
            return result

        with mock.patch.object(module.subprocess, "run", side_effect=malformed_trace):
            with self.assertRaises(ValueError):
                self.invoke(module)

        self.assertFalse((self.root / "output" / "m1_smoke_s13.manifest.json").exists())

    def test_does_not_publish_manifest_for_trace_run_id_mismatch(self):
        module = load_run_case_module()

        def wrong_run_id(argv, **kwargs):
            result = self.completed(argv, **kwargs)
            if argv[:3] != ["git", "rev-parse", "HEAD"]:
                prefix = Path(argv[argv.index("-motivation_trace_prefix") + 1])
                linkmap = Path(f"{prefix}.linkmap.csv")
                header = ",".join(TRACE_HEADERS["linkmap"])
                linkmap.write_text(f"{header}\n2,other,1,queue-1,100,0\n", encoding="ascii")
            return result

        with mock.patch.object(module.subprocess, "run", side_effect=wrong_run_id):
            with self.assertRaisesRegex(ValueError, "trace run_id mismatch"):
                self.invoke(module)

        self.assertFalse((self.root / "output" / "m1_smoke_s13.manifest.json").exists())

    def test_does_not_publish_manifest_for_post_run_output_symlink(self):
        module = load_run_case_module()

        def symlink_output(argv, **kwargs):
            result = self.completed(argv, **kwargs)
            if argv[:3] != ["git", "rev-parse", "HEAD"]:
                simulation = Path(argv[argv.index("-o") + 1])
                simulation.unlink()
                os.symlink(self.traffic, simulation)
            return result

        with mock.patch.object(module.subprocess, "run", side_effect=symlink_output):
            with self.assertRaisesRegex(ValueError, "regular non-symlink"):
                self.invoke(module)

        self.assertFalse((self.root / "output" / "m1_smoke_s13.manifest.json").exists())

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
            {"degraded_links": 2**32},
            {"degraded_capacity_gbps": 0},
            {"degraded_capacity_gbps": 101},
            {"degraded_links": 0, "degraded_capacity_gbps": 50},
            {"degraded_links": 2, "degraded_capacity_gbps": 100},
            {"traffic": self.root / "missing.cm"},
            {"background_config": self.root / "missing-background.csv"},
        )
        for values in invalid:
            with self.subTest(values=values):
                with mock.patch.object(module.subprocess, "run") as run:
                    with self.assertRaises((TypeError, ValueError, FileNotFoundError)):
                        self.invoke(module, **values)
                    run.assert_not_called()


class M1ConfigTest(unittest.TestCase):
    def test_scenario_identifier_helper_is_conservative(self):
        module = load_run_case_module()
        self.assertEqual(module.validate_identifier("gray_c50-d2.s13", "scenario_id"),
                         "gray_c50-d2.s13")
        for value in ("", "../escape", "/absolute", "has space", "line\nbreak"):
            with self.subTest(value=value):
                with self.assertRaises((TypeError, ValueError)):
                    module.validate_identifier(value, "scenario_id")

    def test_scripts_validate_scenario_before_filename_construction(self):
        experiment = ADD_MOTIVATION / "expM1_entropy_quality"
        for name in ("calibrate.sh", "repro.sh"):
            with self.subTest(script=name):
                script = (experiment / name).read_text(encoding="ascii")
                validation = script.index('--validate-identifier "$scenario_id"')
                filename = script.index('traffic="$OUT/${run_id}.cm"')
                self.assertLess(validation, filename)

    def test_calibration_is_exact_product_and_formal_is_locked_pair(self):
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

        with (M1_CONFIGS / "formal.csv").open(newline="", encoding="ascii") as handle:
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
            formal_rows = list(reader)

        self.assertEqual(len(formal_rows), 10)
        symmetric = [row for row in formal_rows if int(row["degraded_links"]) == 0]
        gray = [row for row in formal_rows if int(row["degraded_links"]) > 0]
        self.assertEqual(len(symmetric), 5)
        self.assertEqual(len(gray), 5)
        self.assertEqual({int(row["seed"]) for row in symmetric}, {13, 14, 15, 16, 17})
        self.assertEqual({int(row["seed"]) for row in gray}, {13, 14, 15, 16, 17})
        self.assertEqual(
            {float(row["offered_load"]) for row in symmetric},
            {float(row["offered_load"]) for row in gray},
        )
        symmetric_configs = {
            (row["scenario_id"], row["degraded_capacity_gbps"], row["offered_load"])
            for row in symmetric
        }
        gray_configs = {
            (
                row["scenario_id"],
                row["degraded_links"],
                row["degraded_capacity_gbps"],
                row["offered_load"],
            )
            for row in gray
        }
        self.assertEqual(len(symmetric_configs), 1)
        self.assertEqual(len(gray_configs), 1)


if __name__ == "__main__":
    unittest.main()
