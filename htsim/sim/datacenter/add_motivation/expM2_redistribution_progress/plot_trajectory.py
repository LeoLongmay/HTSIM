#!/usr/bin/env python3
"""Plot fixed representative real-topology paths for the controlled M2 cases."""

from __future__ import annotations

import csv
import json
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[4]))

from htsim.sim.datacenter.add_motivation.common.trace_schema import load_trace_compact


ROOT = HERE / "data" / "controlled" / "trajectory_c25"
FIG_ROOT = HERE / "figs" / "controlled"
RESIDUAL_THRESHOLD_PS = 14_000_000
WARMUP_PS = 1_000_000_000
PATH_FIELDS = (
    "schema_version", "run_id", "flow_id", "entropy", "physical_path_id",
    "resolution_status", "queue_fingerprint", "bottleneck_rate_gbps",
    "contains_reduced_link", "ordered_queue_ids",
)


def _unique_by_path(rows: list[dict]) -> list[dict]:
    selected = []
    seen = set()
    for row in sorted(rows, key=lambda item: (item["entropy"], item["physical_path_id"])):
        if row["physical_path_id"] not in seen:
            selected.append(row)
            seen.add(row["physical_path_id"])
    return selected


def _representatives(bundle, scenario: str) -> tuple[int, list[dict]]:
    grouped = defaultdict(list)
    for row in bundle.pathmap:
        grouped[row["flow_id"]].append(row)
    for flow_id in sorted(grouped):
        paths = _unique_by_path(grouped[flow_id])
        reduced = [row for row in paths if row["contains_reduced_link"]]
        healthy = [row for row in paths if not row["contains_reduced_link"]]
        if scenario == "recoverable" and len(reduced) >= 1 and len(healthy) >= 3:
            return flow_id, reduced[:1] + healthy[:3]
        if scenario == "persistent" and len(reduced) >= 3 and len(healthy) >= 1:
            return flow_id, healthy[:1] + reduced[:3]
    raise ValueError(f"no representative flow satisfies the {scenario} path rule")


def _write_csv(path: Path, fields: tuple[str, ...], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="ascii") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _epoch_rows(bundle, flow_id: int, representatives: list[dict]) -> list[dict]:
    selected_entropy = {row["entropy"] for row in representatives}
    path_info = {row["entropy"]: row for row in representatives}
    epochs = {
        row["epoch_id"]: row
        for row in bundle.epoch
        if row["flow_id"] == flow_id and row["end_ps"] >= WARMUP_PS
    }
    samples = defaultdict(list)
    all_samples = defaultdict(list)
    for ack in bundle.ack:
        if (ack["flow_id"] != flow_id or ack["time_ps"] < WARMUP_PS
                or not ack["genuine_sample"]):
            continue
        if ack["epoch_id"] not in epochs:
            continue
        all_samples[ack["epoch_id"]].append(ack["qdelay_ps"])
        if ack["entropy"] in selected_entropy:
            samples[(ack["epoch_id"], ack["entropy"])].append(ack["qdelay_ps"])

    output = []
    for epoch_id, meta in sorted(epochs.items()):
        qdelays = all_samples.get(epoch_id, [])
        if not qdelays:
            continue
        qmin = min(qdelays)
        for entropy in sorted(selected_entropy):
            values = samples.get((epoch_id, entropy), [])
            if not values:
                continue
            info = path_info[entropy]
            output.append({
                "time_us": meta["end_ps"] / 1_000_000,
                "epoch_id": epoch_id,
                "entropy": entropy,
                "physical_path_id": info["physical_path_id"],
                "path_class": "reduced" if info["contains_reduced_link"] else "healthy",
                "qdelay_us": statistics.median(values) / 1_000_000,
                "qmin_us": qmin / 1_000_000,
                "residual_threshold_us": (qmin + RESIDUAL_THRESHOLD_PS) / 1_000_000,
                "region": meta["actual_region"],
            })
    return output


