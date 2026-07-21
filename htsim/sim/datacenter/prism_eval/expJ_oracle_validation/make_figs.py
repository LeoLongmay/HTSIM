#!/usr/bin/env python3
import argparse
import csv
import math
import os
import statistics
import sys
import tempfile
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
PRISM_EVAL = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(PRISM_EVAL, "common"))
from plot_style import COLORS, apply_style, save  # noqa: E402

RAW_DIR = os.path.join(HERE, "data", "raw")
SUMMARY_CSV = os.path.join(HERE, "data", "summary.csv")
CONFUSION_CSV = os.path.join(HERE, "data", "confusion.csv")
LEAD_LAG_CSV = os.path.join(HERE, "data", "lead_lag.csv")
FIG_DIR = os.path.join(HERE, "figs")

REQUIRED = {
    "run_id", "seed", "scenario", "flow_id", "epoch_id", "epoch_start_ns",
    "epoch_end_ns", "kappa", "n_min", "t_cc_us", "t_spray_us",
    "num_ack_samples", "num_oracle_ack_snapshots",
    "num_distinct_sampled_entropies", "num_eligible_entropies",
    "entropy_coverage_ratio", "num_distinct_sampled_paths", "num_eligible_paths",
    "path_coverage_ratio", "oracle_resolution_failures", "epoch_sample_deferred",
    "row_status", "est_smoothed_cc_us", "est_smoothed_spray_us",
    "oracle_smoothed_cc_us", "oracle_smoothed_spray_us",
    "boundary_oracle_smoothed_cc_us", "boundary_oracle_smoothed_spray_us",
    "oracle_mean_instant_cc_us", "oracle_mean_instant_spray_us",
    "oracle_floor_temporal_range_us", "est_state", "oracle_state",
    "boundary_oracle_state", "state_match", "boundary_state_match",
    "abs_error_cc_us", "abs_error_spray_us", "boundary_abs_error_cc_us",
    "boundary_abs_error_spray_us",
}
STATES = ["Increase", "Hold", "Decrease"]
COVERAGE_BUCKETS = [
    ("<=25%", lambda x: x <= 0.25),
    ("25-50%", lambda x: 0.25 < x <= 0.50),
    ("50-75%", lambda x: 0.50 < x <= 0.75),
    (">75%", lambda x: x > 0.75),
]


def f(row, key):
    return float(row[key])


def percentile(values, pct):
    if not values:
        return math.nan
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * pct / 100.0
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return xs[lo]
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def read_rows(raw_dir=RAW_DIR):
    rows = []
    names = sorted(os.listdir(raw_dir)) if os.path.isdir(raw_dir) else []
    for name in names:
        if not name.endswith(".csv"):
            continue
        path = os.path.join(raw_dir, name)
        with open(path, newline="") as fp:
            reader = csv.DictReader(fp)
            missing = REQUIRED - set(reader.fieldnames or [])
            if missing:
                raise SystemExit(
                    f"{path}: old or malformed oracle schema; missing {sorted(missing)}. "
                    "Rerun expJ before aggregating."
                )
            for line_no, row in enumerate(reader, start=2):
                try:
                    for key in ("kappa", "t_cc_us", "t_spray_us", "entropy_coverage_ratio",
                                "path_coverage_ratio", "est_smoothed_cc_us",
                                "est_smoothed_spray_us"):
                        float(row[key])
                    for key in ("seed", "n_min", "num_ack_samples",
                                "num_oracle_ack_snapshots", "num_distinct_sampled_entropies",
                                "num_eligible_entropies", "num_distinct_sampled_paths",
                                "num_eligible_paths", "oracle_resolution_failures",
                                "epoch_sample_deferred"):
                        int(row[key])
                    if row["row_status"] == "ok":
                        for key in ("oracle_smoothed_cc_us", "oracle_smoothed_spray_us",
                                    "boundary_oracle_smoothed_cc_us",
                                    "boundary_oracle_smoothed_spray_us", "abs_error_cc_us",
                                    "abs_error_spray_us", "boundary_abs_error_cc_us",
                                    "boundary_abs_error_spray_us"):
                            if not math.isfinite(float(row[key])):
                                raise ValueError(f"non-finite {key}")
                except ValueError as exc:
                    raise SystemExit(f"{path}:{line_no}: malformed field: {exc}")
                for key in ("entropy_coverage_ratio", "path_coverage_ratio"):
                    value = f(row, key)
                    if math.isfinite(value) and not 0.0 <= value <= 1.0:
                        raise SystemExit(f"{path}:{line_no}: {key} outside [0,1]: {value}")
                rows.append(row)
    if not rows:
        raise SystemExit(f"no raw oracle CSV files found under {raw_dir}")
    return rows


