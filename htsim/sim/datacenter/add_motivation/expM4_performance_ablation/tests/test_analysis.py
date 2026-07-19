import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from htsim.sim.datacenter.add_motivation.expM4_performance_ablation import analyzer, make_figs, run


class AnalysisTests(unittest.TestCase):
    def test_analyze_writes_exact_per_seed_and_summary_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            formal = Path(directory) / "formal"
            aggregate = Path(directory) / "aggregate"
            _write_formal_fixture(formal)

            result = analyzer.analyze_formal(formal, aggregate)

            self.assertEqual(len(result["per_seed"]), 24)
            self.assertEqual(len(result["summary"]), 8)
            with (aggregate / "m4_per_seed.csv").open(newline="", encoding="ascii") as stream:
                per_seed = list(csv.DictReader(stream))
            with (aggregate / "m4_summary.csv").open(newline="", encoding="ascii") as stream:
                summary = list(csv.DictReader(stream))
            self.assertEqual(len(per_seed), 24)
            self.assertEqual(len(summary), 8)
            row = next(row for row in per_seed if row["arm"] == "reps_nscc" and row["scenario"] == "recoverable" and row["seed"] == "13")
            self.assertEqual(row["avg_fct_us"], "1000")
            self.assertEqual(row["p99_fct_us"], "1000")
            self.assertEqual(row["completion_rate"], "1")
            self.assertEqual(row["completed"], "6")
            self.assertEqual(row["total_started"], "6")
            self.assertEqual(next(row for row in summary if row["arm"] == "reps_nscc" and row["scenario"] == "recoverable")["n_seeds"], "3")

    def test_analyze_rejects_runner_invalid_flow_content(self):
        with tempfile.TemporaryDirectory() as directory:
            formal = Path(directory) / "formal"
            _write_formal_fixture(formal)
            flow = formal / "formal_reps_nscc_recoverable_s13.flow.txt"
            flow.write_text("0 Type FLOW_EVENT SrcID 1 Ev START FlowID 2 Flowsize 32000000\n", encoding="ascii")

            with self.assertRaisesRegex(ValueError, "flow"):
                analyzer.analyze_formal(formal, Path(directory) / "aggregate")

    def test_analyze_rejects_missing_and_identity_mismatched_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            formal = Path(directory) / "formal"
            _write_formal_fixture(formal)
            (formal / "formal_reps_nscc_recoverable_s13.manifest.json").unlink()
            with self.assertRaisesRegex(ValueError, "exactly 24"):
                analyzer.analyze_formal(formal, Path(directory) / "aggregate")

        with tempfile.TemporaryDirectory() as directory:
            formal = Path(directory) / "formal"
            _write_formal_fixture(formal)
            manifest_path = formal / "formal_reps_nscc_recoverable_s13.manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="ascii"))
            manifest["scenario_config"]["degraded_links"] = 8
            manifest_path.write_text(json.dumps(manifest), encoding="ascii")
            with self.assertRaisesRegex(ValueError, "scenario_config"):
                analyzer.analyze_formal(formal, Path(directory) / "aggregate")

    def test_analyze_rejects_nonfinite_and_nonpositive_metrics(self):
        cases = (
            ("nan_avg", float("nan"), 0.001, 1.0),
            ("infinite_p99", 0.001, float("inf"), 1.0),
            ("zero_goodput", 0.001, 0.001, 0.0),
        )
        for name, avg_s, p99_s, goodput in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                formal = Path(directory) / "formal"
                _write_formal_fixture(formal)

                with patch.object(analyzer, "fct_stats", side_effect=lambda path: {
                    "avg_s": avg_s,
                    "p99_s": p99_s,
                    "completion_rate": 1.0,
                    "completed": 6 if "recoverable" in str(path) else 12,
                    "total_started": 6 if "recoverable" in str(path) else 12,
                }), patch.object(analyzer, "aggregate_goodput_gbps", return_value=goodput), self.assertRaisesRegex(
                    ValueError, "metric"
                ):
                    analyzer.analyze_formal(formal, Path(directory) / "aggregate")

    def test_figure_reads_summary_csv_and_writes_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            formal = root / "formal"
            aggregate = root / "aggregate"
            _write_formal_fixture(formal)
            analyzer.analyze_formal(formal, aggregate)

            figure = make_figs.render_figure(aggregate / "m4_summary.csv", root / "figs")

            self.assertEqual(figure.name, "m4_performance_ablation.pdf")
            self.assertGreater(figure.stat().st_size, 0)

    def test_figure_rejects_nonfinite_summary_values(self):
        for value in ("nan", "inf"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                formal = root / "formal"
                aggregate = root / "aggregate"
                _write_formal_fixture(formal)
                analyzer.analyze_formal(formal, aggregate)
                summary_path = aggregate / "m4_summary.csv"
                with summary_path.open(newline="", encoding="ascii") as stream:
                    rows = list(csv.DictReader(stream))
                rows[0]["mean_goodput_gbps"] = value
                with summary_path.open("w", newline="", encoding="ascii") as stream:
                    writer = csv.DictWriter(stream, fieldnames=analyzer.SUMMARY_FIELDS, lineterminator="\n")
                    writer.writeheader()
                    writer.writerows(rows)

                with self.assertRaisesRegex(ValueError, "numeric"):
                    make_figs.render_figure(summary_path, root / "figs")


def _write_formal_fixture(formal: Path) -> None:
    formal.mkdir(parents=True)
    for case in run.cases_for_phase("formal"):
        scenario = run.SCENARIOS[case.scenario]
        expected_flows = run.generate_workload(foreground_flows=scenario.foreground_flows, seed=case.seed)
        workload = formal / "workloads" / f"{case.scenario}_s{case.seed}.cm"
        workload.parent.mkdir(exist_ok=True)
        workload.write_text(run.workload_text(foreground_flows=scenario.foreground_flows, seed=case.seed), encoding="ascii")
        run_id = f"formal_{case.arm}_{case.scenario}_s{case.seed}"
        dat_path = formal / f"{run_id}.dat"
        expected = run._expected_manifest(
            phase="formal",
            case=case,
            run_id=run_id,
            workload=workload,
            workload_hash=run._sha256(workload),
            dat_path=dat_path,
        )
        bindings = {}
        lines = []
        finish_s = (case.seed - 12) / 1_000.0
        for flow in expected_flows:
            src_id = flow.flow_id * 2_000
            flow_id = src_id + 1
            bindings[(src_id, flow_id)] = (flow.src, flow.flow_id)
            lines.append(f"0.000000000 Type FLOW_EVENT SrcID {src_id} Ev START FlowID {flow_id} Flowsize 32000000\n")
        for flow in expected_flows:
            src_id = flow.flow_id * 2_000
            flow_id = src_id + 1
            lines.append(f"{finish_s:.9f} Type FLOW_EVENT SrcID {src_id} Ev FINISH FlowID {flow_id} Bytes 32000000 Pkts 1\n")
        (formal / f"{run_id}.flow.txt").write_text("".join(lines), encoding="ascii")
        (formal / f"{run_id}.stdout").write_text("ok\n", encoding="ascii")
        manifest = expected | {"flow_event_bindings": run._serialized_event_bindings(bindings)}
        (formal / f"{run_id}.manifest.json").write_text(
            json.dumps(manifest, sort_keys=True), encoding="ascii"
        )