def _plot(scenario: str, flow_id: int, paths: list[dict], rows: list[dict], reject_times: dict[int, list[float]]) -> None:
    os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".matplotlib-cache"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, (axis, state_axis) = plt.subplots(
        2, 1, figsize=(9.0, 4.8), sharex=True,
        gridspec_kw={"height_ratios": (12, 1)},
    )
    palette = ("#d1495b", "#2378b5", "#59a14f", "#8c6bb1")
    by_entropy = defaultdict(list)
    for row in rows:
        by_entropy[row["entropy"]].append(row)
    reject_label_added = False
    for color, path in zip(palette, paths):
        values = sorted(by_entropy[path["entropy"]], key=lambda row: row["time_us"])
        label = f"entropy {path['entropy']} ({'reduced' if path['contains_reduced_link'] else 'healthy'})"
        axis.plot([row["time_us"] for row in values], [row["qdelay_us"] for row in values],
                  color=color, linewidth=1.6, label=label)
        rejects = reject_times.get(path["entropy"], [])
        if rejects:
            axis.scatter(rejects, [max(row["qdelay_us"] for row in values)] * len(rejects),
                         color=color, marker="x", s=18, zorder=3,
                         label="residual reject" if not reject_label_added else None)
            reject_label_added = True

    threshold = {}
    for row in rows:
        threshold[row["epoch_id"]] = row
    threshold_rows = [threshold[key] for key in sorted(threshold)]
    axis.plot([row["time_us"] for row in threshold_rows],
              [row["residual_threshold_us"] for row in threshold_rows],
              color="black", linestyle="--", linewidth=1.0, label="qmin + 14us")
    axis.set_ylabel("end-to-end queuing delay (us)")
    configured_label = "capacity-recoverable" if scenario == "recoverable" else "capacity-persistent"
    axis.set_title(f"M2 {configured_label}, 25Gbps reduced links: flow {flow_id}")
    axis.grid(alpha=0.25)
    axis.legend(frameon=False, ncol=2, fontsize=8)
    state_colors = {"increase": "#59a14f", "hold": "#f28e2b", "decrease": "#d1495b"}
    boundaries = [row["time_us"] for row in threshold_rows]
    if len(boundaries) > 1:
        final_width = boundaries[-1] - boundaries[-2]
    else:
        final_width = 1.0
    start = boundaries[0]
    active_region = threshold_rows[0]["region"]
    for row in threshold_rows[1:]:
        if row["region"] == active_region:
            continue
        state_axis.axvspan(start, row["time_us"], color=state_colors.get(active_region, "#999999"))
        start = row["time_us"]
        active_region = row["region"]
    state_axis.axvspan(start, boundaries[-1] + final_width,
                         color=state_colors.get(active_region, "#999999"))
    state_axis.set_yticks([])
    state_axis.set_ylabel("Prism\nstate", rotation=0, labelpad=22, va="center")
    state_axis.set_xlabel("time (us)")
    state_axis.set_xlim(axis.get_xlim())
    from matplotlib.patches import Patch
    state_axis.legend(
        handles=[Patch(color=color, label=region) for region, color in state_colors.items()],
        frameon=False, ncol=3, fontsize=7, loc="center right",
    )
    figure.tight_layout()
    FIG_ROOT.mkdir(parents=True, exist_ok=True)
    stem = FIG_ROOT / f"m2_trajectory_c25_{scenario}"
    figure.savefig(stem.with_suffix(".png"), dpi=180, bbox_inches="tight")
    figure.savefig(stem.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(figure)


def main() -> None:
    for scenario in ("recoverable", "persistent"):
        manifest_path = ROOT / f"trajectory_c25_{scenario}_s101.manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="ascii"))
        bundle = load_trace_compact(manifest_path.with_suffix("").with_suffix(""))
        flow_id, paths = _representatives(bundle, scenario)
        rows = _epoch_rows(bundle, flow_id, paths)
        if len(rows) < 12:
            raise ValueError(f"too few representative samples for {scenario}")
        reject_times = defaultdict(list)
        selected_entropy = {path["entropy"] for path in paths}
        for token in bundle.token:
            if (token["flow_id"] == flow_id and token["operation"] == "reject_high_residual"
                    and token["entropy"] in selected_entropy and token["time_ps"] >= WARMUP_PS):
                reject_times[token["entropy"]].append(token["time_ps"] / 1_000_000)
        path_rows = [{field: path[field] for field in PATH_FIELDS} for path in paths]
        _write_csv(ROOT / f"trajectory_c25_{scenario}_paths.csv", PATH_FIELDS, path_rows)
        _write_csv(ROOT / f"trajectory_c25_{scenario}_series.csv", tuple(rows[0]), rows)
        _plot(scenario, flow_id, paths, rows, reject_times)
        print(f"{scenario}: flow={flow_id}, samples={len(rows)}")


if __name__ == "__main__":
    main()
