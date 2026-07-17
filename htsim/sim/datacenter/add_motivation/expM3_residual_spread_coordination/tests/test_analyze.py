import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.analyze import (
    analyze_data,
)
from htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination import make_figs
from htsim.sim.datacenter.add_motivation.common.trace_schema import _SCHEMAS


HEADERS = {kind: tuple(name for name, _parser in schema) for kind, schema in _SCHEMAS.items()}
MODES = ("original_prism", "prism_recycle", "full_prism")


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


def _manifest(run_id, scenario, mode, seed, foreground_flows):
    return {
        "run_id": run_id,
        "seed": seed,
        "experiment": "M3_residual_spread_coordination",
        "phase": "fixture",
        "config": {
            "cc": "prism",
            "load_balancing_algo": "reps_actual",
            "prism_coordination_mode": mode,
            "degraded_links": 8,
            "degraded_capacity_gbps": 25.0,
        },
        "analysis_config": {
            "scenario": scenario,
            "foreground_flows": foreground_flows,
            "offered_load_gbps": 744.0 if scenario == "recoverable" else 931.0,
            "seed": seed,
        },
    }


def _write_bundle(root, scenario, mode, seed=13, *, handoff=False,
                  refresh_complete=True, recycled=False, progress=True,
                  coordination_recycle=False, throttled_bytes=100, healthy_bytes=900,
                  foreground_flows=2, completed_spread_ps=6_000_000,
                  pathmap_resolution="resolved", duplicate_pathmap=False,
                  ack_flow_ids=None, ack_physical_path_ids=None):
    run_id = f"fixture_{scenario}_{mode}_s{seed}"
    prefix = root / run_id
    run_id_values = {"run_id": run_id}
    ack_flow_ids = ack_flow_ids or (1, 2)
    ack_physical_path_ids = ack_physical_path_ids or (10, 20)
    _write_csv(prefix.with_suffix(".ack.csv"), "ack", [
        _row("ack", **run_id_values, seed=seed, scenario=scenario, event_seq=1,
             time_ps=2_000_000_000, flow_id=ack_flow_ids[0], epoch_id=1, acked_psn=1,
             entropy=0, physical_path_id=ack_physical_path_ids[0], raw_rtt_ps=18_000_000,
             base_rtt_ps=14_000_000, qdelay_ps=4_000_000, ecn=0,
             genuine_sample=1, retransmitted=0,
             selection_source="recycled" if recycled else "fresh",
             newly_acked_bytes=throttled_bytes,
             new_data_bytes_sent_total=throttled_bytes, cwnd_bytes=12000),
        _row("ack", **run_id_values, seed=seed, scenario=scenario, event_seq=2,
             time_ps=2_000_000_000, flow_id=ack_flow_ids[1], epoch_id=1, acked_psn=1,
             entropy=0, physical_path_id=ack_physical_path_ids[1], raw_rtt_ps=16_000_000,
             base_rtt_ps=14_000_000, qdelay_ps=2_000_000, ecn=0,
             genuine_sample=1, retransmitted=0, selection_source="fresh",
             newly_acked_bytes=healthy_bytes,
             new_data_bytes_sent_total=healthy_bytes, cwnd_bytes=13000),
    ])
    _write_csv(prefix.with_suffix(".token.csv"), "token", [])
    _write_csv(prefix.with_suffix(".epoch.csv"), "epoch", [
        _row("epoch", **run_id_values, event_seq=3, flow_id=1, epoch_id=1,
             start_ps=1_000_000_000, end_ps=2_000_000_000, sample_count=3,
             raw_floor_ps=2_000_000, raw_spread_ps=8_000_000,
             smooth_floor_ps=2_000_000, smooth_spread_ps=8_000_000,
             observed_region="hold", actual_region="hold", engaged=1,
             entropy_coverage=8, physical_path_coverage=2,
             new_data_bytes_sent_total=throttled_bytes,
             acked_bytes_total=throttled_bytes, cwnd_bytes=12000),
        _row("epoch", **run_id_values, event_seq=4, flow_id=2, epoch_id=1,
             start_ps=1_000_000_000, end_ps=2_000_000_000, sample_count=3,
             raw_floor_ps=2_000_000, raw_spread_ps=6_000_000,
             smooth_floor_ps=2_000_000, smooth_spread_ps=6_000_000,
             observed_region="hold", actual_region="hold", engaged=1,
             entropy_coverage=8, physical_path_coverage=2,
             new_data_bytes_sent_total=healthy_bytes,
             acked_bytes_total=healthy_bytes, cwnd_bytes=13000),
    ])
    _write_csv(prefix.with_suffix(".background.csv"), "background", [])
    _write_csv(prefix.with_suffix(".pathmap.csv"), "pathmap", [
        _row("pathmap", **run_id_values, flow_id=1, entropy=0, physical_path_id=10,
             resolution_status=pathmap_resolution, queue_fingerprint="1", bottleneck_rate_gbps=25,
             contains_reduced_link=1, ordered_queue_ids="1"),
        _row("pathmap", **run_id_values, flow_id=2, entropy=0, physical_path_id=20,
             resolution_status="resolved", queue_fingerprint="2", bottleneck_rate_gbps=100,
             contains_reduced_link=0, ordered_queue_ids="2"),
    ] + ([
        _row("pathmap", **run_id_values, flow_id=1, entropy=0, physical_path_id=11,
             resolution_status="resolved", queue_fingerprint="3", bottleneck_rate_gbps=100,
             contains_reduced_link=0, ordered_queue_ids="3"),
    ] if duplicate_pathmap else []))
    _write_csv(prefix.with_suffix(".linkmap.csv"), "linkmap", [
        _row("linkmap", **run_id_values, queue_id=1, queue_name="reduced",
             rate_gbps=25, reduced_speed=1),
        _row("linkmap", **run_id_values, queue_id=2, queue_name="healthy",
             rate_gbps=100, reduced_speed=0),
    ])
    action = "invalidate" if coordination_recycle else ("round_complete_handoff" if handoff else "round_complete_progress")
    _write_csv(prefix.with_suffix(".coordination.csv"), "coordination", [
        _row("coordination", **run_id_values, event_seq=5, time_ps=2_200_000_000,
             flow_id=1, epoch_id=1, round_id=1, cache_slot=4294967295,
             cache_generation=18446744073709551615, floor_ps=2_000_000,
             spread_ps=completed_spread_ps, spread_ref_ps=8_000_000, residual_ps=0,
             action=action, reason="slot_high_residual" if coordination_recycle else ("spread_not_reduced" if handoff else "spread_reduced"),
             refresh_complete=int(refresh_complete and not coordination_recycle), progress=int(progress and not handoff and not coordination_recycle),
             handoff=int(handoff and not coordination_recycle), cwnd_bytes=12000,
             control_state="decrease" if handoff else "hold"),
    ])
    (root / f"{run_id}.manifest.json").write_text(
        json.dumps(_manifest(run_id, scenario, mode, seed, foreground_flows)), encoding="ascii"
    )


