#!/usr/bin/env python3
"""Aggregate ExpL sink delivery rates into reproducible CSV analysis inputs."""

from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import math
import statistics
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Iterable


HERE = Path(__file__).resolve().parent
RATE_SERIES_FIELDS = (
    "kind", "condition", "arm", "beta", "seed", "time_us", "rate_gbps",
    "display_rate_gbps",
)
STABILITY_SUMMARY_FIELDS = (
    "kind", "condition", "arm", "beta", "seed", "valid", "steady_samples",
    "steady_mean_gbps", "coefficient_of_variation", "normalized_p95_p5",
    "settling_time_us",
)
AGGREGATE_SEED = "aggregate"
LOCKED_SEEDS = frozenset((13, 14, 15, 16, 17))
EXPECTED_AGGREGATE_GROUPS = frozenset(
    [("primary", condition, arm, "") for condition in ("symmetric", "asymmetric")
     for arm in ("ops", "reps", "strack", "decmt")]
    + [("beta", "", "", beta) for beta in ("1.0", "0.5", "0.3", "0.15")]
)


@dataclasses.dataclass(frozen=True)
class RateBin:
    """Aggregate sink delivery rate at one fixed-width bin start, in Gbps."""

    time_us: float
    rate_gbps: float


@dataclasses.dataclass(frozen=True)
class StabilityMetrics:
    """Unfiltered steady-window rate-stability results for one trajectory."""

    valid: bool
    steady_samples: int
    steady_mean_gbps: float | None
    coefficient_of_variation: float | None
    normalized_p95_p5: float | None
    settling_time_us: float | None


def parse_sink_rate(path: Path) -> list[tuple[float, int, float]]:
    """Return ``(time_s, sink_id, rate_gbps)`` entries from decoded sink RATE lines."""
    path = Path(path)
    records: list[tuple[float, int, float]] = []
    with path.open(encoding="ascii") as stream:
        for line_number, line in enumerate(stream, start=1):
            fields = line.split()
            try:
                type_index = fields.index("Type")
            except ValueError:
                continue
            if type_index + 1 >= len(fields) or fields[type_index + 1] != "UEC_SINK":
                continue
            if "Rate" not in fields:
                continue
            try:
                sink_id = int(fields[fields.index("ID") + 1])
                time_s = float(fields[0])
                # UecSinkLoggerSampling writes byte/s; figures report Gb/s.
                rate_gbps = float(fields[-1]) * 8.0 / 1e9
            except (IndexError, ValueError) as exc:
                raise ValueError(f"{path}: line {line_number}: invalid UEC_SINK Rate record") from exc
            if not (math.isfinite(time_s) and math.isfinite(rate_gbps)):
                raise ValueError(f"{path}: line {line_number}: non-finite UEC_SINK Rate record")
            records.append((time_s, sink_id, rate_gbps))
    return sorted(records, key=lambda record: (record[0], record[1]))


def aggregate_bins(records: Iterable[tuple[float, int, float]], bin_us: int = 10) -> list[RateBin]:
    """Sum all sink rates into fixed bins, filling only observed interior gaps with zero."""
    if not isinstance(bin_us, int) or isinstance(bin_us, bool) or bin_us <= 0:
        raise ValueError("bin_us must be a positive integer")
    summed: dict[int, float] = {}
    for time_s, _sink_id, rate_gbps in records:
        if not (math.isfinite(time_s) and math.isfinite(rate_gbps)):
            raise ValueError("rate records must be finite")
        bin_index = math.floor(time_s * 1e6 / bin_us)
        summed[bin_index] = summed.get(bin_index, 0.0) + rate_gbps
    if not summed:
        return []
    first, last = min(summed), max(summed)
    return [
        RateBin(float(bin_index * bin_us), summed.get(bin_index, 0.0))
        for bin_index in range(first, last + 1)
    ]


def centered_mean(bins: Sequence[RateBin], width_us: float = 50) -> list[RateBin]:
    """Return a centered display-only arithmetic mean over a ``width_us`` window."""
    if not math.isfinite(width_us) or width_us <= 0:
        raise ValueError("width_us must be positive and finite")
    ordered = sorted(bins, key=lambda bin_: bin_.time_us)
    half_width = width_us / 2.0
    result = []
    for index, target in enumerate(ordered):
        rates = [
            sample.rate_gbps
            for sample in ordered
            if (
                abs(sample.time_us - target.time_us) < half_width
                or (
                    index in (0, len(ordered) - 1)
                    and math.isclose(abs(sample.time_us - target.time_us), half_width)
                )
            )
        ]
        result.append(RateBin(target.time_us, statistics.fmean(rates)))
    return result


