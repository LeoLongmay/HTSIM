#!/usr/bin/env python3
"""Validate and render the isolated ExpA strict-LAPS smoke comparison."""
import argparse
import csv
import math
import pathlib
import statistics
import sys

HERE = pathlib.Path(__file__).resolve().parent
COMMON = HERE.parents[1] / "common"
sys.path.insert(0, str(COMMON))
import metrics  # noqa: E402
import plot_style  # noqa: E402

ARMS = (("ops", "OPS", "ops"), ("reps", "REPS", "reps"),
        ("decmt", "DecMT", "prism"), ("laps", "LAPS", "laps"))
FAILEDS = (0, 8)
SEEDS = (13, 14, 15)
METRICS = ("goodput_gbps", "avg_fct_us", "p99_fct_us", "completion_rate")


def tag(arm, failed, seed):
    return f"expA_smoke_{arm}_f{failed}_s{seed}"


def parse_run(flow_path):
    stats = metrics.fct_stats(flow_path)
    row = {
        "goodput_gbps": metrics.aggregate_goodput_gbps(flow_path),
        "avg_fct_us": stats["avg_s"] * 1e6,
        "p99_fct_us": stats["p99_s"] * 1e6,
        "completion_rate": stats["completion_rate"],
    }
    if row["completion_rate"] < 1.0:
        raise RuntimeError(f"{flow_path.stem}: completion_rate={row['completion_rate']:.6f}")
    if not all(math.isfinite(value) for value in row.values()):
        raise RuntimeError(f"non-finite metric in {flow_path.name}")
    return row


def require_complete_matrix(data_dir):
    rows = []
    for arm, _, _ in ARMS:
        for failed in FAILEDS:
            for seed in SEEDS:
                run_tag = tag(arm, failed, seed)
                flow_path = data_dir / f"{run_tag}.flow.txt"
                if not flow_path.is_file():
                    raise RuntimeError(f"missing required cell: {run_tag}")
                row = parse_run(flow_path)
                row.update(arm=arm, failed=failed, seed=seed)
                rows.append(row)
    if len({(row['arm'], row['failed'], row['seed']) for row in rows}) != 24:
        raise RuntimeError("duplicate smoke matrix key")
    return rows


def write_summary(rows, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("row_type", "arm", "failed", "seed", "metric", "value", "mean", "min", "max"))
        writer.writeheader()
        for row in rows:
            for metric in METRICS:
                writer.writerow({"row_type": "seed", "arm": row["arm"], "failed": row["failed"], "seed": row["seed"], "metric": metric, "value": row[metric], "mean": "", "min": "", "max": ""})
        for arm, _, _ in ARMS:
            for failed in FAILEDS:
                group = [row for row in rows if row["arm"] == arm and row["failed"] == failed]
                for metric in METRICS:
                    values = [row[metric] for row in group]
                    writer.writerow({"row_type": "aggregate", "arm": arm, "failed": failed, "seed": "", "metric": metric, "value": "", "mean": statistics.mean(values), "min": min(values), "max": max(values)})


def render(rows, figs_dir):
    import matplotlib.pyplot as plt
    plot_style.apply_style(13)
    figs_dir.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(3, 1, figsize=(5.2, 8.0), sharex=True)
    for axis, (metric, ylabel) in zip(axes, (("goodput_gbps", "Goodput (Gbps)"), ("avg_fct_us", "Avg FCT (us)"), ("p99_fct_us", "P99 FCT (us)"))):
        for arm, display, color in ARMS:
            means, lower, upper = [], [], []
            for failed in FAILEDS:
                values = [row[metric] for row in rows if row["arm"] == arm and row["failed"] == failed]
                mean = statistics.mean(values)
                means.append(mean); lower.append(mean - min(values)); upper.append(max(values) - mean)
            axis.errorbar(FAILEDS, means, yerr=[lower, upper], marker="o", lw=2, ms=6, capsize=3, color=plot_style.COLORS[color], label=display)
        axis.set_ylabel(ylabel); axis.grid(alpha=0.3)
    axes[0].legend(fontsize=9)
    axes[-1].set_xlabel("Degraded core links (-failed)")
    axes[-1].set_xticks(FAILEDS)
    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(figs_dir / f"expA_laps_smoke_performance.{ext}", bbox_inches="tight")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=pathlib.Path, default=HERE / "data")
    parser.add_argument("--figs-dir", type=pathlib.Path, default=HERE / "figs")
    args = parser.parse_args()
    rows = require_complete_matrix(args.data_dir)
    write_summary(rows, args.data_dir / "summary.csv")
    render(rows, args.figs_dir)


if __name__ == "__main__":
    main()