class AnalyzeTests(unittest.TestCase):
    def _all_modes(self, root, scenario, **changes):
        for mode in MODES:
            _write_bundle(root, scenario, mode, **changes.get(mode, {}))

    def test_rejects_handoff_before_refresh_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._all_modes(root, "persistent", full_prism={"handoff": True, "progress": False, "refresh_complete": False})
            with self.assertRaisesRegex(ValueError, "handoff before refresh completion"):
                analyze_data(root)

    def test_rejects_original_prism_recycle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._all_modes(root, "recoverable", original_prism={"coordination_recycle": True})
            with self.assertRaisesRegex(ValueError, "original_prism emitted recycle"):
                analyze_data(root)

    def test_rejects_recoverable_full_prism_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._all_modes(root, "recoverable", full_prism={"handoff": True, "progress": False})
            with self.assertRaisesRegex(ValueError, "recoverable full_prism handed off"):
                analyze_data(root)

    def test_rejects_full_prism_handoff_after_positive_spread_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._all_modes(root, "persistent", full_prism={"handoff": True, "progress": False})
            with self.assertRaisesRegex(ValueError, "handoff after positive spread progress"):
                analyze_data(root)

    def test_rejects_missing_manifest_foreground_ack_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._all_modes(root, "persistent", original_prism={"foreground_flows": 3})
            with self.assertRaisesRegex(ValueError, "foreground ACK coverage"):
                analyze_data(root)

    def test_rejects_substituted_foreground_ack_flow_id(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._all_modes(root, "persistent", original_prism={"ack_flow_ids": (1, 3)})
            with self.assertRaisesRegex(ValueError, "foreground ACK flow IDs"):
                analyze_data(root)

    def test_rejects_ack_pathmap_physical_path_id_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._all_modes(root, "persistent", original_prism={"ack_physical_path_ids": (11, 20)})
            with self.assertRaisesRegex(ValueError, "physical path ID mismatch"):
                analyze_data(root)

    def test_rejects_unresolved_pathmap_attribution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._all_modes(root, "persistent", original_prism={"pathmap_resolution": "unresolved"})
            with self.assertRaisesRegex(ValueError, "unresolved pathmap attribution"):
                analyze_data(root)

    def test_rejects_duplicate_pathmap_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._all_modes(root, "persistent", original_prism={"duplicate_pathmap": True})
            with self.assertRaisesRegex(ValueError, "duplicate pathmap mapping"):
                analyze_data(root)

    def test_recoverable_progress_records_positive_spread_change_and_lower_throttled_ratio(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._all_modes(root, "recoverable", prism_recycle={"throttled_bytes": 50, "healthy_bytes": 950})
            results = analyze_data(root)
            recycle = next(row for row in results["per_seed_metrics"] if row["mode"] == "prism_recycle")
            original = next(row for row in results["per_seed_metrics"] if row["mode"] == "original_prism")
            round_row = next(row for row in results["rounds"] if row["mode"] == "prism_recycle")
            self.assertLess(recycle["throttled_traffic_ratio"], original["throttled_traffic_ratio"])
            self.assertTrue(round_row["progress"])
            self.assertGreater(round_row["spread_change_ps"], 0)

    def test_accepts_persistent_no_progress_then_full_prism_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._all_modes(root, "persistent", full_prism={
                "handoff": True,
                "progress": False,
                "completed_spread_ps": 8_000_000,
            })
            results = analyze_data(root)
            handoff = next(row for row in results["rounds"] if row["mode"] == "full_prism")
            self.assertFalse(handoff["progress"])
            self.assertTrue(handoff["handoff"])

    def test_epoch_aggregation_aligns_seed_rows_by_epoch_index(self):
        rows = [
            {"scenario": "persistent", "mode": "full_prism", "seed": "13", "epoch_index": "1", "floor_ps": "2", "spread_ps": "6", "cwnd_bytes": "12000", "hold_fraction": "1"},
            {"scenario": "persistent", "mode": "full_prism", "seed": "13", "epoch_index": "2", "floor_ps": "4", "spread_ps": "8", "cwnd_bytes": "14000", "hold_fraction": "0"},
            {"scenario": "persistent", "mode": "full_prism", "seed": "17", "epoch_index": "1", "floor_ps": "6", "spread_ps": "10", "cwnd_bytes": "16000", "hold_fraction": "0"},
        ]

        aggregate = make_figs._aggregate_epochs(rows, "persistent", "full_prism")

        self.assertEqual([row["epoch_index"] for row in aggregate], [1, 2])
        self.assertEqual([row["floor_ps"] for row in aggregate], [4.0, 4.0])
        self.assertEqual(aggregate[0]["hold_fraction"], 0.5)

    def test_epoch_figure_input_requires_control_state_fractions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "epoch_series.csv"
            path.write_text(
                "scenario,mode,seed,epoch_index,floor_ps,spread_ps,cwnd_bytes\n"
                "persistent,full_prism,13,1,2,6,12000\n",
                encoding="ascii",
            )
            with patch.object(make_figs, "AGGREGATE", root):
                with self.assertRaisesRegex(ValueError, "hold_fraction"):
                    make_figs._read("epoch_series.csv", make_figs.EPOCH_SERIES_FIELDS)


if __name__ == "__main__":
    unittest.main()
