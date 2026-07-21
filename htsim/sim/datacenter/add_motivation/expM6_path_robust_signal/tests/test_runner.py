"""Contract tests for the fixed M6 real-asymmetry runner."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from htsim.sim.datacenter.add_motivation.expM6_path_robust_signal import run


class M6RunnerTests(unittest.TestCase):
    def test_locked_case_matrices_are_exact(self):
        formal = run.cases_for_phase("formal")
        smoke = run.cases_for_phase("smoke")

        self.assertEqual(len(formal), 90)
        self.assertEqual(len(smoke), 3)
        self.assertEqual(
            {(case.arm, case.failed, case.seed) for case in formal},
            {
                (arm, failed, seed)
                for arm in run.ARMS
                for failed in (0, 4, 8)
                for seed in range(13, 23)
            },
        )
        self.assertEqual({case.failed for case in smoke}, {4})
        self.assertEqual({case.seed for case in smoke}, {13})

    def test_arm_mapping_and_environment_are_locked(self):
        expected = {
            "reps_nscc": ("nscc", "reps_actual", "-disable_trim"),
            "original_prism": ("prism", "reps_actual", "-disable_trim -prism_coordination_mode original_prism"),
            "path_robust_spread_prism": ("prism", "reps_actual", "-disable_trim -prism_coordination_mode original_prism -prism_path_median_spread"),
        }
        for arm, (cc, lb, extra_args) in expected.items():
            with self.subTest(arm=arm):
                case = run.Case(arm, 4, 13)
                command = run.run_lib_command(case, Path("/tmp/m2m.cm"), Path("/tmp/output"))
                env = run.fixed_environment(case)
                self.assertEqual(command[2:4], [cc, lb])
                self.assertEqual(command[4], "4")
                self.assertEqual(env["PATHS"], "8")
                self.assertEqual(env["END_MS"], "8")
                self.assertEqual(env["EXTRA_ARGS"], extra_args)
                self.assertNotIn("PRISM_EPOCH", env)
                self.assertNotIn("PRISM_PATHRTT", env)

    def test_workload_is_the_fixed_expa_many_to_many_matrix(self):
        with tempfile.TemporaryDirectory() as directory:
            workload = Path(directory) / "m2m.cm"
            digest = run.ensure_workload(workload)

            lines = workload.read_text(encoding="ascii").splitlines()
            self.assertEqual(lines[:2], ["Nodes 128", "Connections 64"])
            self.assertEqual(lines[2], "16->0 start 1000 size 2000000")
            self.assertEqual(lines[-1], "79->15 start 1000 size 2000000")
            self.assertEqual(len(digest), 64)

    def test_matching_outputs_reuse_and_conflicting_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = self._inputs(root)
            case = run.Case("path_robust_spread_prism", 4, 13)
            with self._patched_inputs(inputs), patch.object(
                run.subprocess, "run", side_effect=self._successful_run_lib
            ) as mocked:
                first = run.run_one(case, phase="smoke", output_root=root / "smoke")
                second = run.run_one(case, phase="smoke", output_root=root / "smoke")
                self.assertEqual(first, second)
                self.assertEqual(mocked.call_count, 1)
                self.assertEqual(len(json.loads(first.read_text(encoding="ascii"))["flow_event_bindings"]), 64)

                manifest = json.loads(first.read_text(encoding="ascii"))
                manifest["failed_links"] = 8
                first.write_text(json.dumps(manifest), encoding="ascii")
                with self.assertRaisesRegex(ValueError, "identity conflicts"):
                    run.run_one(case, phase="smoke", output_root=root / "smoke")
                self.assertEqual(mocked.call_count, 1)

    def test_rejects_incomplete_flow_and_stale_temporary_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = self._inputs(root)
            case = run.Case("reps_nscc", 4, 13)
            run_id = run.case_id(case)
            output = root / "smoke"
            output.mkdir()
            (output / f"{run_id}.dat").write_text("stale", encoding="ascii")
            with self._patched_inputs(inputs), self.assertRaisesRegex(FileExistsError, "temporary"):
                run.run_one(case, phase="smoke", output_root=output)

            (output / f"{run_id}.dat").unlink()
            with self._patched_inputs(inputs), patch.object(
                run.subprocess, "run", side_effect=self._incomplete_run_lib
            ), self.assertRaisesRegex(RuntimeError, "incomplete flow"):
                run.run_one(case, phase="smoke", output_root=output)

    def test_runner_rejects_flow_event_ids_with_different_idmap_endpoints(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = self._inputs(root)
            idmap = self._idmap_text().replace("2001 Uec_16_0", "2001 Uec_16_1")
            with self._patched_inputs(inputs), patch.object(
                run.subprocess, "run", side_effect=self._run_lib_with(self._flow_text(), idmap)
            ), self.assertRaisesRegex(RuntimeError, "flow output"):
                run.run_one(run.Case("reps_nscc", 4, 13), phase="smoke", output_root=root / "smoke")

    def test_runner_rejects_flow_event_id_absent_from_idmap(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = self._inputs(root)
            flow = self._flow_text().replace("FlowID 2001", "FlowID 9999")
            with self._patched_inputs(inputs), patch.object(
                run.subprocess, "run", side_effect=self._run_lib_with(flow, self._idmap_text())
            ), self.assertRaisesRegex(RuntimeError, "flow output"):
                run.run_one(run.Case("reps_nscc", 4, 13), phase="smoke", output_root=root / "smoke")

    def test_runner_rejects_duplicate_start_and_finish_events(self):
        duplicates = {
            "start": "0.000001000 Type FLOW_EVENT SrcID 1001 Ev START FlowID 2001 Flowsize 2000000\n",
            "finish": "0.001001000 Type FLOW_EVENT SrcID 1001 Ev FINISH FlowID 2001 Bytes 2000000 Pkts 1\n",
        }
        for name, duplicate in duplicates.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                inputs = self._inputs(root)
                with self._patched_inputs(inputs), patch.object(
                    run.subprocess,
                    "run",
                    side_effect=self._run_lib_with(self._flow_text() + duplicate, self._idmap_text()),
                ), self.assertRaisesRegex(RuntimeError, "duplicate"):
                    run.run_one(run.Case("reps_nscc", 4, 13), phase="smoke", output_root=root / "smoke")

    @staticmethod
    def _inputs(root: Path) -> dict[str, Path]:
        topology = root / "fat_tree_128_1os.topo"
        binary = root / "htsim_uec"
        decoder = root / "parse_output"
        run_lib = root / "run_lib.sh"
        for path in (topology, binary, decoder, run_lib):
            path.write_text(path.name, encoding="ascii")
        return {"topology": topology, "binary": binary, "decoder": decoder, "run_lib": run_lib}

    @staticmethod
    def _flow_text(completed: int = 64) -> str:
        lines = []
        for flow_id in range(1, 65):
            lines.append(
                f"0.000001000 Type FLOW_EVENT SrcID {1000 + flow_id} Ev START FlowID {2000 + flow_id} Flowsize 2000000\n"
            )
        for flow_id in range(1, completed + 1):
            lines.append(
                f"0.001001000 Type FLOW_EVENT SrcID {1000 + flow_id} Ev FINISH FlowID {2000 + flow_id} Bytes 2000000 Pkts 1\n"
            )
        return "".join(lines)

    @staticmethod
    def _idmap_text() -> str:
        lines = []
        for flow_id in range(1, 65):
            endpoint = f"Uec_{15 + flow_id}_{(flow_id - 1) % 16}"
            lines.extend((f"{1000 + flow_id} {endpoint}\n", f"{2000 + flow_id} {endpoint}\n"))
        return "".join(lines)

    @classmethod
    def _successful_run_lib(cls, command, **kwargs):
        output = Path(command[-1])
        tag = command[-2]
        output.mkdir(parents=True, exist_ok=True)
        (output / f"{tag}.flow.txt").write_text(cls._flow_text(), encoding="ascii")
        (output / f"{tag}.stdout").write_text("ok\n", encoding="ascii")
        (output / f"{tag}.idmap").write_text(cls._idmap_text(), encoding="ascii")
        return subprocess.CompletedProcess(command, 0)

    @classmethod
    def _incomplete_run_lib(cls, command, **kwargs):
        output = Path(command[-1])
        tag = command[-2]
        output.mkdir(parents=True, exist_ok=True)
        (output / f"{tag}.flow.txt").write_text(cls._flow_text(completed=63), encoding="ascii")
        (output / f"{tag}.stdout").write_text("ok\n", encoding="ascii")
        (output / f"{tag}.idmap").write_text(cls._idmap_text(), encoding="ascii")
        return subprocess.CompletedProcess(command, 0)

    @classmethod
    def _run_lib_with(cls, flow: str, idmap: str):
        def runner(command, **kwargs):
            output = Path(command[-1])
            tag = command[-2]
            output.mkdir(parents=True, exist_ok=True)
            (output / f"{tag}.flow.txt").write_text(flow, encoding="ascii")
            (output / f"{tag}.stdout").write_text("ok\n", encoding="ascii")
            (output / f"{tag}.idmap").write_text(idmap, encoding="ascii")
            return subprocess.CompletedProcess(command, 0)
        return runner

    @staticmethod
    def _patched_inputs(inputs: dict[str, Path]):
        return patch.multiple(
            run,
            TOPOLOGY=inputs["topology"],
            HTSIM_UEC=inputs["binary"],
            PARSE_OUTPUT=inputs["decoder"],
            RUN_LIB=inputs["run_lib"],
        )


if __name__ == "__main__":
    unittest.main()
