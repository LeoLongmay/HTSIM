#!/usr/bin/env python3
"""Offline, observation-only PRIME penalty-lifecycle analysis."""
import argparse
import csv
import math
import pathlib
import statistics


LIFECYCLE_FIELDS = (
    "flow", "episode", "feedback_type", "feedback_time_ps", "tuple",
    "penalty_before", "penalty_after", "selections_until_reselect",
    "time_until_reselect_ps", "distinct_tuples_before_reselect",
    "first_reselection_reason", "selected_penalty_before_reselect", "censored",
)
AGGREGATE_FIELDS = (
    "failed", "feedback_type", "episode_count", "resolved_count", "censored_count",
    "p50_selections_until_reselect", "p95_selections_until_reselect",
    "p50_time_until_reselect_ps", "p95_time_until_reselect_ps",
)
FAILURE_FEEDBACK = frozenset(("ecn", "nack", "timeout"))


def _event_key(event, fallback):
    """Keep trace order deterministic; legacy traces retain file order."""
    value = event.get("event_seq", "")
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _blank_episode(event, episode):
    return {
        "flow": int(event["flow"]),
        "episode": episode,
        "feedback_type": event["feedback"],
        "feedback_time_ps": int(event["time_ps"]),
        "tuple": event["tuple"],
        "penalty_before": event.get("penalty_before", ""),
        "penalty_after": event.get("penalty_after", ""),
        "selections_until_reselect": 0,
        "time_until_reselect_ps": None,
        "distinct_tuples_before_reselect": set(),
        "first_reselection_reason": "",
        "selected_penalty_before_reselect": "",
        "censored": True,
    }


def analyze_events(events):
    """Return resolved and end-of-trace-censored feedback episodes.

    Events are ordered by diagnostic sequence, partitioned by flow, and may
    contain multiple open episodes per flow.  A selection resolves every open
    episode for that flow whose failed tuple it reselects.  The reselected
    tuple itself is intentionally excluded from ``distinct_tuples_before``.
    """
    ordered = sorted(enumerate(events), key=lambda item: _event_key(item[1], item[0]))
    pending, rows, next_episode = {}, [], {}
    for _, event in ordered:
        flow = int(event["flow"])
        if event.get("event") == "feedback" and event.get("feedback") in FAILURE_FEEDBACK:
            episode = next_episode.get(flow, 0) + 1
            next_episode[flow] = episode
            pending.setdefault(flow, []).append(_blank_episode(event, episode))
            continue
        if event.get("event") != "selection":
            continue
        survivors = []
        for episode in pending.get(flow, []):
            episode["selections_until_reselect"] += 1
            if event.get("tuple") != episode["tuple"]:
                episode["distinct_tuples_before_reselect"].add(event.get("tuple", ""))
                survivors.append(episode)
                continue
            episode["time_until_reselect_ps"] = int(event["time_ps"]) - episode["feedback_time_ps"]
            episode["first_reselection_reason"] = event.get("reason", "")
            episode["selected_penalty_before_reselect"] = event.get("penalty_before", "")
            episode["censored"] = False
            episode["distinct_tuples_before_reselect"] = len(
                episode["distinct_tuples_before_reselect"])
            rows.append(episode)
        pending[flow] = survivors
    for flow in sorted(pending):
        for episode in pending[flow]:
            episode["distinct_tuples_before_reselect"] = len(
                episode["distinct_tuples_before_reselect"])
            rows.append(episode)
    return sorted(rows, key=lambda row: (row["feedback_time_ps"], row["flow"], row["episode"]))


def read_events(path):
    with pathlib.Path(path).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def analyze_input(input_path):
    input_path = pathlib.Path(input_path)
    traces = [input_path] if input_path.is_file() else sorted(input_path.rglob("*.prime.tsv"))
    if not traces:
        raise RuntimeError(f"no PRIME diagnostic TSV files found in {input_path}")
    return [row for trace in traces for row in analyze_events(read_events(trace))]


def _percentile(values, fraction):
    if not values:
        return math.nan
    values = sorted(values)
    return values[round(fraction * (len(values) - 1))]


def _failed_from_path(path):
    for component in pathlib.Path(path).parts:
        marker = "_f"
        if marker in component:
            suffix = component.rsplit(marker, 1)[1]
            candidate = suffix.split("_", 1)[0]
            if candidate.isdigit():
                return int(candidate)
    return ""


def aggregate_input(input_path):
    input_path = pathlib.Path(input_path)
    traces = [input_path] if input_path.is_file() else sorted(input_path.rglob("*.prime.tsv"))
    groups = {}
    for trace in traces:
        failed = _failed_from_path(trace)
        for row in analyze_events(read_events(trace)):
            groups.setdefault((failed, row["feedback_type"]), []).append(row)
    output = []
    for (failed, feedback), rows in sorted(groups.items(), key=lambda item: (str(item[0][0]), item[0][1])):
        resolved = [row for row in rows if not row["censored"]]
        output.append({
            "failed": failed, "feedback_type": feedback, "episode_count": len(rows),
            "resolved_count": len(resolved), "censored_count": len(rows) - len(resolved),
            "p50_selections_until_reselect": _percentile(
                [row["selections_until_reselect"] for row in resolved], 0.50),
            "p95_selections_until_reselect": _percentile(
                [row["selections_until_reselect"] for row in resolved], 0.95),
            "p50_time_until_reselect_ps": _percentile(
                [row["time_until_reselect_ps"] for row in resolved], 0.50),
            "p95_time_until_reselect_ps": _percentile(
                [row["time_until_reselect_ps"] for row in resolved], 0.95),
        })
    return output


def _write_tsv(path, fields, rows):
    with pathlib.Path(path).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                key: "" if value is None else str(value).lower() if isinstance(value, bool) else value
                for key, value in row.items()
            })


def render_lifecycle(rows, output_path):
    import matplotlib.pyplot as plt

    labels = [f"f={row['failed']}\n{row['feedback_type']}" for row in rows]
    resolved = [row["resolved_count"] for row in rows]
    censored = [row["censored_count"] for row in rows]
    fig, axis = plt.subplots(figsize=(max(4.5, len(rows) * 1.1), 3.5))
    positions = list(range(len(rows)))
    axis.bar(positions, resolved, label="resolved", color="#4477aa")
    axis.bar(positions, censored, bottom=resolved, label="censored", color="#cc6677")
    axis.set_xticks(positions, labels)
    axis.set_ylabel("Penalty episodes")
    axis.set_title("PRIME feedback penalty lifecycle")
    axis.grid(axis="y", alpha=0.3)
    axis.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=160)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    _write_tsv(args.output / "prime_penalty_lifecycle.tsv", LIFECYCLE_FIELDS,
               analyze_input(args.input))
    aggregates = aggregate_input(args.input)
    _write_tsv(args.output / "prime_penalty_lifecycle_summary.tsv", AGGREGATE_FIELDS, aggregates)
    render_lifecycle(aggregates, args.output / "fig_prime_penalty_lifecycle.png")


if __name__ == "__main__":
    main()
