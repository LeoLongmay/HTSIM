import csv
import tempfile
import unittest
from pathlib import Path

from htsim.sim.datacenter.add_motivation.common.residual_join import (
    attach_same_epoch_residuals,
)
from htsim.sim.datacenter.add_motivation.common.trace_schema import (
    TraceValidationError,
    load_trace,
)
from test_trace_schema import HEADERS, valid_rows


def write_rows(directory, rows):
    prefix = Path(directory) / "residual"
    for kind, fieldnames in HEADERS.items():
        with Path(f"{prefix}.{kind}.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows[kind])
    return prefix


def residual_rows():
    rows = valid_rows()
    first = rows["ack"][0]
    second = dict(first)
    second.update({
        "event_seq": "1", "time_ps": "105", "acked_psn": "11",
        "qdelay_ps": "17000000", "raw_rtt_ps": "34000000",
        "newly_acked_bytes": "4150", "new_data_bytes_sent_total": "12450",
    })
    fallback = dict(first)
    fallback.update({
        "event_seq": "2", "time_ps": "108", "acked_psn": "12",
        "qdelay_ps": "50000000", "genuine_sample": "0",
    })
    rows["ack"] = [first, second, fallback]
    rows["token"] = []
    rows["epoch"][0].update({
        "event_seq": "3", "sample_count": "2", "raw_floor_ps": "3000000",
        "raw_spread_ps": "14000000",
    })
    return rows


class ResidualJoinTests(unittest.TestCase):
    def test_attaches_exact_same_epoch_raw_residuals_to_genuine_acks_only(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = load_trace(write_rows(directory, residual_rows()))
            joined = attach_same_epoch_residuals(bundle)

        self.assertEqual([row.residual_ps for row in joined], [0, 14_000_000])
        self.assertEqual([row.floor_ps for row in joined], [3_000_000, 3_000_000])
        self.assertEqual([row.spread_ps for row in joined], [14_000_000, 14_000_000])
        self.assertEqual([row.high_residual for row in joined], [False, True])
        self.assertEqual([row.row["event_seq"] for row in joined], [0, 1])

    def test_rejects_ack_without_same_flow_epoch_with_filename_and_key(self):
        rows = residual_rows()
        rows["ack"][0]["epoch_id"] = "999"
        with tempfile.TemporaryDirectory() as directory:
            bundle = load_trace(write_rows(directory, rows))
            with self.assertRaisesRegex(TraceValidationError, r"residual\.ack\.csv.*epoch_id"):
                attach_same_epoch_residuals(bundle)

    def test_rejects_recorded_raw_extrema_that_disagree_with_genuine_acks(self):
        rows = residual_rows()
        rows["epoch"][0]["raw_spread_ps"] = "13999999"
        with tempfile.TemporaryDirectory() as directory:
            bundle = load_trace(write_rows(directory, rows))
            with self.assertRaisesRegex(
                TraceValidationError,
                r"residual\.epoch\.csv.*raw_spread_ps",
            ):
                attach_same_epoch_residuals(bundle)

    def test_rejects_duplicate_epoch_identity(self):
        rows = residual_rows()
        duplicate = dict(rows["epoch"][0])
        duplicate["event_seq"] = "4"
        rows["epoch"].append(duplicate)
        with tempfile.TemporaryDirectory() as directory:
            bundle = load_trace(write_rows(directory, rows))
            with self.assertRaisesRegex(TraceValidationError, r"residual\.epoch\.csv.*epoch_id"):
                attach_same_epoch_residuals(bundle)

    def test_validates_empty_closed_epoch_as_zero_extrema(self):
        rows = residual_rows()
        rows["ack"] = []
        rows["epoch"][0].update({
            "event_seq": "0", "sample_count": "0", "raw_floor_ps": "0",
            "raw_spread_ps": "0",
        })
        with tempfile.TemporaryDirectory() as directory:
            bundle = load_trace(write_rows(directory, rows))
            self.assertEqual(attach_same_epoch_residuals(bundle), ())


if __name__ == "__main__":
    unittest.main()
