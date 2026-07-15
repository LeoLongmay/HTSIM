import csv
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from htsim.sim.datacenter.add_motivation.expM2_redistribution_progress import make_figs


SUMMARY_FIELDS = (
    "cell_id", "foreground_flows", "hot_path_groups", "background_utilization",
    "seed", "episode_count", "completed_rounds", "valid_completed_rounds",
    "completion_rate", "low_floor_high_spread_occupancy",
)
ROUND_FIELDS = (
    "cell_id", "foreground_flows", "hot_path_groups", "background_utilization",
    "seed", "complete", "valid_round", "capacity_classification",
    "failed_predicates",
)


def _write(path: Path, fields, rows) -> None:
    with path.open("w", newline="", encoding="ascii") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _fixture_rows(*, reverse=False):
    summaries = []
    rounds = []
    for foreground in make_figs.COARSE_FOREGROUND:
        for hot_groups in make_figs.COARSE_HOT_GROUPS:
            for utilization in make_figs.COARSE_UTILIZATION:
                cell_id = (
                    f"coarse-f{foreground}-h{hot_groups}-u{int(utilization * 100)}"
                )
                classifications = ["invalid"]
                if (foreground, hot_groups, utilization) == (16, 4, 0.5):
                    classifications = ["recoverable", "persistent"]
                elif (foreground, hot_groups, utilization) == (8, 2, 0.25):
                    classifications = ["recoverable", "recoverable"]
                elif (foreground, hot_groups, utilization) == (32, 6, 0.75):
                    classifications = ["persistent", "persistent"]
                valid_count = int(classifications[0] != "invalid")
                summaries.append({
                    "cell_id": cell_id,
                    "foreground_flows": foreground,
                    "hot_path_groups": hot_groups,
                    "background_utilization": utilization,
                    "seed": 101,
                    "episode_count": len(classifications),
                    "completed_rounds": len(classifications),
                    "valid_completed_rounds": valid_count,
                    "completion_rate": 1.0,
                    "low_floor_high_spread_occupancy": 0.2 + utilization / 2,
                })
                for index, classification in enumerate(classifications):
                    rounds.append({
                        "cell_id": cell_id,
                        "foreground_flows": foreground,
                        "hot_path_groups": hot_groups,
                        "background_utilization": utilization,
                        "seed": 101,
                        "complete": 1,
                        "valid_round": int(index < valid_count),
                        "capacity_classification": classification,
                        "failed_predicates": (
                            "capacity_witness_invalid:delivery;"
                            "coarse_scenario_inference_invalid_completed_evidence"
                            if classification == "invalid" else ""
                        ),
                    })
    if reverse:
        summaries.reverse()
        rounds.reverse()
    return summaries, rounds


def _write_fixture(directory: Path, *, reverse=False) -> None:
    summaries, rounds = _fixture_rows(reverse=reverse)
    _write(directory / "summary.csv", SUMMARY_FIELDS, summaries)
    _write(directory / "rounds.csv", ROUND_FIELDS, rounds)


class CalibrationPlotTests(unittest.TestCase):
    def tearDown(self):
        shutil.rmtree(make_figs._CACHE_DIR, ignore_errors=True)

    def test_render_uses_only_aggregates_preserves_mixed_and_is_order_independent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_data = root / "first"
            second_data = root / "second"
            first_data.mkdir()
            second_data.mkdir()
            _write_fixture(first_data)
            _write_fixture(second_data, reverse=True)

            with mock.patch.object(make_figs, "_read", wraps=make_figs._read) as reader:
                first_outputs = make_figs.render_calibration(
                    first_data, root / "figs" / "first"
                )
            second_outputs = make_figs.render_calibration(
                second_data, root / "figs" / "second"
            )

            self.assertEqual(
                [call.args[0].name for call in reader.call_args_list],
                ["summary.csv", "rounds.csv"],
            )
            self.assertEqual(
                {path.name for path in first_outputs},
                {
                    "calibration_diagnostics.csv",
                    "m2_coarse_diagnostics.png",
                    "m2_coarse_diagnostics.pdf",
                },
            )
            self.assertTrue(
                all(path.is_file() and path.stat().st_size > 0 for path in first_outputs)
            )
            with first_outputs[0].open(newline="", encoding="ascii") as stream:
                first_rows = list(csv.DictReader(stream))
            with second_outputs[0].open(newline="", encoding="ascii") as stream:
                second_rows = list(csv.DictReader(stream))
            self.assertEqual(first_rows, second_rows)
            self.assertEqual(len(first_rows), 27)
            mixed = next(
                row for row in first_rows
                if row["cell_id"] == "coarse-f16-h4-u50"
            )
            self.assertEqual(mixed["capacity_profile"], "mixed")
            self.assertEqual(mixed["recoverable_completed_rounds"], "1")
            self.assertEqual(mixed["persistent_completed_rounds"], "1")
            self.assertEqual(mixed["recoverable_fraction"], "0.5")
            self.assertEqual(mixed["persistent_fraction"], "0.5")
            self.assertFalse(list(root.rglob("*.tmp")))
            self.assertTrue(
                all(path.is_file() and path.stat().st_size > 0 for path in second_outputs)
            )

    def test_requires_exact_preregistered_cell_binding_without_duplicates(self):
        mutations = {
            "missing summary": lambda summaries, rounds: summaries.pop(),
            "duplicate summary": lambda summaries, rounds: summaries.append(dict(summaries[0])),
            "missing rounds": lambda summaries, rounds: rounds.__setitem__(
                slice(None), [row for row in rounds if row["cell_id"] != summaries[0]["cell_id"]]
            ),
            "extra cell": lambda summaries, rounds: summaries.append({
                **summaries[0], "cell_id": "coarse-f24-h2-u25", "foreground_flows": 24,
            }),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                summaries, rounds = _fixture_rows()
                mutate(summaries, rounds)
                _write(root / "summary.csv", SUMMARY_FIELDS, summaries)
                _write(root / "rounds.csv", ROUND_FIELDS, rounds)
                with self.assertRaisesRegex(ValueError, "27 preregistered|duplicate"):
                    make_figs.render_calibration(root, root / "figs")
                self.assertFalse((root / "calibration_diagnostics.csv").exists())
                self.assertFalse((root / "figs").exists())

    def test_selftest_leaves_no_generated_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = root / "cache"
            with (
                mock.patch.object(make_figs, "HERE", root),
                mock.patch.object(make_figs, "_CACHE_DIR", cache),
            ):
                make_figs.selftest()
            self.assertFalse(cache.exists())
            self.assertEqual(list((root / "data").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
