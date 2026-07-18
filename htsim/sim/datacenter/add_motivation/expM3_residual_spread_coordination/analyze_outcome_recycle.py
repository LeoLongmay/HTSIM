#!/usr/bin/env python3
"""Measure the physical traffic split in each exact outcome-recycle window."""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path

from htsim.sim.datacenter.add_motivation.common.trace_schema import load_trace


MODES = ("prism_recycle", "outcome_recycle")
SEEDS = (13, 14, 15)
ROUTE_HASH_SEED = 13
ECN_THRESHOLD_PACKETS = 211
STAGES = ("pre", "post1", "post2")
OUTCOME_FIELDS = (
    "run_id", "scenario", "mode", "seed", "flow_id", "round_id", "stage",
    "start_ps", "end_ps", "online_classified_bytes", "online_harmful_bytes",
    "online_exposure", "healthy_acked_bytes", "throttled_acked_bytes",
    "offline_reduced_link_share",
)
SUMMARY_FIELDS = (
    "seed", "complete_outcome_count", "mean_pre_exposure", "mean_post1_exposure",
    "mean_post2_exposure", "mean_pre_reduced_link_share",
    "mean_post1_reduced_link_share", "mean_post2_reduced_link_share",
)


def _ratio(throttled: int, healthy: int) -> float:
    total = throttled + healthy
    if total <= 0:
        raise ValueError("outcome window has no ACKed bytes")
    return throttled / total


