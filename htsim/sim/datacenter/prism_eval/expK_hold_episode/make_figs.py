#!/usr/bin/env python3
"""Render the read-only Prism Hold-episode summary figure."""
import argparse
import csv
import math
import statistics
import sys
from collections import Counter
from pathlib import Path


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))
from plot_style import apply_style  # noqa: E402


OUTCOMES = ("recovered", "ineffective", "mixed")
COUNT_KINDS = ("complete", "incomplete", "recovered", "ineffective", "mixed")
COUNT_COLORS = {
    "complete": "tab:blue",
    "incomplete": "tab:gray",
    "recovered": "tab:green",
    "ineffective": "tab:red",
    "mixed": "tab:purple",
}
OUTCOME_COLORS = {key: COUNT_COLORS[key] for key in OUTCOMES}


def _read_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(newline="") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames:
                raise ValueError("missing header")
            return list(reader)
    except OSError as exc:
        raise SystemExit(f"cannot read {path}: {exc}") from exc


def _float(row: dict[str, str], key: str) -> float | None:
    value = row.get(key, "").strip()
    if not value:
        return None
    try:
        result = float(value)
    except ValueError as exc:
        raise SystemExit(f"malformed {key!r} value {value!r}") from exc
    if not math.isfinite(result):
        raise SystemExit(f"non-finite {key!r} value {value!r}")
    return result


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _summary_count(row: dict[str, str], kind: str, fallback: int) -> int:
    for key in (f"{kind}_episodes", f"{kind}_count", kind):
        if key not in row or not row[key].strip():
            continue
        try:
            value = int(row[key])
        except ValueError as exc:
            raise SystemExit(f"malformed {key!r} count {row[key]!r}") from exc
        if value < 0:
            raise SystemExit(f"negative {key!r} count {row[key]!r}")
        return value
    return fallback


def _annotate_insufficient(ax, labels: list[str]) -> None:
    for index, label in enumerate(labels):
        ax.text(
            0.5,
            0.94 - index * 0.10,
            f"{label}: insufficient complete Hold episodes",
            ha="center",
            va="top",
            transform=ax.transAxes,
            fontsize=7,
        )


def _plot_counts(ax, scenarios: list[str], episodes, summaries) -> None:
    counts = Counter((row.get("scenario", ""), row.get("status", "")) for row in episodes)
    outcomes = Counter((row.get("scenario", ""), row.get("outcome", "")) for row in episodes)
    summary_by_scenario = {row["scenario"]: row for row in summaries if row.get("scenario")}
    width = 0.8 / len(COUNT_KINDS)
    x = list(range(len(scenarios)))
    for index, kind in enumerate(COUNT_KINDS):
        values = []
        for scenario in scenarios:
            fallback = (counts[(scenario, kind)] if kind in ("complete", "incomplete")
                        else outcomes[(scenario, kind)])
            values.append(_summary_count(summary_by_scenario.get(scenario, {}), kind, fallback))
        offset = [value - 0.4 + width * (index + 0.5) for value in x]
        ax.bar(offset, values, width=width, color=COUNT_COLORS[kind], label=kind)
    ax.set_title("Episode coverage and outcomes")
    ax.set_ylabel("episodes")
    ax.set_xticks(x)
    ax.set_xticklabels(scenarios, rotation=25, ha="right")
    ax.legend(frameon=False, fontsize=7, ncol=2)


def _plot_entry_scatter(ax, scenarios: list[str], complete, seed_summaries=()) -> None:
    for outcome in OUTCOMES:
        rows = [row for row in complete if row.get("outcome") == outcome]
        xs = [_float(row, "f_entry_ns") for row in rows]
        ys = [_float(row, "s_entry_ns") for row in rows]
        points = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
        if points:
            ax.scatter(*zip(*points), color=OUTCOME_COLORS[outcome], label=outcome,
                       s=22, alpha=0.85)
    missing = [
        scenario for scenario in scenarios
        if not any(row.get("scenario") == scenario for row in complete)
    ]
    missing.extend(
        outcome for outcome in OUTCOMES
        if not any(row.get("outcome") == outcome for row in complete)
    )
    missing.extend(
        f"{row['scenario']} (seed {row['seed']})"
        for row in seed_summaries
        if _summary_count(row, "complete", 0) == 0
    )
    _annotate_insufficient(ax, missing)
    ax.set_title("Hold-entry signal")
    ax.set_xlabel("entry F (ns)")
    ax.set_ylabel("entry S (ns)")
    handles, _ = ax.get_legend_handles_labels()
    if handles:
        ax.legend(frameon=False, fontsize=7)


