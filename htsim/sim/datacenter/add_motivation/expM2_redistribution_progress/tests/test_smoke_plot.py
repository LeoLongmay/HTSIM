import csv
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from htsim.sim.datacenter.add_motivation.expM2_redistribution_progress import make_figs


EPOCH_FIELDS = (
    "scenario", "seed", "flow_id", "round_index", "event_seq", "aligned_time_ps",
    "F_ps", "S_ps", "S_ref_ps", "actual_cwnd_bytes", "actual_state", "hold",
    "round_complete_marker",
)
ROUND_FIELDS = (
    "scenario", "seed", "flow_id", "round_index", "complete", "valid_round", "delta_S",
)
SUMMARY_FIELDS = ("scenario", "seed", "completion_rate", "censor_rate")


def _write(path, fields, rows):
    with path.open("w", newline="", encoding="ascii") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _write_aggregate(directory: Path, *, scenario="recoverable", valid=True):
    epochs = []
    for event_seq, (floor, spread, state) in enumerate((
        (7_000_000, 24_000_000, "hold"),
        (8_000_000, 20_000_000, "hold"),
        (9_000_000, 17_000_000, "increase"),
    )):
        epochs.append({
            "scenario": scenario, "seed": 101, "flow_id": 3, "round_index": 0,
            "event_seq": event_seq, "aligned_time_ps": event_seq * 4_000_000,
            "F_ps": floor, "S_ps": spread, "S_ref_ps": 24_000_000,
            "actual_cwnd_bytes": 64_000 + event_seq * 4_000,
            "actual_state": state, "hold": int(state == "hold"),
            "round_complete_marker": int(event_seq == 2),
        })
    rounds = [
        {
            "scenario": scenario, "seed": 101, "flow_id": 3, "round_index": 0,
            "complete": 1, "valid_round": int(valid), "delta_S": 0.29,
        },
        {
            "scenario": scenario, "seed": 101, "flow_id": 1, "round_index": 1,
            "complete": 1, "valid_round": 0, "delta_S": 99,
        },
    ]
    summaries = [{
        "scenario": scenario, "seed": 101, "completion_rate": 0.5, "censor_rate": 0.5,
    }]
    _write(directory / "epochs.csv", EPOCH_FIELDS, epochs)
    _write(directory / "rounds.csv", ROUND_FIELDS, rounds)
    _write(directory / "summary.csv", SUMMARY_FIELDS, summaries)


def _round(*, flow, index, delta, seed=13):
    return {
        "scenario": "recoverable", "seed": str(seed), "flow_id": str(flow),
        "round_index": str(index), "complete": "1", "valid_round": "1",
        "delta_S": str(delta),
    }


def _epochs(*, flow, index, times, seed=13):
    return [
        {
            "scenario": "recoverable", "seed": str(seed), "flow_id": str(flow),
            "round_index": str(index), "event_seq": str(event_seq),
            "aligned_time_ps": str(aligned_time_ps),
        }
        for event_seq, aligned_time_ps in enumerate(times)
    ]