def _nearest_rank(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[math.ceil(fraction * len(ordered)) - 1]


def _settling_time(
    bins: Sequence[RateBin], steady_mean_gbps: float, steady_us: tuple[float, float],
) -> float | None:
    """Find the first time followed by 200 us wholly within ten percent of steady mean."""
    if steady_mean_gbps <= 0:
        return None
    start_us, end_us = steady_us
    ordered = sorted(
        (bin_ for bin_ in bins if start_us <= bin_.time_us <= end_us),
        key=lambda bin_: bin_.time_us,
    )
    if not ordered:
        return None
    lower = steady_mean_gbps * 0.9
    upper = steady_mean_gbps * 1.1
    for index, candidate in enumerate(ordered):
        end_time = candidate.time_us + 200.0
        if end_time > end_us:
            continue
        window = [sample for sample in ordered[index:] if sample.time_us <= end_time]
        if not window or window[-1].time_us < end_time:
            continue
        if all(lower <= sample.rate_gbps <= upper for sample in window):
            return candidate.time_us
    return None


def stability_metrics(
    bins: Sequence[RateBin], steady_us: tuple[float, float] = (1000, 6000),
) -> StabilityMetrics:
    """Calculate unsmoothed rate variation and convergence against the steady mean."""
    start_us, end_us = steady_us
    if not (math.isfinite(start_us) and math.isfinite(end_us) and start_us <= end_us):
        raise ValueError("steady_us must be an ordered finite interval")
    ordered = sorted(bins, key=lambda bin_: bin_.time_us)
    steady = [
        bin_.rate_gbps
        for bin_ in ordered
        if start_us <= bin_.time_us <= end_us and bin_.rate_gbps > 0
    ]
    if len(steady) < 100:
        return StabilityMetrics(False, len(steady), None, None, None, None)
    mean = statistics.fmean(steady)
    if mean <= 0:
        return StabilityMetrics(False, len(steady), None, None, None, None)
    p5 = _nearest_rank(steady, 0.05)
    p95 = _nearest_rank(steady, 0.95)
    return StabilityMetrics(
        valid=True,
        steady_samples=len(steady),
        steady_mean_gbps=mean,
        coefficient_of_variation=statistics.pstdev(steady) / mean,
        normalized_p95_p5=(p95 - p5) / mean,
        settling_time_us=_settling_time(ordered, mean, steady_us),
    )


def median_trajectory(series_by_seed: Mapping[object, Sequence[RateBin]] | Sequence[Sequence[RateBin]]) -> list[RateBin]:
    """Return the pointwise median of timestamp-aligned raw seed trajectories."""
    series = list(series_by_seed.values()) if isinstance(series_by_seed, Mapping) else list(series_by_seed)
    if not series:
        return []
    aligned = [sorted(seed_series, key=lambda bin_: bin_.time_us) for seed_series in series]
    timestamps = [bin_.time_us for bin_ in aligned[0]]
    if any([bin_.time_us for bin_ in seed_series] != timestamps for seed_series in aligned[1:]):
        raise ValueError("seed trajectories must have identical bin timestamps")
    return [
        RateBin(time_us, statistics.median(seed_series[index].rate_gbps for seed_series in aligned))
        for index, time_us in enumerate(timestamps)
    ]


def _metadata(manifest_path: Path) -> tuple[dict, Path]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="ascii"))
        output_files = manifest["output_files"]
        sink_name = output_files["sink"]["filename"]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError(f"invalid ExpL manifest: {manifest_path}") from exc
    if manifest.get("kind") not in {"primary", "beta"} or not isinstance(manifest.get("seed"), int):
        raise ValueError(f"invalid ExpL case metadata: {manifest_path}")
    if not isinstance(sink_name, str) or Path(sink_name).name != sink_name:
        raise ValueError(f"invalid ExpL sink filename: {manifest_path}")
    sink_path = manifest_path.parent / sink_name
    if not sink_path.is_file():
        raise ValueError(f"missing ExpL sink trace: {sink_path}")
    return manifest, sink_path


def _group_key(manifest: dict) -> tuple[str, str, str, str]:
    beta = manifest.get("beta")
    return (
        manifest["kind"],
        "" if manifest.get("condition") is None else str(manifest["condition"]),
        "" if manifest.get("arm") is None else str(manifest["arm"]),
        "" if beta is None else str(beta),
    )


def _base_row(manifest: dict, seed: int | str) -> dict[str, object]:
    return {
        "kind": manifest["kind"],
        "condition": "" if manifest.get("condition") is None else manifest["condition"],
        "arm": "" if manifest.get("arm") is None else manifest["arm"],
        "beta": "" if manifest.get("beta") is None else manifest["beta"],
        "seed": seed,
    }


