#!/usr/bin/env python3
"""Summarize the isolated equal-path-domain PATHS=16 PRIME ExpA matrix."""
import argparse
import csv
import math
import pathlib
import re
import statistics


ARMS = (("ops", "OPS"), ("reps", "REPS"), ("decmt", "DecMT"), ("prime", "Prime"))
FAILEDS = (0, 8)
SEEDS = (13, 14, 15)
PATHS = 16
END_MS = 8
SOURCE_UPLINKS = frozenset(range(4))
BASE_FIELDS = ("row_type", "arm", "failed", "seed", "paths", "end_ms", "started_count",
               "completion_count", "censored_count", "fct_mean_us", "fct_p50_us",
               "fct_p95_us", "fct_p99_us", "delivered_bytes", "delivered_goodput_gbps",
               "feedback_count", "selection_count", "source_uplinks")


def _one(directory, suffix):
    matches = sorted(directory.glob(f"*{suffix}"))
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one {suffix} in {directory}, found {len(matches)}")
    return matches[0]


def _optional_one(directory, suffix):
    matches = sorted(directory.glob(f"*{suffix}"))
    if len(matches) > 1:
        raise RuntimeError(f"expected at most one {suffix} in {directory}, found {len(matches)}")
    return matches[0] if matches else None


def _flow_summary(path):
    starts, finishes = {}, {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        fields = line.split()
        if "FLOW_EVENT" not in fields:
            continue
        key = (int(fields[fields.index("SrcID") + 1]), int(fields[fields.index("FlowID") + 1]))
        if fields[fields.index("Ev") + 1] == "START":
            starts[key] = float(fields[0])
        elif fields[fields.index("Ev") + 1] == "FINISH":
            finishes[key] = float(fields[0])
    fcts = sorted((finishes[key] - started) * 1e6 for key, started in starts.items()
                  if key in finishes)
    return len(starts), fcts


def _delivered_bytes(path):
    pattern = re.compile(r"^UEC_DELIVERY_SUMMARY flow=(\d+) delivered_bytes=(\d+)$")
    delivered = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = pattern.match(line.strip())
        if match:
            flow, bytes_delivered = map(int, match.groups())
            if flow in delivered:
                raise RuntimeError(f"duplicate delivery summary for flow {flow}")
            delivered[flow] = bytes_delivered
    if not delivered:
        raise RuntimeError(f"missing UEC_DELIVERY_SUMMARY in {path}")
    return sum(delivered.values())


def _trace_summary(path):
    selections, feedbacks = 0, 0
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream, delimiter="\t"):
            if row["event"] == "feedback":
                feedbacks += 1
            elif row["event"] == "selection":
                selections += 1
    return selections, feedbacks


def source_uplink_coverage(run_dir):
    """Return all source-ToR uplinks observed in selection events for one PRIME cell."""
    trace = _one(pathlib.Path(run_dir), ".prime.tsv")
    uplinks = set()
    with trace.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream, delimiter="\t"):
            if row["event"] != "selection":
                continue
            tuple_parts = row["tuple"].split("/")
            if not tuple_parts or not tuple_parts[0]:
                raise RuntimeError(f"invalid PRIME tuple in {trace}: {row['tuple']!r}")
            uplinks.add(int(tuple_parts[0]))
    return uplinks


def _percentile(values, fraction):
    return values[round(fraction * (len(values) - 1))] if values else math.nan


def tag(arm, failed, seed):
    return f"expA_prime_paths16_{arm}_f{failed}_s{seed}"


def build_summary_row(run_dir, arm, failed, seed, end_ms=END_MS):
    run_dir = pathlib.Path(run_dir)
    started, fcts = _flow_summary(_one(run_dir, ".flow.txt"))
    delivered = _delivered_bytes(_one(run_dir, ".stdout"))
    trace_path = _optional_one(run_dir, ".prime.tsv")
    if arm == "Prime":
        if trace_path is None:
            raise RuntimeError(f"missing PRIME_DIAG trace in {run_dir}")
        uplinks = source_uplink_coverage(run_dir)
        if uplinks != SOURCE_UPLINKS:
            raise RuntimeError(f"missing required Prime source uplink(s) in {run_dir}: "
                               f"observed={sorted(uplinks)} expected={sorted(SOURCE_UPLINKS)}")
        selections, feedbacks = _trace_summary(trace_path)
    else:
        uplinks, selections, feedbacks = set(), 0, 0
    return {"row_type": "cell", "arm": arm, "failed": failed, "seed": seed, "paths": PATHS,
            "end_ms": end_ms, "started_count": started, "completion_count": len(fcts),
            "censored_count": started - len(fcts),
            "fct_mean_us": statistics.mean(fcts) if fcts else math.nan,
            "fct_p50_us": _percentile(fcts, 0.50), "fct_p95_us": _percentile(fcts, 0.95),
            "fct_p99_us": _percentile(fcts, 0.99), "delivered_bytes": delivered,
            "delivered_goodput_gbps": delivered * 8.0 / (end_ms * 1e6),
            "feedback_count": feedbacks, "selection_count": selections,
            "source_uplinks": ",".join(map(str, sorted(uplinks))), "_fct_samples_us": fcts}


def read_paths16_matrix(input_dir, end_ms=END_MS):
    rows = []
    input_dir = pathlib.Path(input_dir)
    for arm, display in ARMS:
        for failed in FAILEDS:
            for seed in SEEDS:
                run_dir = input_dir / tag(arm, failed, seed)
                if not run_dir.is_dir():
                    raise RuntimeError(f"missing required cell: {run_dir.name}")
                rows.append(build_summary_row(run_dir, display, failed, seed, end_ms))
    return rows


def _aggregate(rows):
    aggregates = []
    for _, arm in ARMS:
        for failed in FAILEDS:
            group = [row for row in rows if row["arm"] == arm and row["failed"] == failed]
            fcts = sorted(sample for row in group for sample in row["_fct_samples_us"])
            total_end_ms = sum(row["end_ms"] for row in group)
            aggregates.append({"row_type": "aggregate", "arm": arm, "failed": failed, "seed": "",
                               "paths": PATHS, "end_ms": total_end_ms,
                               "started_count": sum(row["started_count"] for row in group),
                               "completion_count": sum(row["completion_count"] for row in group),
                               "censored_count": sum(row["censored_count"] for row in group),
                               "fct_mean_us": statistics.mean(fcts) if fcts else math.nan,
                               "fct_p50_us": _percentile(fcts, 0.50),
                               "fct_p95_us": _percentile(fcts, 0.95),
                               "fct_p99_us": _percentile(fcts, 0.99),
                               "delivered_bytes": sum(row["delivered_bytes"] for row in group),
                               "delivered_goodput_gbps": (
                                   sum(row["delivered_bytes"] for row in group) * 8.0 /
                                   (total_end_ms * 1e6) if total_end_ms else math.nan),
                               "feedback_count": sum(row["feedback_count"] for row in group),
                               "selection_count": sum(row["selection_count"] for row in group),
                               "source_uplinks": "0,1,2,3" if arm == "Prime" else ""})
    return aggregates


def write_summary(rows, output):
    all_rows = rows + _aggregate(rows)
    with pathlib.Path(output).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=BASE_FIELDS, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_rows)
    return all_rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    rows = read_paths16_matrix(args.input)
    write_summary(rows, args.output / "prime_paths16_compare.tsv")
    from make_figs import render
    render(rows, args.output)


if __name__ == "__main__":
    main()