class SmokePlotTests(unittest.TestCase):
    def tearDown(self):
        shutil.rmtree(make_figs._CACHE_DIR, ignore_errors=True)

    def test_single_real_scenario_renders_from_only_three_aggregate_csvs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_dir = root / "aggregate"
            output_dir = root / "figs" / "smoke"
            data_dir.mkdir()
            _write_aggregate(data_dir)
            with mock.patch.object(make_figs, "_read", wraps=make_figs._read) as reader:
                outputs = make_figs.render_smoke(data_dir, output_dir)

            self.assertEqual(
                {call.args[0].name for call in reader.call_args_list},
                {"epochs.csv", "rounds.csv", "summary.csv"},
            )
            self.assertEqual(
                {path.name for path in outputs},
                {
                    "m2_redistribution_progress_smoke.png",
                    "m2_redistribution_progress_smoke.pdf",
                },
            )
            self.assertTrue(all(path.is_file() and path.stat().st_size > 0 for path in outputs))
            self.assertEqual(
                {path.name for path in data_dir.iterdir()},
                {"epochs.csv", "rounds.csv", "summary.csv"},
            )
            for output in outputs:
                output.unlink()
            self.assertTrue(all(not path.exists() for path in outputs))

        self.assertFalse(root.exists())

    def test_invalid_scenario_or_no_valid_completed_round_fails(self):
        for scenario, valid, expected in (
            ("recoverable", False, "no valid completed"),
            ("invalid", True, "invalid inferred scenario"),
        ):
            with self.subTest(scenario=scenario, valid=valid):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    data_dir = root / "aggregate"
                    data_dir.mkdir()
                    _write_aggregate(data_dir, scenario=scenario, valid=valid)
                    with self.assertRaisesRegex(ValueError, expected):
                        make_figs.render_smoke(data_dir, root / "figs" / "smoke")
                    self.assertFalse((root / "figs" / "smoke").exists())

    def test_representative_uses_median_seed_without_delta_preference(self):
        rounds = [
            _round(flow=9, index=0, delta=999, seed=12),
            _round(flow=1, index=0, delta=999, seed=13),
            _round(flow=2, index=0, delta=-999, seed=13),
            _round(flow=9, index=0, delta=999, seed=14),
        ]
        epochs = (
            _epochs(flow=9, index=0, times=(0, 10), seed=12)
            + _epochs(flow=1, index=0, times=(0, 10, 20), seed=13)
            + _epochs(flow=2, index=0, times=(0, 10, 20), seed=13)
            + _epochs(flow=9, index=0, times=(0, 10), seed=14)
        )

        first, series = make_figs._representative(epochs, rounds, "recoverable")
        rounds[1]["delta_S"], rounds[2]["delta_S"] = (
            rounds[2]["delta_S"], rounds[1]["delta_S"]
        )
        second, _ = make_figs._representative(epochs, rounds, "recoverable")

        self.assertEqual(int(first["seed"]), 13)
        self.assertEqual(int(first["flow_id"]), 1)
        self.assertEqual(int(second["flow_id"]), 1)
        self.assertEqual(len(series), 3)

    def test_representative_is_independent_of_input_order(self):
        rounds = [
            _round(flow=3, index=1, delta=0.1),
            _round(flow=2, index=4, delta=0.2),
        ]
        epochs = (
            _epochs(flow=3, index=1, times=(0, 10, 30))
            + _epochs(flow=2, index=4, times=(0, 10, 30))
        )

        forward, forward_series = make_figs._representative(
            epochs, rounds, "recoverable"
        )
        reverse, reverse_series = make_figs._representative(
            list(reversed(epochs)), list(reversed(rounds)), "recoverable"
        )

        self.assertEqual(
            (int(forward["flow_id"]), int(forward["round_index"])),
            (int(reverse["flow_id"]), int(reverse["round_index"])),
        )
        self.assertEqual(int(forward["flow_id"]), 2)
        self.assertEqual(
            [int(row["event_seq"]) for row in forward_series],
            [int(row["event_seq"]) for row in reverse_series],
        )

    def test_representative_prefers_epoch_count_then_time_coverage(self):
        rounds = [
            _round(flow=1, index=0, delta=100),
            _round(flow=2, index=0, delta=-100),
            _round(flow=3, index=0, delta=0),
        ]
        epochs = (
            _epochs(flow=1, index=0, times=(0, 100))
            + _epochs(flow=2, index=0, times=(0, 10, 20))
            + _epochs(flow=3, index=0, times=(0, 10, 40))
        )

        chosen, series = make_figs._representative(epochs, rounds, "recoverable")

        self.assertEqual(int(chosen["flow_id"]), 3)
        self.assertEqual([int(row["aligned_time_ps"]) for row in series], [0, 10, 40])

    def test_representative_rejects_all_single_point_candidates(self):
        rounds = [
            _round(flow=1, index=0, delta=0.1),
            _round(flow=2, index=0, delta=0.2),
        ]
        epochs = (
            _epochs(flow=1, index=0, times=(0,))
            + _epochs(flow=2, index=0, times=(100,))
        )

        with self.assertRaisesRegex(ValueError, "fewer than 2 aggregate epoch points"):
            make_figs._representative(epochs, rounds, "recoverable")


if __name__ == "__main__":
    unittest.main()
