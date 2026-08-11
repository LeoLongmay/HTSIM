#!/usr/bin/env python3
"""Extract and render censored ExpA flow, delivery, and LAPS PIT evidence."""
import argparse
import csv
import math
import re
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean, stdev

ARM_ORDER = ("OPS", "REPS", "DecMT", "LAPS")
DIAGNOSTIC_FIELDS = (
    "time_ns", "event_seq", "flow", "event_type", "pid", "seq", "bytes",
    "rate_bps", "target_rate_bps", "all_paths_high", "target_delay_ns",
    "min_delay_ns", "one_way_delay_ns", "recovery_cause", "timer_deadline_ns",
    "is_retransmission", "outstanding_probes", "pit_valid", "pit_selectable",
    "pit_probe_pending", "pit_updated_at_ns", "pit_deadline_ns",
)
METRIC_FIELDS = (
    "completion_count", "censored_count", "fct_sample_count", "fct_mean_us",
    "fct_p50_us", "fct_p95_us", "delivered_bytes", "goodput_gbps", "new", "rtx",
    "probe_sent", "probe_acked", "diagnostic_events", "pit_invariant_violations",
)
REQUIRED_FIELDS = ("arm", "failed", "seed", *METRIC_FIELDS)
INT_FIELDS = {
    "failed", "seed", "completion_count", "censored_count", "fct_sample_count",
    "delivered_bytes", "new", "rtx", "probe_sent", "probe_acked",
    "diagnostic_events", "pit_invariant_violations",
}


def percentile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        return math.nan
    index = int(round(fraction * (len(ordered) - 1)))
    return ordered[index]


def parse_flow_events(path: Path):
    starts = {}
    finishes = {}
    with path.open(encoding="ascii") as stream:
        for line_number, line in enumerate(stream, start=1):
            fields = line.split()
            if "FLOW_EVENT" not in fields:
                continue
            try:
                key = (int(fields[fields.index("SrcID") + 1]),
                       int(fields[fields.index("FlowID") + 1]))
                event = fields[fields.index("Ev") + 1]
                timestamp = float(fields[0])
            except (ValueError, IndexError) as exc:
                raise ValueError(f"malformed FLOW_EVENT line {line_number}") from exc
            if event == "START":
                if key in starts:
                    raise ValueError(f"duplicate START for {key}")
                starts[key] = (timestamp, int(fields[fields.index("Flowsize") + 1]))
            elif event == "FINISH":
                if key in finishes:
                    raise ValueError(f"duplicate FINISH for {key}")
                finishes[key] = (timestamp, int(fields[fields.index("Bytes") + 1]))
    return starts, finishes


def parse_delivered_bytes(stdout_path: Path, expected_flows: int):
    pattern = re.compile(r"^UEC_DELIVERY_SUMMARY flow=(\d+) delivered_bytes=(\d+)$")
    delivered = {}
    with stdout_path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            match = pattern.match(line.strip())
            if not match:
                continue
            flow, byte_count = map(int, match.groups())
            if flow in delivered:
                raise ValueError(f"duplicate UEC_DELIVERY_SUMMARY flow={flow}")
            delivered[flow] = byte_count
    if len(delivered) != expected_flows:
        raise ValueError(
            f"expected {expected_flows} delivery summaries, observed {len(delivered)}")
    return sum(delivered.values())


def pit_invariant_counts(diagnostics_path: Path | None):
    if diagnostics_path is None:
        return {"probe_sent": 0, "probe_acked": 0, "diagnostic_events": 0,
                "pit_invariant_violations": 0}
    sent = set()
    probes_sent = probes_acked = events = violations = 0
    with diagnostics_path.open(newline="", encoding="ascii") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != DIAGNOSTIC_FIELDS:
            raise ValueError("LAPS diagnostics have an unexpected schema")
        for row in reader:
            events += 1
            event = row["event_type"]
            if event not in {"probe_sent", "probe_acked", "data_acked"}:
                continue
            try:
                time_ns = int(row["time_ns"])
                key = (int(row["flow"]), int(row["pid"]), int(row["seq"]))
                valid = row["pit_valid"] == "1"
                selectable = row["pit_selectable"] == "1"
                pending = row["pit_probe_pending"] == "1"
                updated_at = int(row["pit_updated_at_ns"])
            except (TypeError, ValueError):
                violations += 1
                continue
            if event == "probe_sent":
                probes_sent += 1
                if key in sent:
                    violations += 1
                sent.add(key)
                if not (valid and not selectable and pending and updated_at == time_ns and
                        row["pit_deadline_ns"] == ""):
                    violations += 1
            else:
                if event == "probe_acked":
                    probes_acked += 1
                    if key not in sent:
                        violations += 1
                    else:
                        sent.remove(key)
                deadline = row["pit_deadline_ns"]
                if not (valid and selectable and not pending and updated_at == time_ns and
                        deadline != "" and int(deadline) > time_ns):
                    violations += 1
    return {"probe_sent": probes_sent, "probe_acked": probes_acked,
            "diagnostic_events": events, "pit_invariant_violations": violations}


