#!/usr/bin/env python3
"""Archive and redraw FigF1 and FigF3 without ExpF simulation logs."""
from __future__ import annotations

import argparse
import csv
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMMON = HERE.parent / "common"
sys.path.insert(0, str(COMMON))
import msgsweep_figs  # noqa: E402

BASELINES = [("ops", "OPS+NSCC", "ops"), ("reps", "REPS+NSCC", "reps"),
             ("swift", "REPS+Swift", "swift"), ("mswift", "REPS+MSwift", "mswift"),
             ("mnscc", "REPS+MNSCC", "mnscc"), ("strack", "STrack", "strack"),
             ("prism", "Prism", "prism")]
SEEDS = [13, 14, 15, 16, 17]
SIZES = [16384, 65536, 262144, 1048576, 4194304]


def _write(path: Path, fields: list[str], rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="ascii", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)


def extract(data: Path, archive: Path) -> None:
    """Archive the available FigF3 sweep; FigF1's original logs are absent."""
    sweep = msgsweep_figs.aggregate_slowdown_vs_best(
        data, "expFmsg", [arm for arm, _label, _color in BASELINES], SIZES, SEEDS)
    _write(archive / "figF3_ai_msgsize.csv", ["arm", "size", "mean", "err_lo", "err_hi", "min_cr"],
           [{"arm": arm, "size": size, "mean": repr(sweep[arm][size][0]),
             "err_lo": repr(sweep[arm][size][1]), "err_hi": repr(sweep[arm][size][2]),
             "min_cr": repr(sweep[arm][size][3])}
            for arm, _label, _color in BASELINES for size in SIZES])


def _read(path: Path):
    with path.open(encoding="ascii", newline="") as stream:
        return list(csv.DictReader(stream))


def render(archive: Path, figures: Path) -> None:
    sweep = {arm: {} for arm, _label, _color in BASELINES}
    for row in _read(archive / "figF3_ai_msgsize.csv"):
        sweep[row["arm"]][int(row["size"])] = tuple(float(row[name]) for name in ("mean", "err_lo", "err_hi", "min_cr"))
    original_sweep = msgsweep_figs.aggregate_slowdown_vs_best
    try:
        msgsweep_figs.aggregate_slowdown_vs_best = lambda *_args, **_kwargs: sweep
        msgsweep_figs.render_relative_bars(archive, figures, "expFmsg", BASELINES, "reps", SIZES, SEEDS,
                                           "figF3_ai_msgsize", ylabel="CCT slowdown", ybottom=0.0,
                                           vs_best=True)
    finally:
        msgsweep_figs.aggregate_slowdown_vs_best = original_sweep


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extract", action="store_true")
    parser.add_argument("--data", type=Path, default=HERE / "data")
    parser.add_argument("--archive-dir", type=Path, default=HERE / "archive_data")
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--figs", type=Path, default=HERE / "figs")
    args = parser.parse_args()
    if args.extract: extract(args.data, args.archive_dir)
    if args.render: render(args.archive_dir, args.figs)
    if not args.extract and not args.render: parser.error("provide --extract, --render, or both")


if __name__ == "__main__": main()
