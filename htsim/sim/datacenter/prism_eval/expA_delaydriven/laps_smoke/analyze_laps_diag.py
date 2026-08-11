#!/usr/bin/env python3
"""Summarize opt-in strict-LAPS diagnostics without altering simulation behavior."""
import argparse
import csv
import pathlib

HEADER = "time_ns,event_seq,flow,event_type,pid,seq,bytes,rate_bps,target_rate_bps,all_paths_high,target_delay_ns,min_delay_ns,one_way_delay_ns,recovery_cause,timer_deadline_ns,is_retransmission,outstanding_probes,pit_valid,pit_selectable,pit_probe_pending,pit_updated_at_ns,pit_deadline_ns".split(",")
EVENTS = {"rate_update", "probe_sent", "probe_acked", "data_sent", "data_acked",
          "recovery", "recovery_timer_armed", "recovery_timeout_fired"}
CAUSES = {"ack_gap", "timeout", "nack"}


def read_trace(path):
    with pathlib.Path(path).open(newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != HEADER:
            raise ValueError("invalid LAPS diagnostic CSV header")
        rows = list(reader)
    previous = -1
    for row in rows:
        if row["event_type"] not in EVENTS:
            raise ValueError("unknown LAPS event type")
        sequence = int(row["event_seq"])
        if sequence <= previous:
            raise ValueError("non-monotonic LAPS event sequence")
        previous = sequence
        if row["event_type"] == "recovery" and row["recovery_cause"] not in CAUSES:
            raise ValueError("unknown LAPS recovery cause")
    return rows


def flow_completion(path):
    lines = [line for line in pathlib.Path(path).read_text().splitlines() if line.strip()]
    completed = len(lines) // 2
    total = max(completed, 64)
    return {"completed": completed, "total": total}


def summarize(run_name, events, completion):
    rates = [int(row["rate_bps"]) for row in events if row["event_type"] == "rate_update" and row["rate_bps"]]
    data = [row for row in events if row["event_type"] == "data_sent"]
    probes_sent = sum(row["event_type"] == "probe_sent" for row in events)
    probes_acked = sum(row["event_type"] == "probe_acked" for row in events)
    by_pid = {}
    for row in data:
        by_pid[row["pid"]] = by_pid.get(row["pid"], 0) + 1
    total_data = len(data)
    recovery = {cause: sum(row["event_type"] == "recovery" and row["recovery_cause"] == cause for row in events) for cause in CAUSES}
    return {
        "run": run_name, "completed": completion["completed"], "total": completion["total"],
        "completion_rate": completion["completed"] / completion["total"],
        "min_rate_bps": min(rates) if rates else "", "last_rate_bps": rates[-1] if rates else "",
        "rate_updates": len(rates), "probe_sent": probes_sent, "probe_acked": probes_acked,
        "probe_ack_ratio": probes_acked / probes_sent if probes_sent else "",
        "data_sent": total_data, "pid_data_share_max": max(by_pid.values()) / total_data if total_data else "",
        "ack_gap_recovery": recovery["ack_gap"], "timeout_recovery": recovery["timeout"],
        "nack_recovery": recovery["nack"],
    }


def diagnosis_lines(degraded, reference):
    lines = ["# Strict-LAPS Diagnostic Evidence", "", "This report is observational; it does not tune LAPS.", ""]
    for row in (reference, degraded):
        lines.append(f"- {row['run']}: completion {row['completed']}/{row['total']} ({row['completion_rate']:.3%}), min rate {row['min_rate_bps']}, probe ACK ratio {row['probe_ack_ratio']}, max PID share {row['pid_data_share_max']:.3f}.")
    labels = []
    if degraded["min_rate_bps"] != "" and degraded["min_rate_bps"] <= 1: labels.append("severe rate collapse")
    if degraded["probe_ack_ratio"] != "" and degraded["probe_ack_ratio"] < 0.8: labels.append("poor probe ACK coverage")
    if degraded["pid_data_share_max"] != "" and degraded["pid_data_share_max"] > 0.5: labels.append("concentrated PID selection")
    if degraded["data_sent"] and (degraded["ack_gap_recovery"] + degraded["timeout_recovery"] + degraded["nack_recovery"]) / degraded["data_sent"] > 0.1: labels.append("high private-recovery pressure")
    lines.extend(["", "Evidence labels: " + (", ".join(labels) if labels else "none triggered")])
    return lines


def main():
    parser = argparse.ArgumentParser()
    for prefix in ("degraded", "reference"):
        parser.add_argument(f"--{prefix}-trace", required=True, type=pathlib.Path)
        parser.add_argument(f"--{prefix}-flow", required=True, type=pathlib.Path)
    parser.add_argument("--output-dir", required=True, type=pathlib.Path)
    args = parser.parse_args()
    rows = [summarize(name, read_trace(getattr(args, f"{name}_trace")), flow_completion(getattr(args, f"{name}_flow"))) for name in ("reference", "degraded")]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir / "summary.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys()); writer.writeheader(); writer.writerows(rows)
    (args.output_dir / "diagnosis.md").write_text("\n".join(diagnosis_lines(rows[1], rows[0])) + "\n")


if __name__ == "__main__":
    main()
