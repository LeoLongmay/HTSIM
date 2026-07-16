#!/usr/bin/env python3
"""Validate residual thresholds against trace-visible reduced-link ground truth."""

from __future__ import annotations

import csv
import dataclasses
import json
import math
import os
import tempfile
from collections import defaultdict
from pathlib import Path

try:
    from htsim.sim.datacenter.add_motivation.common.residual_join import attach_same_epoch_residuals
    from htsim.sim.datacenter.add_motivation.common.shadow_replay import _unclosed_tail_ack_event_seqs
    from htsim.sim.datacenter.add_motivation.common.trace_schema import load_trace_compact
except ModuleNotFoundError:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[5]))
    from htsim.sim.datacenter.add_motivation.common.residual_join import attach_same_epoch_residuals
    from htsim.sim.datacenter.add_motivation.common.shadow_replay import _unclosed_tail_ack_event_seqs
    from htsim.sim.datacenter.add_motivation.common.trace_schema import load_trace_compact


HERE = Path(__file__).resolve().parent
CONFIRMATION = HERE / "data" / "controlled" / "confirmation"
OUTPUT = HERE / "data" / "controlled" / "threshold_diagnostic.csv"
FIGURE = HERE / "figs" / "controlled" / "m2_threshold_ground_truth"
THRESHOLDS_US = (8, 10, 14)
WARMUP_PS = 1_000_000_000
MIN_HIGH_COVERAGE = 0.01


def _atomic_csv(path: Path, fields: tuple[str, ...], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", newline="", encoding="ascii", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _load_run(manifest_path: Path) -> list[dict]:
    manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    config = manifest["analysis_config"]
    prefix = manifest_path.with_suffix("").with_suffix("")
    bundle = load_trace_compact(prefix)
    tail = _unclosed_tail_ack_event_seqs(bundle)
    bundle = dataclasses.replace(
        bundle, ack=tuple(row for row in bundle.ack if row["event_seq"] not in tail),
    )
    reduced_by_entropy = {
        (row["flow_id"], row["entropy"]): row["contains_reduced_link"]
        for row in bundle.pathmap
    }
    if len(reduced_by_entropy) != len(bundle.pathmap):
        raise ValueError(f"duplicate pathmap key in {manifest_path}")
    rows = []
    for item in attach_same_epoch_residuals(bundle):
        ack = item.row
        if ack["ecn"] or ack["time_ps"] < WARMUP_PS:
            continue
        key = (ack["flow_id"], ack["entropy"])
        if key not in reduced_by_entropy:
            raise ValueError(f"ACK path mapping is absent for {key} in {manifest_path}")
        rows.append({
            "run_id": bundle.run_id,
            "scenario": config["scenario"],
            "seed": config["seed"],
            "residual_ps": item.residual_ps,
            "reduced_path": int(reduced_by_entropy[key]),
        })
    return rows


def _summarize(rows: list[dict], threshold_us: int, split: str) -> dict:
    threshold_ps = threshold_us * 1_000_000
    high = [row for row in rows if row["residual_ps"] >= threshold_ps]
    low = [row for row in rows if row["residual_ps"] < threshold_ps]
    if not high or not low:
        raise ValueError(f"{split} threshold {threshold_us}us has an empty group")
    high_rate = sum(row["reduced_path"] for row in high) / len(high)
    low_rate = sum(row["reduced_path"] for row in low) / len(low)
    if low_rate <= 0:
        raise ValueError(f"{split} threshold {threshold_us}us has zero low-path rate")
    return {
        "split": split,
        "threshold_us": threshold_us,
        "sample_count": len(rows),
        "high_count": len(high),
        "low_count": len(low),
        "high_coverage": len(high) / len(rows),
        "high_reduced_rate": high_rate,
        "low_reduced_rate": low_rate,
        "risk_ratio": high_rate / low_rate,
    }


def run() -> tuple[list[dict], int]:
    rows = []
    for manifest_path in sorted(CONFIRMATION.glob("*.manifest.json")):
        rows.extend(_load_run(manifest_path))
    calibration = [row for row in rows if row["seed"] == 101]
    confirmation = [row for row in rows if row["seed"] in (102, 103)]
    if not calibration or not confirmation:
        raise ValueError("threshold diagnostic requires confirmation seeds 101-103")
    outputs = [
        _summarize(calibration, threshold, "calibration")
        for threshold in THRESHOLDS_US
    ]
    eligible = [row for row in outputs if row["high_coverage"] >= MIN_HIGH_COVERAGE]
    if not eligible:
        raise ValueError("no threshold has the minimum high-residual coverage")
    selected = max(eligible, key=lambda row: (row["risk_ratio"], row["threshold_us"]))
    selected_threshold = int(selected["threshold_us"])
    outputs.extend(
        _summarize(confirmation, threshold, "confirmation")
        for threshold in THRESHOLDS_US
    )
    for row in outputs:
        row["selected"] = int(row["threshold_us"] == selected_threshold)
        row["warmup_us"] = WARMUP_PS / 1_000_000
        row["minimum_high_coverage"] = MIN_HIGH_COVERAGE
    fields = tuple(outputs[0])
    _atomic_csv(OUTPUT, fields, outputs)
    return outputs, selected_threshold


def render(rows: list[dict], selected_threshold: int) -> None:
    os.environ.setdefault("MPLCONFIGDIR", str(HERE / "data" / "controlled" / ".matplotlib-cache"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    by_split = defaultdict(list)
    for row in rows:
        by_split[row["split"]].append(row)
    figure, axes = plt.subplots(1, 2, figsize=(8.4, 3.3))
    for split, color in (("calibration", "#2378b5"), ("confirmation", "#d1495b")):
        ordered = sorted(by_split[split], key=lambda row: row["threshold_us"])
        x = [row["threshold_us"] for row in ordered]
        axes[0].plot(x, [row["risk_ratio"] for row in ordered], marker="o", label=split, color=color)
        axes[1].plot(x, [row["high_coverage"] for row in ordered], marker="o", label=split, color=color)
    axes[0].axhline(1, color="black", linewidth=0.8)
    axes[0].set_ylabel("reduced-path risk ratio")
    axes[0].set_title("High residual identifies reduced paths")
    axes[1].axhline(MIN_HIGH_COVERAGE, color="black", linewidth=0.8, linestyle="--")
    axes[1].set_ylabel("high-residual sample fraction")
    axes[1].set_title("Usable sample coverage")
    for axis in axes:
        axis.axvline(selected_threshold, color="#59a14f", linestyle="--", linewidth=1)
        axis.set_xlabel("residual threshold (us)")
        axis.set_xticks(THRESHOLDS_US)
        axis.grid(axis="y", alpha=0.25)
        axis.legend(frameon=False)
    figure.tight_layout()
    FIGURE.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(FIGURE.with_suffix(".png"), dpi=180, bbox_inches="tight")
    figure.savefig(FIGURE.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(figure)


if __name__ == "__main__":
    result_rows, result_threshold = run()
    render(result_rows, result_threshold)
    print(f"selected_residual_threshold_us={result_threshold}")