def _manifest(path: Path) -> tuple[str, str, int, str]:
    try:
        manifest = json.loads(path.read_text(encoding="ascii"))
        config = manifest["config"]
        analysis = manifest["analysis_config"]
        run_id = manifest["run_id"]
        seed = manifest["seed"]
        mode = config["prism_coordination_mode"]
        scenario = analysis["scenario"]
    except (KeyError, OSError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid outcome-recycle manifest {path}: {exc}") from exc
    if (
        manifest.get("experiment") != "M3_residual_spread_coordination"
        or manifest.get("phase") != "outcome_recycle"
        or mode not in MODES
        or scenario != "recoverable"
        or seed not in SEEDS
        or analysis.get("seed") != seed
        or config.get("cc") != "prism"
        or config.get("load_balancing_algo") != "reps_actual"
        or config.get("motivation_ecmp_hash_seed") != ROUTE_HASH_SEED
        or config.get("motivation_ecn_threshold_packets") != ECN_THRESHOLD_PACKETS
        or config.get("degraded_links") != 2
        or float(config.get("degraded_capacity_gbps", 0.0)) != 25.0
    ):
        raise ValueError(f"{path}: does not belong to the locked outcome-recycle matrix")
    return run_id, scenario, seed, mode


def _validate_manifest_set(paths: list[Path]) -> None:
    expected = {(mode, seed) for mode in MODES for seed in SEEDS}
    actual = []
    for path in paths:
        try:
            _run_id, _scenario, seed, mode = _manifest(path)
        except ValueError as exc:
            raise ValueError("require the locked six-case manifest set") from exc
        actual.append((mode, seed))
    if len(actual) != len(expected) or set(actual) != expected or len(set(actual)) != len(actual):
        raise ValueError("require the locked six-case manifest set")


def _validate_exposure(row: dict, stage: str) -> None:
    classified = row[f"{stage}_classified_bytes"]
    harmful = row[f"{stage}_harmful_bytes"]
    exposure = row[f"{stage}_exposure"]
    if classified <= 0:
        raise ValueError(f"{stage} classified bytes must be positive")
    if harmful > classified:
        raise ValueError(f"{stage} harmful bytes cannot exceed classified bytes")
    expected = harmful / classified
    if not math.isclose(exposure, expected, rel_tol=1e-6, abs_tol=1e-6):
        raise ValueError(f"{stage} exposure must equal harmful/classified")


def _outcome_rows(manifest_path: Path) -> list[dict]:
    run_id, scenario, seed, mode = _manifest(manifest_path)
    prefix = manifest_path.with_suffix("").with_suffix("")
    bundle = load_trace(prefix)
    if bundle.run_id != run_id:
        raise ValueError(f"{manifest_path}: trace run ID mismatch")
    if mode == "prism_recycle":
        if bundle.outcome:
            raise ValueError(f"{run_id}: baseline must not emit outcome records")
        return []

    reduced = {
        (row["flow_id"], row["entropy"]): row["contains_reduced_link"]
        for row in bundle.pathmap
    }
    rows = []
    for outcome in bundle.outcome:
        if outcome["run_id"] != run_id or outcome["seed"] != seed:
            raise ValueError(f"{run_id}: outcome identity mismatch")
        for stage in STAGES:
            _validate_exposure(outcome, stage)
            start = outcome[f"{stage}_start_ps"]
            end = outcome[f"{stage}_end_ps"]
            if end <= start or end - start != outcome["window_ps"]:
                raise ValueError(f"{run_id}: {stage} window does not match window_ps")
            healthy = 0
            throttled = 0
            for ack in bundle.ack:
                if not start <= ack["time_ps"] < end:
                    continue
                key = (ack["flow_id"], ack["entropy"])
                if key not in reduced:
                    raise ValueError(f"{run_id}: ACK lacks pathmap attribution for {key}")
                if reduced[key]:
                    throttled += ack["newly_acked_bytes"]
                else:
                    healthy += ack["newly_acked_bytes"]
            rows.append({
                "run_id": run_id,
                "scenario": scenario,
                "mode": mode,
                "seed": seed,
                "flow_id": outcome["flow_id"],
                "round_id": outcome["round_id"],
                "stage": stage,
                "start_ps": start,
                "end_ps": end,
                "online_classified_bytes": outcome[f"{stage}_classified_bytes"],
                "online_harmful_bytes": outcome[f"{stage}_harmful_bytes"],
                "online_exposure": outcome[f"{stage}_exposure"],
                "healthy_acked_bytes": healthy,
                "throttled_acked_bytes": throttled,
                "offline_reduced_link_share": _ratio(throttled, healthy),
            })
    return rows


def _summaries(rows: list[dict]) -> list[dict]:
    grouped: dict[int, dict[tuple[int, int], dict[str, dict]]] = defaultdict(dict)
    for row in rows:
        grouped[row["seed"]].setdefault((row["flow_id"], row["round_id"]), {})[row["stage"]] = row
    summaries = []
    for seed in SEEDS:
        complete = [stages for stages in grouped[seed].values() if set(stages) == set(STAGES)]
        result = {"seed": seed, "complete_outcome_count": len(complete)}
        for stage in STAGES:
            exposures = [stages[stage]["online_exposure"] for stages in complete]
            shares = [stages[stage]["offline_reduced_link_share"] for stages in complete]
            result[f"mean_{stage}_exposure"] = sum(exposures) / len(exposures) if exposures else ""
            result[f"mean_{stage}_reduced_link_share"] = sum(shares) / len(shares) if shares else ""
        summaries.append(result)
    return summaries


def _write_csv(path: Path, fields: tuple[str, ...], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="ascii") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def analyze_outcome_recycle(data_root: Path | str, output_root: Path | str) -> dict[str, list[dict]]:
    """Write per-window physical traffic shares for completed strict replacements."""
    data_root = Path(data_root)
    output_root = Path(output_root)
    manifests = sorted(path for path in data_root.rglob("*.manifest.json") if output_root not in path.parents)
    if not manifests:
        raise ValueError(f"no outcome-recycle manifests below {data_root}")
    _validate_manifest_set(manifests)
    outcomes = []
    for manifest in manifests:
        outcomes.extend(_outcome_rows(manifest))
    outcomes.sort(key=lambda row: (row["seed"], row["start_ps"], row["flow_id"], row["round_id"], row["stage"]))
    summaries = _summaries(outcomes)
    output_root.mkdir(parents=True, exist_ok=True)
    _write_csv(output_root / "outcomes.csv", OUTCOME_FIELDS, outcomes)
    _write_csv(output_root / "summary.csv", SUMMARY_FIELDS, summaries)
    return {"outcomes": outcomes, "summary": summaries}


if __name__ == "__main__":
    HERE = Path(__file__).resolve().parent
    analyze_outcome_recycle(HERE / "data" / "outcome_recycle", HERE / "data" / "outcome_recycle" / "aggregate")
