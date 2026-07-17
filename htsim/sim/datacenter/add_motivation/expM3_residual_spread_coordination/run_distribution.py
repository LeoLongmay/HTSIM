#!/usr/bin/env python3
"""Run the locked M3 traffic-distribution matrix."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[4]))

from htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination import run


MODES = ("original_prism", "prism_recycle")
SEEDS = (13, 14, 15)
CONFIG = HERE / "configs" / "distribution.csv"
OUTPUT = HERE / "data" / "distribution"


def _validate_distribution_rows(rows: list[dict[str, str]]) -> tuple[dict[str, str], ...]:
    expected = {
        (mode, scenario, seed, degraded_links, 25.0)
        for mode in MODES
        for scenario, degraded_links in (("recoverable", 2), ("persistent", 8))
        for seed in SEEDS
    }
    try:
        actual = {
            (
                row["mode"],
                row["scenario"],
                int(row["seed"]),
                int(row["degraded_links"]),
                float(row["degraded_capacity_gbps"]),
            )
            for row in rows
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("distribution.csv must contain exactly the locked 12 M3 distribution rows") from exc
    if len(rows) != 12 or actual != expected:
        raise ValueError("distribution.csv must contain exactly the locked 12 M3 distribution rows")
    return tuple(rows)


def _distribution_rows() -> tuple[dict[str, str], ...]:
    with CONFIG.open(newline="", encoding="ascii") as stream:
        rows = list(csv.DictReader(stream))
    return _validate_distribution_rows(rows)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for row in _distribution_rows():
        run._run_one(
            phase="distribution",
            output=OUTPUT,
            mode=row["mode"],
            scenario=row["scenario"],
            seed=int(row["seed"]),
            degraded_links=int(row["degraded_links"]),
            degraded_capacity_gbps=float(row["degraded_capacity_gbps"]),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
