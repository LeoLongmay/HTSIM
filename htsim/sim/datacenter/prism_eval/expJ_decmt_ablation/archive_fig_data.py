#!/usr/bin/env python3
"""Archive and redraw the three standalone ExpJ failed=8 bar panels."""

from __future__ import annotations

import argparse
import csv
import importlib.util
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("expj_make_figs", HERE / "make_figs.py")
assert SPEC and SPEC.loader
make_figs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(make_figs)

FIELDS = (
    "arm", "mean_goodput_gbps", "std_goodput_gbps", "mean_avg_fct_us",
    "std_avg_fct_us", "mean_p99_fct_us", "std_p99_fct_us",
)


def extract(summary_path: Path, archive_dir: Path) -> None:
    """Retain only the four failed=8 means and standard deviations drawn as bars."""
    rows = make_figs._read_summary(summary_path)
    selected = [row for row in rows if int(row["failed_links"]) == 8]
    if {row["arm"] for row in selected} != set(make_figs.run.ARMS) or len(selected) != 4:
        raise ValueError("expected exactly four failed=8 ExpJ summary rows")
    archive_dir.mkdir(parents=True, exist_ok=True)
    with (archive_dir / "figJ1_failed8_bars.csv").open("w", encoding="ascii", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows([{field: row[field] for field in FIELDS} for row in selected])


def render(archive_dir: Path, figures_dir: Path) -> None:
    """Redraw the requested panels from their exact bar heights and error bars."""
    with (archive_dir / "figJ1_failed8_bars.csv").open(encoding="ascii", newline="") as stream:
        rows = list(csv.DictReader(stream))
    values = {(row["arm"], 8): {**row, "failed_links": 8, "n_seeds": 10} for row in rows}
    expected = {(arm, 8) for arm in make_figs.run.ARMS}
    if set(values) != expected:
        raise ValueError("archive is missing one or more ExpJ bar rows")
    make_figs.render_single_panels(values, figures_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extract", action="store_true")
    parser.add_argument("--summary", type=Path, default=HERE / "data" / "aggregate" / "summary.csv")
    parser.add_argument("--archive-dir", type=Path, default=HERE / "archive_data")
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--figs", type=Path, default=HERE / "figs")
    args = parser.parse_args()
    if args.extract:
        extract(args.summary, args.archive_dir)
    if args.render:
        render(args.archive_dir, args.figs)
    if not args.extract and not args.render:
        parser.error("provide --extract, --render, or both")


if __name__ == "__main__":
    main()
