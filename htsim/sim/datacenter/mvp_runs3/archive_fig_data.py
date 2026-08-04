#!/usr/bin/env python3
"""Create and render compact, plotting-complete archives for five MVP figures.

``--extract`` reads the legacy simulation artifacts once and writes CSV tables below
``archive_data/``.  ``--render`` reads only those CSV tables; it never opens a
simulation log.  This makes later visual edits independent of the raw runs.
"""

from __future__ import annotations

import argparse
import csv
import os
import statistics as st
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib as mpl

mpl.rcParams["pdf.fonttype"] = 42
mpl.rcParams["ps.fonttype"] = 42

import matplotlib.pyplot as plt


HERE = Path(__file__).resolve().parent
ARCHIVE = HERE / "archive_data"
SEEDS = (13, 14, 15, 16, 17)
ARCHIVE_FILES = {
    "figA": "figA_floor_vs_load.csv",
    "figC": "figC_lb_depends_on_bottleneck.csv",
    "figI2": "figI2_cc_lb_tuning_coupled.csv",
    "figS1_samples": "figS1_path_samples.csv",
    "figS1_markers": "figS1_markers.csv",
    "figS2": "figS2_load_sweep.csv",
}


def _write(name: str, fields: tuple[str, ...], rows: list[dict[str, object]], archive: Path) -> None:
    archive.mkdir(parents=True, exist_ok=True)
    with (archive / ARCHIVE_FILES[name]).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _read(name: str, fields: tuple[str, ...], archive: Path) -> list[dict[str, str]]:
    path = archive / ARCHIVE_FILES[name]
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(fields):
            raise ValueError(f"unexpected archive schema in {path}")
        rows = list(reader)
    if not rows:
        raise ValueError(f"archive table is empty: {path}")
    return rows


def _ms(base: str, baseline: str, win: tuple[float, float], key: str, *, const_base: float | None = None) -> tuple[float, float, int]:
    """Legacy FigA/FigC statistic: seed medians followed by mean and population std."""
    import pathrtt_analyze as analysis

    values = []
    for seed in SEEDS:
        rows = analysis.parse_csv(HERE / f"{base}.s{seed}.pathrtt.csv")
        aggregate = analysis.aggregate_rows(rows, min_samples=200, baseline=baseline, win=win, const_base=const_base)
        if aggregate:
            values.append(aggregate[key])
    if len(values) != len(SEEDS):
        raise ValueError(f"missing complete five-seed series for {base}")
    return st.mean(values), st.pstdev(values), len(values)


