import csv
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from htsim.sim.datacenter.add_motivation.expM2_redistribution_progress.analyze import (
    CONFIG_FIELDS,
    EvidenceError,
    MIN_VALID_COMPLETED_ROUNDS,
    _apply_coarse_scenario,
    _config,
    _read_manifest,
    capacity_witness,
    foreground_offered_load,
    formal_acceptance,
    select_confirmation,
    select_formal,
)
from htsim.sim.datacenter.add_motivation.expM2_redistribution_progress.make_figs import (
    FIGS,
    STEM,
    _CACHE_DIR,
    _representative,
    _valid_seed_deltas,
    selftest as figure_selftest,
)


def capacity_bundle(*, bad_fingerprint=False, delivered_scale=1.0, unresolved=False):
    queues = [f"CS{i}->US0({i})" for i in range(6)]
    linkmap = tuple(
        {"queue_name": name, "rate_gbps": 100.0, "queue_id": index}
        for index, name in enumerate(queues)
    )
    pathmap = [
        {"resolution_status": "resolved", "queue_fingerprint": "|".join(queues)},
        {"resolution_status": "resolved", "queue_fingerprint": "|".join(queues)},
    ]
    if unresolved:
        pathmap.append({
            "resolution_status": "resolution_failed", "queue_fingerprint": "",
        })
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
        pathmap=tuple(pathmap), linkmap=linkmap, background=tuple(background), epoch=(),
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


class CapacityWitnessTests(unittest.TestCase):
    def test_deduplicates_cut_and_classifies_strictly(self):
        witness = capacity_witness(capacity_bundle(), 100, 900_000_000)
        self.assertEqual(witness.c_healthy_gbps, 400)
        self.assertEqual(witness.c_hot_residual_gbps, 100)
        self.assertEqual(witness.c_effective_residual_gbps, 500)
        self.assertEqual(witness.classify(350), "recoverable")
        self.assertEqual(witness.classify(450), "persistent")
        self.assertEqual(witness.classify(400), "invalid")
        self.assertEqual(witness.classify(500), "invalid")

    def test_requires_exactly_one_background_cut_queue(self):
        with self.assertRaisesRegex(EvidenceError, "exactly one target-pod cut queue"):
            capacity_witness(capacity_bundle(bad_fingerprint=True), 100, 900_000_000)

    def test_rejects_partially_resolved_foreground_pathmap(self):
        with self.assertRaisesRegex(EvidenceError, "foreground pathmap contains unresolved"):
            capacity_witness(capacity_bundle(unresolved=True), 100, 900_000_000)

    def test_rejects_delivery_outside_five_percent(self):
        with self.assertRaisesRegex(EvidenceError, "more than 5%"):
            capacity_witness(
                capacity_bundle(delivered_scale=0.94), 100, 900_000_000
            )


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
        self.assertEqual((witness.elapsed_ps_min, witness.elapsed_ps_max), (1_000, 1_000))

    def test_invalid_counter_is_not_coerced_to_throughput(self):
        bundle = SimpleNamespace(epoch=(
            {"flow_id": 1, "end_ps": 100, "event_seq": 1, "new_data_bytes_sent_total": 20},
            {"flow_id": 1, "end_ps": 200, "event_seq": 2, "new_data_bytes_sent_total": 10},
        ))
        witness = foreground_offered_load(bundle, 100, 200)
        self.assertFalse(witness.valid)
        self.assertIn("decreasing_new_data_counter", witness.failed_predicates[0])


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
            with confirmation_path.open(newline="", encoding="ascii") as stream:
                self.assertEqual(tuple(csv.DictReader(stream)), tuple(
                    {key: str(value) for key, value in row.items()} for row in selected
                ))

            confirmed = []
            for scenario in ("recoverable", "persistent"):
                for seed in (101, 102, 103):
                    confirmed.append(summary(f"{scenario}-0", scenario, seed))
            formal_path = Path(directory) / "formal.csv"
            formal = select_formal(confirmed, formal_path)
            self.assertEqual(len(formal), 10)
            with formal_path.open(newline="", encoding="ascii") as stream:
                reader = csv.DictReader(stream)
                self.assertEqual(tuple(reader.fieldnames), CONFIG_FIELDS)
                self.assertEqual({int(row["seed"]) for row in reader}, {13, 14, 15, 16, 17})

            failed = [row for row in confirmed if row["scenario"] == "recoverable"]
            self.assertEqual(select_formal(failed, formal_path), [])
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
             "round_index": "0", "event_seq": str(flow)}
            for flow in (0, 1, 2)
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