def _outcome_rows(complete, outcome: str):
    return [row for row in complete if row.get("outcome") == outcome]


def _plot_delay_medians(ax, complete) -> None:
    windows = ("pre", "post1", "post2")
    x = list(range(len(windows)))
    missing = []
    for outcome in ("recovered", "ineffective"):
        rows = _outcome_rows(complete, outcome)
        low = [_median([value for row in rows
                       if (value := _float(row, f"{window}_low_support")) is not None])
               for window in windows]
        high = [_median([value for row in rows
                        if (value := _float(row, f"{window}_high_tail")) is not None])
                for window in windows]
        if any(value is None for value in low + high):
            missing.append(outcome)
            continue
        ax.plot(x, low, color=OUTCOME_COLORS[outcome], marker="o", lw=1.6,
                label=f"{outcome} low support")
        ax.plot(x, high, color=OUTCOME_COLORS[outcome], marker="x", ls="--", lw=1.2,
                label=f"{outcome} high tail")
    _annotate_insufficient(ax, missing)
    ax.set_title("Delay support and tail")
    ax.set_ylabel("median fraction")
    ax.set_ylim(-0.03, 1.03)
    ax.set_xticks(x)
    ax.set_xticklabels(windows)
    handles, _ = ax.get_legend_handles_labels()
    if handles:
        ax.legend(frameon=False, fontsize=6, loc="best")


def _plot_progress_medians(ax, complete) -> None:
    windows = ("pre", "post1", "post2")
    x = list(range(len(windows)))
    missing = []
    for outcome in ("recovered", "ineffective"):
        rows = _outcome_rows(complete, outcome)
        medians = []
        for window in windows:
            ratios = []
            for row in rows:
                pre = _float(row, "pre_ack_rate_bps")
                rate = _float(row, f"{window}_ack_rate_bps")
                if pre is not None and pre > 0 and rate is not None:
                    ratios.append(rate / pre)
            medians.append(_median(ratios))
        if any(value is None for value in medians):
            missing.append(outcome)
            continue
        ax.plot(x, medians, color=OUTCOME_COLORS[outcome], marker="o", lw=1.6,
                label=outcome)
    _annotate_insufficient(ax, missing)
    ax.axhline(1.0, color="0.4", lw=0.8, ls=":")
    ax.set_title("Normalized ACK progress")
    ax.set_ylabel("median window rate / pre rate")
    ax.set_xticks(x)
    ax.set_xticklabels(windows)
    handles, _ = ax.get_legend_handles_labels()
    if handles:
        ax.legend(frameon=False, fontsize=7)


def render(input_dir: Path, output_pdf: Path) -> None:
    """Render the four-panel summary from aggregate Hold-episode CSV files."""
    input_dir = Path(input_dir)
    output_pdf = Path(output_pdf)
    episodes = _read_csv(input_dir / "episode_rows.csv")
    summaries = _read_csv(input_dir / "scenario_summary.csv")
    seed_summaries = _read_csv(input_dir / "seed_summary.csv")
    if any("scenario" not in row for row in episodes + summaries):
        raise SystemExit("aggregate CSVs must include a scenario column")
    scenarios = sorted({row["scenario"] for row in episodes + summaries if row.get("scenario")})
    if not scenarios:
        raise SystemExit("aggregate CSVs contain no scenarios")
    complete = [row for row in episodes if row.get("status") == "complete"]

    import matplotlib.pyplot as plt

    apply_style(8)
    fig, axes = plt.subplots(2, 2, figsize=(10.5, 6.6))
    _plot_counts(axes[0, 0], scenarios, episodes, summaries)
    _plot_entry_scatter(axes[0, 1], scenarios, complete, seed_summaries)
    _plot_delay_medians(axes[1, 0], complete)
    _plot_progress_medians(axes[1, 1], complete)
    fig.tight_layout()
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_pdf, bbox_inches="tight", pad_inches=0.04)
    fig.savefig(output_pdf.with_suffix(".png"), bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="aggregate CSV directory")
    parser.add_argument("--output", type=Path, required=True, help="output PDF path")
    args = parser.parse_args()
    render(args.input, args.output)


if __name__ == "__main__":
    main()
