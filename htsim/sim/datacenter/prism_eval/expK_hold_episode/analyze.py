#!/usr/bin/env python3
"""Extract descriptive outcomes from PRISM HOLD-entry ACK traces."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


HOLD_REGION = 1
SUMMARY_FIELDS = (
    "scenario",
    "episodes",
    "complete",
    "incomplete",
    "recovered",
    "ineffective",
    "mixed",
)
EPISODE_FIELDS = (
    "scenario",
    "seed",
    "flow_id",
    "entry_time_ns",
    "f_entry_ns",
    "s_entry_ns",
    "status",
    "outcome",
    "missing_delay_support",
    "pre_ack_bytes",
    "pre_ack_rate_bps",
    "pre_valid_samples",
    "pre_low_support",
    "pre_high_tail",
    "post1_ack_bytes",
    "post1_ack_rate_bps",
    "post1_valid_samples",
    "post1_low_support",
    "post1_high_tail",
    "post2_ack_bytes",
    "post2_ack_rate_bps",
    "post2_valid_samples",
    "post2_low_support",
    "post2_high_tail",
)


@dataclass(frozen=True)
class Epoch:
    time_ns: int
    flow_id: int
    base_rtt_ns: int
    c_cc_ns: int
    c_spray_ns: int
    region: int
    cwnd_bytes: int
    samples: int
    cut: int


@dataclass(frozen=True)
class Ack:
    time_ns: int
    flow_id: int
    valid_delay_sample: int
    qdelay_ns: int
    base_rtt_ns: int
    ecn: int
    newly_acked_bytes: int
    cwnd_bytes: int


def _parse_uint(value: str, path: Path, line_number: int, field_name: str) -> int:
    if not value or not value.isascii() or not value.isdecimal():
        raise ValueError(f"{path}: line {line_number}: invalid {field_name!r}: {value!r}")
    return int(value)


def _parse_binary(value: str, path: Path, line_number: int, field_name: str) -> int:
    parsed = _parse_uint(value, path, line_number, field_name)
    if parsed not in (0, 1):
        raise ValueError(f"{path}: line {line_number}: {field_name} must be 0 or 1")
    return parsed


def load_epochs(path: Path) -> list[Epoch]:
    """Load the first nine PRISM_EPOCH columns, ignoring later optional fields."""
    rows: list[Epoch] = []
    with path.open(newline="") as stream:
        for line_number, fields in enumerate(csv.reader(stream), start=1):
            if len(fields) < 9:
                raise ValueError(f"{path}: line {line_number}: expected at least 9 fields")
            values = [
                _parse_uint(value, path, line_number, name)
                for value, name in zip(
                    fields[:9],
                    (
                        "time_ns", "flow_id", "base_rtt_ns", "c_cc_ns", "c_spray_ns",
                        "region", "cwnd_bytes", "samples", "cut",
                    ),
                )
            ]
            rows.append(Epoch(*values))
    return sorted(rows, key=lambda row: (row.flow_id, row.time_ns))


def load_hold_acks(path: Path) -> list[Ack]:
    """Load the exact eight-field PRISM_HOLD_TRACE ACK schema."""
    rows: list[Ack] = []
    with path.open(newline="") as stream:
        for line_number, fields in enumerate(csv.reader(stream), start=1):
            if len(fields) != 8:
                raise ValueError(f"{path}: line {line_number}: expected exactly 8 fields")
            values = [
                _parse_uint(value, path, line_number, name)
                for value, name in zip(
                    fields,
                    (
                        "time_ns", "flow_id", "valid_delay_sample", "qdelay_ns", "base_rtt_ns",
                        "ecn", "newly_acked_bytes", "cwnd_bytes",
                    ),
                )
            ]
            if values[2] not in (0, 1) or values[5] not in (0, 1):
                raise ValueError(f"{path}: line {line_number}: binary fields must be 0 or 1")
            rows.append(Ack(*values))
    return sorted(rows, key=lambda row: (row.flow_id, row.time_ns))


def _threshold_ns(manifest: dict, name: str) -> int:
    ns_key = f"{name}_ns"
    if ns_key in manifest:
        value = manifest[ns_key]
    else:
        us_key = f"{name}_us"
        if us_key not in manifest:
            raise ValueError(f"manifest is missing {ns_key} or {us_key}")
        value = manifest[us_key] * 1_000
    if not isinstance(value, int) or value < 0:
        raise ValueError(f"manifest {name} threshold must be a non-negative integer")
    return value


def _window_metrics(
    acks: Iterable[Ack],
    start_ns: int,
    end_ns: int,
    base_rtt_ns: int,
    t_cc_ns: int,
    high_threshold_ns: int,
) -> dict:
    window = [ack for ack in acks if start_ns < ack.time_ns <= end_ns]
    valid = [ack for ack in window if ack.valid_delay_sample]
    count = len(valid)
    return {
        "ack_bytes": sum(ack.newly_acked_bytes for ack in window),
        "ack_rate_bps": sum(ack.newly_acked_bytes for ack in window) * 8 * 1_000_000_000 / base_rtt_ns,
        "valid_samples": count,
        "low_support": (
            sum(ack.qdelay_ns <= t_cc_ns for ack in valid) / count if count else None
        ),
        "high_tail": (
            sum(ack.qdelay_ns >= high_threshold_ns for ack in valid) / count if count else None
        ),
    }


def _episode_row(manifest: dict, epoch: Epoch, acks: list[Ack], t_cc_ns: int, t_spray_ns: int) -> dict:
    if epoch.base_rtt_ns <= 0:
        raise ValueError(f"flow {epoch.flow_id} at {epoch.time_ns}: base RTT must be positive")
    entry = epoch.time_ns
    base = epoch.base_rtt_ns
    windows = {
        "pre": _window_metrics(acks, entry - base, entry, base, t_cc_ns, epoch.c_cc_ns + t_spray_ns),
        "post1": _window_metrics(acks, entry, entry + base, base, t_cc_ns, epoch.c_cc_ns + t_spray_ns),
        "post2": _window_metrics(acks, entry + base, entry + 2 * base, base, t_cc_ns, epoch.c_cc_ns + t_spray_ns),
    }
    complete = any(ack.time_ns >= entry + 2 * base for ack in acks)
    row = {
        "scenario": manifest["scenario"],
        "seed": manifest["seed"],
        "flow_id": epoch.flow_id,
        "entry_time_ns": entry,
        "f_entry_ns": epoch.c_cc_ns,
        "s_entry_ns": epoch.c_spray_ns,
        "status": "complete" if complete else "incomplete",
        "outcome": "incomplete",
        "missing_delay_support": 0,
    }
    for prefix, metrics in windows.items():
        for name, value in metrics.items():
            row[f"{prefix}_{name}"] = value

    if not complete:
        return row

    required_fractions = (
        row["pre_low_support"],
        row["pre_high_tail"],
        row["post1_high_tail"],
        row["post2_low_support"],
        row["post2_high_tail"],
    )
    if any(value is None for value in required_fractions):
        row["missing_delay_support"] = 1
        row["outcome"] = "mixed"
        return row

    recovered = (
        row["post1_ack_rate_bps"] >= row["pre_ack_rate_bps"]
        and row["post2_ack_rate_bps"] >= row["pre_ack_rate_bps"]
        and row["post1_high_tail"] < row["pre_high_tail"]
        and row["post2_high_tail"] < row["pre_high_tail"]
        and row["post2_low_support"] >= row["pre_low_support"]
    )
    ineffective = (
        row["post2_high_tail"] >= row["pre_high_tail"]
        and row["post2_ack_rate_bps"] <= row["pre_ack_rate_bps"]
    )
    row["outcome"] = "recovered" if recovered else "ineffective" if ineffective else "mixed"
    return row


def extract_episodes(manifest: dict, epochs: list[Epoch], acks: list[Ack]) -> list[dict]:
    """Return per-flow HOLD entries with exact adjacent base-RTT window metrics."""
    if "scenario" not in manifest or "seed" not in manifest:
        raise ValueError("manifest is missing scenario or seed")
    t_cc_ns = _threshold_ns(manifest, "t_cc")
    t_spray_ns = _threshold_ns(manifest, "t_spray")
    acks_by_flow: dict[int, list[Ack]] = defaultdict(list)
    for ack in sorted(acks, key=lambda row: (row.flow_id, row.time_ns)):
        acks_by_flow[ack.flow_id].append(ack)

    rows = []
    previous_region: dict[int, int] = {}
    for epoch in sorted(epochs, key=lambda row: (row.flow_id, row.time_ns)):
        previous = previous_region.get(epoch.flow_id)
        if epoch.region == HOLD_REGION and previous is not None and previous != HOLD_REGION:
            rows.append(_episode_row(manifest, epoch, acks_by_flow[epoch.flow_id], t_cc_ns, t_spray_ns))
        previous_region[epoch.flow_id] = epoch.region
    return rows


def write_aggregate(rows: list[dict], output_dir: Path) -> None:
    """Write stable per-episode rows and scenario-level outcome counts."""
    output_dir.mkdir(parents=True, exist_ok=True)
    extra_fields = sorted({key for row in rows for key in row} - set(EPISODE_FIELDS))
    with (output_dir / "episode_rows.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=[*EPISODE_FIELDS, *extra_fields], extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)

    scenarios = sorted({row["scenario"] for row in rows})
    with (output_dir / "scenario_summary.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        for scenario in scenarios:
            scenario_rows = [row for row in rows if row["scenario"] == scenario]
            outcomes = [row["outcome"] for row in scenario_rows]
            writer.writerow({
                "scenario": scenario,
                "episodes": len(scenario_rows),
                "complete": sum(row["status"] == "complete" for row in scenario_rows),
                "incomplete": sum(row["status"] == "incomplete" for row in scenario_rows),
                "recovered": outcomes.count("recovered"),
                "ineffective": outcomes.count("ineffective"),
                "mixed": outcomes.count("mixed"),
            })


def _trace_path(manifest_path: Path, manifest: dict, kind: str) -> Path:
    for key in (f"{kind}_path", f"{kind}_csv", f"{kind}_file"):
        if key in manifest:
            path = Path(manifest[key])
            return path if path.is_absolute() else manifest_path.parent / path
    tag = manifest_path.name.removesuffix(".manifest.json")
    return manifest_path.parent / f"{tag}.{kind}.csv"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    rows: list[dict] = []
    for manifest_path in sorted(args.input.glob("*.manifest.json")):
        manifest = json.loads(manifest_path.read_text())
        rows.extend(extract_episodes(
            manifest,
            load_epochs(_trace_path(manifest_path, manifest, "epoch")),
            load_hold_acks(_trace_path(manifest_path, manifest, "hold")),
        ))
    write_aggregate(rows, args.output)


if __name__ == "__main__":
    main()
