#!/usr/bin/env python3
"""Archive and redraw ExpG2 A2A and Butterfly message-size figures."""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))
import msgsweep_figs  # noqa: E402

BASELINES = [("ops", "OPS+NSCC", "ops"), ("reps", "REPS+NSCC", "reps"),
             ("swift", "REPS+Swift", "swift"), ("mswift", "REPS+MSwift", "mswift"),
             ("mnscc", "REPS+MNSCC", "mnscc"), ("strack", "STrack", "strack"),
             ("prism", "Prism", "prism")]
SIZES = [16384, 65536, 262144, 1048576, 4194304]
COLLECTIVES = (("a2a", list(range(13, 18)), "figH_a2a_msgsize", None),
               ("bfly", list(range(13, 43)), "figH_bfly_msgsize", [0, 1, 2]))


def _write(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="ascii", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["arm", "size", "mean", "err_lo", "err_hi", "min_cr"], lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)


def extract(data: Path, archive: Path) -> None:
    for collective, seeds, stem, _yticks in COLLECTIVES:
        values = msgsweep_figs.aggregate_slowdown_vs_best(
            data, f"expG2{collective}", [arm for arm, _label, _color in BASELINES], SIZES, seeds)
        _write(archive / f"{stem}.csv",
               [{"arm": arm, "size": size, "mean": repr(values[arm][size][0]),
                 "err_lo": repr(values[arm][size][1]), "err_hi": repr(values[arm][size][2]),
                 "min_cr": repr(values[arm][size][3])}
                for arm, _label, _color in BASELINES for size in SIZES])


def render(archive: Path, figures: Path) -> None:
    for collective, seeds, stem, yticks in COLLECTIVES:
        with (archive / f"{stem}.csv").open(encoding="ascii", newline="") as stream:
            rows = list(csv.DictReader(stream))
        values = {arm: {} for arm, _label, _color in BASELINES}
        for row in rows:
            values[row["arm"]][int(row["size"])] = tuple(float(row[key]) for key in ("mean", "err_lo", "err_hi", "min_cr"))
        original = msgsweep_figs.aggregate_slowdown_vs_best
        try:
            msgsweep_figs.aggregate_slowdown_vs_best = lambda *_args, **_kwargs: values
            msgsweep_figs.render_relative_bars(archive, figures, f"expG2{collective}", BASELINES, "reps",
                                               SIZES, seeds, stem, ylabel="CCT slowdown", ybottom=0.0,
                                               vs_best=True, yticks=yticks)
        finally:
            msgsweep_figs.aggregate_slowdown_vs_best = original


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
