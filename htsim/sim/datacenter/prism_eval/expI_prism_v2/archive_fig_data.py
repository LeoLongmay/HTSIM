#!/usr/bin/env python3
"""Archive and redraw the six selected 1024-node CDF figures.

The CSV files contain the exact ECDF coordinates submitted to Matplotlib.  They
are intentionally plot-ready: simulation logs and unplotted samples are not
needed to redraw the six archival figures.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.axes_grid1.inset_locator import inset_axes

HERE = Path(__file__).resolve().parent
SOURCE_PATH = HERE / "make_1024_ack_qdelay_cdf.py"
SPEC = importlib.util.spec_from_file_location("source_cdf", SOURCE_PATH)
assert SPEC and SPEC.loader
source = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(source)

SEEDS = [13, 14, 15, 16, 17]
QDELAY_INPUTS = {
    16: "ack_qdelay_1024",
    24: "ack_qdelay_1024_f24",
    32: "ack_qdelay_1024_f32",
}
ARMS = source.CDF_ARMS


def _write_rows(path: Path, header: list[str], rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="ascii") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def extract(data_root: Path, archive_dir: Path) -> None:
    """Store only the rendered ECDF coordinates for the six selected panels."""
    for failure, subdir in QDELAY_INPUTS.items():
        samples = {
            arm: [source.load_qdelay_us(data_root / subdir / f"{arm}_s{seed}.csv")
                  for seed in SEEDS]
            for arm in ARMS
        }
        values = [value for per_arm in samples.values() for per_seed in per_arm for value in per_seed]
        grids = {
            "main": source.plot_grid(values, source.MAIN_ACK_QDELAY_XMAX_US),
            "tail": source.plot_grid(values, max(values)),
        }
        rows = []
        for region, grid in grids.items():
            for arm in ARMS:
                for x, y in zip(grid, source.mean_seed_ecdf(samples[arm], grid)):
                    rows.append((region, arm, repr(x), repr(y)))
        _write_rows(archive_dir / f"figI_1024_ack_qdelay_f{failure}.csv",
                    ["region", "arm", "x_us", "cdf"], rows)

    evidence = data_root / "double_evidence"
    for failure in QDELAY_INPUTS:
        samples = {
            arm: [[value / 1000.0 for value in source._flow_fcts_us(
                evidence / f"double_{arm}_f{failure}_s{seed}.flow.txt")]
                  for seed in SEEDS]
            for arm in ARMS
        }
        values = [value for per_arm in samples.values() for per_seed in per_arm for value in per_seed]
        grid = source.plot_grid(values, max(values))
        rows = [
            (arm, repr(x), repr(y))
            for arm in ARMS
            for x, y in zip(grid, source.mean_seed_ecdf(samples[arm], grid))
        ]
        _write_rows(archive_dir / f"figI_1024_f{failure}_fct_cdf.csv",
                    ["arm", "x_ms", "cdf"], rows)


def _load_qdelay(path: Path):
    curves: dict[tuple[str, str], tuple[list[float], list[float]]] = {}
    collected: dict[tuple[str, str], list[tuple[float, float]]] = {}
    with path.open(newline="", encoding="ascii") as stream:
        for row in csv.DictReader(stream):
            collected.setdefault((row["region"], row["arm"]), []).append(
                (float(row["x_us"]), float(row["cdf"]))
            )
    for key, values in collected.items():
        curves[key] = ([v[0] for v in values], [v[1] for v in values])
    return curves


def _load_fct(path: Path):
    curves: dict[str, tuple[list[float], list[float]]] = {}
    collected: dict[str, list[tuple[float, float]]] = {}
    with path.open(newline="", encoding="ascii") as stream:
        for row in csv.DictReader(stream):
            collected.setdefault(row["arm"], []).append((float(row["x_ms"]), float(row["cdf"])))
    for arm, values in collected.items():
        curves[arm] = ([v[0] for v in values], [v[1] for v in values])
    return curves


def _save(figure, path: Path, *, pad_inches: float | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    save_kwargs = {"bbox_inches": "tight"}
    if pad_inches is not None:
        save_kwargs["pad_inches"] = pad_inches
    figure.savefig(path.with_suffix(".png"), dpi=180, **save_kwargs)
    figure.savefig(path.with_suffix(".pdf"), **save_kwargs)
    plt.close(figure)


def render_qdelay(data_path: Path, output_stem: Path) -> None:
    curves = _load_qdelay(data_path)
    source.apply_reference_figure_style()
    figure, axis = plt.subplots(figsize=source.REFERENCE_FIGSIZE_IN, layout="constrained")
    inset = inset_axes(axis, width="100%", height="100%", loc="lower left",
                       bbox_to_anchor=(0.62, 0.16, 0.28, 0.28),
                       bbox_transform=axis.transAxes, borderpad=0)
    full_xmax = 0.0
    for arm in ARMS:
        x, y = curves[("main", arm)]
        axis.plot(x, y, color=source.color_for_arm(arm), linewidth=2.2, label=ARMS[arm])
        axis.plot(x, y, color=source.color_for_arm(arm), linewidth=2.2, label=ARMS[arm])
        x, y = curves[("tail", arm)]
        full_xmax = max(full_xmax, x[-1])
        inset.plot(x, y, color=source.color_for_arm(arm), linewidth=1.6)
    axis.set_xlim(0.0, source.MAIN_ACK_QDELAY_XMAX_US)
    axis.set_ylim(0.0, 0.8)
    axis.set_xlabel("Queueing delay (us)")
    axis.set_ylabel("CDF")
    axis.grid(alpha=0.25)
    inset.set_xlim(40.0, min(100.0, full_xmax))
    inset.set_ylim(0.8, 1.01)
    inset.set_title("tail range", fontsize=18)
    inset.tick_params(labelsize=18)
    inset.grid(alpha=0.2)
    _save(figure, output_stem, pad_inches=0.04)


def render_fct(data_path: Path, output_stem: Path) -> None:
    curves = _load_fct(data_path)
    source.apply_reference_figure_style()
    figure, axis = plt.subplots(figsize=source.REFERENCE_FIGSIZE_IN, layout="constrained")
    xmax = 0.0
    for arm in ARMS:
        x, y = curves[arm]
        xmax = max(xmax, x[-1])
        axis.plot(x, y, linewidth=2.2, color=source.color_for_arm(arm))
    axis.set_xlim(0.0, xmax)
    axis.set_ylim(0.0, 1.01)
    axis.set_xlabel("Avg FCT (ms)")
    axis.set_ylabel("CDF")
    axis.grid(alpha=0.25)
    _save(figure, output_stem, pad_inches=None)


def render(archive_dir: Path, figures_dir: Path) -> None:
    for failure in QDELAY_INPUTS:
        suffix = "cdf" if failure == 16 else f"f{failure}"
        render_qdelay(archive_dir / f"figI_1024_ack_qdelay_f{failure}.csv",
                      figures_dir / f"figI_1024_ack_qdelay_{suffix}")
        render_fct(archive_dir / f"figI_1024_f{failure}_fct_cdf.csv",
                   figures_dir / f"figI_1024_f{failure}_fct_cdf")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extract", action="store_true")
    parser.add_argument("--data-root", type=Path, default=HERE / "data")
    parser.add_argument("--archive-dir", type=Path, default=HERE / "archive_data")
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--figs", type=Path, default=HERE / "figs")
    args = parser.parse_args()
    if args.extract:
        extract(args.data_root, args.archive_dir)
    if args.render:
        render(args.archive_dir, args.figs)
    if not args.extract and not args.render:
        parser.error("provide --extract, --render, or both")


if __name__ == "__main__":
    main()
