import csv
import sys
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import analyze


def _manifest(**overrides):
    manifest = {
        "scenario": "f0",
        "seed": 13,
        "t_cc_ns": 14,
        "t_spray_ns": 14,
    }
    manifest.update(overrides)
    return manifest


def _load(tmp_path, epochs, acks):
    epoch_path = tmp_path / "case.epoch.csv"
    hold_path = tmp_path / "case.hold.csv"
    epoch_path.write_text("\n".join(",".join(map(str, row)) for row in epochs) + "\n")
    hold_path.write_text("\n".join(",".join(map(str, row)) for row in acks) + "\n")
    return analyze.load_epochs(epoch_path), analyze.load_hold_acks(hold_path)


def test_extracts_only_nonhold_to_hold_transition(tmp_path):
    epochs, acks = _load(
        tmp_path,
        [
            (100, 7, 100, 5, 20, 0, 1000, 1, 0),
            (200, 7, 100, 5, 20, 1, 1000, 1, 0),
            (300, 7, 100, 5, 20, 1, 1000, 1, 0),
        ],
        [
            (150, 7, 1, 14, 100, 0, 1, 1000),
            (250, 7, 1, 14, 100, 0, 1, 1000),
            (350, 7, 1, 14, 100, 0, 1, 1000),
            (400, 7, 1, 14, 100, 0, 1, 1000),
        ],
    )

    rows = analyze.extract_episodes(_manifest(), epochs, acks)

    assert [row["entry_time_ns"] for row in rows] == [200]


def test_uses_adjacent_base_rtt_windows_and_ack_bytes(tmp_path):
    epochs, acks = _load(
        tmp_path,
        [
            (100, 7, 100, 5, 20, 0, 1000, 1, 0),
            (200, 7, 100, 5, 20, 1, 1000, 1, 0),
        ],
        [
            (150, 7, 1, 14, 100, 0, 0, 1000),
            (200, 7, 0, 0, 100, 0, 1, 1000),
            (250, 7, 1, 14, 100, 0, 0, 1000),
            (300, 7, 0, 0, 100, 0, 1, 1000),
            (350, 7, 1, 14, 100, 0, 0, 1000),
            (400, 7, 1, 14, 100, 0, 1, 1000),
        ],
    )

    row = analyze.extract_episodes(_manifest(), epochs, acks)[0]

    assert row["pre_ack_rate_bps"] == 80_000_000
    assert row["post1_low_support"] == 1.0
    assert row["post2_high_tail"] == 0.0


def test_marks_missing_second_post_window_incomplete(tmp_path):
    epochs, acks = _load(
        tmp_path,
        [
            (100, 7, 100, 5, 20, 0, 1000, 1, 0),
            (200, 7, 100, 5, 20, 1, 1000, 1, 0),
        ],
        [
            (150, 7, 1, 14, 100, 0, 1, 1000),
            (300, 7, 1, 14, 100, 0, 1, 1000),
        ],
    )

    row = analyze.extract_episodes(_manifest(), epochs, acks)[0]

    assert row["status"] == "incomplete"
    assert row["outcome"] == "incomplete"


def test_complete_episode_without_valid_delay_samples_is_mixed(tmp_path):
    epochs, acks = _load(
        tmp_path,
        [
            (100, 7, 100, 5, 20, 0, 1000, 1, 0),
            (200, 7, 100, 5, 20, 1, 1000, 1, 0),
        ],
        [
            (150, 7, 0, 0, 100, 0, 1, 1000),
            (250, 7, 0, 0, 100, 0, 1, 1000),
            (350, 7, 0, 0, 100, 0, 1, 1000),
            (400, 7, 0, 0, 100, 0, 1, 1000),
        ],
    )

    row = analyze.extract_episodes(_manifest(), epochs, acks)[0]

    assert row["status"] == "complete"
    assert row["missing_delay_support"] == 1
    assert row["outcome"] == "mixed"


