#!/usr/bin/env python3
"""Plot the actual REPS cache actions against the resulting traffic distribution."""

from __future__ import annotations

import csv
import math
import os
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[4]))

from htsim.sim.datacenter.add_motivation.common.trace_schema import load_trace_compact


ROOT = HERE / "data" / "controlled" / "reps_actual_nscc_motivation_c25"
FIG_ROOT = HERE / "figs" / "controlled"
WARMUP_PS = 1_000_000_000
BIN_PS = 25_000_000
FIELDS = (
    "time_us", "healthy_qdelay_median_us", "reduced_qdelay_median_us",
    "all_sample_spread_us", "reduced_acked_byte_share_pct", "acked_bytes",
    "cache_admissions", "cache_slot_overwrites", "cache_reuses", "empty_cache_explores",
    "cumulative_slot_overwrites",
)


def _write_csv(path, rows):
    with path.open("w", newline="", encoding="ascii") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _median_or_nan(values):
    return statistics.median(values) / 1_000_000 if values else math.nan


def _summarize(bundle):
    path_class = {
        (row["flow_id"], row["entropy"]): row["contains_reduced_link"]
        for row in bundle.pathmap
    }
    bins = defaultdict(lambda: {
        "healthy": [], "reduced": [], "all": [], "acked_bytes": 0,
        "reduced_bytes": 0, "events": Counter(),
    })
    for ack in bundle.ack:
        if not ack["genuine_sample"] or ack["time_ps"] < WARMUP_PS:
            continue
        bucket = bins[ack["time_ps"] // BIN_PS]
        is_reduced = path_class[(ack["flow_id"], ack["entropy"])]
        bucket["all"].append(ack["qdelay_ps"])
        bucket["reduced" if is_reduced else "healthy"].append(ack["qdelay_ps"])
        bucket["acked_bytes"] += ack["newly_acked_bytes"]
        if is_reduced:
            bucket["reduced_bytes"] += ack["newly_acked_bytes"]
    for token in bundle.token:
        if token["time_ps"] >= WARMUP_PS:
            bins[token["time_ps"] // BIN_PS]["events"][token["operation"]] += 1

    rows = []
    cumulative_overwrites = 0
    for index in sorted(bins):
        bucket = bins[index]
        if not bucket["all"]:
            continue
        events = bucket["events"]
        overwrites = events["overwrite_good_ack"]
        cumulative_overwrites += overwrites
        rows.append({
            "time_us": (index * BIN_PS + BIN_PS / 2) / 1_000_000,
            "healthy_qdelay_median_us": _median_or_nan(bucket["healthy"]),
            "reduced_qdelay_median_us": _median_or_nan(bucket["reduced"]),
            "all_sample_spread_us": (max(bucket["all"]) - min(bucket["all"])) / 1_000_000,
            "reduced_acked_byte_share_pct": 100 * bucket["reduced_bytes"] / bucket["acked_bytes"],
            "acked_bytes": bucket["acked_bytes"],
            "cache_admissions": events["enqueue_good_ack"] + overwrites,
            "cache_slot_overwrites": overwrites,
            "cache_reuses": events["dequeue_recycle"],
            "empty_cache_explores": events["select_random_empty"],
            "cumulative_slot_overwrites": cumulative_overwrites,
        })
    if len(rows) < 12:
        raise ValueError("insufficient post-warmup samples")
    return rows


def _plot(scenario, rows):
    os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".matplotlib-cache"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(3, 1, figsize=(9.2, 6.8), sharex=True,
                                gridspec_kw={"height_ratios": (3.2, 2.3, 2.6)})
    delay_axis, distribution_axis, cache_axis = axes
    time = [row["time_us"] for row in rows]

    delay_axis.plot(time, [row["healthy_qdelay_median_us"] for row in rows],
                    color="#2378b5", linewidth=1.5, label="healthy-path median")
    delay_axis.plot(time, [row["reduced_qdelay_median_us"] for row in rows],
                    color="#d1495b", linewidth=1.5, label="25Gbps-path median")
    delay_axis.plot(time, [row["all_sample_spread_us"] for row in rows],
                    color="#555555", linewidth=1.0, linestyle="--", label="all-sample delay range")
    delay_axis.axhline(14, color="black", linewidth=0.8, linestyle=":", label="14us reference")
    delay_axis.set_ylabel("queuing delay (us)")
    delay_axis.set_title(
        f"Actual 8-entry REPS + NSCC, {scenario} capacity case (25Gbps)"
    )
    delay_axis.grid(alpha=0.25)
    delay_axis.legend(frameon=False, ncol=2, fontsize=8)

    distribution_axis.plot(time, [row["reduced_acked_byte_share_pct"] for row in rows],
                           color="#d1495b", linewidth=1.5)
    distribution_axis.set_ylabel("25Gbps-path traffic (%)")
    distribution_axis.set_ylim(bottom=0)
    distribution_axis.grid(alpha=0.25)

    cache_axis.plot(time, [row["cache_slot_overwrites"] for row in rows],
                    color="#59a14f", linewidth=1.2, label="circular-slot overwrites")
    cache_axis.plot(time, [row["cache_reuses"] for row in rows],
                    color="#2378b5", linewidth=1.2, label="cached-entropy reuses")
    cache_axis.plot(time, [row["empty_cache_explores"] for row in rows],
                    color="#f28e2b", linewidth=1.1, label="empty-cache explores")
    cache_axis.set_ylabel("REPS actions / 25us")
    cache_axis.set_xlabel("time (us)")
    cache_axis.grid(alpha=0.25)
    cache_axis.legend(frameon=False, ncol=3, fontsize=7, loc="upper right")
    figure.tight_layout()

    FIG_ROOT.mkdir(parents=True, exist_ok=True)
    stem = FIG_ROOT / f"m2_reps_actual_nscc_motivation_c25_{scenario}"
    figure.savefig(stem.with_suffix(".png"), dpi=180, bbox_inches="tight")
    figure.savefig(stem.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(figure)


def _plot_persistent_paper_panels(rows):
    """Export the two result panels as separate single-column paper figures."""
    os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".matplotlib-cache"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    FIG_ROOT.mkdir(parents=True, exist_ok=True)
    time = [row["time_us"] for row in rows]

    with plt.rc_context({"font.size": 24}):
        figure, axis = plt.subplots()
        axis.plot(time, [row["healthy_qdelay_median_us"] for row in rows],
                  color="C0", linewidth=2)
        axis.plot(time, [row["reduced_qdelay_median_us"] for row in rows],
                  color="C1", linewidth=2)
        axis.plot(time, [row["all_sample_spread_us"] for row in rows],
                  color="C3", linewidth=2, linestyle="--")
        axis.axhline(14, color="black", linewidth=2, linestyle=":")
        axis.set_xlabel("time (us)")
        axis.set_ylabel("Queueing delay (us)")
        axis.grid(alpha=0.3)
        figure.tight_layout()
        stem = FIG_ROOT / "m2_reps_actual_nscc_persistent_delay"
        figure.savefig(stem.with_suffix(".pdf"), bbox_inches="tight", pad_inches=0.05)
        figure.savefig(stem.with_suffix(".png"), dpi=140, bbox_inches="tight", pad_inches=0.05)
        plt.close(figure)

        figure, axis = plt.subplots()
        throttled = [row["reduced_acked_byte_share_pct"] for row in rows]
        healthy = [100 - value for value in throttled]
        axis.plot(time, healthy, color="C0", linewidth=2)
        axis.plot(time, throttled, color="C1", linewidth=2)
        axis.set_xlabel("time (us)")
        axis.set_ylabel("Traffic ratio (%)")
        axis.set_ylim(0, 100)
        axis.grid(alpha=0.3)
        figure.tight_layout()
        stem = FIG_ROOT / "m2_reps_actual_nscc_persistent_traffic"
        figure.savefig(stem.with_suffix(".pdf"), bbox_inches="tight", pad_inches=0.05)
        figure.savefig(stem.with_suffix(".png"), dpi=140, bbox_inches="tight", pad_inches=0.05)
        plt.close(figure)

    from matplotlib.lines import Line2D
    with plt.rc_context({"font.size": 18}):
        legend = plt.figure(figsize=(8, 1.1))
        handles = (
            Line2D([], [], color="C0", linewidth=2, label="healthy-path"),
            Line2D([], [], color="C1", linewidth=2, label="throttled-path"),
            Line2D([], [], color="C3", linewidth=2, linestyle="--",
                   label="cross-flow delay range"),
            Line2D([], [], color="black", linewidth=2, linestyle=":",
                   label="target queueing delay"),
        )
        legend.legend(handles=handles, loc="center", ncol=2, frameon=False)
        stem = FIG_ROOT / "m2_reps_actual_nscc_persistent_legend"
        legend.savefig(stem.with_suffix(".pdf"), bbox_inches="tight", pad_inches=0.05)
        legend.savefig(stem.with_suffix(".png"), dpi=140, bbox_inches="tight", pad_inches=0.05)
        plt.close(legend)


def main():
    for scenario in ("recoverable", "persistent"):
        prefix = ROOT / f"reps_actual_nscc_c25_{scenario}_s101"
        rows = _summarize(load_trace_compact(prefix))
        _write_csv(ROOT / f"reps_actual_nscc_c25_{scenario}_global_series.csv", rows)
        _plot(scenario, rows)
        first = statistics.mean(row["reduced_acked_byte_share_pct"] for row in rows[:10])
        last = statistics.mean(row["reduced_acked_byte_share_pct"] for row in rows[-10:])
        print(
            f"{scenario}: bins={len(rows)}, reduced_share_first_250us={first:.2f}%, "
            f"last_250us={last:.2f}%, overwrites={rows[-1]['cumulative_slot_overwrites']}"
        )
        if scenario == "persistent":
            _plot_persistent_paper_panels(rows)


if __name__ == "__main__":
    main()
