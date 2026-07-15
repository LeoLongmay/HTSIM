import csv
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from htsim.sim.datacenter.add_motivation.expM2_redistribution_progress import make_figs


SELECTION_FIELDS = (
    "cell_id", "scenario", "foreground_flows", "hot_path_groups",
    "background_utilization", "seed",
)
SUMMARY_FIELDS = SELECTION_FIELDS + (
    "round_count", "completed_rounds", "valid_completed_rounds", "completion_rate",
    "median_delta_S", "literal_no_progress_rate", "low_floor_fraction",
    "L_foreground_gbps", "C_healthy_gbps", "C_effective_residual_gbps",
)


def _write(path: Path, fields, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="ascii") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _rows():
    selections = []
    summaries = []
    literals = {101: 0.500001, 102: 0.5, 103: 0.51}
    low_floors = {101: 0.8, 102: 0.8, 103: 0.799999}
    for seed in (101, 102, 103):
        common = {
            "cell_id": "coarse-f16-h6-u25", "scenario": "persistent",
            "foreground_flows": 16, "hot_path_groups": 6,
            "background_utilization": 0.25, "seed": seed,
        }
        selections.append(common)
        summaries.append({
            **common, "round_count": 10, "completed_rounds": 9,
            "valid_completed_rounds": 8, "completion_rate": 0.9,
            "median_delta_S": (seed - 102) / 1000,
            "literal_no_progress_rate": literals[seed],
            "low_floor_fraction": low_floors[seed],
            "L_foreground_gbps": 1300, "C_healthy_gbps": 1000,
            "C_effective_residual_gbps": 1450,
        })
    return summaries, selections


def _fixture(root: Path):
    summaries, selections = _rows()
    data = root / "confirmation"
    selection = root / "confirmation_selection.csv"
    _write(data / "summary.csv", SUMMARY_FIELDS, summaries)
    _write(selection, SELECTION_FIELDS, selections)
    return data, selection


class ConfirmationPlotTests(unittest.TestCase):
    def tearDown(self):
        shutil.rmtree(make_figs._CACHE_DIR, ignore_errors=True)

    def test_render_writes_real_nonempty_outputs_and_uses_strict_thresholds(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data, selection = _fixture(root)
            with mock.patch.object(make_figs, "_read", wraps=make_figs._read) as reader:
                outputs = make_figs.render_confirmation(
                    data, selection, root / "figs",
                )

            self.assertEqual(
                [call.args[0].name for call in reader.call_args_list],
                ["summary.csv", "confirmation_selection.csv"],
            )
            self.assertEqual(
                {path.name for path in outputs},
                {
                    "confirmation_diagnostics.csv",
                    "m2_confirmation_diagnostics.png",
                    "m2_confirmation_diagnostics.pdf",
                },
            )
            self.assertTrue(all(path.stat().st_size > 0 for path in outputs))
            with outputs[0].open(newline="", encoding="ascii") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual([row["seed"] for row in rows], ["101", "102", "103"])
            self.assertEqual([row["outcome_pass"] for row in rows], ["1", "0", "0"])
            self.assertEqual([row["capacity_pass"] for row in rows], ["1", "1", "1"])
            self.assertFalse(list(root.rglob("*.tmp")))

    def test_requires_exact_seed_cell_and_persistent_selection_binding(self):
        mutations = {
            "missing seed": lambda summaries, selections: summaries.pop(),
            "duplicate seed": lambda summaries, selections: summaries.__setitem__(
                2, {**summaries[2], "seed": 102}
            ),
            "summary cell mismatch": lambda summaries, selections: summaries[2].__setitem__(
                "cell_id", "coarse-f16-h4-u25"
            ),
            "selection cell mismatch": lambda summaries, selections: selections[2].__setitem__(
                "hot_path_groups", 4
            ),
            "wrong scenario": lambda summaries, selections: [
                row.__setitem__("scenario", "recoverable") for row in selections
            ],
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                summaries, selections = _rows()
                mutate(summaries, selections)
                data = root / "confirmation"
                selection = root / "confirmation_selection.csv"
                _write(data / "summary.csv", SUMMARY_FIELDS, summaries)
                _write(selection, SELECTION_FIELDS, selections)
                with self.assertRaisesRegex(
                    ValueError, "101/102/103|duplicate|current selection|identical cell|persistent",
                ):
                    make_figs.render_confirmation(data, selection, root / "figs")
                self.assertFalse((data / "confirmation_diagnostics.csv").exists())
                self.assertFalse((root / "figs").exists())
                self.assertFalse(list(root.rglob("*.tmp")))

    def test_selftest_cleans_confirmation_outputs_and_cache(self):
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
