#!/usr/bin/env python3
"""Archive and redraw the two standalone FigL1 rate-stability panels."""

from __future__ import annotations

import argparse
import csv
import importlib.util
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("expL_make_figs", HERE / "make_figs.py")
assert SPEC and SPEC.loader
make_figs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(make_figs)


def extract(data_dir: Path, archive_dir: Path) -> None:
    """Keep precisely the primary trajectories used by the two panels."""
    rows = make_figs._read_csv(data_dir / "rate_series.csv", make_figs.RATE_SERIES_FIELDS)
    selected = [row for row in rows if row["kind"] == "primary"]
    if not selected:
        raise ValueError("no primary rate-series rows found")
    archive_dir.mkdir(parents=True, exist_ok=True)
    output = archive_dir / "figL1_rate_panels.csv"
    with output.open("w", newline="", encoding="ascii") as stream:
        writer = csv.DictWriter(stream, fieldnames=make_figs.RATE_SERIES_FIELDS,
                                lineterminator="\n")
        writer.writeheader()
        writer.writerows(selected)


def render(archive_dir: Path, figures_dir: Path) -> None:
    """Redraw both requested panels from archive-only plotting coordinates."""
    rows = make_figs._read_csv(archive_dir / "figL1_rate_panels.csv",
                               make_figs.RATE_SERIES_FIELDS)
    for condition in make_figs.CONDITIONS:
        make_figs._render_primary_panel(rows, figures_dir, condition)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extract", action="store_true")
    parser.add_argument("--data", type=Path, default=HERE / "data")
    parser.add_argument("--archive-dir", type=Path, default=HERE / "archive_data")
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--figs", type=Path, default=HERE / "figs")
    args = parser.parse_args()
    if args.extract:
        extract(args.data, args.archive_dir)
    if args.render:
        render(args.archive_dir, args.figs)
    if not args.extract and not args.render:
        parser.error("provide --extract, --render, or both")


if __name__ == "__main__":
    main()
