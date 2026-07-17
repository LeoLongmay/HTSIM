import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.analyze import (
    ROUND_MATRIX_PREDICATE,
    TABLE_FIELDS,
    _is_true,
    analyze_data,
    main,
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
    degraded_links = 2 if scenario == "recoverable" else 8
    return {
        "run_id": run_id,
        "seed": seed,
        "experiment": "M3_residual_spread_coordination",
        "phase": "fixture",
        "config": {
            "cc": "prism",
            "load_balancing_algo": "reps_actual",
            "prism_coordination_mode": mode,
            "degraded_links": degraded_links,
            "degraded_capacity_gbps": 25.0,
        },
        "analysis_config": {
            "scenario": scenario,
            "foreground_flows": foreground_flows,
            "degraded_links": degraded_links,
            "offered_load_gbps": 744.0 if scenario == "recoverable" else 931.0,
            "seed": seed,
        },
    }


def _set_manifest_degraded_links(root, scenario, mode, *, section, degraded_links, seed=13):
    run_id = f"fixture_{scenario}_{mode}_s{seed}"
    manifest_path = root / f"{run_id}.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    manifest[section]["degraded_links"] = degraded_links
    manifest_path.write_text(json.dumps(manifest), encoding="ascii")


def _write_bundle(root, scenario, mode, seed=13, *, handoff=False,
                  refresh_complete=True, recycled=False, progress=True,
                  retry=False,
                  coordination_recycle=False, throttled_bytes=100, healthy_bytes=900,
                  foreground_flows=2, completed_spread_ps=6_000_000,
                  pathmap_resolution="resolved", duplicate_pathmap=False,
                  ack_flow_ids=None, ack_physical_path_ids=None,
                  ack_event_seq=1, ack_epoch_id=1,
                  observer_epoch_id=1, coordination_epoch_id=1,
                  coordination_time_ps=2_200_000_000,
                  coordination_record_start_time_ps=2_100_000_000,
                  observer_epoch_start_ps=1_000_000_000,
                  observer_epoch_end_ps=2_000_000_000,
                  coordination_event_seq=5, observer_event_seq=3,
                  replacement_chain=None, clean_scan=None, emit_terminal=True):
    run_id = f"fixture_{scenario}_{mode}_s{seed}"
    prefix = root / run_id
    run_id_values = {"run_id": run_id}
    ack_flow_ids = ack_flow_ids or (1, 2)
    ack_physical_path_ids = ack_physical_path_ids or (10, 20)
    ack_rows = [
        _row("ack", **run_id_values, seed=seed, scenario=scenario, event_seq=ack_event_seq,
             time_ps=2_000_000_000, flow_id=ack_flow_ids[0], epoch_id=ack_epoch_id, acked_psn=1,
             entropy=0, physical_path_id=ack_physical_path_ids[0], raw_rtt_ps=18_000_000,
             base_rtt_ps=14_000_000, qdelay_ps=4_000_000, ecn=0,
             genuine_sample=1, retransmitted=0,
             selection_source="recycled" if recycled else "fresh",
             newly_acked_bytes=throttled_bytes,
             new_data_bytes_sent_total=throttled_bytes, cwnd_bytes=12000),
        _row("ack", **run_id_values, seed=seed, scenario=scenario, event_seq=ack_event_seq + 1,
             time_ps=2_000_000_000, flow_id=ack_flow_ids[1], epoch_id=ack_epoch_id, acked_psn=1,
             entropy=0, physical_path_id=ack_physical_path_ids[1], raw_rtt_ps=16_000_000,
             base_rtt_ps=14_000_000, qdelay_ps=2_000_000, ecn=0,
             genuine_sample=1, retransmitted=0, selection_source="fresh",
             newly_acked_bytes=healthy_bytes,
             new_data_bytes_sent_total=healthy_bytes, cwnd_bytes=13000),
    ]
    token_rows = []
    coordination_rows = []
    if clean_scan:
        terminal_event_seq = 13
        for slot in range(8):
            if clean_scan == "missing_slot" and slot == 7:
                continue
            coordination_rows.append(_row(
                "coordination", **run_id_values, event_seq=5 + slot,
                time_ps=coordination_record_start_time_ps + slot * 10_000_000, flow_id=1, epoch_id=1,
                round_id=1, cache_slot=slot, cache_generation=10 + slot,
                floor_ps=2_000_000, spread_ps=6_000_000, spread_ref_ps=8_000_000,
                residual_ps=4_000_000, action="retain", reason="slot_low_residual",
                refresh_complete=0, progress=0, handoff=0, cwnd_bytes=12000,
                control_state="hold",
            ))
        if clean_scan == "pending_after_retain":
            coordination_rows.append(_row(
                "coordination", **run_id_values, event_seq=13,
                time_ps=coordination_record_start_time_ps + 90_000_000, flow_id=1, epoch_id=1, round_id=1,
                cache_slot=7, cache_generation=17, floor_ps=2_000_000,
                spread_ps=6_000_000, spread_ref_ps=8_000_000, residual_ps=4_000_000,
                action="pending", reason="awaiting_observation", refresh_complete=0,
                progress=0, handoff=0, cwnd_bytes=12000, control_state="hold",
            ))
            terminal_event_seq = 14
        elif clean_scan in {"invalidate_after_retain", "invalidate_out_of_range_after_retain"}:
            coordination_rows.append(_row(
                "coordination", **run_id_values, event_seq=13,
                time_ps=coordination_record_start_time_ps + 90_000_000, flow_id=1, epoch_id=1, round_id=1,
                cache_slot=8 if clean_scan == "invalidate_out_of_range_after_retain" else 7,
                cache_generation=18 if clean_scan == "invalidate_out_of_range_after_retain" else 17,
                floor_ps=2_000_000,
                spread_ps=6_000_000, spread_ref_ps=8_000_000, residual_ps=4_000_000,
                action="invalidate", reason="slot_high_residual", refresh_complete=0,
                progress=0, handoff=0, cwnd_bytes=12000, control_state="hold",
            ))
            terminal_event_seq = 14
        action = "round_complete_retry" if retry else (
            "round_complete_handoff" if handoff else "round_complete_progress"
        )
        coordination_rows.append(_row(
            "coordination", **run_id_values, event_seq=terminal_event_seq,
            time_ps=coordination_time_ps, flow_id=1, epoch_id=coordination_epoch_id,
            round_id=1, cache_slot=4294967295, cache_generation=18446744073709551615,
            floor_ps=2_000_000, spread_ps=completed_spread_ps, spread_ref_ps=8_000_000,
            residual_ps=0, action=action,
            reason="spread_not_reduced" if retry or handoff else "spread_reduced",
            refresh_complete=int(refresh_complete), progress=int(progress and not handoff and not retry),
            handoff=int(handoff and not retry), cwnd_bytes=12000,
            control_state="decrease" if handoff else "hold",
        ))
    elif replacement_chain:
        invalidation = _row(
            "coordination", **run_id_values, event_seq=5, time_ps=2_100_000_000,
            flow_id=1, epoch_id=1, round_id=1, cache_slot=3, cache_generation=10,
            floor_ps=2_000_000, spread_ps=8_000_000, spread_ref_ps=8_000_000,
            residual_ps=6_000_000, action="invalidate", reason="slot_high_residual",
            refresh_complete=0, progress=0, handoff=0, cwnd_bytes=12000,
            control_state="hold",
        )
        coordination_rows.append(invalidation)
        terminal_event_seq = 6
        if replacement_chain != "without_admission":
            admission_event_seq = 7 if replacement_chain == "admission_after_terminal" else 6
            admission_time_ps = 2_210_000_000 if replacement_chain == "admission_after_terminal" else 2_110_000_000
            admission_generation = 10 if replacement_chain == "stale_generation" else 11
            ack_rows.append(_row(
                "ack", **run_id_values, seed=seed, scenario=scenario,
                event_seq=admission_event_seq, time_ps=admission_time_ps, flow_id=1,
                epoch_id=2, acked_psn=2, entropy=1, physical_path_id=10,
                raw_rtt_ps=18_000_000, base_rtt_ps=14_000_000, qdelay_ps=4_000_000,
                ecn=0, genuine_sample=1, retransmitted=0, selection_source="fresh",
                newly_acked_bytes=0, new_data_bytes_sent_total=throttled_bytes,
                cwnd_bytes=12000,
            ))
            token_rows.append(_row(
                "token", **run_id_values, event_seq=admission_event_seq + 1,
                time_ps=admission_time_ps + 10_000_000, flow_id=1,
                operation="enqueue_good_ack", reason="admit", token_id=1, entropy=1,
                queue_depth_before=0, queue_depth_after=1,
                related_ack_event_seq=admission_event_seq, cache_slot=3,
                cache_generation=admission_generation, admission_written=1,
            ))
            if replacement_chain != "admission_after_terminal":
                terminal_event_seq = admission_event_seq + 2
            if replacement_chain != "without_retain":
                retain_event_seq = admission_event_seq + 2 if replacement_chain == "admission_after_terminal" else terminal_event_seq
                coordination_rows.append(_row(
                    "coordination", **run_id_values, event_seq=retain_event_seq,
                    time_ps=admission_time_ps + 20_000_000, flow_id=1, epoch_id=2,
                    round_id=1, cache_slot=3, cache_generation=admission_generation,
                    floor_ps=2_000_000, spread_ps=6_000_000, spread_ref_ps=8_000_000,
                    residual_ps=4_000_000, action="retain", reason="slot_low_residual",
                    refresh_complete=0, progress=0, handoff=0, cwnd_bytes=12000,
                    control_state="hold",
                ))
                if replacement_chain != "admission_after_terminal":
                    terminal_event_seq += 1
        action = "round_complete_retry" if retry else (
            "round_complete_handoff" if handoff else "round_complete_progress"
        )
        coordination_rows.append(_row(
            "coordination", **run_id_values, event_seq=terminal_event_seq,
            time_ps=coordination_time_ps, flow_id=1, epoch_id=coordination_epoch_id,
            round_id=1, cache_slot=4294967295, cache_generation=18446744073709551615,
            floor_ps=2_000_000, spread_ps=completed_spread_ps, spread_ref_ps=8_000_000,
            residual_ps=0, action=action,
            reason="spread_not_reduced" if retry or handoff else "spread_reduced",
            refresh_complete=int(refresh_complete), progress=int(progress and not handoff and not retry),
            handoff=int(handoff and not retry), cwnd_bytes=12000,
            control_state="decrease" if handoff else "hold",
        ))
    _write_csv(prefix.with_suffix(".ack.csv"), "ack", ack_rows)
    _write_csv(prefix.with_suffix(".token.csv"), "token", token_rows)
    _write_csv(prefix.with_suffix(".epoch.csv"), "epoch", [
        _row("epoch", **run_id_values, event_seq=observer_event_seq, flow_id=1, epoch_id=observer_epoch_id,
             start_ps=observer_epoch_start_ps, end_ps=observer_epoch_end_ps, sample_count=3,
             raw_floor_ps=2_000_000, raw_spread_ps=8_000_000,
             smooth_floor_ps=2_000_000, smooth_spread_ps=8_000_000,
             observed_region="hold", actual_region="hold", engaged=1,
             entropy_coverage=8, physical_path_coverage=2,
             new_data_bytes_sent_total=throttled_bytes,
             acked_bytes_total=throttled_bytes, cwnd_bytes=12000),
        _row("epoch", **run_id_values, event_seq=observer_event_seq + 1, flow_id=2, epoch_id=observer_epoch_id,
             start_ps=observer_epoch_start_ps, end_ps=observer_epoch_end_ps, sample_count=3,
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
    if not replacement_chain and not clean_scan and emit_terminal:
        action = "invalidate" if coordination_recycle else (
            "round_complete_retry" if retry else (
                "round_complete_handoff" if handoff else "round_complete_progress"
            )
        )
        coordination_rows.append(_row(
            "coordination", **run_id_values, event_seq=coordination_event_seq, time_ps=coordination_time_ps,
            flow_id=1, epoch_id=coordination_epoch_id, round_id=1, cache_slot=4294967295,
            cache_generation=18446744073709551615, floor_ps=2_000_000,
            spread_ps=completed_spread_ps, spread_ref_ps=8_000_000, residual_ps=0,
            action=action, reason="slot_high_residual" if coordination_recycle else (
                "spread_not_reduced" if retry or handoff else "spread_reduced"
            ),
            refresh_complete=int(refresh_complete and not coordination_recycle), progress=int(progress and not handoff and not retry and not coordination_recycle),
            handoff=int(handoff and not retry and not coordination_recycle), cwnd_bytes=12000,
            control_state="decrease" if handoff else "hold",
        ))
    _write_csv(
        prefix.with_suffix(".coordination.csv"),
        "coordination",
        sorted(coordination_rows, key=lambda row: int(row["event_seq"])),
    )
    (root / f"{run_id}.manifest.json").write_text(
        json.dumps(_manifest(run_id, scenario, mode, seed, foreground_flows)), encoding="ascii"
    )


class AnalyzeTests(unittest.TestCase):
    def test_rejects_manifest_with_wrong_scenario_degraded_link_count(self):
        for scenario, expected_links, wrong_links in (
            ("recoverable", 2, 8),
            ("persistent", 8, 2),
        ):
            for section in ("config", "analysis_config"):
                with self.subTest(scenario=scenario, section=section), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    _write_bundle(root, scenario, "prism_recycle", replacement_chain="complete")
                    _set_manifest_degraded_links(
                        root,
                        scenario,
                        "prism_recycle",
                        section=section,
                        degraded_links=wrong_links,
                    )

                    with self.assertRaisesRegex(
                        ValueError,
                        f"{scenario} requires {expected_links} degraded links",
                    ):
                        analyze_data(root)

    def test_recoverable_full_prism_pre_warmup_handoff_emits_no_round_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_bundle(
                root,
                "recoverable",
                "full_prism",
                handoff=True,
                progress=False,
                clean_scan=True,
                coordination_time_ps=950_000_000,
                coordination_record_start_time_ps=850_000_000,
                completed_spread_ps=8_000_000,
                ack_event_seq=20,
                observer_event_seq=30,
            )

            result = analyze_data(root)

        self.assertEqual(result["rounds"], [])

    def test_recoverable_full_prism_pre_warmup_handoff_with_incomplete_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_bundle(
                root,
                "recoverable",
                "full_prism",
                handoff=True,
                progress=False,
                clean_scan="missing_slot",
                coordination_time_ps=950_000_000,
                coordination_record_start_time_ps=850_000_000,
                completed_spread_ps=8_000_000,
                ack_event_seq=20,
                observer_event_seq=30,
            )

            with self.assertRaisesRegex(ValueError, "terminal evidence"):
                analyze_data(root)

    def _supported_verifier_rows(self):
        metrics = []
        rounds = []
        for scenario in ("recoverable", "persistent"):
            for mode in MODES:
                for seed in (13, 14, 15):
                    metrics.append({
                        "run_id": f"formal_{scenario}_{mode}_s{seed}",
                        "scenario": scenario,
                        "mode": mode,
                        "seed": seed,
                        "throttled_traffic_ratio": 0.9 if (scenario, mode) == ("recoverable", "full_prism") else 0.1,
                        "goodput_gbps": 1.0,
                        "p99_genuine_qdelay_ps": 99,
                    })
        for seed in (13, 14):
            rounds.append({
                "run_id": f"formal_recoverable_prism_recycle_s{seed}",
                "scenario": "recoverable",
                "mode": "prism_recycle",
                "seed": seed,
                "round_index": 1,
                "refresh_complete": 1,
                "progress": 1,
                "handoff": 0,
                "replacement_chain_complete": 1,
            })
            rounds.append({
                "run_id": f"formal_recoverable_full_prism_s{seed}",
                "scenario": "recoverable",
                "mode": "full_prism",
                "seed": seed,
                "round_index": 1,
                "refresh_complete": 1,
                "progress": 1,
                "handoff": 0,
                "replacement_chain_complete": 1,
            })
            rounds.append({
                "run_id": f"formal_persistent_full_prism_s{seed}",
                "scenario": "persistent",
                "mode": "full_prism",
                "seed": seed,
                "round_index": 1,
                "refresh_complete": 1,
                "progress": 0,
                "handoff": 1,
                "replacement_chain_complete": 1,
            })
        return metrics, rounds

    def _write_verifier_aggregate(self, root, metrics, rounds):
        aggregate = root / "aggregate"
        aggregate.mkdir()
        for name, rows in (("per_seed_metrics", metrics), ("rounds", rounds)):
            with (aggregate / f"{name}.csv").open("w", newline="", encoding="ascii") as stream:
                writer = csv.DictWriter(stream, fieldnames=TABLE_FIELDS[name], lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)

    def _verdict(self, root):
        output = io.StringIO()
        with redirect_stdout(output):
            status = main(["--data-root", str(root), "--verify-only"])
        self.assertEqual(status, 0)
        return output.getvalue()

    def test_verify_only_supports_chain_backed_majority_seed_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            metrics, rounds = self._supported_verifier_rows()
            self._write_verifier_aggregate(Path(directory), metrics, rounds)

            self.assertEqual(self._verdict(Path(directory)), "supported\n")

    def test_verify_only_supports_persistent_clean_scan_handoff_majority(self):
        with tempfile.TemporaryDirectory() as directory:
            metrics, rounds = self._supported_verifier_rows()
            for row in (row for row in rounds if row["scenario"] == "persistent"):
                row["replacement_chain_complete"] = 0
                row["clean_scan_complete"] = 1
            self._write_verifier_aggregate(Path(directory), metrics, rounds)

            self.assertEqual(self._verdict(Path(directory)), "supported\n")

    def test_verify_only_does_not_count_clean_scans_as_recoverable_recycling(self):
        with tempfile.TemporaryDirectory() as directory:
            metrics, rounds = self._supported_verifier_rows()
            for row in (
                row for row in rounds
                if row["scenario"] == "recoverable" and row["mode"] == "prism_recycle"
            ):
                row["replacement_chain_complete"] = 0
                row["clean_scan_complete"] = 1
            self._write_verifier_aggregate(Path(directory), metrics, rounds)

            self.assertEqual(
                self._verdict(Path(directory)),
                "not_supported: at least two recoverable/prism_recycle seeds have a chain-backed progress round\n",
            )

    def test_verify_only_does_not_select_success_from_one_recoverable_seed(self):
        with tempfile.TemporaryDirectory() as directory:
            metrics, rounds = self._supported_verifier_rows()
            rounds[:] = [
                row for row in rounds
                if not (row["scenario"] == "recoverable" and row["seed"] == 14)
            ]
            self._write_verifier_aggregate(Path(directory), metrics, rounds)

            self.assertEqual(
                self._verdict(Path(directory)),
                "not_supported: at least two recoverable/prism_recycle seeds have a chain-backed progress round\n",
            )

    def test_verify_only_rejects_incomplete_fixed_matrix(self):
        with tempfile.TemporaryDirectory() as directory:
            metrics, rounds = self._supported_verifier_rows()
            metrics.pop()
            self._write_verifier_aggregate(Path(directory), metrics, rounds)

            self.assertEqual(
                self._verdict(Path(directory)),
                "not_supported: fixed complete 18-run matrix (scenarios recoverable/persistent, modes original_prism/prism_recycle/full_prism, seeds 13/14/15)\n",
            )

    def test_verify_only_rejects_empty_rounds_before_selecting_a_seed(self):
        with tempfile.TemporaryDirectory() as directory:
            metrics, _rounds = self._supported_verifier_rows()
            self._write_verifier_aggregate(Path(directory), metrics, [])

            self.assertEqual(
                self._verdict(Path(directory)),
                "not_supported: at least two recoverable/prism_recycle seeds have a chain-backed progress round\n",
            )

    def test_verify_only_treats_missing_boolean_cell_as_false(self):
        with tempfile.TemporaryDirectory() as directory:
            metrics, rounds = self._supported_verifier_rows()
            progress_row = next(row for row in rounds if row["scenario"] == "recoverable")
            del progress_row["progress"]
            self._write_verifier_aggregate(Path(directory), metrics, rounds)

            self.assertEqual(
                self._verdict(Path(directory)),
                "not_supported: at least two recoverable/prism_recycle seeds have a chain-backed progress round\n",
            )
            self.assertFalse(_is_true({}, "progress"))
            self.assertFalse(_is_true({"progress": None}, "progress"))
            self.assertFalse(_is_true({"progress": 1}, "progress"))

    def test_verify_only_requires_refresh_completion_for_every_counted_terminal(self):
        for refresh_complete in ("", None, "0"):
            with self.subTest(refresh_complete=refresh_complete), tempfile.TemporaryDirectory() as directory:
                metrics, rounds = self._supported_verifier_rows()
                for row in (
                    row for row in rounds
                    if row["scenario"] == "recoverable" and row["mode"] == "prism_recycle"
                ):
                    if refresh_complete is None:
                        del row["refresh_complete"]
                    else:
                        row["refresh_complete"] = refresh_complete
                self._write_verifier_aggregate(Path(directory), metrics, rounds)

                self.assertEqual(
                    self._verdict(Path(directory)),
                    "not_supported: at least two recoverable/prism_recycle seeds have a chain-backed progress round\n",
                )

    def test_verify_only_rejects_recoverable_progress_with_coexisting_applied_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            metrics, rounds = self._supported_verifier_rows()
            rounds.append({
                "run_id": "formal_recoverable_full_prism_s13",
                "scenario": "recoverable",
                "mode": "full_prism",
                "seed": 13,
                "round_index": 2,
                "refresh_complete": 1,
                "replacement_chain_complete": 1,
                "progress": 0,
                "handoff": 1,
            })
            self._write_verifier_aggregate(Path(directory), metrics, rounds)

            self.assertEqual(
                self._verdict(Path(directory)),
                "not_supported: at least two recoverable/full_prism seeds have a chain-backed progress round and no applied handoff\n",
            )

    def test_verify_only_rejects_duplicate_metric_run_id(self):
        with tempfile.TemporaryDirectory() as directory:
            metrics, rounds = self._supported_verifier_rows()
            metrics[-1]["run_id"] = metrics[0]["run_id"]
            self._write_verifier_aggregate(Path(directory), metrics, rounds)

            self.assertEqual(
                self._verdict(Path(directory)),
                "not_supported: fixed complete 18-run matrix (scenarios recoverable/persistent, modes original_prism/prism_recycle/full_prism, seeds 13/14/15)\n",
            )

    def test_verify_only_rejects_rounds_from_foreign_run_id(self):
        with tempfile.TemporaryDirectory() as directory:
            metrics, rounds = self._supported_verifier_rows()
            next(row for row in rounds if row["scenario"] == "recoverable")["run_id"] = "foreign-run"
            self._write_verifier_aggregate(Path(directory), metrics, rounds)

            self.assertEqual(
                self._verdict(Path(directory)),
                f"not_supported: {ROUND_MATRIX_PREDICATE}\n",
            )

    def test_verify_only_rejects_appended_foreign_blank_round(self):
        with tempfile.TemporaryDirectory() as directory:
            metrics, rounds = self._supported_verifier_rows()
            rounds.append({
                "run_id": "foreign-run",
                "scenario": "",
                "mode": "",
                "seed": "",
            })
            self._write_verifier_aggregate(Path(directory), metrics, rounds)

            self.assertEqual(
                self._verdict(Path(directory)),
                f"not_supported: {ROUND_MATRIX_PREDICATE}\n",
            )

    def test_verify_only_rejects_recoverable_full_prism_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            metrics, rounds = self._supported_verifier_rows()
            for row in (row for row in rounds if row["scenario"] == "recoverable"):
                row["handoff"] = 1
            self._write_verifier_aggregate(Path(directory), metrics, rounds)

            self.assertEqual(
                self._verdict(Path(directory)),
                "not_supported: at least two recoverable/full_prism seeds have a chain-backed progress round and no applied handoff\n",
            )

    def test_verify_only_keeps_descriptive_metrics_out_of_support_gates(self):
        with tempfile.TemporaryDirectory() as directory:
            metrics, rounds = self._supported_verifier_rows()
            next(row for row in metrics if row["scenario"] == "recoverable" and row["mode"] == "full_prism")["throttled_traffic_ratio"] = 0.2
            self._write_verifier_aggregate(Path(directory), metrics, rounds)

            next(row for row in metrics if row["scenario"] == "persistent" and row["mode"] == "full_prism")["goodput_gbps"] = "not-a-number"
            next(row for row in metrics if row["scenario"] == "persistent" and row["mode"] == "full_prism")["p99_genuine_qdelay_ps"] = "not-a-number"
            self.assertEqual(self._verdict(Path(directory)), "supported\n")

    def test_verify_only_rejects_persistent_full_prism_without_no_progress_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            metrics, rounds = self._supported_verifier_rows()
            for row in (row for row in rounds if row["scenario"] == "persistent"):
                row["handoff"] = 0
            self._write_verifier_aggregate(Path(directory), metrics, rounds)

            self.assertEqual(
                self._verdict(Path(directory)),
                "not_supported: at least two persistent/full_prism seeds have an evidence-backed no-progress applied-handoff round\n",
            )

    def test_verify_only_rejects_persistent_original_prism_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            metrics, rounds = self._supported_verifier_rows()
            rounds.append({
                "run_id": "formal_persistent_original_prism_s13",
                "scenario": "persistent",
                "mode": "original_prism",
                "seed": 13,
                "handoff": 1,
                "progress": 0,
            })
            self._write_verifier_aggregate(Path(directory), metrics, rounds)

            self.assertEqual(
                self._verdict(Path(directory)),
                "not_supported: no persistent/original_prism seed has a handoff round\n",
            )

    def test_verify_only_rejects_persistent_prism_recycle_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            metrics, rounds = self._supported_verifier_rows()
            rounds.append({
                "run_id": "formal_persistent_prism_recycle_s13",
                "scenario": "persistent",
                "mode": "prism_recycle",
                "seed": 13,
                "handoff": 1,
                "progress": 0,
            })
            self._write_verifier_aggregate(Path(directory), metrics, rounds)

            self.assertEqual(
                self._verdict(Path(directory)),
                "not_supported: no persistent/prism_recycle seed has a handoff round\n",
            )

    def _all_modes(self, root, scenario, **changes):
        for mode in MODES:
            options = dict(changes.get(mode, {}))
            if mode == "original_prism":
                if not options.get("coordination_recycle"):
                    options.setdefault("emit_terminal", False)
            else:
                options.setdefault("replacement_chain", "complete")
            _write_bundle(root, scenario, mode, **options)

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

    def test_rejects_terminal_without_replacement_admission(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_bundle(root, "persistent", "prism_recycle", replacement_chain="without_admission")

            with self.assertRaisesRegex(ValueError, "terminal evidence"):
                analyze_data(root)

    def test_rejects_terminal_only_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_bundle(root, "persistent", "prism_recycle", replacement_chain=None)

            with self.assertRaisesRegex(ValueError, "terminal evidence"):
                analyze_data(root)

    def test_accepts_complete_clean_scan_and_emits_distinct_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_bundle(root, "persistent", "prism_recycle", clean_scan="complete")

            results = analyze_data(root, write=True)

            terminal = results["rounds"][0]
            self.assertFalse(terminal["replacement_chain_complete"])
            self.assertTrue(terminal["clean_scan_complete"])
            with (root / "aggregate" / "rounds.csv").open(newline="", encoding="ascii") as stream:
                self.assertIn("clean_scan_complete", csv.DictReader(stream).fieldnames)

    def test_rejects_clean_scan_with_missing_or_replaced_latest_slot(self):
        for clean_scan in (
            "missing_slot",
            "pending_after_retain",
            "invalidate_after_retain",
            "invalidate_out_of_range_after_retain",
        ):
            with self.subTest(clean_scan=clean_scan), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                _write_bundle(root, "persistent", "prism_recycle", clean_scan=clean_scan)

                with self.assertRaisesRegex(ValueError, "terminal evidence"):
                    analyze_data(root)

    def test_rejects_replacement_admission_with_stale_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_bundle(root, "persistent", "prism_recycle", replacement_chain="stale_generation")

            with self.assertRaisesRegex(ValueError, "terminal evidence"):
                analyze_data(root)

    def test_rejects_replacement_admission_after_terminal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_bundle(root, "persistent", "prism_recycle", replacement_chain="admission_after_terminal")

            with self.assertRaisesRegex(ValueError, "terminal evidence"):
                analyze_data(root)

    def test_rejects_replacement_admission_without_later_retain(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_bundle(root, "persistent", "prism_recycle", replacement_chain="without_retain")

            with self.assertRaisesRegex(ValueError, "terminal evidence"):
                analyze_data(root)

    def test_accepts_ordered_replacement_admission_retain_and_terminal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_bundle(root, "persistent", "prism_recycle", replacement_chain="complete")

            results = analyze_data(root)

            terminal = results["rounds"][0]
            self.assertTrue(terminal["replacement_chain_complete"])

    def test_counts_retry_terminal_with_replacement_evidence_without_progress_or_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_bundle(
                root,
                "persistent",
                "full_prism",
                replacement_chain="complete",
                retry=True,
            )

            results = analyze_data(root)

            terminal = results["rounds"][0]
            metrics = results["per_seed_metrics"][0]
            self.assertTrue(terminal["replacement_chain_complete"])
            self.assertFalse(terminal["progress"])
            self.assertFalse(terminal["handoff"])
            self.assertEqual(metrics["completed_rounds"], 1)
            self.assertEqual(metrics["progress_rounds"], 0)
            self.assertEqual(metrics["handoff_rounds"], 0)

    def test_rejects_recoverable_full_prism_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._all_modes(
                root,
                "recoverable",
                full_prism={
                    "handoff": True,
                    "progress": False,
                    "completed_spread_ps": 8_000_000,
                },
            )
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

    def test_maps_terminal_round_to_latest_same_flow_observer_epoch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._all_modes(root, "persistent", prism_recycle={
                "observer_epoch_id": 4,
                "coordination_epoch_id": 91,
                "coordination_time_ps": 2_200_000_000,
            })

            results = analyze_data(root)

            round_row = next(row for row in results["rounds"] if row["mode"] == "prism_recycle")
            self.assertEqual(round_row["epoch_id"], 91)
            self.assertEqual(round_row["plot_epoch_index"], 4)

    def test_valid_pre_warmup_terminal_is_validated_without_round_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_bundle(
                root,
                "persistent",
                "prism_recycle",
                clean_scan="complete",
                ack_event_seq=14, ack_epoch_id=2,
                coordination_record_start_time_ps=860_000_000,
                coordination_time_ps=950_000_000,
                observer_event_seq=1,
                observer_epoch_start_ps=700_000_000,
                observer_epoch_end_ps=850_000_000,
            )

            results = analyze_data(root)

            self.assertEqual(results["rounds"], [])
            self.assertEqual(results["per_seed_metrics"][0]["completed_rounds"], 0)

    def test_malformed_pre_warmup_terminal_still_fails_evidence_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_bundle(
                root,
                "persistent",
                "prism_recycle",
                clean_scan="missing_slot",
                ack_event_seq=14, ack_epoch_id=2,
                coordination_record_start_time_ps=860_000_000,
                coordination_time_ps=950_000_000,
                observer_event_seq=1,
                observer_epoch_start_ps=700_000_000,
                observer_epoch_end_ps=850_000_000,
            )

            with self.assertRaisesRegex(ValueError, "terminal evidence"):
                analyze_data(root)

    def test_rejects_terminal_round_without_completed_same_flow_observer_epoch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._all_modes(root, "persistent", prism_recycle={
                "coordination_time_ps": 2_200_000_000,
                "observer_event_seq": 10,
                "observer_epoch_start_ps": 2_100_000_000,
                "observer_epoch_end_ps": 3_000_000_000,
            })
            with self.assertRaisesRegex(ValueError, "no completed observer epoch"):
                analyze_data(root)

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

    def test_handoff_markers_use_mapped_plot_epoch_index(self):
        x, y = make_figs._handoff_marker_coordinates(
            [{
                "scenario": "persistent",
                "mode": "full_prism",
                "handoff": "True",
                "epoch_id": "91",
                "plot_epoch_index": "4",
                "floor_ps": "2000000",
            }],
            "persistent",
            "full_prism",
        )

        self.assertEqual(x, [4])
        self.assertEqual(y, [2.0])


if __name__ == "__main__":
    unittest.main()
