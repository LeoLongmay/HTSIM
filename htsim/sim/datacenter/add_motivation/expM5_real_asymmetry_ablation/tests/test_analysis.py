"""TDD coverage for M5 finite-flow aggregation and rendering."""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from htsim.sim.datacenter.add_motivation.expM5_real_asymmetry_ablation import analyzer, make_figs, run


class M5AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.hash_patch = patch.object(run, "_sha256", return_value="synthetic-sha256")
        self.hash_patch.start()

    def tearDown(self):
        self.hash_patch.stop()

    def test_analyze_writes_exact_matrix_and_ten_seed_means(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            formal = root / "formal"
            aggregate = root / "aggregate"
            _write_formal_fixture(formal)

            result = analyzer.analyze_formal(formal, aggregate)

            self.assertEqual(len(result["per_seed"]), 120)
            self.assertEqual(len(result["summary"]), 12)
            with (aggregate / "m5_per_seed.csv").open(newline="", encoding="ascii") as stream:
                per_seed = list(csv.DictReader(stream))
            with (aggregate / "m5_summary.csv").open(newline="", encoding="ascii") as stream:
                summary = list(csv.DictReader(stream))
            self.assertEqual(len(per_seed), 120)
            self.assertEqual(len(summary), 12)
            row = next(row for row in per_seed if row["arm"] == "reps_nscc" and row["failed_links"] == "0" and row["seed"] == "13")
            self.assertEqual(row["avg_fct_us"], "1000")
            self.assertEqual(row["p99_fct_us"], "1000")
            self.assertEqual(row["completion_rate"], "1")
            self.assertEqual(row["completed"], "64")
            self.assertEqual(row["total_started"], "64")
            summary_row = next(row for row in summary if row["arm"] == "full_prism" and row["failed_links"] == "8")
            self.assertEqual(summary_row["n_seeds"], "10")
            self.assertEqual(summary_row["mean_avg_fct_us"], "5500")

    def test_analyze_rejects_missing_or_runner_invalid_input(self):
        with tempfile.TemporaryDirectory() as directory:
            formal = Path(directory) / "formal"
            _write_formal_fixture(formal)
            (formal / "m5_reps_nscc_f0_s13.manifest.json").unlink()
            with self.assertRaisesRegex(ValueError, "exactly 120"):
                analyzer.analyze_formal(formal, Path(directory) / "aggregate")

        with tempfile.TemporaryDirectory() as directory:
            formal = Path(directory) / "formal"
            _write_formal_fixture(formal)
            (formal / "m5_reps_nscc_f0_s13.idmap").write_text("1 Uec_16_0\n", encoding="ascii")
            with self.assertRaisesRegex(ValueError, "flow"):
                analyzer.analyze_formal(formal, Path(directory) / "aggregate")

    def test_figure_reads_summary_only_and_writes_single_stem(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            formal = root / "formal"
            aggregate = root / "aggregate"
            _write_formal_fixture(formal)
            analyzer.analyze_formal(formal, aggregate)

            pdf = make_figs.render_figure(aggregate / "m5_summary.csv", root / "figs")

            self.assertEqual(pdf.name, "m5_real_asymmetry_ablation.pdf")
            self.assertGreater(pdf.stat().st_size, 0)
            self.assertGreater((root / "figs" / "m5_real_asymmetry_ablation.png").stat().st_size, 0)

    def test_figure_rejects_nonfinite_summary_value(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            formal = root / "formal"
            aggregate = root / "aggregate"
            _write_formal_fixture(formal)
            analyzer.analyze_formal(formal, aggregate)
            summary_path = aggregate / "m5_summary.csv"
            with summary_path.open(newline="", encoding="ascii") as stream:
                rows = list(csv.DictReader(stream))
            rows[0]["mean_goodput_gbps"] = "nan"
            with summary_path.open("w", newline="", encoding="ascii") as stream:
                writer = csv.DictWriter(stream, fieldnames=analyzer.SUMMARY_FIELDS, lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaisesRegex(ValueError, "numeric"):
                make_figs.render_figure(summary_path, root / "figs")


def _write_formal_fixture(formal: Path) -> None:
    formal.mkdir(parents=True)
    workload = formal / "m2m.cm"
    workload_hash = run.ensure_workload(workload)
    for case in run.cases_for_phase("formal"):
        run_id = run.case_id(case)
        outputs = run._required_outputs(formal, run_id)
        expected = run._expected_manifest(
            phase="formal",
            case=case,
            workload=workload,
            workload_hash=workload_hash,
            output_root=formal,
        )
        lines = []
        bindings = {}
        finish_s = (case.seed - 12) / 1_000.0 + 0.000001
        idmap_lines = []
        for index, (src, dst) in enumerate(sorted(run._expected_workload_endpoints()), start=1):
            src_id = 10_000 + index
            flow_id = 20_000 + index
            bindings[(src_id, flow_id)] = (src, dst)
            idmap_lines.extend((f"{src_id} Uec_{src}_{dst}\n", f"{flow_id} Uec_{src}_{dst}\n"))
            lines.append(
                f"0.000001000 Type FLOW_EVENT SrcID {src_id} Ev START FlowID {flow_id} Flowsize 2000000\n"
            )
        for index, (src, dst) in enumerate(sorted(run._expected_workload_endpoints()), start=1):
            src_id = 10_000 + index
            flow_id = 20_000 + index
            lines.append(
                f"{finish_s:.9f} Type FLOW_EVENT SrcID {src_id} Ev FINISH FlowID {flow_id} Bytes 2000000 Pkts 1\n"
            )
        outputs["flow"].write_text("".join(lines), encoding="ascii")
        outputs["stdout"].write_text("ok\n", encoding="ascii")
        outputs["idmap"].write_text("".join(idmap_lines), encoding="ascii")
        outputs["manifest"].write_text(
            json.dumps(expected | {"flow_event_bindings": run._serialized_event_bindings(bindings)}, sort_keys=True),
            encoding="ascii",
        )


if __name__ == "__main__":
    unittest.main()