def extract_cell_metrics(flow_path: Path, stdout_path: Path,
                         diagnostics_path: Path | None, fct_path: Path,
                         censored_path: Path, horizon_s: float, expected_flows: int):
    starts, finishes = parse_flow_events(flow_path)
    if len(starts) != expected_flows:
        raise ValueError(f"expected {expected_flows} START records, observed {len(starts)}")
    completed = []
    censored = []
    for key, (start, flowsize) in sorted(starts.items()):
        if key in finishes:
            finish, delivered = finishes[key]
            if finish < start:
                raise ValueError(f"FINISH precedes START for {key}")
            completed.append((key, start, finish, (finish - start) * 1e6, delivered))
        else:
            censored.append((key, start, flowsize))
    extra_finishes = set(finishes) - set(starts)
    if extra_finishes:
        raise ValueError(f"FINISH without START: {sorted(extra_finishes)}")

    with fct_path.open("w", encoding="ascii", newline="") as stream:
        stream.write("src_id\tflow_id\tstart_s\tfinish_s\tfct_us\tdelivered_bytes\n")
        for (src, flow), start, finish, fct_us, delivered in completed:
            stream.write(f"{src}\t{flow}\t{start:.9f}\t{finish:.9f}\t{fct_us:.6f}\t{delivered}\n")
    with censored_path.open("w", encoding="ascii", newline="") as stream:
        stream.write("src_id\tflow_id\tstart_s\tflowsize_bytes\tcensored_at_s\n")
        for (src, flow), start, flowsize in censored:
            stream.write(f"{src}\t{flow}\t{start:.9f}\t{flowsize}\t{horizon_s:.9f}\n")

    fcts = [row[3] for row in completed]
    delivered_bytes = parse_delivered_bytes(stdout_path, expected_flows)
    diag = pit_invariant_counts(diagnostics_path)
    summary_match = None
    with stdout_path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            if line.startswith("New:"):
                summary_match = re.search(r"New:\s+(\d+).*Rtx:\s+(\d+)", line)
    if summary_match is None:
        raise ValueError("missing New/Rtx simulator summary")
    return {
        "completion_count": len(completed), "censored_count": len(censored),
        "fct_sample_count": len(fcts),
        "fct_mean_us": mean(fcts) if fcts else math.nan,
        "fct_p50_us": percentile(fcts, 0.50), "fct_p95_us": percentile(fcts, 0.95),
        "delivered_bytes": delivered_bytes,
        "goodput_gbps": delivered_bytes * 8 / horizon_s / 1e9,
        "new": int(summary_match.group(1)), "rtx": int(summary_match.group(2)), **diag,
    }


def read_rows(summary_path: Path):
    with summary_path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        if reader.fieldnames is None or not set(REQUIRED_FIELDS).issubset(reader.fieldnames):
            raise ValueError("summary.tsv is missing required columns")
        rows, keys = [], set()
        for line, row in enumerate(reader, start=2):
            parsed = {name: (int(row[name]) if name in INT_FIELDS else float(row[name]))
                      for name in REQUIRED_FIELDS if name != "arm"}
            if row["arm"] not in ARM_ORDER:
                raise ValueError(f"unexpected arm in line {line}: {row['arm']}")
            key = (row["arm"], parsed["failed"], parsed["seed"])
            if key in keys:
                raise ValueError(f"duplicate summary key: {key}")
            keys.add(key)
            rows.append({"arm": row["arm"], **parsed})
    if not rows:
        raise ValueError("summary.tsv has no measurements")
    return rows


def aggregate(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["failed"], row["arm"])].append(row)
    result = {}
    for key, group in grouped.items():
        result[key] = {"n": len(group)}
        for field in ("completion_count", "censored_count", "goodput_gbps",
                      "fct_mean_us", "fct_p95_us", "pit_invariant_violations"):
            values = [row[field] for row in group if not math.isnan(row[field])]
            result[key][field + "_mean"] = mean(values) if values else math.nan
            result[key][field + "_error"] = stdev(values) if len(values) > 1 else 0.0
    return result


