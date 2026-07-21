#!/usr/bin/env python3
"""Aggregate opt-in strict-LAPS recovery summaries by failed-link point."""

import argparse
import csv
import pathlib
import re


RUN_RE = re.compile(r"expA_laps_diag_f(?P<failed>\d+)_s\d+\.stdout$")
PREFIX = "LAPS_RECOVERY_SUMMARY "
FIELDS = (
    "acked", "stale_ack", "ack_gap_events", "ack_gap_records",
    "timeout_events", "timeout_records", "nack", "stale_nack",
    "retired", "stale_retire", "source_ack_gap_rtx", "source_timeout_rtx",
)


def parse_summary(line):
    if not line.startswith(PREFIX):
        return None
    values = {}
    for token in line.strip().split()[1:]:
        key, value = token.split("=", 1)
        values[key] = int(value)
    if "flow" not in values or any(field not in values for field in FIELDS):
        raise ValueError("incomplete LAPS_RECOVERY_SUMMARY")
    return values


def write_summary(input_dir, output):
    totals = {}
    for path in sorted(pathlib.Path(input_dir).glob("*.stdout")):
        match = RUN_RE.match(path.name)
        if not match:
            continue
        failed = int(match.group("failed"))
        for line in path.read_text().splitlines():
            values = parse_summary(line)
            if values is None:
                continue
            row = totals.setdefault(failed, {"runs": 0, **{field: 0 for field in FIELDS}})
            row["runs"] += 1
            for field in FIELDS:
                row[field] += values[field]
    with pathlib.Path(output).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("failed", "runs", *FIELDS))
        writer.writeheader()
        for failed in sorted(totals):
            writer.writerow({"failed": failed, **totals[failed]})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    args = parser.parse_args()
    write_summary(args.input, args.output)