def _write_csv(path: Path, fields: Sequence[str], rows: Iterable[dict[str, object]]) -> None:
    with path.open("w", encoding="ascii", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="raise", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def require_publishable_aggregate_metrics(rows: Iterable[dict[str, object]]) -> None:
    """Reject formal plots missing a valid, settled 1--6 ms aggregate metric."""
    aggregate_rows = {
        (str(row["kind"]), str(row["condition"]), str(row["arm"]), str(row["beta"])): row
        for row in rows
        if str(row.get("seed")) == AGGREGATE_SEED
    }
    problems = []
    for key in sorted(EXPECTED_AGGREGATE_GROUPS):
        row = aggregate_rows.get(key)
        if row is None:
            problems.append(f"missing {key}")
            continue
        settling_time = row.get("settling_time_us")
        if row.get("valid") is not True or settling_time is None:
            problems.append(f"invalid or unsettled {key}")
            continue
        try:
            if not math.isfinite(float(settling_time)):
                problems.append(f"invalid or unsettled {key}")
        except (TypeError, ValueError):
            problems.append(f"invalid or unsettled {key}")
    if problems:
        raise ValueError("ExpL aggregate metrics invalid or unsettled: " + "; ".join(problems))


def write_analysis(data_dir: Path, output_dir: Path) -> dict[str, list[dict[str, object]]]:
    """Write per-seed raw rates plus an aggregate median/display trajectory and metrics."""
    data_dir = Path(data_dir)
    output_dir = Path(output_dir)
    manifest_paths = sorted(data_dir.glob("*.manifest.json"))
    if not manifest_paths:
        raise ValueError(f"no ExpL manifests found in {data_dir}")

    groups: dict[tuple[str, str, str, str], list[tuple[dict, list[RateBin]]]] = {}
    for manifest_path in manifest_paths:
        manifest, sink_path = _metadata(manifest_path)
        bins = aggregate_bins(parse_sink_rate(sink_path))
        groups.setdefault(_group_key(manifest), []).append((manifest, bins))

    rate_rows: list[dict[str, object]] = []
    summary_rows: list[dict[str, object]] = []
    for key in sorted(groups):
        cases = sorted(groups[key], key=lambda item: item[0]["seed"])
        if len({manifest["seed"] for manifest, _ in cases}) != len(cases):
            raise ValueError(f"duplicate ExpL seed for {key}")
        actual_seeds = {manifest["seed"] for manifest, _ in cases}
        if actual_seeds != LOCKED_SEEDS:
            raise ValueError(
                f"ExpL group {key} must contain exactly seeds {sorted(LOCKED_SEEDS)}; "
                f"got {sorted(actual_seeds)}"
            )
        for manifest, bins in cases:
            for bin_ in bins:
                rate_rows.append(_base_row(manifest, manifest["seed"]) | {
                    "time_us": bin_.time_us,
                    "rate_gbps": bin_.rate_gbps,
                    "display_rate_gbps": "",
                })
            metrics = stability_metrics(bins)
            summary_rows.append(_base_row(manifest, manifest["seed"]) | dataclasses.asdict(metrics))

        aggregate = median_trajectory([bins for _manifest, bins in cases])
        displayed = centered_mean(aggregate)
        if len(aggregate) != len(displayed):
            raise RuntimeError("display trajectory lost aggregate bins")
        for raw_bin, displayed_bin in zip(aggregate, displayed):
            rate_rows.append(_base_row(cases[0][0], AGGREGATE_SEED) | {
                "time_us": raw_bin.time_us,
                "rate_gbps": raw_bin.rate_gbps,
                "display_rate_gbps": displayed_bin.rate_gbps,
            })
        summary_rows.append(
            _base_row(cases[0][0], AGGREGATE_SEED) | dataclasses.asdict(stability_metrics(aggregate))
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "rate_series.csv", RATE_SERIES_FIELDS, rate_rows)
    _write_csv(output_dir / "stability_summary.csv", STABILITY_SUMMARY_FIELDS, summary_rows)
    return {"rate_series": rate_rows, "stability_summary": summary_rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=HERE / "data" / "raw")
    parser.add_argument("--output", type=Path, default=HERE / "data")
    parser.add_argument("--historical-check", action="store_true")
    parser.add_argument("--require-publishable-aggregates", action="store_true")
    args = parser.parse_args()
    analysis = write_analysis(args.input, args.output)
    if args.require_publishable_aggregates:
        require_publishable_aggregate_metrics(analysis["stability_summary"])
    if args.historical_check:
        print("historical-check: parsed and aggregated retained sink trace")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
