import csv
import tempfile
import unittest
from pathlib import Path

from htsim.sim.datacenter.add_motivation.common.trace_schema import (
    TraceValidationError,
    load_trace,
    load_trace_compact,
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
    "outcome": (
        "schema_version", "run_id", "seed", "scenario", "event_seq", "time_ps",
        "flow_id", "round_id", "window_ps", "pre_classified_bytes",
        "pre_harmful_bytes", "pre_exposure", "post1_classified_bytes",
        "post1_harmful_bytes", "post1_exposure", "post2_classified_bytes",
        "post2_harmful_bytes", "post2_exposure",
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
                "related_ack_event_seq": "0", "cache_slot": "3",
                "cache_generation": "5", "admission_written": "1",
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
        "coordination": [
            {
                "schema_version": "2", "run_id": "fixture", "event_seq": "100",
                "time_ps": "1000", "flow_id": "7", "epoch_id": "3", "round_id": "1",
                "cache_slot": "2", "cache_generation": "9", "floor_ps": "3000000",
                "spread_ps": "1000000", "spread_ref_ps": "1200000", "residual_ps": "500000",
                "action": "retain", "reason": "residual_below_threshold",
                "refresh_complete": "1", "progress": "0", "handoff": "0",
                "cwnd_bytes": "16600", "control_state": "hold",
            },
        ],
        "outcome": [
            {
                "schema_version": "2", "run_id": "fixture", "seed": "13",
                "scenario": "unit", "event_seq": "101", "time_ps": "1100",
                "flow_id": "7", "round_id": "1", "window_ps": "40",
                "pre_classified_bytes": "100", "pre_harmful_bytes": "0",
                "pre_exposure": "0.0", "post1_classified_bytes": "100",
                "post1_harmful_bytes": "30", "post1_exposure": "0.3",
                "post2_classified_bytes": "100", "post2_harmful_bytes": "50",
                "post2_exposure": "0.5",
            },
        ],
    }


def write_trace(directory, rows=None, headers=None, *, include_outcome=False):
    prefix = Path(directory) / "fixture"
    rows = valid_rows() if rows is None else rows
    headers = HEADERS if headers is None else headers
    for kind, fieldnames in headers.items():
        if kind == "outcome" and not include_outcome:
            continue
        with Path(f"{prefix}.{kind}.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows[kind])
    return prefix


class TraceSchemaTests(unittest.TestCase):
    def test_compact_loader_preserves_all_values_events_and_source_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix = write_trace(directory, include_outcome=True)
            with Path(f"{prefix}.ack.csv").open("a", encoding="utf-8") as stream:
                stream.write("\n")
            default = load_trace(prefix)
            compact = load_trace_compact(prefix)

            self.assertEqual(compact.run_id, default.run_id)
            for kind, fields in HEADERS.items():
                default_rows = getattr(default, kind)
                compact_rows = getattr(compact, kind)
                self.assertEqual(len(compact_rows), len(default_rows))
                for default_row, compact_row in zip(default_rows, compact_rows):
                    self.assertEqual(
                        [compact_row[field] for field in fields],
                        [default_row[field] for field in fields],
                    )
                    self.assertEqual(compact_row.source_path, default_row.source_path)
            self.assertEqual(
                [(event.event_seq, event.kind) for event in compact.events],
                [(event.event_seq, event.kind) for event in default.events],
            )

    def test_compact_rows_are_non_dict_fixed_slot_read_only_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = load_trace_compact(write_trace(directory))

        row = bundle.ack[0]
        self.assertNotIsInstance(row, dict)
        self.assertEqual(type(row).__slots__, ("_values", "_schema"))
        self.assertFalse(hasattr(row, "__dict__"))
        self.assertEqual(row["event_seq"], 0)
        self.assertEqual(row.get("event_seq"), 0)
        self.assertIsNone(row.get("absent"))
        self.assertEqual(row.get("absent", 17), 17)
        with self.assertRaises(KeyError):
            _ = row["absent"]

    def test_compact_and_default_report_identical_validation_errors(self):
        cases = []

        rows = valid_rows()
        rows["ack"][0]["schema_version"] = "1"
        cases.append(("schema", rows, HEADERS))

        rows = valid_rows()
        rows["ack"] = []
        headers = dict(HEADERS)
        headers["ack"] = HEADERS["ack"][:-1]
        cases.append(("header", rows, headers))

        rows = valid_rows()
        rows["ack"][0]["qdelay_ps"] = "invalid"
        cases.append(("typed_value", rows, HEADERS))

        rows = valid_rows()
        earlier = dict(rows["ack"][0])
        earlier["event_seq"] = "3"
        rows["ack"] = [earlier, rows["ack"][0]]
        cases.append(("within_file_sequence", rows, HEADERS))

        rows = valid_rows()
        rows["token"][0]["event_seq"] = "0"
        cases.append(("duplicate_sequence", rows, HEADERS))

        rows = valid_rows()
        rows["token"][0]["time_ps"] = "99"
        cases.append(("global_time", rows, HEADERS))

        rows = valid_rows()
        rows["linkmap"][0]["run_id"] = "other"
        cases.append(("run_id", rows, HEADERS))

        rows = valid_rows()
        rows["token"][0]["related_ack_event_seq"] = "99"
        cases.append(("ack_token_reference", rows, HEADERS))

        rows = valid_rows()
        rows["token"][0]["entropy"] = "2"
        cases.append(("ack_token_entropy", rows, HEADERS))

        rows = valid_rows()
        rows["ack"][0]["ecn"] = "1"
        cases.append(("ack_token_ecn", rows, HEADERS))

        rows = valid_rows()
        later_ack = dict(rows["ack"][0])
        later_ack.update({"event_seq": "3", "time_ps": "120", "acked_psn": "11"})
        rows["ack"].append(later_ack)
        cases.append(("epoch_close", rows, HEADERS))

        for name, rows, headers in cases:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as directory:
                prefix = write_trace(directory, rows, headers)
                messages = []
                for loader in (load_trace, load_trace_compact):
                    with self.assertRaises(TraceValidationError) as raised:
                        loader(prefix)
                    messages.append(str(raised.exception))
                self.assertEqual(messages[1], messages[0])

    def test_loads_optional_outcome_file_with_explicit_types(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = load_trace(write_trace(directory, include_outcome=True))

        self.assertEqual(bundle.run_id, "fixture")
        self.assertEqual([event.event_seq for event in bundle.events], [0, 1, 2, 100, 101])
        self.assertEqual(
            [event.kind for event in bundle.events],
            ["ack", "token", "epoch", "coordination", "outcome"],
        )
        self.assertIsInstance(bundle.ack[0]["event_seq"], int)
        self.assertIsInstance(bundle.ack[0]["ecn"], bool)
        self.assertIsInstance(bundle.pathmap[0]["bottleneck_rate_gbps"], float)
        self.assertIsInstance(bundle.linkmap[0]["reduced_speed"], bool)
        self.assertIsInstance(bundle.coordination[0]["refresh_complete"], bool)
        self.assertIsInstance(bundle.outcome[0]["pre_exposure"], float)
        self.assertEqual(bundle.token[0]["cache_slot"], 3)
        self.assertEqual(bundle.token[0]["cache_generation"], 5)
        self.assertTrue(bundle.token[0]["admission_written"])
        self.assertNotIn("event_seq", bundle.pathmap[0])

    def test_outcome_file_is_optional_for_existing_trace_bundles(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix = write_trace(directory)
            for loader in (load_trace, load_trace_compact):
                with self.subTest(loader=loader.__name__):
                    bundle = loader(prefix)
                    self.assertEqual(bundle.outcome, ())

    def test_rejects_nonfinite_outcome_exposure(self):
        rows = valid_rows()
        rows["outcome"][0]["post1_exposure"] = "nan"
        with tempfile.TemporaryDirectory() as directory:
            prefix = write_trace(directory, rows, include_outcome=True)
            with self.assertRaisesRegex(TraceValidationError, r"outcome\.csv.*post1_exposure"):
                load_trace(prefix)

    def test_rejects_written_admission_with_sentinel_slot(self):
        rows = valid_rows()
        rows["token"][0]["cache_slot"] = str(2**16 - 1)
        with tempfile.TemporaryDirectory() as directory:
            prefix = write_trace(directory, rows)
            with self.assertRaisesRegex(TraceValidationError, r"fixture\.token\.csv.*cache_slot"):
                load_trace(prefix)

    def test_rejects_written_admission_with_sentinel_generation(self):
        rows = valid_rows()
        rows["token"][0]["cache_generation"] = "0"
        with tempfile.TemporaryDirectory() as directory:
            prefix = write_trace(directory, rows)
            with self.assertRaisesRegex(
                TraceValidationError,
                r"fixture\.token\.csv.*cache_generation",
            ):
                load_trace(prefix)

    def test_rejects_written_admission_for_dequeue(self):
        rows = valid_rows()
        rows["token"][0].update({
            "operation": "dequeue_recycle", "reason": "recycle", "cache_slot": "3",
            "cache_generation": "5", "admission_written": "1",
        })
        with tempfile.TemporaryDirectory() as directory:
            prefix = write_trace(directory, rows)
            with self.assertRaisesRegex(
                TraceValidationError,
                r"fixture\.token\.csv.*admission_written",
            ):
                load_trace(prefix)

    def test_accepts_legacy_admission_with_sentinel_provenance(self):
        rows = valid_rows()
        rows["token"][0].update({
            "cache_slot": str(2**16 - 1), "cache_generation": "0",
            "admission_written": "0",
        })
        with tempfile.TemporaryDirectory() as directory:
            prefix = write_trace(directory, rows)
            for loader in (load_trace, load_trace_compact):
                with self.subTest(loader=loader.__name__):
                    token = loader(prefix).token[0]
                    self.assertFalse(token["admission_written"])
                    self.assertEqual(token["cache_slot"], 2**16 - 1)
                    self.assertEqual(token["cache_generation"], 0)

    def test_rejects_missing_coordination_leaf(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix = write_trace(directory)
            Path(f"{prefix}.coordination.csv").unlink()
            with self.assertRaisesRegex(TraceValidationError, r"fixture\.coordination\.csv.*file"):
                load_trace(prefix)

    def test_rejects_non_monotonic_coordination_event_sequence_within_file(self):
        rows = valid_rows()
        later = dict(rows["coordination"][0])
        later["event_seq"] = "101"
        rows["coordination"] = [later, rows["coordination"][0]]
        with tempfile.TemporaryDirectory() as directory:
            prefix = write_trace(directory, rows)
            with self.assertRaisesRegex(
                TraceValidationError,
                r"fixture\.coordination\.csv.*event_seq",
            ):
                load_trace(prefix)

    def test_rejects_invalidation_marked_refresh_complete(self):
        rows = valid_rows()
        rows["coordination"][0].update({"action": "invalidate", "refresh_complete": "1"})
        with tempfile.TemporaryDirectory() as directory:
            prefix = write_trace(directory, rows)
            with self.assertRaisesRegex(
                TraceValidationError,
                r"fixture\.coordination\.csv.*refresh_complete",
            ):
                load_trace(prefix)

    def test_rejects_handoff_without_round_complete_handoff_action(self):
        rows = valid_rows()
        rows["coordination"][0].update({"action": "retain", "handoff": "1"})
        with tempfile.TemporaryDirectory() as directory:
            prefix = write_trace(directory, rows)
            with self.assertRaisesRegex(
                TraceValidationError,
                r"fixture\.coordination\.csv.*action",
            ):
                load_trace(prefix)

    def test_allows_round_complete_handoff_terminal_no_op(self):
        rows = valid_rows()
        rows["coordination"][0].update({
            "action": "round_complete_handoff", "handoff": "0",
            "refresh_complete": "1", "progress": "0", "cwnd_bytes": "1000",
        })
        with tempfile.TemporaryDirectory() as directory:
            prefix = write_trace(directory, rows)
            for loader in (load_trace, load_trace_compact):
                with self.subTest(loader=loader.__name__):
                    bundle = loader(prefix)
                    self.assertFalse(bundle.coordination[0]["handoff"])

    def test_allows_round_complete_clean_only_for_clean_terminal_state(self):
        valid = valid_rows()
        valid["coordination"][0].update({
            "action": "round_complete_clean", "refresh_complete": "1",
            "progress": "0", "handoff": "0",
        })
        with tempfile.TemporaryDirectory() as directory:
            prefix = write_trace(directory, valid)
            for loader in (load_trace, load_trace_compact):
                with self.subTest(loader=loader.__name__):
                    self.assertEqual(
                        loader(prefix).coordination[0]["action"],
                        "round_complete_clean",
                    )

        for field in ("refresh_complete", "progress", "handoff"):
            rows = valid_rows()
            rows["coordination"][0].update({
                "action": "round_complete_clean", "refresh_complete": "1",
                "progress": "0", "handoff": "0",
            })
            rows["coordination"][0][field] = "0" if field == "refresh_complete" else "1"
            with tempfile.TemporaryDirectory() as directory:
                prefix = write_trace(directory, rows)
                for loader in (load_trace, load_trace_compact):
                    with self.subTest(loader=loader.__name__, field=field):
                        with self.assertRaisesRegex(
                            TraceValidationError,
                            r"fixture\.coordination\.csv",
                        ):
                            loader(prefix)

    def test_allows_round_complete_retry_only_after_refresh_without_progress_or_handoff(self):
        valid = valid_rows()
        valid["coordination"][0].update({
            "action": "round_complete_retry", "refresh_complete": "1",
            "progress": "0", "handoff": "0",
        })
        with tempfile.TemporaryDirectory() as directory:
            prefix = write_trace(directory, valid)
            for loader in (load_trace, load_trace_compact):
                with self.subTest(loader=loader.__name__):
                    self.assertEqual(
                        loader(prefix).coordination[0]["action"],
                        "round_complete_retry",
                    )

        for field in ("refresh_complete", "progress", "handoff"):
            rows = valid_rows()
            rows["coordination"][0].update({
                "action": "round_complete_retry", "refresh_complete": "1",
                "progress": "0", "handoff": "0",
            })
            rows["coordination"][0][field] = "0" if field == "refresh_complete" else "1"
            with tempfile.TemporaryDirectory() as directory:
                prefix = write_trace(directory, rows)
                for loader in (load_trace, load_trace_compact):
                    with self.subTest(loader=loader.__name__, field=field):
                        with self.assertRaisesRegex(
                            TraceValidationError,
                            r"fixture\.coordination\.csv",
                        ):
                            loader(prefix)

    def test_rejects_round_complete_handoff_terminal_no_op_without_refresh(self):
        rows = valid_rows()
        rows["coordination"][0].update({
            "action": "round_complete_handoff", "handoff": "0",
            "refresh_complete": "0", "progress": "0",
        })
        with tempfile.TemporaryDirectory() as directory:
            prefix = write_trace(directory, rows)
            with self.assertRaisesRegex(
                TraceValidationError,
                r"fixture\.coordination\.csv.*refresh_complete",
            ):
                load_trace(prefix)

    def test_rejects_round_complete_handoff_terminal_no_op_with_progress(self):
        rows = valid_rows()
        rows["coordination"][0].update({
            "action": "round_complete_handoff", "handoff": "0",
            "refresh_complete": "1", "progress": "1",
        })
        with tempfile.TemporaryDirectory() as directory:
            prefix = write_trace(directory, rows)
            with self.assertRaisesRegex(
                TraceValidationError,
                r"fixture\.coordination\.csv.*progress",
            ):
                load_trace(prefix)

    def test_rejects_round_complete_progress_without_progress(self):
        rows = valid_rows()
        rows["coordination"][0].update({
            "action": "round_complete_progress", "progress": "0",
        })
        with tempfile.TemporaryDirectory() as directory:
            prefix = write_trace(directory, rows)
            with self.assertRaisesRegex(
                TraceValidationError,
                r"fixture\.coordination\.csv.*progress",
            ):
                load_trace(prefix)

    def test_rejects_progress_without_round_complete_progress_action(self):
        rows = valid_rows()
        rows["coordination"][0].update({"action": "retain", "progress": "1"})
        with tempfile.TemporaryDirectory() as directory:
            prefix = write_trace(directory, rows)
            with self.assertRaisesRegex(
                TraceValidationError,
                r"fixture\.coordination\.csv.*action",
            ):
                load_trace(prefix)

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

    def test_rejects_ack_time_decrease_in_global_event_order(self):
        rows = valid_rows()
        rows["token"][0].update({
            "event_seq": "0", "time_ps": "110", "operation": "select_first_window",
            "reason": "first_window", "related_ack_event_seq": str(2**64 - 1),
        })
        rows["ack"][0]["event_seq"] = "1"
        with tempfile.TemporaryDirectory() as directory:
            prefix = write_trace(directory, rows)
            with self.assertRaisesRegex(TraceValidationError, r"fixture\.ack\.csv.*time_ps"):
                load_trace(prefix)

    def test_rejects_token_time_decrease_in_global_event_order(self):
        rows = valid_rows()
        rows["token"][0]["time_ps"] = "99"
        with tempfile.TemporaryDirectory() as directory:
            prefix = write_trace(directory, rows)
            with self.assertRaisesRegex(TraceValidationError, r"fixture\.token\.csv.*time_ps"):
                load_trace(prefix)

    def test_rejects_background_time_decrease_in_global_event_order(self):
        rows = valid_rows()
        rows["background"] = [{
            "schema_version": "2", "run_id": "fixture", "event_seq": "2",
            "time_ps": "109", "background_id": "5", "operation": "delivery",
            "src": "0", "dst": "16", "path_index": "2",
            "configured_rate_gbps": "25", "delivered_bytes": "4150",
            "queue_fingerprint": "4:5:6",
        }]
        rows["epoch"][0]["event_seq"] = "3"
        with tempfile.TemporaryDirectory() as directory:
            prefix = write_trace(directory, rows)
            with self.assertRaisesRegex(
                TraceValidationError,
                r"fixture\.background\.csv.*time_ps",
            ):
                load_trace(prefix)

    def test_rejects_epoch_end_time_decrease_in_global_event_order(self):
        rows = valid_rows()
        rows["epoch"][0]["end_ps"] = "109"
        with tempfile.TemporaryDirectory() as directory:
            prefix = write_trace(directory, rows)
            with self.assertRaisesRegex(TraceValidationError, r"fixture\.epoch\.csv.*end_ps"):
                load_trace(prefix)

    def test_allows_equal_effective_times_across_event_kinds(self):
        rows = valid_rows()
        rows["ack"][0]["time_ps"] = "100"
        rows["token"][0]["time_ps"] = "100"
        rows["background"] = [{
            "schema_version": "2", "run_id": "fixture", "event_seq": "2",
            "time_ps": "100", "background_id": "5", "operation": "delivery",
            "src": "0", "dst": "16", "path_index": "2",
            "configured_rate_gbps": "25", "delivered_bytes": "4150",
            "queue_fingerprint": "4:5:6",
        }]
        rows["epoch"][0].update({"event_seq": "3", "end_ps": "100"})
        with tempfile.TemporaryDirectory() as directory:
            bundle = load_trace(write_trace(directory, rows))
        self.assertEqual([event.event_seq for event in bundle.events], [0, 1, 2, 3, 100])

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
        rows["ack"][0].update({"event_seq": "2", "time_ps": "110"})
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

    def test_rejects_enqueue_entropy_that_differs_from_referenced_ack(self):
        rows = valid_rows()
        rows["token"][0]["entropy"] = "2"
        with tempfile.TemporaryDirectory() as directory:
            prefix = write_trace(directory, rows)
            with self.assertRaisesRegex(
                TraceValidationError,
                r"fixture\.token\.csv.*entropy",
            ):
                load_trace(prefix)

    def test_rejects_enqueue_from_ecn_marked_ack(self):
        rows = valid_rows()
        rows["ack"][0]["ecn"] = "1"
        with tempfile.TemporaryDirectory() as directory:
            prefix = write_trace(directory, rows)
            with self.assertRaisesRegex(
                TraceValidationError,
                r"fixture\.token\.csv.*related_ack_event_seq",
            ):
                load_trace(prefix)

    def test_rejects_multiple_enqueues_from_one_ack(self):
        rows = valid_rows()
        duplicate = dict(rows["token"][0])
        duplicate.update({
            "event_seq": "2", "token_id": "43",
            "queue_depth_before": "1", "queue_depth_after": "2",
        })
        rows["token"].append(duplicate)
        rows["epoch"][0]["event_seq"] = "3"
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
        later_ack.update({"event_seq": "3", "time_ps": "120", "acked_psn": "11"})
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
                if key == "entropy":
                    rows["token"][0]["entropy"] = value
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
