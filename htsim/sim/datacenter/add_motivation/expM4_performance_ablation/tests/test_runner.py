import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from htsim.sim.datacenter.add_motivation.expM4_performance_ablation import run


class RunnerTests(unittest.TestCase):
    def test_fixed_matrices_have_locked_case_counts(self):
        formal = run.cases_for_phase("formal")
        smoke = run.cases_for_phase("smoke")

        self.assertEqual(len(formal), 24)
        self.assertEqual(len(smoke), 8)
        self.assertEqual(
            {(case.arm, case.scenario, case.seed) for case in formal},
            {
                (arm, scenario, seed)
                for arm in run.ARMS
                for scenario in run.SCENARIOS
                for seed in run.SEEDS
            },
        )
        self.assertEqual({case.seed for case in smoke}, {13})

    def test_parse_case_rejects_unknown_arm(self):
        with self.assertRaisesRegex(ValueError, "locked M4 arm"):
            run.parse_case(("not_an_arm", "recoverable", "13"))

    def test_runner_uses_direct_fixed_argv_without_coordination_for_nscc(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary, decoder = self._binaries(root)
            calls = self._successful_subprocess(binary, decoder)

            with patch.object(run, "HTSIM_UEC", binary), patch.object(run, "PARSE_OUTPUT", decoder), patch.object(
                run.subprocess, "run", side_effect=calls
            ) as mocked:
                manifest_path = run.run_one(
                    run.Case("reps_nscc", "recoverable", 13),
                    phase="smoke",
                    output_root=root / "smoke",
                )

            argv = mocked.call_args_list[0].args[0]
            self.assertIn("-sender_cc_only", argv)
            self.assertEqual(argv[argv.index("-sender_cc_algo") + 1], "nscc")
            self.assertEqual(argv[argv.index("-load_balancing_algo") + 1], "reps_actual")
            self.assertEqual(argv[argv.index("-paths") + 1], "8")
            self.assertEqual(argv[argv.index("-mtu") + 1], "4150")
            self.assertEqual(argv[argv.index("-q") + 1], "211")
            self.assertIn("-disable_trim", argv)
            self.assertEqual(argv[argv.index("-target_q_delay") + 1], "14")
            self.assertEqual(argv[argv.index("-prism_t_spray") + 1], "14")
            self.assertEqual(argv[argv.index("-prism_kappa") + 1], "1")
            self.assertEqual(argv[argv.index("-prism_n_min") + 1], "3")
            self.assertEqual(argv[argv.index("-degraded_links") + 1], "2")
            self.assertEqual(argv[argv.index("-degraded_capacity_gbps") + 1], "25")
            self.assertEqual(argv[argv.index("-end") + 1], "40")
            self.assertNotIn("-prism_coordination_mode", argv)
            self.assertEqual(Path(mocked.call_args_list[0].kwargs["cwd"]).parent, root / "smoke")
            self.assertTrue(manifest_path.is_file())
            self.assertTrue((root / "smoke" / "smoke_reps_nscc_recoverable_s13.flow.txt").is_file())
            self.assertFalse((root / "smoke" / "smoke_reps_nscc_recoverable_s13.dat").exists())
            self.assertFalse((root / "smoke" / "smoke_reps_nscc_recoverable_s13.ascii.tmp").exists())

    def test_prism_arm_adds_its_coordination_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary, decoder = self._binaries(root)
            calls = self._successful_subprocess(binary, decoder)

            with patch.object(run, "HTSIM_UEC", binary), patch.object(run, "PARSE_OUTPUT", decoder), patch.object(
                run.subprocess, "run", side_effect=calls
            ) as mocked:
                run.run_one(
                    run.Case("full_prism", "persistent", 13),
                    phase="smoke",
                    output_root=root / "smoke",
                )

            argv = mocked.call_args_list[0].args[0]
            self.assertEqual(argv[argv.index("-sender_cc_algo") + 1], "prism")
            self.assertEqual(argv[argv.index("-prism_coordination_mode") + 1], "full_prism")
            self.assertEqual(argv[argv.index("-degraded_links") + 1], "8")

    def test_matching_manifest_and_flow_are_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary, decoder = self._binaries(root)
            calls = self._successful_subprocess(binary, decoder)
            case = run.Case("residual_prism", "recoverable", 13)

            with patch.object(run, "HTSIM_UEC", binary), patch.object(run, "PARSE_OUTPUT", decoder), patch.object(
                run.subprocess, "run", side_effect=calls
            ) as mocked:
                first = run.run_one(case, phase="smoke", output_root=root / "smoke")
                second = run.run_one(case, phase="smoke", output_root=root / "smoke")

            self.assertEqual(first, second)
            self.assertEqual(mocked.call_count, 2)

    def test_changed_binary_rejects_reuse_without_subprocess(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary, decoder = self._binaries(root)
            calls = self._successful_subprocess(binary, decoder)
            case = run.Case("residual_prism", "recoverable", 13)

            with patch.object(run, "HTSIM_UEC", binary), patch.object(run, "PARSE_OUTPUT", decoder), patch.object(
                run.subprocess, "run", side_effect=calls
            ) as mocked:
                run.run_one(case, phase="smoke", output_root=root / "smoke")
                binary.write_bytes(b"changed binary")
                with self.assertRaisesRegex(ValueError, "identity conflicts at binary"):
                    run.run_one(case, phase="smoke", output_root=root / "smoke")

            self.assertEqual(mocked.call_count, 2)

    def test_conflicting_manifest_is_rejected_without_subprocess(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "smoke"
            root.mkdir(parents=True)
            run_id = "smoke_reps_nscc_recoverable_s13"
            (root / f"{run_id}.flow.txt").write_text("0 Type FLOW_EVENT\n", encoding="ascii")
            (root / f"{run_id}.stdout").write_text("ok\n", encoding="ascii")
            (root / f"{run_id}.manifest.json").write_text(
                json.dumps({"run_id": run_id, "arm": "full_prism"}), encoding="ascii"
            )

            with patch.object(run.subprocess, "run") as mocked, self.assertRaisesRegex(ValueError, "identity"):
                run.run_one(
                    run.Case("reps_nscc", "recoverable", 13), phase="smoke", output_root=root
                )

            mocked.assert_not_called()

    @staticmethod
    def _binaries(root):
        binary = root / "htsim_uec"
        decoder = root / "parse_output"
        binary.write_bytes(b"binary")
        decoder.write_bytes(b"decoder")
        return binary, decoder

    @staticmethod
    def _successful_subprocess(binary, decoder):
        def invoke(argv, **kwargs):
            if argv[0] == str(binary):
                output = Path(argv[argv.index("-o") + 1])
                output.write_bytes(b"dat")
            elif argv[0] == str(decoder):
                kwargs["stdout"].write("0.000000001 Type FLOW_EVENT SrcID 1 Ev START FlowID 1 Flowsize 32000000\n")
            else:
                raise AssertionError(f"unexpected subprocess: {argv}")
            return subprocess.CompletedProcess(argv, 0)

        return invoke