def valid_rows(rows):
    return [r for r in rows if r["row_status"] == "ok"]


def _agreement(rs, key="state_match"):
    return sum(int(r[key]) for r in rs) / len(rs) if rs else math.nan


def aggregate(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(row["scenario"], f(row, "kappa"), int(row["n_min"]))].append(row)

    os.makedirs(os.path.dirname(SUMMARY_CSV), exist_ok=True)
    summary_fields = [
        "scenario", "kappa", "n_min", "valid_epochs", "skipped_epochs",
        "sample_deferred_epochs", "state_agreement", "boundary_state_agreement",
        "agreement_increase", "agreement_hold", "agreement_decrease",
        "median_abs_error_cc_us", "p90_abs_error_cc_us", "p99_abs_error_cc_us",
        "median_abs_error_spray_us", "p90_abs_error_spray_us", "p99_abs_error_spray_us",
        "boundary_p90_abs_error_cc_us", "boundary_p90_abs_error_spray_us",
        "median_entropy_coverage", "median_path_coverage", "false_spread_rate",
        "median_oracle_instant_spread_us", "median_oracle_floor_temporal_range_us",
    ]
    summary = []
    for (scenario, kappa, n_min), all_rs in sorted(groups.items()):
        rs = valid_rows(all_rs)
        row = {
            "scenario": scenario,
            "kappa": f"{kappa:g}",
            "n_min": n_min,
            "valid_epochs": len(rs),
            "skipped_epochs": len(all_rs) - len(rs),
            "sample_deferred_epochs": sum(int(r["epoch_sample_deferred"]) for r in all_rs),
            "state_agreement": _agreement(rs),
            "boundary_state_agreement": _agreement(rs, "boundary_state_match"),
        }
        for state in STATES:
            state_rs = [r for r in rs if r["oracle_state"] == state]
            row[f"agreement_{state.lower()}"] = _agreement(state_rs)
        for comp in ("cc", "spray"):
            errors = [f(r, f"abs_error_{comp}_us") for r in rs]
            row[f"median_abs_error_{comp}_us"] = statistics.median(errors) if errors else math.nan
            row[f"p90_abs_error_{comp}_us"] = percentile(errors, 90)
            row[f"p99_abs_error_{comp}_us"] = percentile(errors, 99)
            row[f"boundary_p90_abs_error_{comp}_us"] = percentile(
                [f(r, f"boundary_abs_error_{comp}_us") for r in rs], 90)
        row["median_entropy_coverage"] = (
            statistics.median(f(r, "entropy_coverage_ratio") for r in rs) if rs else math.nan)
        row["median_path_coverage"] = (
            statistics.median(f(r, "path_coverage_ratio") for r in rs) if rs else math.nan)
        false_den = [r for r in rs if f(r, "oracle_smoothed_spray_us") < f(r, "t_spray_us")]
        false_num = [r for r in false_den
                     if f(r, "est_smoothed_spray_us") >= f(r, "t_spray_us")]
        row["false_spread_rate"] = (len(false_num) / len(false_den)
                                    if scenario == "symmetric" and false_den else math.nan)
        row["median_oracle_instant_spread_us"] = (
            statistics.median(f(r, "oracle_mean_instant_spray_us") for r in rs)
            if rs else math.nan)
        row["median_oracle_floor_temporal_range_us"] = (
            statistics.median(f(r, "oracle_floor_temporal_range_us") for r in rs)
            if rs else math.nan)
        summary.append(row)

    with open(SUMMARY_CSV, "w", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=summary_fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(summary)

    with open(CONFUSION_CSV, "w", newline="") as fp:
        fields = ["scenario", "kappa", "n_min", "oracle_kind", "est_state",
                  "oracle_state", "count", "row_pct"]
        writer = csv.DictWriter(fp, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for (scenario, kappa, n_min), all_rs in sorted(groups.items()):
            rs = valid_rows(all_rs)
            for kind, oracle_key in (("ack_time_envelope", "oracle_state"),
                                     ("boundary_snapshot", "boundary_oracle_state")):
                counts = Counter((r["est_state"], r[oracle_key]) for r in rs)
                row_totals = Counter(r["est_state"] for r in rs)
                for est in STATES:
                    for oracle in STATES:
                        count = counts[(est, oracle)]
                        writer.writerow({
                            "scenario": scenario, "kappa": f"{kappa:g}", "n_min": n_min,
                            "oracle_kind": kind, "est_state": est, "oracle_state": oracle,
                            "count": count,
                            "row_pct": count / row_totals[est] if row_totals[est] else math.nan,
                        })
    write_lead_lag(rows)
    return summary


def write_lead_lag(rows):
    series = defaultdict(list)
    for row in valid_rows(rows):
        key = (row["scenario"], f(row, "kappa"), int(row["n_min"]),
               row["run_id"], row["flow_id"])
        series[key].append(row)
    for rs in series.values():
        rs.sort(key=lambda r: int(r["epoch_id"]))

    out = defaultdict(list)
    for key, rs in series.items():
        scenario, kappa, n_min, _run, _flow = key
        by_epoch = {int(r["epoch_id"]): r for r in rs}
        for est in rs:
            epoch = int(est["epoch_id"])
            for lag in range(-2, 3):
                oracle = by_epoch.get(epoch + lag)
                if oracle:
                    out[(scenario, kappa, n_min, lag)].append((est, oracle))

    fields = ["scenario", "kappa", "n_min", "oracle_epoch_offset", "paired_epochs",
              "state_agreement", "median_abs_error_cc_us", "median_abs_error_spray_us"]
    with open(LEAD_LAG_CSV, "w", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for (scenario, kappa, n_min, lag), pairs in sorted(out.items()):
            cc = [abs(f(est, "est_smoothed_cc_us")
                      - f(oracle, "boundary_oracle_smoothed_cc_us")) for est, oracle in pairs]
            spray = [abs(f(est, "est_smoothed_spray_us")
                         - f(oracle, "boundary_oracle_smoothed_spray_us"))
                     for est, oracle in pairs]
            writer.writerow({
                "scenario": scenario, "kappa": f"{kappa:g}", "n_min": n_min,
                "oracle_epoch_offset": lag, "paired_epochs": len(pairs),
                "state_agreement": sum(est["est_state"] == oracle["boundary_oracle_state"]
                                       for est, oracle in pairs) / len(pairs),
                "median_abs_error_cc_us": statistics.median(cc),
                "median_abs_error_spray_us": statistics.median(spray),
            })


def coverage_rows(rows):
    out = {}
    rs_valid = valid_rows(rows)
    for scenario in sorted(set(r["scenario"] for r in rs_valid)):
        for label, pred in COVERAGE_BUCKETS:
            rs = [r for r in rs_valid
                  if r["scenario"] == scenario and pred(f(r, "path_coverage_ratio"))]
            if rs:
                out[(scenario, label)] = (len(rs), _agreement(rs))
    return out


def stream_coverage_rows(raw_dir=RAW_DIR):
    counts = Counter()
    matches = Counter()
    names = sorted(os.listdir(raw_dir)) if os.path.isdir(raw_dir) else []
    for name in names:
        if not name.endswith(".csv"):
            continue
        with open(os.path.join(raw_dir, name), newline="") as fp:
            for row in csv.DictReader(fp):
                if row.get("row_status") != "ok":
                    continue
                coverage = float(row["path_coverage_ratio"])
                for label, pred in COVERAGE_BUCKETS:
                    if pred(coverage):
                        key = (row["scenario"], label)
                        counts[key] += 1
                        matches[key] += int(row["state_match"])
                        break
    return {key: (count, matches[key] / count) for key, count in counts.items()}


def render(summary, cov):
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    apply_style(10)
    fig, axes = plt.subplots(1, 3, figsize=(11.5, 3.2))
    settings = sorted({(float(r["kappa"]), int(r["n_min"])) for r in summary})
    scenarios = sorted({r["scenario"] for r in summary})
    lookup = {(r["scenario"], float(r["kappa"]), int(r["n_min"])): r for r in summary}
    x = list(range(len(settings)))
    labels = [f"{k:g}/{n}" for k, n in settings]
    scenario_colors = dict(zip(scenarios, ["tab:blue", "tab:orange", "tab:green"]))

    for scenario in scenarios:
        color = scenario_colors[scenario]
        aligned = [float(lookup[(scenario, k, n)]["state_agreement"]) for k, n in settings]
        boundary = [float(lookup[(scenario, k, n)]["boundary_state_agreement"])
                    for k, n in settings]
        axes[0].plot(x, aligned, color=color, marker="o", ms=3, lw=1.5, label=scenario)
        axes[0].plot(x, boundary, color=color, marker=".", ms=2, lw=1.0, ls="--")
    axes[0].set_ylim(0, 1.02); axes[0].set_ylabel("state agreement")
    axes[0].set_xticks(x); axes[0].set_xticklabels(labels, rotation=45, ha="right")
    axes[0].set_xlabel("kappa / n_min")
    oracle_handles = [
        Line2D([0], [0], color="0.25", lw=1.5, label="ACK-time envelope"),
        Line2D([0], [0], color="0.25", lw=1.0, ls="--", label="boundary snapshot"),
    ]
    scenario_handles = [Line2D([0], [0], color=scenario_colors[s], lw=1.5, label=s)
                        for s in scenarios]
    axes[0].legend(handles=scenario_handles + oracle_handles, frameon=False, fontsize=7,
                   ncol=2, loc="lower right")

    for scenario in scenarios:
        color = scenario_colors[scenario]
        cc = [float(lookup[(scenario, k, n)]["p90_abs_error_cc_us"]) for k, n in settings]
        spray = [float(lookup[(scenario, k, n)]["p90_abs_error_spray_us"])
                 for k, n in settings]
        axes[1].plot(x, cc, color=color, marker="o", ms=3, lw=1.5)
        axes[1].plot(x, spray, color=color, marker="s", ms=3, lw=1.0, ls="--")
    axes[1].set_ylabel("P90 abs error (us)")
    axes[1].set_xticks(x); axes[1].set_xticklabels(labels, rotation=45, ha="right")
    axes[1].set_xlabel("kappa / n_min")
    component_handles = [
        Line2D([0], [0], color="0.25", marker="o", ms=3, lw=1.5, label="C_cc"),
        Line2D([0], [0], color="0.25", marker="s", ms=3, lw=1.0, ls="--",
               label="C_spray"),
    ]
    axes[1].legend(handles=scenario_handles + component_handles, frameon=False, fontsize=7,
                   ncol=3, loc="lower center", bbox_to_anchor=(0.5, 1.0))

    bucket_labels = [label for label, _ in COVERAGE_BUCKETS]
    bx = list(range(len(bucket_labels)))
    bw = 0.8 / max(1, len(scenarios))
    for idx, scenario in enumerate(scenarios):
        vals = [cov.get((scenario, label), (0, math.nan))[1] for label in bucket_labels]
        offs = [i - 0.4 + bw * (idx + 0.5) for i in bx]
        axes[2].bar(offs, vals, width=bw, label=scenario, color=scenario_colors[scenario])
    axes[2].set_ylim(0, 1.02); axes[2].set_ylabel("agreement")
    axes[2].set_xlabel("physical path coverage")
    axes[2].set_xticks(bx); axes[2].set_xticklabels(bucket_labels)
    axes[2].legend(frameon=False, fontsize=8)

    fig.tight_layout()
    save(fig, "prism_oracle_validation", FIG_DIR)


def selftest():
    with tempfile.TemporaryDirectory() as td:
        raw = os.path.join(td, "raw")
        os.makedirs(raw)
        path = os.path.join(raw, "sample.csv")
        fields = sorted(REQUIRED)
        row = {key: "0" for key in fields}
        row.update({
            "run_id": "t", "seed": 13, "scenario": "symmetric", "flow_id": 1,
            "epoch_id": 0, "epoch_start_ns": 0, "epoch_end_ns": 1, "kappa": 1,
            "n_min": 3, "t_cc_us": 14, "t_spray_us": 14, "num_ack_samples": 3,
            "num_oracle_ack_snapshots": 3, "num_distinct_sampled_entropies": 2,
            "num_eligible_entropies": 8, "entropy_coverage_ratio": 0.25,
            "num_distinct_sampled_paths": 2, "num_eligible_paths": 4,
            "path_coverage_ratio": 0.5, "row_status": "ok", "est_state": "Increase",
            "oracle_state": "Increase", "boundary_oracle_state": "Increase",
            "state_match": 1, "boundary_state_match": 1,
        })
        with open(path, "w", newline="") as fp:
            writer = csv.DictWriter(fp, fieldnames=fields, lineterminator="\n")
            writer.writeheader(); writer.writerow(row)
        rows = read_rows(raw)
        assert len(rows) == 1 and f(rows[0], "path_coverage_ratio") == 0.5
        print("ok oracle aggregation selftest")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--plot-only", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
    if args.render:
        rows = read_rows()
        summary = aggregate(rows)
        render(summary, coverage_rows(rows))
        print(f"wrote {SUMMARY_CSV}")
        print(f"wrote {CONFUSION_CSV}")
        print(f"wrote {LEAD_LAG_CSV}")
    if args.plot_only:
        with open(SUMMARY_CSV, newline="") as fp:
            summary = list(csv.DictReader(fp))
        render(summary, stream_coverage_rows())
        print(f"wrote {os.path.join(FIG_DIR, 'prism_oracle_validation.{png,pdf}')}")


if __name__ == "__main__":
    main()
