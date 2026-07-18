import csv
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from htsim.sim.datacenter.add_motivation.common.trace_schema import _SCHEMAS


HEADERS = {kind: tuple(name for name, _parser in schema) for kind, schema in _SCHEMAS.items()}
MODES = ("prism_recycle", "outcome_recycle")
SEEDS = (13, 14, 15)
BASE_RTT_PS = 10
WINDOW_PS = 4 * BASE_RTT_PS


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


def _manifest(run_id, mode, seed):
    return {
        "run_id": run_id,
        "seed": seed,
        "experiment": "M3_residual_spread_coordination",
        "phase": "outcome_recycle",
        "config": {
            "cc": "prism",
            "load_balancing_algo": "reps_actual",
            "prism_coordination_mode": mode,
            "motivation_ecmp_hash_seed": 13,
            "motivation_ecn_threshold_packets": 211,
            "degraded_links": 2,
            "degraded_capacity_gbps": 25.0,
        },
        "analysis_config": {
            "scenario": "recoverable",
            "seed": seed,
            "degraded_links": 2,
            "degraded_capacity_gbps": 25.0,
        },
    }


def _write_bundle(root, mode, seed, *, complete=True):
    run_id = f"fixture_recoverable_{mode}_s{seed}"
    prefix = root / run_id
    shares = ((30, 70), (20, 80), (10, 90))
    if mode == "prism_recycle":
        shares = ((40, 60), (30, 70), (20, 80))
    ack_rows = []
    event_seq = 1
    for time_ps, (reduced_bytes, healthy_bytes) in zip((300, 340, 380), shares):
        ack_rows.extend((
            _row(
                "ack", run_id=run_id, seed=seed, scenario="recoverable",
                event_seq=event_seq, time_ps=time_ps, flow_id=1, epoch_id=1,
                acked_psn=event_seq, entropy=0, physical_path_id=10,
                raw_rtt_ps=BASE_RTT_PS, base_rtt_ps=BASE_RTT_PS, qdelay_ps=0,
                ecn=0, genuine_sample=1, retransmitted=0, selection_source="recycled",
                newly_acked_bytes=reduced_bytes, new_data_bytes_sent_total=event_seq,
                cwnd_bytes=12000,
            ),
            _row(
                "ack", run_id=run_id, seed=seed, scenario="recoverable",
                event_seq=event_seq + 1, time_ps=time_ps, flow_id=2, epoch_id=1,
                acked_psn=event_seq + 1, entropy=0, physical_path_id=20,
                raw_rtt_ps=BASE_RTT_PS, base_rtt_ps=BASE_RTT_PS, qdelay_ps=0,
                ecn=0, genuine_sample=1, retransmitted=0, selection_source="fresh",
                newly_acked_bytes=healthy_bytes, new_data_bytes_sent_total=event_seq + 1,
                cwnd_bytes=12000,
            ),
        ))
        event_seq += 2
    _write_csv(prefix.with_suffix(".ack.csv"), "ack", ack_rows)
    for kind in ("token", "epoch", "background", "linkmap", "coordination"):
        _write_csv(prefix.with_suffix(f".{kind}.csv"), kind, [])
    _write_csv(prefix.with_suffix(".pathmap.csv"), "pathmap", [
        _row(
            "pathmap", run_id=run_id, flow_id=1, entropy=0, physical_path_id=10,
            resolution_status="resolved", queue_fingerprint="reduced", bottleneck_rate_gbps=25,
            contains_reduced_link=1, ordered_queue_ids="1",
        ),
        _row(
            "pathmap", run_id=run_id, flow_id=2, entropy=0, physical_path_id=20,
            resolution_status="resolved", queue_fingerprint="healthy", bottleneck_rate_gbps=100,
            contains_reduced_link=0, ordered_queue_ids="2",
        ),
    ])
    if mode == "outcome_recycle":
        classified = 100 if complete else 0
        _write_csv(prefix.with_suffix(".outcome.csv"), "outcome", [_row(
            "outcome", run_id=run_id, seed=seed, scenario="recoverable", event_seq=7,
            time_ps=400, flow_id=1, round_id=1, window_ps=WINDOW_PS,
            pre_start_ps=280, pre_end_ps=320,
            pre_classified_bytes=100, pre_harmful_bytes=50, pre_exposure=0.5,
            post1_start_ps=320, post1_end_ps=360,
            post1_classified_bytes=100, post1_harmful_bytes=25, post1_exposure=0.25,
            post2_start_ps=360, post2_end_ps=400,
            post2_classified_bytes=classified, post2_harmful_bytes=0, post2_exposure=0,
        )])
    (root / f"{run_id}.manifest.json").write_text(
        json.dumps(_manifest(run_id, mode, seed)), encoding="ascii"
    )
    return prefix


def _write_locked_bundles(root, *, complete=True):
    for mode in MODES:
        for seed in SEEDS:
            _write_bundle(root, mode, seed, complete=complete)


