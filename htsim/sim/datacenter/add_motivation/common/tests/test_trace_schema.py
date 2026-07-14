import csv
import tempfile
import unittest
from pathlib import Path

from htsim.sim.datacenter.add_motivation.common.trace_schema import (
    TraceValidationError,
    load_trace,
)


HEADERS = {
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
        "related_ack_event_seq",
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
}


def valid_rows():
    return {
        "ack": [
            {
                "schema_version": "2", "run_id": "fixture", "seed": "13",
                "scenario": "unit", "event_seq": "0", "time_ps": "100",
                "flow_id": "7", "epoch_id": "3", "acked_psn": "10", "entropy": "1",
                "physical_path_id": "99", "raw_rtt_ps": "20000000",
                "base_rtt_ps": "17000000", "qdelay_ps": "3000000", "ecn": "0",
                "genuine_sample": "1", "retransmitted": "0",
                "forward_path_backlog_ps": "2500000", "selection_source": "recycle",
                "source_token_id": "41", "newly_acked_bytes": "4150",
                "new_data_bytes_sent_total": "8300", "cwnd_bytes": "16600",
            },
        ],
        "token": [
            {
                "schema_version": "2", "run_id": "fixture", "event_seq": "1",
                "time_ps": "110", "flow_id": "7", "operation": "enqueue_good_ack",
                "reason": "good_ack", "token_id": "42", "entropy": "1",
                "queue_depth_before": "0", "queue_depth_after": "1",
                "related_ack_event_seq": "0",
            },
        ],
        "epoch": [
            {
                "schema_version": "2", "run_id": "fixture", "event_seq": "2",
                "flow_id": "7", "epoch_id": "3", "start_ps": "0", "end_ps": "120",
                "sample_count": "1", "raw_floor_ps": "3000000", "raw_spread_ps": "0",
                "smooth_floor_ps": "3500000", "smooth_spread_ps": "1000000",
                "observed_region": "low_floor_low_spread", "actual_region": "normal",
                "engaged": "0", "entropy_coverage": "1", "physical_path_coverage": "1",
                "new_data_bytes_sent_total": "8300", "acked_bytes_total": "4150",
                "cwnd_bytes": "16600",
            },
        ],
        "background": [],
        "pathmap": [
            {
                "schema_version": "2", "run_id": "fixture", "flow_id": "7",
                "entropy": "1", "physical_path_id": "99", "resolution_status": "resolved",
                "queue_fingerprint": "1:2:3", "bottleneck_rate_gbps": "50.5",
                "contains_reduced_link": "1", "ordered_queue_ids": "1:2:3",
            },
        ],
        "linkmap": [
            {
                "schema_version": "2", "run_id": "fixture", "queue_id": "2",
                "queue_name": "cut-2", "rate_gbps": "50.5", "reduced_speed": "1",
            },
        ],
    }