def extract(archive: Path = ARCHIVE) -> None:
    """Derive every plotted coordinate and error bar from the current raw artifacts."""
    import make_coupling_fig as coupling
    import make_signal_fig as signal

    bprop = min(row[3] for row in __import__("pathrtt_analyze").parse_csv(HERE / "mp_inc_reps_n1.s13.pathrtt.csv"))
    win_inc, win_wp = (1000.0, 7000.0), (500.0, 1500.0)

    fig_a: list[dict[str, object]] = []
    for degree in (16, 32, 64):
        for algorithm, base in (("REPS", f"mp_inc_reps_n{degree}"), ("Oblivious", f"mp_inc_obl_n{degree}")):
            mean, std, count = _ms(base, "const", win_inc, "ccc_med", const_base=bprop)
            fig_a.append({"incast_degree": degree, "algorithm": algorithm, "mean_us": repr(mean), "std_us": repr(std), "n_seeds": count})
    _write("figA", ("incast_degree", "algorithm", "mean_us", "std_us", "n_seeds"), fig_a, archive)

    fig_c: list[dict[str, object]] = []
    for group, base, baseline, win in (
        ("Incast", "mp_inc_reps_n32", "global", win_inc),
        ("Incast", "mp_inc_obl_n32", "global", win_inc),
        ("8 receivers", "mp_wp_reps_f0", "global", win_wp),
        ("8 receivers", "mp_wp_obl_f0", "global", win_wp),
    ):
        algorithm = "REPS" if "reps" in base else "Oblivious"
        mean, std, count = _ms(base, baseline, win, "cspray_med")
        fig_c.append({"group": group, "algorithm": algorithm, "mean_us": repr(mean), "std_us": repr(std), "n_seeds": count})
    _write("figC", ("group", "algorithm", "mean_us", "std_us", "n_seeds"), fig_c, archive)

    fig_i2: list[dict[str, object]] = []
    for metric, function, prefix in (("goodput_gbps", coupling.goodput_gbps, "cpA"), ("latency_us", coupling.mean_latency_us, "cpB")):
        for target in coupling.TQD:
            values = [function(coupling.run_tag(prefix, target, seed)) for seed in coupling.SEEDS]
            fig_i2.append({"target_queueing_delay_us": target, "metric": metric, "mean": repr(st.mean(values)), "std": repr(st.stdev(values)), "n_seeds": len(values)})
    _write("figI2", ("target_queueing_delay_us", "metric", "mean", "std", "n_seeds"), fig_i2, archive)

    samples: list[dict[str, object]] = []
    marker_points = []
    for seed in signal.SEEDS:
        values = signal.path_means(signal.signal_tag(signal.DIST_LOAD, seed))
        if not values:
            raise ValueError(f"missing FigS1 path samples for seed {seed}")
        samples.extend({"seed": seed, "path_delay_us": repr(value)} for value in values)
        point = signal.seed_point(signal.signal_tag(signal.DIST_LOAD, seed))
        if point is None:
            raise ValueError(f"missing FigS1 markers for seed {seed}")
        marker_points.append(point)
    _write("figS1_samples", ("seed", "path_delay_us"), samples, archive)
    _write("figS1_markers", ("metric", "value_us"), [
        {"metric": "floor_us", "value_us": repr(st.mean(point[0] for point in marker_points))},
        {"metric": "avg_delay_us", "value_us": repr(st.mean(point[1] for point in marker_points))},
        {"metric": "target_us", "value_us": repr(signal.TARGET_US)},
    ], archive)

    fig_s2: list[dict[str, object]] = []
    for load in signal.LOADS:
        (floor_mean, floor_std), (avg_mean, avg_std) = signal.across_seeds(load)
        fig_s2.append({"num_senders": load, "floor_mean_us": repr(floor_mean), "floor_std_us": repr(floor_std),
                       "avg_delay_mean_us": repr(avg_mean), "avg_delay_std_us": repr(avg_std), "n_seeds": len(signal.SEEDS)})
    _write("figS2", ("num_senders", "floor_mean_us", "floor_std_us", "avg_delay_mean_us", "avg_delay_std_us", "n_seeds"), fig_s2, archive)


def _save(fig: plt.Figure, stem: str, output: Path, *, dpi: int, pad: float) -> None:
    output.mkdir(parents=True, exist_ok=True)
    fig.savefig(output / f"{stem}.png", dpi=dpi, bbox_inches="tight", pad_inches=pad)
    fig.savefig(output / f"{stem}.pdf", bbox_inches="tight", pad_inches=pad)
    plt.close(fig)