def test_assigns_recovered_ineffective_and_mixed_without_threshold_fit(tmp_path):
    epochs = []
    acks = []
    for flow_id in (1, 2, 3):
        epochs.extend(
            [
                (100, flow_id, 100, 5, 20, 0, 1000, 1, 0),
                (200, flow_id, 100, 5, 20, 1, 1000, 1, 0),
            ]
        )
        acks.extend(
            [
                (150, flow_id, 1, 14, 100, 0, 1, 1000),
                (180, flow_id, 1, 25, 100, 0, 1, 1000),
                (250, flow_id, 1, 14, 100, 0, 1, 1000),
                    (270, flow_id, 1, 14 if flow_id == 1 else 25, 100, 0, 1, 1000),
            ]
        )
    acks.extend(
        [
            (350, 1, 1, 14, 100, 0, 1, 1000),
            (400, 1, 1, 14, 100, 0, 1, 1000),
            (350, 2, 1, 14, 100, 0, 0, 1000),
            (400, 2, 1, 25, 100, 0, 0, 1000),
            (350, 3, 1, 14, 100, 0, 0, 1000),
            (400, 3, 1, 14, 100, 0, 0, 1000),
        ]
    )
    epochs, acks = _load(tmp_path, epochs, acks)

    rows = analyze.extract_episodes(_manifest(), epochs, acks)

    assert [row["outcome"] for row in rows] == ["recovered", "ineffective", "mixed"]


def test_parsers_are_strict_and_sort_by_flow_and_time(tmp_path):
    epoch_path = tmp_path / "case.epoch.csv"
    epoch_path.write_text("200,2,100,5,20,1,1000,1,0,ignored\n100,1,100,5,20,0,1000,1,0\n")
    hold_path = tmp_path / "case.hold.csv"
    hold_path.write_text("200,2,1,14,100,0,1,1000\n100,1,0,0,100,1,1,1000\n")

    assert [(row.flow_id, row.time_ns) for row in analyze.load_epochs(epoch_path)] == [(1, 100), (2, 200)]
    assert [(row.flow_id, row.time_ns) for row in analyze.load_hold_acks(hold_path)] == [(1, 100), (2, 200)]

    hold_path.write_text("100,1,2,0,100,0,1,1000\n")
    with pytest.raises(ValueError, match="line 1"):
        analyze.load_hold_acks(hold_path)


def test_write_aggregate_emits_episode_and_scenario_csvs(tmp_path):
    rows = [
        {"scenario": "f0", "seed": 13, "status": "complete", "outcome": "recovered", "entry_time_ns": 200},
        {"scenario": "f0", "seed": 13, "status": "incomplete", "outcome": "incomplete", "entry_time_ns": 400},
    ]

    analyze.write_aggregate(rows, tmp_path, (("f0", 13), ("incast", 13)))

    with (tmp_path / "episode_rows.csv").open(newline="") as stream:
        episode_rows = list(csv.DictReader(stream))
    with (tmp_path / "scenario_summary.csv").open(newline="") as stream:
        summary_rows = list(csv.DictReader(stream))
    assert [row["outcome"] for row in episode_rows] == ["recovered", "incomplete"]
    assert summary_rows == [
        {
            "scenario": "f0",
            "episodes": "2",
            "complete": "1",
            "incomplete": "1",
            "recovered": "1",
            "ineffective": "0",
            "mixed": "0",
        },
        {
            "scenario": "incast",
            "episodes": "0",
            "complete": "0",
            "incomplete": "0",
            "recovered": "0",
            "ineffective": "0",
            "mixed": "0",
        },
    ]

    with (tmp_path / "seed_summary.csv").open(newline="") as stream:
        seed_rows = list(csv.DictReader(stream))
    assert seed_rows == [
        {
            "scenario": "f0", "seed": "13", "episodes": "2", "complete": "1",
            "incomplete": "1", "recovered": "1", "ineffective": "0", "mixed": "0",
        },
        {
            "scenario": "incast", "seed": "13", "episodes": "0", "complete": "0",
            "incomplete": "0", "recovered": "0", "ineffective": "0", "mixed": "0",
        },
    ]


def test_expected_manifest_paths_ignore_stale_and_require_every_locked_case(tmp_path, monkeypatch):
    class FakeCase:
        def __init__(self, scenario, seed):
            self.scenario = scenario
            self.seed = seed

    monkeypatch.setattr(analyze, "locked_cases", lambda: (FakeCase("f0", 13),))
    monkeypatch.setattr(analyze, "case_tag", lambda case: f"hold_{case.scenario}_s{case.seed}")
    expected = tmp_path / "hold_f0_s13.manifest.json"
    expected.write_text("{}")
    (tmp_path / "stale.manifest.json").write_text("{}")

    assert analyze.expected_manifest_paths(tmp_path) == [expected]

    expected.unlink()
    with pytest.raises(ValueError, match="missing locked manifests"):
        analyze.expected_manifest_paths(tmp_path)