class OutcomeRecycleAnalysisTests(unittest.TestCase):
    def test_rejects_incomplete_online_outcome(self):
        from htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.analyze_outcome_recycle import (
            analyze_outcome_recycle,
        )

        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_locked_bundles(root, complete=False)

            with self.assertRaisesRegex(ValueError, "post2 classified bytes must be positive"):
                analyze_outcome_recycle(root, root / "aggregate")

    def test_rejects_malformed_online_exposure(self):
        from htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.analyze_outcome_recycle import (
            analyze_outcome_recycle,
        )

        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_locked_bundles(root)
            outcome_path = root / "fixture_recoverable_outcome_recycle_s13.outcome.csv"
            with outcome_path.open(newline="", encoding="ascii") as stream:
                rows = list(csv.DictReader(stream))
            rows[0]["post1_exposure"] = "0.5"
            _write_csv(outcome_path, "outcome", rows)

            with self.assertRaisesRegex(ValueError, "post1 exposure must equal harmful/classified"):
                analyze_outcome_recycle(root, root / "aggregate")

    def test_accepts_exposure_rounded_to_trace_precision(self):
        from htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.analyze_outcome_recycle import (
            analyze_outcome_recycle,
        )

        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_locked_bundles(root)
            outcome_path = root / "fixture_recoverable_outcome_recycle_s13.outcome.csv"
            with outcome_path.open(newline="", encoding="ascii") as stream:
                rows = list(csv.DictReader(stream))
            rows[0]["post1_exposure"] = "0.2500001"
            _write_csv(outcome_path, "outcome", rows)

            analyze_outcome_recycle(root, root / "aggregate")

    def test_rejects_manifest_outside_locked_recoverable_matrix(self):
        from htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.analyze_outcome_recycle import (
            analyze_outcome_recycle,
        )

        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_locked_bundles(root)
            manifest_path = root / "fixture_recoverable_prism_recycle_s13.manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="ascii"))
            manifest["config"]["prism_coordination_mode"] = "full_prism"
            manifest_path.write_text(json.dumps(manifest), encoding="ascii")

            with self.assertRaisesRegex(ValueError, "locked six-case manifest set"):
                analyze_outcome_recycle(root, root / "aggregate")

    def test_rejects_manifest_with_unlocked_ecmp_mapping(self):
        from htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.analyze_outcome_recycle import (
            analyze_outcome_recycle,
        )

        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_locked_bundles(root)
            manifest_path = root / "fixture_recoverable_prism_recycle_s13.manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="ascii"))
            manifest["config"]["motivation_ecmp_hash_seed"] = 14
            manifest_path.write_text(json.dumps(manifest), encoding="ascii")

            with self.assertRaisesRegex(ValueError, "locked six-case manifest set"):
                analyze_outcome_recycle(root, root / "aggregate")

    def test_rejects_manifest_without_the_controlled_pre_ecn_condition(self):
        from htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.analyze_outcome_recycle import (
            analyze_outcome_recycle,
        )

        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_locked_bundles(root)
            manifest_path = root / "fixture_recoverable_prism_recycle_s13.manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="ascii"))
            manifest["config"]["motivation_ecn_threshold_packets"] = 210
            manifest_path.write_text(json.dumps(manifest), encoding="ascii")

            with self.assertRaisesRegex(ValueError, "locked six-case manifest set"):
                analyze_outcome_recycle(root, root / "aggregate")

    def test_writes_resolved_reduced_link_byte_shares_without_baseline_online_exposure(self):
        from htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.analyze_outcome_recycle import (
            analyze_outcome_recycle,
        )

        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_locked_bundles(root)
            results = analyze_outcome_recycle(root, root / "aggregate")

            outcomes = results["outcomes"]
            self.assertEqual(len(outcomes), 9)
            outcome_rows = [
                row for row in outcomes
                if row["mode"] == "outcome_recycle" and row["seed"] == 13
            ]
            self.assertEqual(
                [row["offline_reduced_link_share"] for row in outcome_rows],
                [0.3, 0.2, 0.1],
            )
            self.assertEqual(
                [row["online_exposure"] for row in outcome_rows], [0.5, 0.25, 0.0]
            )
            self.assertTrue((root / "aggregate" / "outcomes.csv").is_file())
            self.assertTrue((root / "aggregate" / "summary.csv").is_file())

    def test_renderer_writes_nonempty_pdf_and_png(self):
        from htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.analyze_outcome_recycle import (
            analyze_outcome_recycle,
        )
        from htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.make_outcome_recycle_fig import (
            render_outcome_recycle_figure,
        )

        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_locked_bundles(root)
            aggregate = root / "aggregate"
            figure_root = root / "figs"
            analyze_outcome_recycle(root, aggregate)
            render_outcome_recycle_figure(aggregate, figure_root)

            self.assertGreater((figure_root / "outcome_recycle.png").stat().st_size, 0)
            self.assertGreater((figure_root / "outcome_recycle.pdf").stat().st_size, 0)