def render(archive: Path = ARCHIVE, output: Path = HERE) -> None:
    """Render five figures using only compact archive CSVs."""
    fig_a = _read("figA", ("incast_degree", "algorithm", "mean_us", "std_us", "n_seeds"), archive)
    with plt.rc_context({"font.size": 24}):
        fig, axis = plt.subplots()
        degrees = [16, 32, 64]
        x = list(range(len(degrees)))
        for algorithm, fmt, label in (("REPS", "s-", "REPS"), ("Oblivious", "o--", "Oblivious")):
            rows = [row for row in fig_a if row["algorithm"] == algorithm]
            rows.sort(key=lambda row: int(row["incast_degree"]))
            axis.errorbar(x, [float(row["mean_us"]) for row in rows], yerr=[float(row["std_us"]) for row in rows], fmt=fmt, lw=2.5, ms=11, capsize=6, label=label)
        axis.set_xlabel("Incast degree N"); axis.set_ylabel(r"$C_{cc}$ (us)")
        axis.legend(fontsize=18); axis.grid(alpha=0.3); axis.set_xticks(x, [str(value) for value in degrees])
        axis.set_ylim(10, 11.5); axis.set_yticks([10, 10.5, 11, 11.5]); fig.tight_layout()
        _save(fig, "figA_floor_vs_load", output, dpi=140, pad=0.05)

    fig_c = _read("figC", ("group", "algorithm", "mean_us", "std_us", "n_seeds"), archive)
    with plt.rc_context({"font.size": 24}):
        fig, axis = plt.subplots()
        groups, x, width = ["Incast", "8 receivers"], range(2), 0.25
        for algorithm, offset, label in (("REPS", -width / 2, "REPS"), ("Oblivious", width / 2, "Oblivious")):
            rows = [next(row for row in fig_c if row["group"] == group and row["algorithm"] == algorithm) for group in groups]
            axis.bar([index + offset for index in x], [float(row["mean_us"]) for row in rows], width,
                     yerr=[float(row["std_us"]) for row in rows], capsize=4, label=label)
        axis.set_xticks(list(x), groups); axis.set_ylabel(r"$C_{spray}$ (us)")
        axis.legend(fontsize=18); axis.grid(alpha=0.3, axis="y"); fig.tight_layout()
        _save(fig, "figC_lb_depends_on_bottleneck", output, dpi=140, pad=0.05)

    fig_i2 = _read("figI2", ("target_queueing_delay_us", "metric", "mean", "std", "n_seeds"), archive)
    targets = [2, 4, 6, 8, 12, 16]
    def metric(name: str) -> tuple[list[float], list[float]]:
        rows = [row for row in fig_i2 if row["metric"] == name]
        rows.sort(key=lambda row: int(row["target_queueing_delay_us"]))
        return [float(row["mean"]) for row in rows], [float(row["std"]) for row in rows]
    goodput, goodput_std = metric("goodput_gbps"); latency, latency_std = metric("latency_us")
    with plt.rc_context({"font.size": 12}):
        fig, axg = plt.subplots(figsize=(5.6, 2)); axl = axg.twinx()
        axg.errorbar(targets, goodput, yerr=goodput_std, marker="o", lw=2.0, ms=6, capsize=3, color="tab:green", zorder=3)
        axl.errorbar(targets, latency, yerr=latency_std, marker="s", lw=2.0, ms=6, capsize=3, color="tab:purple", zorder=3); axl.invert_yaxis()
        axg.margins(y=0.11); axl.margins(y=0.13); axg.axvline(6, color="gray", ls="--", lw=1.2, zorder=1)
        axg.annotate("default", xy=(5.97, 0.47), xycoords=axg.get_xaxis_transform(), color="gray", rotation=90, va="top", ha="right", fontsize=10)
        best_goodput, best_latency = targets[goodput.index(max(goodput))], targets[latency.index(min(latency))]
        axg.scatter([best_goodput], [max(goodput)], s=150, facecolors="none", edgecolors="tab:green", lw=2.0, zorder=5)
        axl.scatter([best_latency], [min(latency)], s=150, facecolors="none", edgecolors="tab:purple", lw=2.0, zorder=5)
        axg.annotate("Best", xy=(best_goodput - 1, max(goodput) + 3.5), xytext=(-2, -14), textcoords="offset points", color="tab:green", ha="center", va="top", fontsize=10)
        axl.annotate("Best", xy=(best_latency + 0.7, min(latency) + 1), xytext=(1, 14), textcoords="offset points", color="tab:purple", ha="left", fontsize=10)
        axg.set_xlabel("Target queueing delay (us)"); axg.set_ylabel("Goodput (Gbps)"); axg.yaxis.set_label_coords(-0.08, 0.45); axl.set_ylabel("Latency (us)")
        axg.set_xticks(targets); axg.grid(alpha=0.3)
        from matplotlib.lines import Line2D
        axg.legend(handles=[Line2D([0], [0], color="tab:green", marker="o", lw=2.0, label="Goodput"), Line2D([0], [0], color="tab:purple", marker="s", lw=2.0, label="Latency")], loc="center right", bbox_to_anchor=(1.0, 0.42), fontsize=10, framealpha=0.9, handlelength=1.6)
        fig.tight_layout(); _save(fig, "figI2_cc_lb_tuning_coupled", output, dpi=160, pad=0.04)

    samples = _read("figS1_samples", ("seed", "path_delay_us"), archive)
    markers = {row["metric"]: float(row["value_us"]) for row in _read("figS1_markers", ("metric", "value_us"), archive)}
    with plt.rc_context({"font.size": 24}):
        fig, axis = plt.subplots(figsize=(6.4, 4.8)); values = [float(row["path_delay_us"]) for row in samples]
        axis.hist(values, bins=40, color="tab:gray", alpha=0.55, edgecolor="white")
        axis.axvspan(markers["floor_us"], markers["avg_delay_us"], color="tab:orange", alpha=0.25)
        axis.axvline(markers["floor_us"], color="tab:red", lw=2.8); axis.axvline(markers["avg_delay_us"], color="tab:blue", lw=2.8); axis.axvline(markers["target_us"], color="gray", ls="--", lw=1.8)
        axis.set_xlabel("Per-path queueing delay (us)"); axis.set_ylabel("Number of paths"); axis.grid(alpha=0.3); fig.subplots_adjust(left=0.17, right=0.95, top=0.93, bottom=0.16)
        _save(fig, "figS1_path_distribution", output, dpi=140, pad=0.02)

    fig_s2 = _read("figS2", ("num_senders", "floor_mean_us", "floor_std_us", "avg_delay_mean_us", "avg_delay_std_us", "n_seeds"), archive)
    fig_s2.sort(key=lambda row: int(row["num_senders"])); loads, x = [int(row["num_senders"]) for row in fig_s2], list(range(len(fig_s2)))
    with plt.rc_context({"font.size": 24}):
        fig, axis = plt.subplots(figsize=(6.4, 4.8)); floor = [float(row["floor_mean_us"]) for row in fig_s2]; avg = [float(row["avg_delay_mean_us"]) for row in fig_s2]
        axis.fill_between(x, floor, avg, color="tab:orange", alpha=0.25)
        axis.errorbar(x, avg, yerr=[float(row["avg_delay_std_us"]) for row in fig_s2], marker="s", lw=2.5, ms=9, capsize=5, color="tab:blue")
        axis.errorbar(x, floor, yerr=[float(row["floor_std_us"]) for row in fig_s2], marker="o", lw=2.5, ms=9, capsize=5, color="tab:red")
        axis.axhline(6.0, color="gray", ls="--", lw=1.8); axis.set_xlabel("Number of senders"); axis.set_ylabel("Queueing delay (us)")
        axis.set_xticks(x, [str(load) for load in loads]); axis.set_ylim(bottom=0); axis.grid(alpha=0.3); fig.subplots_adjust(left=0.17, right=0.95, top=0.93, bottom=0.16)
        _save(fig, "figS2_load_sweep", output, dpi=140, pad=0.02)


def selftest() -> None:
    required = set(ARCHIVE_FILES.values())
    if required != {ARCHIVE_FILES[key] for key in ARCHIVE_FILES}:
        raise RuntimeError("duplicate archive file name")
    print("archive_fig_data self-test: PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extract", action="store_true")
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--archive", type=Path, default=ARCHIVE)
    parser.add_argument("--output", type=Path, default=HERE)
    args = parser.parse_args()
    if args.selftest:
        selftest()
    elif args.extract:
        extract(args.archive)
    elif args.render:
        render(args.archive, args.output)
    else:
        parser.error("choose --extract, --render, or --selftest")