def write_trace(directory, rows=None, headers=None):
    prefix = Path(directory) / "fixture"
    rows = valid_rows() if rows is None else rows
    headers = HEADERS if headers is None else headers
    for kind, fieldnames in headers.items():
        with Path(f"{prefix}.{kind}.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows[kind])
    return prefix


class TraceSchemaTests(unittest.TestCase):
    def test_loads_all_six_v2_files_with_explicit_types(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = load_trace(write_trace(directory))

        self.assertEqual(bundle.run_id, "fixture")
        self.assertEqual([event.event_seq for event in bundle.events], [0, 1, 2])
        self.assertEqual([event.kind for event in bundle.events], ["ack", "token", "epoch"])
        self.assertIsInstance(bundle.ack[0]["event_seq"], int)
        self.assertIsInstance(bundle.ack[0]["ecn"], bool)
        self.assertIsInstance(bundle.pathmap[0]["bottleneck_rate_gbps"], float)
        self.assertIsInstance(bundle.linkmap[0]["reduced_speed"], bool)
        self.assertNotIn("event_seq", bundle.pathmap[0])

    def test_rejects_wrong_schema_version_with_filename_and_key(self):
        rows = valid_rows()
        rows["ack"][0]["schema_version"] = "1"
        with tempfile.TemporaryDirectory() as directory:
            prefix = write_trace(directory, rows)
            with self.assertRaisesRegex(TraceValidationError, r"fixture\.ack\.csv.*schema_version"):
                load_trace(prefix)

    def test_rejects_duplicate_event_sequence_across_files(self):
        rows = valid_rows()
        rows["token"][0]["event_seq"] = "0"
        with tempfile.TemporaryDirectory() as directory:
            prefix = write_trace(directory, rows)
            with self.assertRaisesRegex(TraceValidationError, r"fixture\.token\.csv.*event_seq"):
                load_trace(prefix)

    def test_rejects_non_monotonic_event_sequence_within_file(self):
        rows = valid_rows()
        duplicate = dict(rows["ack"][0])
        duplicate["event_seq"] = "3"
        rows["ack"] = [duplicate, rows["ack"][0]]
        with tempfile.TemporaryDirectory() as directory:
            prefix = write_trace(directory, rows)
            with self.assertRaisesRegex(TraceValidationError, r"fixture\.ack\.csv.*event_seq"):
                load_trace(prefix)

    def test_rejects_mismatched_run_id_with_filename_and_key(self):
        rows = valid_rows()
        rows["linkmap"][0]["run_id"] = "other"
        with tempfile.TemporaryDirectory() as directory:
            prefix = write_trace(directory, rows)
            with self.assertRaisesRegex(TraceValidationError, r"fixture\.linkmap\.csv.*run_id"):
                load_trace(prefix)

    def test_rejects_missing_extra_or_reordered_headers(self):
        cases = {
            "missing": HEADERS["ack"][:-1],
            "extra": HEADERS["ack"] + ("unexpected",),
            "reordered": (HEADERS["ack"][1], HEADERS["ack"][0], *HEADERS["ack"][2:]),
        }
        for name, ack_header in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                headers = dict(HEADERS)
                headers["ack"] = ack_header
                rows = valid_rows()
                rows["ack"] = []
                prefix = write_trace(directory, rows, headers)
                with self.assertRaisesRegex(TraceValidationError, r"fixture\.ack\.csv.*header"):
                    load_trace(prefix)

    def test_rejects_invalid_typed_value_with_filename_and_key(self):
        rows = valid_rows()
        rows["background"] = [{
            "schema_version": "2", "run_id": "fixture", "event_seq": "3",
            "time_ps": "130", "background_id": "5", "operation": "delivery",
            "src": "0", "dst": "16", "path_index": "2",
            "configured_rate_gbps": "not-a-rate", "delivered_bytes": "4150",
            "queue_fingerprint": "4:5:6",
        }]
        with tempfile.TemporaryDirectory() as directory:
            prefix = write_trace(directory, rows)
            with self.assertRaisesRegex(
                TraceValidationError,
                r"fixture\.background\.csv.*configured_rate_gbps",
            ):
                load_trace(prefix)

    def test_rejects_negative_value_for_cpp_unsigned_column(self):
        rows = valid_rows()
        rows["ack"][0]["event_seq"] = "-1"
        with tempfile.TemporaryDirectory() as directory:
            prefix = write_trace(directory, rows)
            with self.assertRaisesRegex(TraceValidationError, r"fixture\.ack\.csv.*event_seq"):
                load_trace(prefix)

    def test_rejects_enqueue_reference_to_absent_ack(self):
        rows = valid_rows()
        rows["token"][0]["related_ack_event_seq"] = "99"
        with tempfile.TemporaryDirectory() as directory:
            prefix = write_trace(directory, rows)
            with self.assertRaisesRegex(
                TraceValidationError,
                r"fixture\.token\.csv.*related_ack_event_seq",
            ):
                load_trace(prefix)

    def test_rejects_enqueue_reference_to_later_ack(self):
        rows = valid_rows()
        rows["ack"][0]["event_seq"] = "2"
        rows["token"][0]["related_ack_event_seq"] = "2"
        rows["epoch"][0]["event_seq"] = "3"
        with tempfile.TemporaryDirectory() as directory:
            prefix = write_trace(directory, rows)
            with self.assertRaisesRegex(
                TraceValidationError,
                r"fixture\.token\.csv.*related_ack_event_seq",
            ):
                load_trace(prefix)

    def test_rejects_enqueue_reference_to_ack_from_another_flow(self):
        rows = valid_rows()
        rows["token"][0]["flow_id"] = "8"
        with tempfile.TemporaryDirectory() as directory:
            prefix = write_trace(directory, rows)
            with self.assertRaisesRegex(
                TraceValidationError,
                r"fixture\.token\.csv.*related_ack_event_seq",
            ):
                load_trace(prefix)

    def test_rejects_epoch_close_before_last_ack_in_same_epoch(self):
        rows = valid_rows()
        later_ack = dict(rows["ack"][0])
        later_ack.update({"event_seq": "3", "time_ps": "115", "acked_psn": "11"})
        rows["ack"].append(later_ack)
        with tempfile.TemporaryDirectory() as directory:
            prefix = write_trace(directory, rows)
            with self.assertRaisesRegex(TraceValidationError, r"fixture\.epoch\.csv.*event_seq"):
                load_trace(prefix)

    def test_accepts_exact_cpp_integer_bounds(self):
        cases = {
            "uint32": ("entropy", str(2**32 - 1)),
            "uint64": ("source_token_id", str(2**64 - 1)),
            "int64_min": ("qdelay_ps", str(-(2**63))),
            "int64_max": ("qdelay_ps", str(2**63 - 1)),
        }
        for name, (key, value) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                rows = valid_rows()
                rows["ack"][0][key] = value
                bundle = load_trace(write_trace(directory, rows))
                self.assertEqual(bundle.ack[0][key], int(value))

    def test_rejects_cpp_integer_overflow_with_filename_and_key(self):
        cases = {
            "uint32": ("entropy", str(2**32)),
            "uint64": ("source_token_id", str(2**64)),
            "int64_low": ("qdelay_ps", str(-(2**63) - 1)),
            "int64_high": ("qdelay_ps", str(2**63)),
        }
        for name, (key, value) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                rows = valid_rows()
                rows["ack"][0][key] = value
                prefix = write_trace(directory, rows)
                with self.assertRaisesRegex(
                    TraceValidationError,
                    rf"fixture\.ack\.csv.*{key}",
                ):
                    load_trace(prefix)


if __name__ == "__main__":
    unittest.main()