def render(aggregates, figure_path: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    failures = sorted({failed for failed, _ in aggregates})
    arms = [arm for arm in ARM_ORDER if any((failed, arm) in aggregates for failed in failures)]
    width = 0.8 / len(arms)
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.5), sharex=True)
    for index, arm in enumerate(arms):
        offset = (index - (len(arms) - 1) / 2) * width
        x = [position + offset for position in range(len(failures))]
        for axis, field in zip(axes, ("completion_count", "goodput_gbps")):
            axis.bar(x, [aggregates[(f, arm)][field + "_mean"] for f in failures], width,
                     yerr=[aggregates[(f, arm)][field + "_error"] for f in failures],
                     capsize=3, label=arm)
    for axis, label in zip(axes, ("Completed flows", "Delivered goodput (Gbps)")):
        axis.set_ylabel(label); axis.set_xlabel("Degraded core links (-failed)")
        axis.set_xticks(range(len(failures)), [str(value) for value in failures])
        axis.grid(axis="y", alpha=0.25)
    axes[0].legend(title="Arm"); fig.tight_layout(); fig.savefig(figure_path, dpi=180); plt.close(fig)


def write_report(rows, aggregates, report_path: Path, gate_status: str):
    lines = ["# ExpA gated falsification report", "", f"gate_status: {gate_status}", "",
             "FCT statistics use only observed START/FINISH pairs. Incomplete flows are listed",
             "in each `.censored.tsv` and are never assigned a zero FCT. Delivered goodput uses",
             "the exact application bytes reported by every sink over the 8 ms horizon.",
             "`pit_invariant_violations` is derived from post-event PIT fields in LAPS diagnostics.", "",
             "| failed | arm | seeds | completed | censored | FCT mean us | FCT p95 us | delivered Gbps | PIT violations |",
             "| ---: | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for failed, arm in sorted(aggregates, key=lambda item: (item[0], ARM_ORDER.index(item[1]))):
        value = aggregates[(failed, arm)]
        lines.append(f"| {failed} | {arm} | {value['n']} | {value['completion_count_mean']:.3f} | "
                     f"{value['censored_count_mean']:.3f} | {value['fct_mean_us_mean']:.3f} | "
                     f"{value['fct_p95_us_mean']:.3f} | {value['goodput_gbps_mean']:.6f} | "
                     f"{value['pit_invariant_violations_mean']:.3f} |")
    lines.extend(["", "## Per-run rows", "", "```tsv",
                  "\t".join(REQUIRED_FIELDS)])
    for row in sorted(rows, key=lambda value: (value["failed"], ARM_ORDER.index(value["arm"]), value["seed"])):
        lines.append("\t".join(str(row[field]) for field in REQUIRED_FIELDS))
    lines.extend(["```", ""])
    report_path.write_text("\n".join(lines), encoding="utf-8")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--extract-cell":
        parser = argparse.ArgumentParser()
        parser.add_argument("--extract-cell", action="store_true")
        parser.add_argument("--flow", required=True, type=Path)
        parser.add_argument("--stdout", required=True, type=Path)
        parser.add_argument("--diagnostics", type=Path)
        parser.add_argument("--fct-output", required=True, type=Path)
        parser.add_argument("--censored-output", required=True, type=Path)
        parser.add_argument("--horizon-seconds", required=True, type=float)
        parser.add_argument("--expected-flows", required=True, type=int)
        args = parser.parse_args()
        metrics = extract_cell_metrics(
            args.flow, args.stdout, args.diagnostics, args.fct_output,
            args.censored_output, args.horizon_seconds, args.expected_flows)
        print("\t".join(str(metrics[field]) for field in METRIC_FIELDS))
        return
    parser = argparse.ArgumentParser()
    parser.add_argument("summary_tsv", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--gate-status", required=True, choices=("passed",))
    args = parser.parse_args()
    rows = read_rows(args.summary_tsv)
    aggregates = aggregate(rows)
    figure_path, report_path = args.output_dir / "figure.png", args.output_dir / "report.md"
    if figure_path.exists() or report_path.exists():
        raise SystemExit("ERROR: refusing to overwrite figure.png or report.md")
    render(aggregates, figure_path)
    write_report(rows, aggregates, report_path, args.gate_status)


if __name__ == "__main__":
    main()
