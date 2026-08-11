#!/usr/bin/env python3
"""Summarize the fixed PRIME ExpA smoke matrix without hiding censored flows."""
import argparse
import csv
import math
import pathlib
import re
import statistics


ARMS = (("ops", "OPS"), ("reps", "REPS"), ("decmt", "DecMT"), ("prime", "Prime"))
FAILEDS = (0, 8)
SEEDS = (13, 14, 15)
BASE_FIELDS = ("row_type", "arm", "failed", "seed", "end_ms", "started_count",
               "completion_count", "censored_count", "fct_mean_us", "fct_p50_us",
               "fct_p95_us", "fct_p99_us",
               "delivered_bytes", "delivered_goodput_gbps", "feedback_count",
               "selection_count")


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
    for line in path.read_text().splitlines():
        fields = line.split()
        if "FLOW_EVENT" not in fields:
            continue
        key = (int(fields[fields.index("SrcID") + 1]),
               int(fields[fields.index("FlowID") + 1]))
        if fields[fields.index("Ev") + 1] == "START":
            starts[key] = float(fields[0])
        elif fields[fields.index("Ev") + 1] == "FINISH":
            finishes[key] = float(fields[0])
    fcts = [(finishes[key] - started) * 1e6
            for key, started in starts.items() if key in finishes]
    fcts.sort()
    return len(starts), fcts


def _delivered_bytes(path):
    """Exact end-of-run sink delivery summaries (not sampled CACK packet counts)."""
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
    selections, feedbacks, tier_counts = 0, 0, {}
    with path.open(newline="") as stream:
        for row in csv.DictReader(stream, delimiter="\t"):
            if row["event"] == "feedback":
                feedbacks += 1
            if row["event"] != "selection":
                continue
            selections += 1
            for tier, port in enumerate(filter(None, row["tuple"].split("/"))):
                tier_counts[(tier, int(port))] = tier_counts.get((tier, int(port)), 0) + 1
    shares = {f"tier{tier}_share_{port}": count / selections
              for (tier, port), count in tier_counts.items()} if selections else {}
    return selections, feedbacks, shares


def _percentile(values, fraction):
    if not values:
        return math.nan
    return values[round(fraction * (len(values) - 1))]


def _p99(values):
    return _percentile(values, 0.99)


def build_summary_row(run_dir, arm, failed, seed, end_ms):
    """Build one cell from its decoded flow/sink logs and PRIME observation TSV."""
    run_dir = pathlib.Path(run_dir)
    started, fcts = _flow_summary(_one(run_dir, ".flow.txt"))
    delivered = _delivered_bytes(_one(run_dir, ".stdout"))
    trace_path = _optional_one(run_dir, ".prime.tsv")
    if arm == "Prime" and trace_path is None:
        raise RuntimeError(f"missing PRIME_DIAG trace in {run_dir}")
    selections, feedbacks, shares = _trace_summary(trace_path) if trace_path else (0, 0, {})
    row = {"row_type": "cell", "arm": arm, "failed": failed, "seed": seed,
           "end_ms": end_ms, "started_count": started, "completion_count": len(fcts),
           "censored_count": started - len(fcts),
           "fct_mean_us": statistics.mean(fcts) if fcts else math.nan,
           "fct_p50_us": _percentile(fcts, 0.50),
           "fct_p95_us": _percentile(fcts, 0.95),
           "fct_p99_us": _p99(fcts), "delivered_bytes": delivered,
           "delivered_goodput_gbps": delivered * 8.0 / (end_ms * 1e6),
           "_fct_samples_us": fcts,
           "feedback_count": feedbacks, "selection_count": selections}
    row.update(shares)
    return row


def tag(arm, failed, seed):
    return f"expA_prime_smoke_{arm}_f{failed}_s{seed}"


def read_matrix(input_dir, end_ms=8):
    rows = []
    for arm, display in ARMS:
        for failed in FAILEDS:
            for seed in SEEDS:
                run_dir = pathlib.Path(input_dir) / tag(arm, failed, seed)
                if not run_dir.is_dir():
                    raise RuntimeError(f"missing required cell: {run_dir.name}")
                row = build_summary_row(run_dir, display, failed, seed, end_ms)
                rows.append(row)
    return rows


def _aggregate(rows):
    out = []
    for _, display in ARMS:
        for failed in FAILEDS:
            group = [row for row in rows if row["arm"] == display and row["failed"] == failed]
            merged = {"row_type": "aggregate", "arm": display, "failed": failed, "seed": "",
                      "end_ms": sum(r["end_ms"] for r in group), "started_count": sum(r["started_count"] for r in group),
                      "completion_count": sum(r["completion_count"] for r in group),
                      "censored_count": sum(r["censored_count"] for r in group),
                      "delivered_bytes": sum(r["delivered_bytes"] for r in group),
                      "feedback_count": sum(r["feedback_count"] for r in group),
                      "selection_count": sum(r["selection_count"] for r in group)}
            fcts = sorted(sample for row in group for sample in row.get("_fct_samples_us", []))
            merged["fct_mean_us"] = statistics.mean(fcts) if fcts else math.nan
            merged["fct_p50_us"] = _percentile(fcts, 0.50)
            merged["fct_p95_us"] = _percentile(fcts, 0.95)
            merged["fct_p99_us"] = _p99(fcts)
            merged["delivered_goodput_gbps"] = (
                merged["delivered_bytes"] * 8.0 / (merged["end_ms"] * 1e6)
                if merged["end_ms"] else math.nan)
            for key in {key for row in group for key in row if key.startswith("tier")}:
                weighted = sum(row.get(key, 0.0) * row["selection_count"] for row in group)
                merged[key] = weighted / merged["selection_count"] if merged["selection_count"] else math.nan
            out.append(merged)
    return out


def write_summary(rows, output):
    rows = rows + _aggregate(rows)
    fields = list(BASE_FIELDS) + sorted({key for row in rows for key in row if key.startswith("tier")})
    with pathlib.Path(output).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--end-ms", type=int, default=8)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    rows = read_matrix(args.input, args.end_ms)
    write_summary(rows, args.output / "summary.tsv")
    from make_figs import render
    render(rows, args.output)


if __name__ == "__main__":
    main()
