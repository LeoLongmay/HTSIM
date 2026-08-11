#!/usr/bin/env python3
"""Validate and summarize the bounded PATHS=16 PRIME reproduction traces."""
import argparse
import csv
import io
from pathlib import Path


FIELDS = (
    "event_seq", "time_ps", "flow", "event", "entropy", "tuple", "reason",
    "feedback", "penalty_before", "penalty_after",
)
OUTPUT_FIELDS = (
    "trace", "failed", "seed", "topology", "paths", "end_ms", "disable_trim",
    "uec_delivery_summary", "prime_diag", "event_rows", "ecn_feedback",
    "nack_feedback", "timeout_feedback",
)
HERE = Path(__file__).resolve().parent
SMOKE = HERE.parent
ARCHIVE = SMOKE / "archive_data" / "prime_strict_reproduction_audit.tsv"


def read_trace(lines):
    """Read one exact-schema trace and require sequence IDs 1..N."""
    if isinstance(lines, Path):
        text = lines.read_text(encoding="utf-8")
    elif isinstance(lines, str):
        text = lines
    else:
        text = "\n".join(lines)
    reader = csv.reader(io.StringIO(text), delimiter="\t")
    rows = list(reader)
    if not rows or tuple(rows[0]) != FIELDS:
        raise ValueError("PRIME diagnostic must have the exact ten columns and header")
    events = []
    for number, row in enumerate(rows[1:], start=2):
        if len(row) != len(FIELDS):
            raise ValueError(f"PRIME diagnostic row {number} must have ten columns")
        try:
            event_seq = int(row[0])
        except ValueError as error:
            raise ValueError(f"PRIME diagnostic row {number} has a non-integer event_seq") from error
        expected = len(events) + 1
        if event_seq != expected:
            raise ValueError(
                f"PRIME diagnostic event_seq must be contiguous from 1; got {event_seq}, expected {expected}")
        events.append(dict(zip(FIELDS, row)))
    return events


def analyze_trace(events):
    """Count feedback by emitted repository class; timeout remains distinct."""
    counts = {"ecn": 0, "nack": 0, "timeout": 0}
    for event in events:
        if event["event"] == "feedback" and event["feedback"] in counts:
            counts[event["feedback"]] += 1
    return {
        "event_rows": len(events),
        "ecn_feedback": counts["ecn"],
        "nack_feedback": counts["nack"],
        "timeout_feedback": counts["timeout"],
    }


def _read_manifest(run_root):
    manifest = run_root / "run_manifest.tsv"
    if not manifest.is_file():
        raise RuntimeError(f"missing strict reproduction manifest: {manifest}")
    with manifest.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    required = {"trace", "failed", "seed", "topology", "paths", "end_ms", "disable_trim",
                "uec_delivery_summary", "prime_diag"}
    if not rows or set(rows[0]) != required:
        raise RuntimeError("strict reproduction manifest does not record the exact required flags")
    if len(rows) != 2 or {row["failed"] for row in rows} != {"0", "8"}:
        raise RuntimeError("strict reproduction manifest must contain exactly one f0 and one f8 cell")
    for row in rows:
        if (row["paths"], row["seed"], row["topology"], row["end_ms"], row["disable_trim"],
                row["uec_delivery_summary"], row["prime_diag"]) != (
                    "16", "13", "fat_tree_128_1os.topo", "8", "1", "1", "1"):
            raise RuntimeError("strict reproduction manifest has non-fixed flags")
        expected_trace = f"prime_strict_f{row['failed']}_s13/run.prime.tsv"
        if row["trace"] != expected_trace:
            raise RuntimeError("strict reproduction manifest violates the fixed trace contract")
    return rows


def analyze_run(run_root):
    run_root = Path(run_root).resolve()
    output = []
    for row in _read_manifest(run_root):
        trace = (run_root / row["trace"]).resolve()
        try:
            trace.relative_to(run_root)
        except ValueError as error:
            raise RuntimeError(f"trace escapes run root: {trace}") from error
        if not trace.is_file():
            raise RuntimeError(f"missing PRIME diagnostic: {trace}")
        output.append({**row, **analyze_trace(read_trace(trace))})
    return output


def write_archive(rows):
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    with ARCHIVE.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=OUTPUT_FIELDS, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    return ARCHIVE


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    args = parser.parse_args()
    print(write_archive(analyze_run(args.input)))


if __name__ == "__main__":
    main()
