#!/usr/bin/env python3
"""Summarize the fixed M2 residual-recycling A/B smoke traces."""

from __future__ import annotations

import csv
import json
import os
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[4]))

from htsim.sim.datacenter.add_motivation.common.shadow_replay import _unclosed_tail_ack_event_seqs
from htsim.sim.datacenter.add_motivation.common.trace_schema import load_trace_compact


ROOT = HERE / "data" / "controlled" / "intervention" / "confirmation"
SUMMARY = ROOT / "summary.csv"
FIGURE = HERE / "figs" / "controlled" / "m2_residual_recycling_confirmation"
WARMUP_PS = 1_000_000_000


def _row(manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    config = manifest["config"]
    analysis = manifest["analysis_config"]
    prefix = manifest_path.with_suffix("").with_suffix("")
    bundle = load_trace_compact(prefix)
    tail = _unclosed_tail_ack_event_seqs(bundle)
    reduced = {
        (item["flow_id"], item["entropy"]): bool(item["contains_reduced_link"])
        for item in bundle.pathmap
    }
    acks = [
        ack for ack in bundle.ack
        if ack["event_seq"] not in tail and ack["time_ps"] >= WARMUP_PS
        and ack["genuine_sample"] and not ack["ecn"]
    ]
    if not acks:
        raise ValueError(f"no post-warmup clean ACKs in {manifest_path}")
    selected = [ack for ack in acks if ack["selection_source"] == "recycled"]
    epochs = [epoch for epoch in bundle.epoch if epoch["end_ps"] >= WARMUP_PS]
    if not epochs:
        raise ValueError(f"no post-warmup epochs in {manifest_path}")
    def rate(items):
        return sum(reduced[(ack["flow_id"], ack["entropy"])] for ack in items) / len(items)
    rejects = [
        token for token in bundle.token
        if token["operation"] == "reject_high_residual" and token["time_ps"] >= WARMUP_PS
    ]
    reject_reduced_share = (
        sum(reduced[(token["flow_id"], token["entropy"])] for token in rejects) / len(rejects)
        if rejects else ""
    )
    return {
        "run_id": bundle.run_id,
        "scenario": analysis["scenario"],
        "seed": analysis["seed"],
        "treatment": "recycle" if config["motivation_residual_recycle"] else "baseline",
        "residual_threshold_us": config["motivation_residual_threshold_us"],
        "clean_ack_count": len(acks),
        "reduced_path_ack_share": rate(acks),
        "recycled_ack_count": len(selected),
        "reduced_path_recycled_share": rate(selected) if selected else "",
        "residual_reject_count": len(rejects),
        "reduced_path_reject_share": reject_reduced_share,
        "mean_raw_spread_us": sum(epoch["raw_spread_ps"] for epoch in epochs) / len(epochs) / 1_000_000,
        "hold_epoch_fraction": sum(epoch["actual_region"] == "hold" for epoch in epochs) / len(epochs),
    }


def main() -> None:
    rows = [_row(path) for path in sorted(ROOT.glob("*.manifest.json"))]
    if len(rows) != 12:
        raise ValueError(f"expected exactly twelve A/B manifests, found {len(rows)}")
    fields = tuple(rows[0])
    with SUMMARY.open("w", newline="", encoding="ascii") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".matplotlib-cache"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    metrics = (
        ("reduced_path_recycled_share", "reduced-path share among recycled ACKs"),
        ("mean_raw_spread_us", "mean raw spread (us)"),
        ("hold_epoch_fraction", "Hold epoch fraction"),
    )
    figure, axes = plt.subplots(1, 3, figsize=(10.0, 3.1))
    for axis, (field, label) in zip(axes, metrics):
        for offset, treatment in ((-0.17, "baseline"), (0.17, "recycle")):
            values = []
            for scenario in ("recoverable", "persistent"):
                samples = [row[field] for row in rows if row["scenario"] == scenario and row["treatment"] == treatment]
                samples = [float(value) if value != "" else 0.0 for value in samples]
                values.append(statistics.mean(samples))
            axis.bar([index + offset for index in range(2)], values, width=0.32, label=treatment)
        axis.set_xticks([0, 1], ["recoverable", "persistent"])
        axis.set_ylabel(label)
        axis.grid(axis="y", alpha=0.25)
    axes[0].legend(frameon=False)
    figure.tight_layout()
    FIGURE.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(FIGURE.with_suffix(".png"), dpi=180, bbox_inches="tight")
    figure.savefig(FIGURE.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(figure)


if __name__ == "__main__":
    main()
