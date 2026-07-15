import csv
import json
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from htsim.sim.datacenter.add_motivation.expM2_redistribution_progress import (
    analyze as analyze_module,
)
from htsim.sim.datacenter.add_motivation.expM2_redistribution_progress.analyze import (
    CONFIG_FIELDS,
    EvidenceError,
    MIN_VALID_COMPLETED_ROUNDS,
    _apply_coarse_scenario,
    _config,
    _logical_cut_suffix,
    _read_formal_config,
    _read_manifest,
    capacity_witness,
    foreground_offered_load,
    formal_acceptance,
    preflight_base_rtt,
    select_confirmation,
    select_formal,
    write_preflight_outputs,
)
from htsim.sim.datacenter.add_motivation.expM2_redistribution_progress.make_figs import (
    FIGS,
    STEM,
    _CACHE_DIR,
    _representative,
    _valid_seed_deltas,
    selftest as figure_selftest,
)


def capacity_bundle(*, bad_fingerprint=False, delivered_scale=1.0, unresolved=False,
                    real_queue_names=False):
    logical_queues = [f"CS{i}->US0({i})" for i in range(6)]
    queues = [
        f"queue(100000Mb/s,875650bytes){name}" if real_queue_names else name
        for name in logical_queues
    ]
    linkmap = tuple(
        {"queue_name": name, "rate_gbps": 100.0, "queue_id": index}
        for index, name in enumerate(queues)
    )
    pathmap = [
        {
            "flow_id": flow_id, "entropy": entropy,
            "resolution_status": "resolved", "queue_fingerprint": "|".join(queues),
        }
        for flow_id in (0, 1)
        for entropy in range(8)
    ]
    if unresolved:
        pathmap[-1] = {**pathmap[-1], "resolution_status": "resolution_failed"}
    background = []
    for background_id, queue in enumerate(queues[4:]):
        fingerprint = "edge-only" if bad_fingerprint and background_id == 0 else f"edge|{queue}|host"
        delivered = round(6_250_000 * delivered_scale)
        background.extend((
            {
                "background_id": background_id, "operation": "start", "time_ps": 0,
                "configured_rate_gbps": 50.0, "delivered_bytes": 0,
                "queue_fingerprint": fingerprint,
            },
            {
                "background_id": background_id, "operation": "finish",
                "time_ps": 1_000_000_000, "configured_rate_gbps": 50.0,
                "delivered_bytes": delivered, "queue_fingerprint": fingerprint,
            },
        ))
    return SimpleNamespace(
        pathmap=tuple(pathmap), linkmap=linkmap, background=tuple(background),
        epoch=({"flow_id": 0}, {"flow_id": 1}),
    )


def routing_capacity_bundle(flow_queue_indices, *, background_rates=(50,)):
    queues = tuple(f"CS{index}->US0({index})" for index in range(3))
    pathmap = tuple(
        {
            "flow_id": flow_id, "entropy": entropy,
            "resolution_status": "resolved",
            "queue_fingerprint": queues[queue_index],
        }
        for flow_id, queue_indices in sorted(flow_queue_indices.items())
        for entropy, queue_index in enumerate(queue_indices)
    )
    background = []
    for background_id, rate in enumerate(background_rates):
        background.extend((
            {
                "background_id": background_id, "operation": "start", "time_ps": 0,
                "configured_rate_gbps": rate, "delivered_bytes": 0,
                "queue_fingerprint": f"edge|{queues[2]}|host",
            },
            {
                "background_id": background_id, "operation": "finish",
                "time_ps": 1_000_000_000, "configured_rate_gbps": rate,
                "delivered_bytes": rate * 125_000,
                "queue_fingerprint": f"edge|{queues[2]}|host",
            },
        ))
    return SimpleNamespace(
        pathmap=pathmap,
        linkmap=tuple(
            {"queue_name": queue, "rate_gbps": 100, "queue_id": index}
            for index, queue in enumerate(queues)
        ),
        background=tuple(background),
        epoch=tuple({"flow_id": flow_id} for flow_id in sorted(flow_queue_indices)),
    )


def offered_witness(flow_rates):
    demands = tuple(
        (flow_id, Fraction(str(rate))) for flow_id, rate in sorted(flow_rates.items())
    )
    return analyze_module.OfferedLoadWitness(
        valid=True,
        rate_gbps=sum(float(demand) for _flow_id, demand in demands),
        flow_count=len(demands),
        elapsed_ps_min=1,
        elapsed_ps_max=1,
        failed_predicates=(),
        flow_demands_gbps=demands,
    )


def summary(cell, scenario, seed, *, delta=0.2, no_progress=0.8, low_floor=0.9,
            margin=25.0):
    return {
        "cell_id": cell, "scenario": scenario, "foreground_flows": 4,
        "hot_path_groups": 2, "background_utilization": 0.5, "seed": seed,
        "valid_completed_rounds": 4, "all_valid_rounds_match_scenario": 1,
        "median_delta_S": delta, "literal_no_progress_rate": no_progress,
        "no_progress_rate_1us": no_progress, "no_progress_rate_2us": no_progress,
        "no_progress_rate_4us": no_progress, "low_floor_fraction": low_floor,
        "low_floor_high_spread_occupancy": 0.25,
        "min_capacity_margin_gbps": margin,
    }


def round_row(scenario, seed, flow_id, delta, *, valid=True, complete=True):
    return {
        "scenario": scenario, "seed": seed, "flow_id": flow_id,
        "delta_S": delta, "valid_round": int(valid), "complete": int(complete),
        "capacity_classification": scenario, "round_epoch_count": 10,
        "low_floor_epoch_count": 9, "capacity_valid": 1, "offered_load_valid": 1,
    }


def formal_config_rows():
    rows = []
    for scenario in ("recoverable", "persistent"):
        for seed in (13, 14, 15, 16, 17):
            rows.append({
                "cell_id": f"formal-{scenario}", "scenario": scenario,
                "foreground_flows": 4, "hot_path_groups": 2,
                "background_utilization": 0.5, "seed": seed,
            })
    return rows


def coarse_config_rows():
    return [
        {
            "cell_id": f"coarse-f{foreground}-h{hot}-u{int(utilization * 100)}",
            "scenario": "", "foreground_flows": foreground,
            "hot_path_groups": hot, "background_utilization": utilization,
            "seed": 101,
        }
        for foreground in (8, 16, 32)
        for hot in (2, 4, 6)
        for utilization in (0.25, 0.5, 0.75)
    ]


def confirmation_config_rows():
    rows = []
    for scenario, foreground in (("recoverable", 8), ("persistent", 16)):
        for seed in (101, 102, 103):
            rows.append({
                "cell_id": f"confirmation-{scenario}", "scenario": scenario,
                "foreground_flows": foreground, "hot_path_groups": 2,
                "background_utilization": 0.5, "seed": seed,
            })
    return rows


def write_config(path, rows, fields=CONFIG_FIELDS):
    with path.open("w", newline="", encoding="ascii") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_formal_manifests(path, rows, *, legacy_index=None):
    path.mkdir(parents=True, exist_ok=True)
    for index, row in enumerate(rows):
        run_id = f"{row['scenario']}-s{row['seed']}-{index}"
        payload = {
            "phase": "formal", "run_id": run_id, "seed": row["seed"],
            "analysis_config": row,
        }
        if index == legacy_index:
            payload["config"] = payload.pop("analysis_config")
        (path / f"{run_id}.manifest.json").write_text(
            json.dumps(payload), encoding="ascii",
        )


