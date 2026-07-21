import csv
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from htsim.sim.datacenter.add_motivation.common.trace_schema import _SCHEMAS


HEADERS = {kind: tuple(name for name, _parser in schema) for kind, schema in _SCHEMAS.items()}


def _row(kind, **values):
    row = {name: "0" for name in HEADERS[kind]}
    row.update({name: str(value) for name, value in values.items()})
    row["schema_version"] = "2"
    return row


def _write_csv(path, kind, rows):
    with path.open("w", newline="", encoding="ascii") as stream:
        writer = csv.DictWriter(stream, fieldnames=HEADERS[kind], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _write_bundle(root):
    run_id = "fixture_recoverable_outcome_recycle_s13"
    prefix = root / run_id
    manifest = {
        "run_id": run_id,
        "seed": 13,
        "experiment": "M3_residual_spread_coordination",
        "phase": "outcome_recycle",
        "config": {
            "cc": "prism",
            "load_balancing_algo": "reps_actual",
            "prism_coordination_mode": "outcome_recycle",
            "motivation_ecmp_hash_seed": 13,
            "motivation_ecn_threshold_packets": 211,
            "degraded_links": 2,
            "degraded_capacity_gbps": 25.0,
        },
        "analysis_config": {"scenario": "recoverable", "seed": 13},
    }
    (root / f"{run_id}.manifest.json").write_text(json.dumps(manifest), encoding="ascii")

    _write_csv(prefix.with_suffix(".pathmap.csv"), "pathmap", [
        _row("pathmap", run_id=run_id, flow_id=1, entropy=10, physical_path_id=101,
             resolution_status="resolved", queue_fingerprint="reduced-54",
             bottleneck_rate_gbps=25, contains_reduced_link=1, ordered_queue_ids="4|54|9"),
        _row("pathmap", run_id=run_id, flow_id=1, entropy=20, physical_path_id=102,
             resolution_status="resolved", queue_fingerprint="healthy",
             bottleneck_rate_gbps=100, contains_reduced_link=0, ordered_queue_ids="4|60|9"),
        _row("pathmap", run_id=run_id, flow_id=1, entropy=30, physical_path_id=103,
             resolution_status="resolved", queue_fingerprint="reduced-54-second",
             bottleneck_rate_gbps=25, contains_reduced_link=1, ordered_queue_ids="4|54|10"),
    ])
    _write_csv(prefix.with_suffix(".linkmap.csv"), "linkmap", [
        _row("linkmap", run_id=run_id, queue_id=54,
             queue_name="compqueue(25000Mb/s,218912bytes)CS4->US0(0)", rate_gbps=25,
             reduced_speed=1),
        _row("linkmap", run_id=run_id, queue_id=60, queue_name="healthy", rate_gbps=100,
             reduced_speed=0),
    ])
    _write_csv(prefix.with_suffix(".token.csv"), "token", [
        _row("token", run_id=run_id, event_seq=1, time_ps=100, flow_id=1,
             operation="enqueue_good_ack", reason="good_ack", entropy=10,
             cache_slot=0, cache_generation=1, admission_written=1),
        _row("token", run_id=run_id, event_seq=2, time_ps=110, flow_id=1,
             operation="enqueue_good_ack", reason="good_ack", entropy=20,
             cache_slot=1, cache_generation=1, admission_written=1),
        _row("token", run_id=run_id, event_seq=3, time_ps=115, flow_id=1,
             operation="enqueue_good_ack", reason="good_ack", entropy=30,
             cache_slot=2, cache_generation=1, admission_written=1),
    ])
    _write_csv(prefix.with_suffix(".coordination.csv"), "coordination", [
        _row("coordination", run_id=run_id, event_seq=4, time_ps=120, flow_id=1,
             epoch_id=1, round_id=1, cache_slot=0, cache_generation=1,
             floor_ps=1, spread_ps=20, spread_ref_ps=14, residual_ps=16,
             action="invalidate", reason="residual_threshold", refresh_complete=0,
             progress=0, handoff=0, cwnd_bytes=12000, control_state="hold"),
        _row("coordination", run_id=run_id, event_seq=5, time_ps=130, flow_id=1,
             epoch_id=1, round_id=1, cache_slot=1, cache_generation=1,
             floor_ps=1, spread_ps=20, spread_ref_ps=14, residual_ps=16,
             action="invalidate", reason="ecn_marked", refresh_complete=0,
             progress=0, handoff=0, cwnd_bytes=12000, control_state="hold"),
    ])
    for kind in ("ack", "epoch", "background"):
        _write_csv(prefix.with_suffix(f".{kind}.csv"), kind, [])


class CachePathGroupAnalysisTests(unittest.TestCase):
    def test_residual_targets_are_enriched_on_the_actual_reduced_queue(self):
        from htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.analyze_cache_path_groups import (
            analyze_cache_path_groups,
        )

        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_bundle(root)

            result = analyze_cache_path_groups(root, root / "aggregate")

            self.assertEqual(len(result["targets"]), 1)
            self.assertEqual(result["targets"][0]["queue_group"], "reduced:CS4->US0(0)")
            self.assertEqual(result["targets"][0]["entropy"], 10)
            self.assertEqual(result["targets"][0]["cohort_slot_count"], 2)
            self.assertEqual(result["targets"][0]["additional_cohort_slot_count"], 1)
            summary = result["summary"]
            self.assertEqual(len(summary), 2)
            reduced = next(
                row for row in summary if row["queue_group"] == "reduced:CS4->US0(0)"
            )
            self.assertEqual(reduced["cache_admission_count"], 2)
            self.assertEqual(reduced["high_residual_target_count"], 1)
            self.assertEqual(reduced["cache_admission_share"], 2 / 3)
            self.assertEqual(reduced["high_residual_target_share"], 1.0)
            self.assertEqual(reduced["target_enrichment"], 1.5)
            self.assertEqual(reduced["cohort_with_additional_count"], 1)
            self.assertEqual(reduced["cohort_with_additional_fraction"], 1.0)
            self.assertEqual(reduced["mean_additional_cohort_slot_count"], 1.0)
            self.assertTrue((root / "aggregate" / "cache_path_targets.csv").is_file())
            self.assertTrue((root / "aggregate" / "cache_path_group_summary.csv").is_file())

    def test_consumed_high_residual_reservation_is_a_target(self):
        from htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.analyze_cache_path_groups import (
            analyze_cache_path_groups,
        )

        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_bundle(root)
            path = root / "fixture_recoverable_outcome_recycle_s13.coordination.csv"
            with path.open(newline="", encoding="ascii") as stream:
                rows = list(csv.DictReader(stream))
            rows[0]["action"] = "reserve"
            rows[0]["reason"] = "consumed_high_residual"
            _write_csv(path, "coordination", rows)

            result = analyze_cache_path_groups(root, root / "aggregate")

            self.assertEqual(len(result["targets"]), 1)
            self.assertEqual(result["targets"][0]["entropy"], 10)
            self.assertEqual(result["targets"][0]["queue_group"], "reduced:CS4->US0(0)")
            self.assertEqual(result["targets"][0]["cohort_slot_count"], 2)
            self.assertEqual(result["targets"][0]["additional_cohort_slot_count"], 1)