def write_phase_manifests(path, phase, rows):
    path.mkdir(parents=True, exist_ok=True)
    for index, row in enumerate(rows):
        run_id = f"{phase}-{row['cell_id']}-s{row['seed']}-{index}"
        (path / f"{run_id}.manifest.json").write_text(
            json.dumps({
                "phase": phase, "run_id": run_id, "seed": row["seed"],
                "analysis_config": row,
            }),
            encoding="ascii",
        )


class PreflightTests(unittest.TestCase):
    @staticmethod
    def bundle(base_rtts, *, genuine=True):
        return SimpleNamespace(
            run_id="preflight-s101",
            ack=tuple(
                {"genuine_sample": genuine, "base_rtt_ps": value}
                for value in base_rtts
            ),
        )

    def test_accepts_exactly_ninety_five_percent_and_ignores_non_genuine_ack(self):
        bundle = self.bundle([100] * 19 + [101])
        bundle.ack += ({"genuine_sample": False, "base_rtt_ps": 1},)
        report = preflight_base_rtt(bundle, Path("data/preflight/run"))
        self.assertEqual(report["min"], 100)
        self.assertEqual((report["count"], report["matching"]), (20, 19))
        self.assertEqual(report["ratio"], 0.95)
        self.assertEqual(report["trace_prefix"], "data/preflight/run")

    def test_rejects_match_ratio_below_ninety_five_percent(self):
        with self.assertRaisesRegex(EvidenceError, "below 0.95"):
            preflight_base_rtt(
                self.bundle([100] * 18 + [101, 102]), "data/preflight/run"
            )

    def test_requires_positive_genuine_base_rtt(self):
        with self.assertRaisesRegex(EvidenceError, "positive base_rtt_ps"):
            preflight_base_rtt(self.bundle([0, 0, 0]), "data/preflight/run")

    def test_atomically_writes_base_rtt_and_evidence_manifest(self):
        report = preflight_base_rtt(
            self.bundle([1234] * 20), "data/preflight/preflight-s101"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base_rtt = root / "base_rtt_ps.txt"
            manifest = root / "preflight.json"
            write_preflight_outputs(report, base_rtt, manifest)
            self.assertEqual(base_rtt.read_text(encoding="ascii"), "1234\n")
            self.assertEqual(json.loads(manifest.read_text(encoding="ascii")), report)
            self.assertEqual(list(root.glob("*.tmp")), [])


class ManifestAndModeTests(unittest.TestCase):
    @staticmethod
    def config(seed=101):
        return {
            "cell_id": "smoke-f4-h2-u50", "scenario": "recoverable",
            "foreground_flows": 4, "hot_path_groups": 2,
            "background_utilization": 0.5, "seed": seed,
        }

    def test_manifest_requires_analysis_config_and_exact_phase(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.manifest.json"
            path.write_text(json.dumps({
                "phase": "smoke", "run_id": "run", "seed": 101,
                "config": self.config(),
            }), encoding="ascii")
            with self.assertRaisesRegex(ValueError, "missing analysis_config"):
                _read_manifest(path, "smoke")

            path.write_text(json.dumps({
                "phase": "smoke", "run_id": "run", "seed": 101,
                "analysis_config": self.config(),
            }), encoding="ascii")
            metadata, prefix = _read_manifest(path, "smoke")
            self.assertEqual(metadata, self.config())
            self.assertEqual(prefix, path.parent / "run")
            with self.assertRaisesRegex(ValueError, "wrong phase"):
                _read_manifest(path, "coarse")

    def test_smoke_cli_only_aggregates_smoke_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                mock.patch.object(analyze_module, "HERE", root),
                mock.patch.object(
                    analyze_module, "analyze_phase", return_value=([], [], [])
                ) as analyze,
                mock.patch.object(analyze_module, "select_confirmation") as confirm,
                mock.patch.object(analyze_module, "select_formal") as formal,
            ):
                self.assertEqual(analyze_module.main(["--smoke"]), 0)
            analyze.assert_called_once_with("smoke", root / "data" / "smoke")
            confirm.assert_not_called()
            formal.assert_not_called()

    def test_preflight_cli_loads_prefix_and_publishes_both_outputs(self):
        bundle = PreflightTests.bundle([777] * 20)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prefix = root / "preflight-s101"
            base_rtt = root / "base_rtt_ps.txt"
            manifest = root / "preflight.json"
            with mock.patch.object(
                analyze_module, "load_trace_compact", return_value=bundle
            ) as load:
                result = analyze_module.main([
                    "--preflight-prefix", str(prefix),
                    "--base-rtt-output", str(base_rtt),
                    "--preflight-manifest", str(manifest),
                ])
            self.assertEqual(result, 0)
            load.assert_called_once_with(prefix)
            self.assertEqual(base_rtt.read_text(encoding="ascii"), "777\n")
            self.assertEqual(
                json.loads(manifest.read_text(encoding="ascii"))["trace_prefix"],
                str(prefix),
            )

    def test_preflight_manifest_uses_project_relative_trace_prefix(self):
        bundle = PreflightTests.bundle([777] * 20)
        prefix = analyze_module.HERE / "data" / "preflight" / "preflight-s101"
        report = preflight_base_rtt(bundle, prefix)
        self.assertEqual(report["trace_prefix"], "data/preflight/preflight-s101")


class FormalLockingTests(unittest.TestCase):
    def assert_rejected_before_analysis(self, config_rows, manifest_rows, regex,
                                        *, legacy_index=None, fields=CONFIG_FIELDS):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            formal_config = root / "formal.csv"
            phase_dir = root / "formal"
            write_config(formal_config, config_rows, fields)
            write_formal_manifests(
                phase_dir, manifest_rows, legacy_index=legacy_index,
            )
            with (
                mock.patch.object(analyze_module, "FORMAL_CONFIG", formal_config),
                mock.patch.object(analyze_module, "load_trace_compact") as load,
                mock.patch.object(analyze_module, "analyze_bundle") as aggregate,
                mock.patch.object(analyze_module, "formal_acceptance") as acceptance,
                mock.patch.object(analyze_module, "_write_table") as write,
            ):
                with self.assertRaisesRegex(ValueError, regex):
                    analyze_module.analyze_phase("formal", phase_dir)
            load.assert_not_called()
            aggregate.assert_not_called()
            acceptance.assert_not_called()
            write.assert_not_called()

    def test_formal_config_requires_exact_header_and_ten_rows(self):
        rows = formal_config_rows()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "formal.csv"
            write_config(path, rows, CONFIG_FIELDS[:-1])
            with self.assertRaisesRegex(ValueError, "wrong header"):
                _read_formal_config(path)
            write_config(path, rows[:-1])
            with self.assertRaisesRegex(ValueError, "exactly 10 rows"):
                _read_formal_config(path)

    def test_old_manifest_is_rejected_before_any_analysis(self):
        rows = formal_config_rows()
        self.assert_rejected_before_analysis(
            rows, rows, "missing analysis_config", legacy_index=7,
        )

    def test_mixed_formal_cell_is_rejected_before_any_analysis(self):
        rows = formal_config_rows()
        mixed = [dict(row) for row in rows]
        mixed[2]["cell_id"] = "formal-recoverable-other"
        self.assert_rejected_before_analysis(
            mixed, mixed, "must lock one stable cell",
        )

    def test_manifest_differing_from_current_formal_is_rejected_before_analysis(self):
        rows = formal_config_rows()
        stale = [dict(row) for row in rows]
        stale[4]["hot_path_groups"] = 3
        self.assert_rejected_before_analysis(
            rows, stale, "differs from current formal config",
        )

    def test_matching_formal_lock_allows_aggregation_and_acceptance(self):
        rows = formal_config_rows()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            formal_config = root / "formal.csv"
            phase_dir = root / "formal"
            write_config(formal_config, rows)
            write_formal_manifests(phase_dir, rows)

            def aggregate(_bundle, metadata):
                return SimpleNamespace(
                    summary={**metadata, "run_id": f"run-{metadata['seed']}"},
                    rounds=(), epochs=(),
                )

            acceptance_rows = [
                {"scenario": scenario, "accepted": 1, "failed_predicates": ""}
                for scenario in ("recoverable", "persistent")
            ]
            with (
                mock.patch.object(analyze_module, "FORMAL_CONFIG", formal_config),
                mock.patch.object(analyze_module, "load_trace_compact", return_value=object()) as load,
                mock.patch.object(analyze_module, "analyze_bundle", side_effect=aggregate),
                mock.patch.object(
                    analyze_module, "formal_acceptance", return_value=acceptance_rows,
                ) as acceptance,
                mock.patch.object(analyze_module, "_write_table"),
            ):
                summaries, rounds, epochs = analyze_module.analyze_phase(
                    "formal", phase_dir,
                )
            self.assertEqual(len(summaries), 10)
            self.assertEqual((rounds, epochs), ([], []))
            self.assertEqual(load.call_count, 10)
            acceptance.assert_called_once()


class SearchPhaseLockingTests(unittest.TestCase):
    def assert_rejected_before_analysis(
        self, phase, config_rows, manifest_rows, regex,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / f"{phase}.csv"
            phase_dir = root / phase
            write_config(config_path, config_rows)
            write_phase_manifests(phase_dir, phase, manifest_rows)
            constant = (
                "CALIBRATION_CONFIG" if phase == "coarse"
                else "CONFIRMATION_SELECTION"
            )
            with (
                mock.patch.object(analyze_module, constant, config_path),
                mock.patch.object(analyze_module, "load_trace_compact") as load,
                mock.patch.object(analyze_module, "analyze_bundle") as aggregate,
                mock.patch.object(analyze_module, "_write_table") as write,
            ):
                with self.assertRaisesRegex(ValueError, regex):
                    analyze_module.analyze_phase(phase, phase_dir)
            load.assert_not_called()
            aggregate.assert_not_called()
            write.assert_not_called()

    def test_partial_coarse_manifest_set_is_rejected(self):
        rows = coarse_config_rows()
        self.assert_rejected_before_analysis(
            "coarse", rows, rows[:-1], "expected 27, found 26",
        )

    def test_extra_coarse_manifest_is_rejected(self):
        rows = coarse_config_rows()
        extra = {
            **rows[-1], "cell_id": "coarse-extra", "foreground_flows": 64,
        }
        self.assert_rejected_before_analysis(
            "coarse", rows, [*rows, extra], "expected 27, found 28",
        )

    def test_partial_confirmation_manifest_set_is_rejected(self):
        rows = confirmation_config_rows()
        self.assert_rejected_before_analysis(
            "confirmation", rows, rows[:-1], "expected 6, found 5",
        )

    def test_stale_manifest_parameters_are_rejected(self):
        rows = confirmation_config_rows()
        stale = [dict(row) for row in rows]
        stale[2]["hot_path_groups"] = 4
        self.assert_rejected_before_analysis(
            "confirmation", rows, stale, "differs from current confirmation config",
        )

    def test_exact_coarse_and_confirmation_sets_allow_analysis(self):
        cases = (
            ("coarse", coarse_config_rows(), "CALIBRATION_CONFIG"),
            (
                "confirmation", confirmation_config_rows(),
                "CONFIRMATION_SELECTION",
            ),
        )
        for phase, rows, constant in cases:
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                config_path = root / f"{phase}.csv"
                phase_dir = root / phase
                write_config(config_path, rows)
                write_phase_manifests(phase_dir, phase, reversed(rows))

                def aggregate(_bundle, metadata):
                    return SimpleNamespace(
                        summary={**metadata, "run_id": metadata["cell_id"]},
                        rounds=(), epochs=(),
                    )

                with (
                    mock.patch.object(analyze_module, constant, config_path),
                    mock.patch.object(
                        analyze_module, "load_trace_compact", return_value=object(),
                    ) as load,
                    mock.patch.object(
                        analyze_module, "analyze_bundle", side_effect=aggregate,
                    ),
                    mock.patch.object(analyze_module, "_write_table"),
                ):
                    summaries, rounds, epochs = analyze_module.analyze_phase(
                        phase, phase_dir,
                    )
                self.assertEqual(len(summaries), len(rows))
                self.assertEqual((rounds, epochs), ([], []))
                self.assertEqual(load.call_count, len(rows))


class CapacityWitnessTests(unittest.TestCase):
    def test_canonical_and_real_queue_names_preserve_exact_capacity(self):
        for real_queue_names in (False, True):
            with self.subTest(real_queue_names=real_queue_names):
                witness = capacity_witness(
                    capacity_bundle(real_queue_names=real_queue_names),
                    100, 900_000_000,
                )
                self.assertEqual(witness.c_healthy_gbps, 400)
                self.assertEqual(witness.c_hot_residual_gbps, 100)
                self.assertEqual(witness.c_effective_residual_gbps, 500)
                self.assertEqual(witness.classify(350), "recoverable")
                self.assertEqual(witness.classify(450), "persistent")
                self.assertEqual(witness.classify(400), "invalid")
                self.assertEqual(witness.classify(500), "invalid")

    def test_cut_queue_helper_requires_one_logical_match_at_name_suffix(self):
        logical = "CS0->US0(0)"
        real = "queue(100000Mb/s,875650bytes)CS0->US0(0)"
        self.assertEqual(_logical_cut_suffix(logical), logical)
        self.assertEqual(_logical_cut_suffix(real), logical)
        self.assertIsNone(_logical_cut_suffix(f"{logical}-middle"))
        self.assertIsNone(_logical_cut_suffix(f"{logical}{real}"))

    def test_background_cut_must_match_full_foreground_queue_name(self):
        bundle = capacity_bundle(real_queue_names=True)
        rows = []
        for row in bundle.background:
            fingerprint = row["queue_fingerprint"].replace(
                "queue(100000Mb/s,875650bytes)", "",
            )
            rows.append({**row, "queue_fingerprint": fingerprint})
        bundle.background = tuple(rows)
        with self.assertRaisesRegex(EvidenceError, "absent from foreground cut"):
            capacity_witness(bundle, 100, 900_000_000)

    def test_requires_exactly_one_background_cut_queue(self):
        with self.assertRaisesRegex(EvidenceError, "exactly one target-pod cut queue"):
            capacity_witness(capacity_bundle(bad_fingerprint=True), 100, 900_000_000)

    def test_rejects_partially_resolved_foreground_pathmap(self):
        with self.assertRaisesRegex(EvidenceError, "foreground pathmap contains unresolved"):
            capacity_witness(capacity_bundle(unresolved=True), 100, 900_000_000)

    def test_requires_each_flow_to_cover_entropy_zero_through_seven_once(self):
        for case in ("missing", "duplicate", "extra"):
            with self.subTest(case=case):
                bundle = capacity_bundle()
                rows = list(bundle.pathmap)
                if case == "missing":
                    rows = [
                        row for row in rows
                        if not (row["flow_id"] == 0 and row["entropy"] == 7)
                    ]
                elif case == "duplicate":
                    rows.append(dict(rows[0]))
                else:
                    rows.append({**rows[0], "entropy": 8})
                bundle.pathmap = tuple(rows)
                with self.assertRaisesRegex(
                    EvidenceError, "entropy 0 through 7 exactly once",
                ):
                    capacity_witness(bundle, 100, 900_000_000)

    def test_rejects_a_foreground_flow_missing_entirely_from_pathmap(self):
        bundle = capacity_bundle()
        bundle.pathmap = tuple(
            row for row in bundle.pathmap if row["flow_id"] != 1
        )
        with self.assertRaisesRegex(
            EvidenceError, "flow coverage differs from foreground epoch flows",
        ):
            capacity_witness(bundle, 100, 900_000_000)

    def test_rejects_delivery_outside_five_percent(self):
        with self.assertRaisesRegex(EvidenceError, "more than 5%"):
            capacity_witness(
                capacity_bundle(delivered_scale=0.94), 100, 900_000_000
            )


class RoutingFeasibilityTests(unittest.TestCase):
    @staticmethod
    def classify(flow_queue_indices, flow_rates, *, background_rates=(50,)):
        capacity = capacity_witness(
            routing_capacity_bundle(
                flow_queue_indices, background_rates=background_rates,
            ),
            100,
            900_000_000,
        )
        classification, routing, failures = (
            analyze_module._classify_capacity_and_routing(
                capacity, offered_witness(flow_rates),
            )
        )
        return capacity, classification, routing, failures

    def test_duplicate_entropy_edges_do_not_duplicate_queue_capacity(self):
        capacity, classification, routing, failures = self.classify(
            {0: (0, 0, 0, 0, 0, 0, 0, 2), 1: (1, 1, 1, 1, 1, 1, 1, 2)},
            {0: 150, 1: 0},
            background_rates=(25, 25),
        )
        self.assertEqual(capacity.c_effective_residual_gbps, 250)
        self.assertEqual(capacity.flow_queue_edge_count, 4)
        self.assertEqual(capacity.unique_cut_queue_count, 3)
        self.assertEqual(capacity.duplicate_entropy_edge_count, 12)
        self.assertEqual(routing.healthy_maxflow_gbps, 100)
        self.assertEqual(classification, "invalid")
        self.assertEqual(failures, ("healthy_routing_infeasible",))

    def test_shared_queue_capacity_is_competed_across_flows(self):
        _capacity, classification, routing, failures = self.classify(
            {
                0: (0, 0, 0, 0, 0, 0, 0, 2),
                1: (0, 0, 0, 0, 0, 0, 0, 2),
                2: (1, 1, 1, 1, 1, 1, 1, 2),
            },
            {0: 60, 1: 60, 2: 0},
        )
        self.assertEqual(routing.healthy_maxflow_gbps, 100)
        self.assertEqual(routing.healthy_deficit_gbps, 20)
        self.assertEqual(classification, "invalid")
        self.assertEqual(failures, ("healthy_routing_infeasible",))

    def test_aggregate_healthy_capacity_does_not_prove_routing_feasibility(self):
        capacity, classification, routing, failures = self.classify(
            {0: (0, 0, 0, 0, 0, 0, 0, 2), 1: (1, 1, 1, 1, 1, 1, 1, 2)},
            {0: 150, 1: 10},
        )
        self.assertEqual(capacity.classify(160), "recoverable")
        self.assertEqual(routing.healthy_maxflow_gbps, 110)
        self.assertFalse(routing.healthy_feasible)
        self.assertEqual(classification, "invalid")
        self.assertEqual(failures, ("healthy_routing_infeasible",))

    def test_persistent_requires_both_maxflow_predicates(self):
        capacity, classification, routing, failures = self.classify(
            {0: (0, 0, 0, 0, 0, 0, 0, 2), 1: (1, 1, 1, 1, 1, 1, 1, 2)},
            {0: 120, 1: 100},
        )
        self.assertEqual(capacity.classify(220), "persistent")
        self.assertEqual(routing.healthy_maxflow_gbps, 200)
        self.assertEqual(routing.effective_maxflow_gbps, 220)
        self.assertFalse(routing.healthy_feasible)
        self.assertTrue(routing.effective_feasible)
        self.assertEqual(routing.healthy_deficit_gbps, 20)
        self.assertEqual(routing.effective_deficit_gbps, 0)
        self.assertEqual(classification, "persistent")
        self.assertEqual(failures, ())

    def test_persistent_aggregate_is_invalid_when_effective_routing_fails(self):
        capacity, classification, routing, failures = self.classify(
            {0: (0, 0, 0, 0, 0, 0, 0, 2), 1: (1, 1, 1, 1, 1, 1, 1, 2)},
            {0: 160, 1: 60},
        )
        self.assertEqual(capacity.classify(220), "persistent")
        self.assertEqual(routing.effective_maxflow_gbps, 210)
        self.assertFalse(routing.effective_feasible)
        self.assertEqual(routing.effective_deficit_gbps, 10)
        self.assertEqual(classification, "invalid")
        self.assertEqual(failures, ("effective_routing_infeasible",))

    def test_pathmap_order_does_not_change_capacity_or_routing_witness(self):
        mappings = {
            0: (0, 2, 0, 2, 0, 2, 0, 2),
            1: (1, 2, 1, 2, 1, 2, 1, 2),
        }
        bundle = routing_capacity_bundle(mappings)
        reversed_bundle = routing_capacity_bundle(mappings)
        reversed_bundle.pathmap = tuple(reversed(reversed_bundle.pathmap))
        first = capacity_witness(bundle, 100, 900_000_000)
        second = capacity_witness(reversed_bundle, 100, 900_000_000)
        offered = offered_witness({0: 120, 1: 100})
        self.assertEqual(first, second)
        self.assertEqual(
            analyze_module._routing_witness(first, offered),
            analyze_module._routing_witness(second, offered),
        )

    def test_strict_aggregate_equalities_remain_invalid(self):
        mappings = {
            0: (0, 0, 0, 0, 0, 0, 0, 2),
            1: (1, 1, 1, 1, 1, 1, 1, 2),
        }
        for flow_rates, boundary in (({0: 100, 1: 100}, 200),
                                     ({0: 125, 1: 125}, 250)):
            with self.subTest(boundary=boundary):
                capacity, classification, _routing, failures = self.classify(
                    mappings, flow_rates,
                )
                self.assertEqual(capacity.classify(boundary), "invalid")
                self.assertEqual(classification, "invalid")
                self.assertEqual(failures, ())


class OfferedLoadTests(unittest.TestCase):
    def test_uses_only_bracketing_epoch_send_counters(self):
        bundle = SimpleNamespace(epoch=(
            {"flow_id": 1, "end_ps": 100, "event_seq": 1, "new_data_bytes_sent_total": 10},
            {"flow_id": 1, "end_ps": 1_100, "event_seq": 2, "new_data_bytes_sent_total": 1_010},
            {"flow_id": 2, "end_ps": 100, "event_seq": 3, "new_data_bytes_sent_total": 20},
            {"flow_id": 2, "end_ps": 1_100, "event_seq": 4, "new_data_bytes_sent_total": 1_020},
        ))
        witness = foreground_offered_load(bundle, 100, 1_100)
        self.assertTrue(witness.valid)
        self.assertEqual(witness.rate_gbps, 16_000)
        self.assertEqual(
            witness.flow_demands_gbps,
            ((1, Fraction(8_000)), (2, Fraction(8_000))),
        )
        self.assertEqual((witness.elapsed_ps_min, witness.elapsed_ps_max), (1_000, 1_000))

    def test_invalid_counter_is_not_coerced_to_throughput(self):
        bundle = SimpleNamespace(epoch=(
            {"flow_id": 1, "end_ps": 100, "event_seq": 1, "new_data_bytes_sent_total": 20},
            {"flow_id": 1, "end_ps": 200, "event_seq": 2, "new_data_bytes_sent_total": 10},
        ))
        witness = foreground_offered_load(bundle, 100, 200)
        self.assertFalse(witness.valid)
        self.assertIn("decreasing_new_data_counter", witness.failed_predicates[0])

    def test_bisect_index_matches_public_api_results(self):
        bundle = SimpleNamespace(epoch=(
            {"flow_id": 1, "end_ps": 100, "event_seq": 2,
             "new_data_bytes_sent_total": 20},
            {"flow_id": 1, "end_ps": 1_100, "event_seq": 4,
             "new_data_bytes_sent_total": 1_020},
            {"flow_id": 1, "end_ps": 100, "event_seq": 1,
             "new_data_bytes_sent_total": 10},
            {"flow_id": 2, "end_ps": 100, "event_seq": 3,
             "new_data_bytes_sent_total": 30},
            {"flow_id": 2, "end_ps": 1_100, "event_seq": 5,
             "new_data_bytes_sent_total": 1_030},
        ))
        index = analyze_module._build_epoch_index(bundle.epoch)
        cases = (
            (100, 1_100, None),
            (99, 1_100, None),
            (100, 1_101, None),
            (100, 1_100, (1, 3)),
            (200, 100, None),
        )
        for start_ps, end_ps, flow_ids in cases:
            with self.subTest(
                start_ps=start_ps, end_ps=end_ps, flow_ids=flow_ids,
            ):
                expected = foreground_offered_load(
                    bundle, start_ps, end_ps, flow_ids,
                )
                actual = analyze_module._foreground_offered_load_indexed(
                    index, start_ps, end_ps, flow_ids,
                )
                self.assertEqual(actual, expected)

    def test_latest_snapshot_bound_uses_background_coverage_end(self):
        evidence_end = 150
        coverage_end = 200
        within_coverage = analyze_module._build_epoch_index((
            {"flow_id": 1, "end_ps": 100, "event_seq": 1,
             "new_data_bytes_sent_total": 10},
            {"flow_id": 1, "end_ps": 180, "event_seq": 2,
             "new_data_bytes_sent_total": 90},
        ))
        witness = analyze_module._foreground_offered_load_indexed(
            within_coverage, 100, evidence_end, latest_snapshot_ps=coverage_end,
        )
        self.assertTrue(witness.valid)
        self.assertEqual((witness.elapsed_ps_min, witness.elapsed_ps_max), (80, 80))

        beyond_coverage = analyze_module._build_epoch_index((
            {"flow_id": 1, "end_ps": 100, "event_seq": 1,
             "new_data_bytes_sent_total": 10},
            {"flow_id": 1, "end_ps": 201, "event_seq": 2,
             "new_data_bytes_sent_total": 90},
        ))
        witness = analyze_module._foreground_offered_load_indexed(
            beyond_coverage, 100, evidence_end, latest_snapshot_ps=coverage_end,
        )
        self.assertFalse(witness.valid)
        self.assertEqual(
            witness.failed_predicates, ("flow_1:missing_bracketing_epoch",),
        )


class IndexedAnalyzeBundleTests(unittest.TestCase):
    @staticmethod
    def epoch(flow_id, event_seq, end_ps, sent):
        return {
            "flow_id": flow_id, "event_seq": event_seq,
            "start_ps": max(0, end_ps - 100), "end_ps": end_ps,
            "new_data_bytes_sent_total": sent,
            "raw_floor_ps": 10_000_000, "raw_spread_ps": 20_000_000,
            "cwnd_bytes": 10_000, "actual_region": "hold",
            "entropy_coverage": 8, "physical_path_coverage": 8,
        }

    @staticmethod
    def shadow(flow_id, round_index, start_event_seq, end_event_seq, end_ps,
               *, start_ps=100):
        return SimpleNamespace(
            flow_id=flow_id, round_index=round_index,
            start_event_seq=start_event_seq, end_event_seq=end_event_seq,
            start_ps=start_ps, end_ps=end_ps, complete=True, censored=False,
            censor_reason=None, s_ref_ps=20_000_000, s_end_ps=19_000_000,
            delta_s=1_000_000, no_progress=False, fifo_depth_at_start=3,
            replacement_count=0, seeded_pass_count=3, seeded_fail_count=0,
            admission_pass_count=0, admission_fail_count=0,
        )

    def test_analyze_builds_one_epoch_index_and_one_capacity_witness(self):
        bundle = capacity_bundle()
        late_end = 1_000_000_001
        bundle.run_id = "indexed-s101"
        bundle.ack = (
            {"flow_id": 0, "event_seq": 10, "time_ps": 99,
             "qdelay_ps": 1, "genuine_sample": True},
            {"flow_id": 0, "event_seq": 11, "time_ps": 100,
             "qdelay_ps": 2, "genuine_sample": True},
            {"flow_id": 0, "event_seq": 12, "time_ps": 150,
             "qdelay_ps": 999, "genuine_sample": False},
            {"flow_id": 0, "event_seq": 13, "time_ps": 200,
             "qdelay_ps": 4, "genuine_sample": True},
            {"flow_id": 0, "event_seq": 14, "time_ps": 201,
             "qdelay_ps": 8, "genuine_sample": True},
            {"flow_id": 1, "event_seq": 15, "time_ps": 100,
             "qdelay_ps": 3, "genuine_sample": True},
            {"flow_id": 1, "event_seq": 16, "time_ps": 200,
             "qdelay_ps": 5, "genuine_sample": True},
        )
        bundle.epoch = (
            self.epoch(0, 1, 100, 0), self.epoch(0, 2, 200, 1),
            self.epoch(0, 3, late_end, 2),
            self.epoch(1, 4, 100, 0), self.epoch(1, 5, 200, 1),
            self.epoch(1, 6, late_end, 2),
        )
        shadows = (
            self.shadow(0, 0, 1, 2, 200),
            self.shadow(1, 0, 4, 5, 200),
            self.shadow(0, 1, 1, 3, late_end),
        )
        config = {
            "cell_id": "indexed", "scenario": "recoverable",
            "foreground_flows": 2, "hot_path_groups": 2,
            "background_utilization": 0.5, "seed": 101,
        }
        direct_capacity = capacity_witness(bundle, 100, 200)
        with (
            mock.patch.object(analyze_module, "replay_shadow", return_value=shadows),
            mock.patch.object(
                analyze_module, "_build_epoch_index",
                wraps=analyze_module._build_epoch_index,
            ) as build_index,
            mock.patch.object(
                analyze_module, "capacity_witness",
                wraps=analyze_module.capacity_witness,
            ) as capacity,
            mock.patch.object(
                analyze_module, "_build_genuine_ack_index",
                wraps=analyze_module._build_genuine_ack_index,
            ) as build_ack_index,
        ):
            result = analyze_module.analyze_bundle(bundle, config)

        self.assertEqual(build_index.call_count, 1)
        self.assertEqual(build_ack_index.call_count, 1)
        self.assertEqual(capacity.call_count, 1)
        self.assertEqual(len(result.rounds), 3)
        for row in result.rounds[:2]:
            self.assertEqual(row["capacity_valid"], 1)
            self.assertEqual(row["C_healthy_gbps"], direct_capacity.c_healthy_gbps)
            self.assertEqual(
                row["C_hot_residual_gbps"], direct_capacity.c_hot_residual_gbps,
            )
            self.assertEqual(
                row["C_effective_residual_gbps"],
                direct_capacity.c_effective_residual_gbps,
            )
            self.assertEqual(row["healthy_maxflow_gbps"], 160)
            self.assertEqual(row["effective_maxflow_gbps"], 160)
            self.assertEqual(row["healthy_feasible"], 1)
            self.assertEqual(row["effective_feasible"], 1)
            self.assertEqual(row["healthy_deficit_gbps"], 0)
            self.assertEqual(row["effective_deficit_gbps"], 0)
            self.assertEqual(row["flow_queue_edge_count"], 12)
            self.assertEqual(row["unique_cut_queue_count"], 6)
            self.assertEqual(row["duplicate_entropy_edge_count"], 84)
        self.assertEqual(result.rounds[0]["mean_qdelay_ps"], 3.0)
        self.assertEqual(result.rounds[1]["mean_qdelay_ps"], 4.0)
        self.assertEqual(result.rounds[0]["round_epoch_count"], 1)
        self.assertEqual(result.rounds[0]["hold_epoch_count"], 1)
        self.assertEqual(result.rounds[0]["hold_duration_ps"], 100)
        self.assertEqual(
            [row["event_seq"] for row in result.epochs if row["round_index"] == 0
             and row["flow_id"] == 0],
            [2],
        )
        self.assertEqual(result.rounds[2]["capacity_valid"], 1)
        self.assertEqual(result.rounds[2]["complete"], 0)
        self.assertEqual(result.rounds[2]["censored"], 1)
        self.assertEqual(
            result.rounds[2]["censor_reason"], "observation_end_right_censored",
        )
        self.assertEqual(result.rounds[2]["S_end_ps"], "")
        self.assertEqual(result.rounds[2]["delta_S"], "")
        self.assertEqual(result.rounds[2]["literal_no_progress"], "")
        self.assertNotIn(
            "background_id 0 does not cover evaluated interval",
            result.rounds[2]["failed_predicates"],
        )

    def test_observation_window_excludes_tails_and_right_censors_crossing_round(self):
        observation_start = 20_000
        observation_end = 120_000
        bundle = capacity_bundle()
        bundle.run_id = "observation-s101"
        bundle.background = tuple(
            {
                **row,
                "time_ps": (
                    observation_start if row["operation"] == "start"
                    else observation_end
                ),
                "delivered_bytes": 0 if row["operation"] == "start" else 625,
            }
            for row in bundle.background
        )
        bundle.epoch = (
            self.epoch(0, 0, 10_000, 0),
            self.epoch(0, 1, 30_000, 1),
            self.epoch(0, 2, 40_000, 2),
            self.epoch(0, 3, 110_000, 3),
            self.epoch(0, 4, 120_000, 4),
            self.epoch(0, 5, 130_000, 5),
            self.epoch(1, 6, 30_000, 1),
            self.epoch(1, 7, 40_000, 2),
            self.epoch(1, 8, 120_000, 3),
            self.epoch(1, 9, 130_000, 4),
        )
        bundle.ack = (
            {"flow_id": 0, "event_seq": 20, "time_ps": 35_000,
             "qdelay_ps": 1, "genuine_sample": True},
            {"flow_id": 0, "event_seq": 21, "time_ps": 115_000,
             "qdelay_ps": 2, "genuine_sample": True},
            {"flow_id": 0, "event_seq": 22, "time_ps": 125_000,
             "qdelay_ps": 999, "genuine_sample": True},
        )
        shadows = (
            self.shadow(0, -1, 0, 1, 30_000, start_ps=10_000),
            self.shadow(0, 0, 1, 2, 40_000, start_ps=30_000),
            self.shadow(1, 0, 6, 7, 40_000, start_ps=30_000),
            self.shadow(0, 1, 3, 5, 130_000, start_ps=110_000),
            self.shadow(1, 1, 8, 9, 130_000, start_ps=120_000),
        )
        config = {
            "cell_id": "observation", "scenario": "",
            "foreground_flows": 2, "hot_path_groups": 2,
            "background_utilization": 0.5, "seed": 101,
        }
        with mock.patch.object(
            analyze_module, "replay_shadow", return_value=shadows,
        ) as replay:
            result = analyze_module.analyze_bundle(bundle, config)

        replay_bundle = replay.call_args.args[0]
        self.assertTrue(
            all(row["end_ps"] <= observation_end for row in replay_bundle.epoch)
        )
        self.assertTrue(
            all(row["time_ps"] <= observation_end for row in replay_bundle.ack)
        )
        self.assertEqual(len(result.rounds), 3)
        self.assertEqual(result.summary["scenario"], "recoverable")
        self.assertEqual(result.summary["completed_rounds"], 2)
        self.assertEqual(result.summary["valid_completed_rounds"], 2)
        self.assertEqual(result.summary["censored_rounds"], 1)
        self.assertEqual(
            {(row["flow_id"], row["round_index"]) for row in result.rounds},
            {(0, 0), (1, 0), (0, 1)},
        )
        crossing = next(row for row in result.rounds if row["round_index"] == 1)
        self.assertEqual(crossing["complete"], 0)
        self.assertEqual(crossing["censored"], 1)
        self.assertEqual(crossing["censor_reason"], "observation_end_right_censored")
        self.assertEqual(crossing["S_end_ps"], "")
        self.assertEqual(crossing["delta_S"], "")
        self.assertEqual(crossing["literal_no_progress"], "")
        self.assertEqual(crossing["mean_qdelay_ps"], 2.0)
        self.assertTrue(
            all(row["event_time_ps"] <= observation_end for row in result.epochs)
        )
        self.assertNotIn(5, {row["event_seq"] for row in result.epochs})

    def test_evidence_end_uses_last_common_foreground_snapshot(self):
        coverage_start = 20_000
        coverage_end = 120_000
        evidence_end = 100_000
        bundle = capacity_bundle()
        bundle.run_id = "common-evidence-s101"
        bundle.background = tuple(
            {
                **row,
                "time_ps": (
                    coverage_start if row["operation"] == "start" else coverage_end
                ),
                "delivered_bytes": 0 if row["operation"] == "start" else 625,
            }
            for row in bundle.background
        )
        bundle.epoch = (
            self.epoch(0, 0, 30_000, 0),
            self.epoch(0, 1, 80_000, 1),
            self.epoch(0, 2, 90_000, 2),
            self.epoch(0, 3, 100_000, 3),
            self.epoch(1, 6, 30_000, 0),
            self.epoch(1, 7, 80_000, 1),
            self.epoch(1, 8, 110_000, 2),
            self.epoch(1, 9, 120_000, 3),
        )
        bundle.ack = (
            {"flow_id": 0, "event_seq": 20, "time_ps": 95_000,
             "qdelay_ps": 2, "genuine_sample": True},
            {"flow_id": 0, "event_seq": 21, "time_ps": 105_000,
             "qdelay_ps": 999, "genuine_sample": True},
        )
        shadows = (
            self.shadow(0, 0, 1, 2, 90_000, start_ps=80_000),
            self.shadow(1, 1, 7, 8, 110_000, start_ps=80_000),
        )
        config = {
            "cell_id": "common-evidence", "scenario": "",
            "foreground_flows": 2, "hot_path_groups": 2,
            "background_utilization": 0.5, "seed": 101,
        }
        with (
            mock.patch.object(
                analyze_module, "replay_shadow", return_value=shadows,
            ) as replay,
            mock.patch.object(
                analyze_module, "capacity_witness",
                wraps=analyze_module.capacity_witness,
            ) as capacity,
        ):
            result = analyze_module.analyze_bundle(bundle, config)

        replay_bundle = replay.call_args.args[0]
        self.assertEqual(
            max(row["end_ps"] for row in replay_bundle.epoch), evidence_end,
        )
        self.assertEqual(capacity.call_args.args[1:], (coverage_start, coverage_end))
        self.assertEqual(len(result.rounds), 2)
        self.assertEqual(result.summary["scenario"], "recoverable")
        self.assertEqual(result.summary["completed_rounds"], 1)
        self.assertEqual(result.summary["valid_completed_rounds"], 1)
        completed = next(row for row in result.rounds if row["round_index"] == 0)
        self.assertEqual(completed["offered_load_valid"], 1)
        self.assertEqual(completed["offered_elapsed_ps_min"], 10_000)
        self.assertEqual(completed["offered_elapsed_ps_max"], 30_000)
        crossing = next(row for row in result.rounds if row["round_index"] == 1)
        self.assertEqual(crossing["complete"], 0)
        self.assertEqual(crossing["censored"], 1)
        self.assertEqual(crossing["censor_reason"], "observation_end_right_censored")
        self.assertEqual(crossing["offered_load_valid"], 1)
        self.assertEqual(crossing["S_end_ps"], "")
        self.assertEqual(crossing["delta_S"], "")
        self.assertEqual(crossing["literal_no_progress"], "")
        self.assertNotIn(8, {row["event_seq"] for row in result.epochs})

    def test_ack_prefix_index_matches_closed_interval_fmean_semantics(self):
        acknowledgements = (
            {"flow_id": 0, "event_seq": 1, "time_ps": 99,
             "qdelay_ps": 7, "genuine_sample": True},
            {"flow_id": 0, "event_seq": 2, "time_ps": 100,
             "qdelay_ps": 2**53 + 1, "genuine_sample": True},
            {"flow_id": 0, "event_seq": 3, "time_ps": 150,
             "qdelay_ps": 500, "genuine_sample": False},
            {"flow_id": 0, "event_seq": 4, "time_ps": 200,
             "qdelay_ps": -(2**53), "genuine_sample": True},
            {"flow_id": 0, "event_seq": 5, "time_ps": 200,
             "qdelay_ps": 3, "genuine_sample": True},
            {"flow_id": 1, "event_seq": 6, "time_ps": 100,
             "qdelay_ps": 11, "genuine_sample": True},
        )
        index = analyze_module._build_genuine_ack_index(acknowledgements)
        for flow_id, start_ps, end_ps in (
            (0, 100, 200),
            (0, 99, 100),
            (0, 101, 199),
            (1, 100, 100),
            (2, 0, 1_000),
        ):
            with self.subTest(
                flow_id=flow_id, start_ps=start_ps, end_ps=end_ps,
            ):
                values = [
                    ack["qdelay_ps"] for ack in acknowledgements
                    if ack["flow_id"] == flow_id and ack["genuine_sample"]
                    and start_ps <= ack["time_ps"] <= end_ps
                ]
                expected = analyze_module._mean(values) if values else None
                self.assertEqual(
                    analyze_module._indexed_mean_qdelay(
                        index, flow_id, start_ps, end_ps,
                    ),
                    expected,
                )


class SelectionAndAcceptanceTests(unittest.TestCase):
    def test_empty_coarse_scenario_is_inferred_or_explicitly_invalid(self):
        metadata = _config({
            "cell_id": "coarse", "scenario": "", "foreground_flows": 4,
            "hot_path_groups": 2, "background_utilization": 0.5, "seed": 101,
        })
        rounds = [round_row("", 101, flow, 0.1) for flow in range(3)]
        for row in rounds:
            row["capacity_classification"] = "recoverable"
            row["failed_predicates"] = ""
        epochs = [{"scenario": ""}]
        _apply_coarse_scenario(metadata, rounds, epochs)
        self.assertEqual(metadata["scenario"], "recoverable")
        self.assertEqual({row["scenario"] for row in rounds}, {"recoverable"})
        self.assertEqual(epochs[0]["scenario"], "recoverable")

        mixed_metadata = {**metadata, "scenario": ""}
        mixed_rounds = [dict(row) for row in rounds]
        mixed_rounds[0]["capacity_classification"] = "persistent"
        mixed_epochs = [{"scenario": ""}]
        _apply_coarse_scenario(mixed_metadata, mixed_rounds, mixed_epochs)
        self.assertEqual(mixed_metadata["scenario"], "invalid")
        self.assertEqual({row["scenario"] for row in mixed_rounds}, {"invalid"})
        self.assertTrue(all(not row["valid_round"] for row in mixed_rounds))
        self.assertIn("mixed_capacity_classification", mixed_rounds[0]["failed_predicates"])

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.manifest.json"
            path.write_text(json.dumps({
                "phase": "confirmation", "run_id": "run", "seed": 101,
                "analysis_config": {
                    "cell_id": "coarse", "scenario": "", "foreground_flows": 4,
                    "hot_path_groups": 2, "background_utilization": 0.5, "seed": 101,
                },
            }), encoding="ascii")
            with self.assertRaisesRegex(ValueError, "must lock scenario"):
                _read_manifest(path, "confirmation")

    def test_selection_is_deterministic_and_formal_is_confirmation_only(self):
        coarse = []
        for scenario in ("recoverable", "persistent"):
            coarse.extend(summary(f"{scenario}-{index}", scenario, 101, margin=30-index)
                          for index in range(4))
        with tempfile.TemporaryDirectory() as directory:
            confirmation_path = Path(directory) / "confirmation.csv"
            selected = select_confirmation(coarse, confirmation_path)
            self.assertEqual(len(selected), 18)
            expected_confirmation = (
                ",".join(CONFIG_FIELDS) + "\n"
                + "".join(
                    ",".join(str(row[field]) for field in CONFIG_FIELDS) + "\n"
                    for row in selected
                )
            ).encode("ascii")
            self.assertEqual(confirmation_path.read_bytes(), expected_confirmation)
            with confirmation_path.open(newline="", encoding="ascii") as stream:
                self.assertEqual(tuple(csv.DictReader(stream)), tuple(
                    {key: str(value) for key, value in row.items()} for row in selected
                ))
            self.assertEqual(select_confirmation([], confirmation_path), [])
            self.assertEqual(
                confirmation_path.read_bytes(),
                (",".join(CONFIG_FIELDS) + "\n").encode("ascii"),
            )

            confirmed = []
            for scenario in ("recoverable", "persistent"):
                for seed in (101, 102, 103):
                    confirmed.append(summary(f"{scenario}-0", scenario, seed))
            formal_path = Path(directory) / "formal.csv"
            formal = select_formal(confirmed, formal_path)
            self.assertEqual(len(formal), 10)
            expected_formal = (
                ",".join(CONFIG_FIELDS) + "\n"
                + "".join(
                    ",".join(str(row[field]) for field in CONFIG_FIELDS) + "\n"
                    for row in formal
                )
            ).encode("ascii")
            self.assertEqual(formal_path.read_bytes(), expected_formal)
            with formal_path.open(newline="", encoding="ascii") as stream:
                reader = csv.DictReader(stream)
                self.assertEqual(tuple(reader.fieldnames), CONFIG_FIELDS)
                self.assertEqual({int(row["seed"]) for row in reader}, {13, 14, 15, 16, 17})

            failed = [row for row in confirmed if row["scenario"] == "recoverable"]
            self.assertEqual(select_formal(failed, formal_path), [])
            self.assertEqual(
                formal_path.read_bytes(),
                (",".join(CONFIG_FIELDS) + "\n").encode("ascii"),
            )
            with formal_path.open(newline="", encoding="ascii") as stream:
                reader = csv.DictReader(stream)
                self.assertEqual(tuple(reader.fieldnames), CONFIG_FIELDS)
                self.assertEqual(list(reader), [])

    def test_selection_rejects_sparse_or_zero_occupancy_candidates(self):
        rows = []
        for scenario in ("recoverable", "persistent"):
            rows.append(summary(f"{scenario}-valid", scenario, 101))
            sparse = summary(f"{scenario}-sparse", scenario, 101, margin=100)
            sparse["valid_completed_rounds"] = MIN_VALID_COMPLETED_ROUNDS - 1
            rows.append(sparse)
            no_occupancy = summary(f"{scenario}-empty", scenario, 101, margin=200)
            no_occupancy["low_floor_high_spread_occupancy"] = 0
            rows.append(no_occupancy)
        with tempfile.TemporaryDirectory() as directory:
            selected = select_confirmation(rows, Path(directory) / "confirmation.csv")
        self.assertEqual({row["cell_id"] for row in selected},
                         {"recoverable-valid", "persistent-valid"})

    def test_formal_acceptance_excludes_censored_rounds(self):
        summaries = []
        rounds = []
        for scenario in ("recoverable", "persistent"):
            for seed in (13, 14, 15, 16, 17):
                summaries.append(summary("formal-" + scenario, scenario, seed))
                rounds.extend(round_row(scenario, seed, flow, 0.2 if scenario == "recoverable" else -0.1)
                              for flow in (0, 1, 0))
                rounds.append(round_row(scenario, seed, 99, -100.0, valid=False, complete=False))
        results = formal_acceptance(summaries, rounds, samples=200)
        self.assertEqual([row["accepted"] for row in results], [1, 1])
        self.assertGreater(results[0]["bootstrap_95pct_lower"], 0)

    def test_formal_acceptance_reports_mixed_cell_ids(self):
        summaries = []
        rounds = []
        for scenario in ("recoverable", "persistent"):
            for seed in (13, 14, 15, 16, 17):
                summaries.append(summary(f"formal-{scenario}", scenario, seed))
                rounds.extend(
                    round_row(
                        scenario, seed, flow,
                        0.2 if scenario == "recoverable" else -0.1,
                    )
                    for flow in (0, 1, 0)
                )
        summaries[0]["cell_id"] = "formal-recoverable-stale"
        recoverable = formal_acceptance(summaries, rounds, samples=20)[0]
        self.assertEqual(recoverable["accepted"], 0)
        self.assertIn(
            "formal_mixed_cell_ids_within_scenario",
            recoverable["failed_predicates"],
        )

    def test_completed_capacity_mismatch_cannot_disappear_as_invalid(self):
        summaries = [summary("persistent", "persistent", seed) for seed in (13, 14, 15, 16, 17)]
        rounds = [
            round_row("persistent", seed, flow, -0.1)
            for seed in (13, 14, 15, 16, 17) for flow in (0, 1)
        ]
        rounds[0]["valid_round"] = 0
        rounds[0]["capacity_classification"] = "recoverable"
        result = formal_acceptance(summaries, rounds, samples=20)[1]
        self.assertEqual(result["accepted"], 0)
        self.assertIn("persistent_capacity_relation_not_in_every_valid_round",
                      result["failed_predicates"])

    def test_recoverable_rejects_completed_invalid_capacity_and_sparse_evidence(self):
        summaries = [summary("recoverable", "recoverable", seed)
                     for seed in (13, 14, 15, 16, 17)]
        rounds = [
            round_row("recoverable", seed, flow, 0.2)
            for seed in (13, 14, 15, 16, 17) for flow in (0, 1, 0)
        ]
        rounds[0]["valid_round"] = 0
        rounds[0]["capacity_valid"] = 0
        result = formal_acceptance(summaries, rounds, samples=20)[0]
        self.assertEqual(result["accepted"], 0)
        self.assertIn("recoverable_capacity_relation_not_in_every_completed_round",
                      result["failed_predicates"])
        self.assertIn("fewer_than_3_valid_completed_rounds_in_a_formal_seed",
                      result["failed_predicates"])


class FigureInputTests(unittest.TestCase):
    def test_representative_and_delta_use_only_valid_rounds(self):
        rounds = [
            {"scenario": "recoverable", "seed": "13", "flow_id": "0",
             "round_index": "0", "complete": "1", "valid_round": "0", "delta_S": "9"},
            {"scenario": "recoverable", "seed": "13", "flow_id": "1",
             "round_index": "0", "complete": "1", "valid_round": "1", "delta_S": "0.2"},
            {"scenario": "recoverable", "seed": "13", "flow_id": "2",
             "round_index": "0", "complete": "0", "valid_round": "0", "delta_S": ""},
        ]
        epochs = [
            {"scenario": "recoverable", "seed": "13", "flow_id": str(flow),
             "round_index": "0", "event_seq": str(flow * 10 + point),
             "aligned_time_ps": str(point * 1_000_000)}
            for flow in (0, 1, 2) for point in (0, 1)
        ]
        chosen, series = _representative(epochs, rounds, "recoverable")
        self.assertEqual(chosen["flow_id"], "1")
        self.assertEqual({row["flow_id"] for row in series}, {"1"})
        self.assertEqual(_valid_seed_deltas(rounds, "recoverable", 13), [0.2])

    def test_selftest_removes_placeholder_figures_and_cache(self):
        figure_selftest()
        for suffix in ("png", "pdf"):
            self.assertFalse((FIGS / f"{STEM}.{suffix}").exists())
        self.assertFalse(_CACHE_DIR.exists())


if __name__ == "__main__":
    unittest.main()
