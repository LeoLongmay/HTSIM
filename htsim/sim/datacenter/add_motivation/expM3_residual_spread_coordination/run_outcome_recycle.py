#!/usr/bin/env python3
"""Run the locked recoverable M3 outcome-recycle comparison."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[4]))

from htsim.sim.datacenter.add_motivation.common import run_case
from htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination import run


MODES = ("prism_recycle", "outcome_recycle")
SEEDS = (13, 14, 15)
CONFIG = HERE / "configs" / "outcome_recycle.csv"
OUTPUT = HERE / "data" / "outcome_recycle"

# This runner owns its phase without widening common runner state globally.
run_case.VALID_PHASES.add("outcome_recycle")


def _validate_outcome_recycle_rows(rows: list[dict[str, str]]) -> tuple[dict[str, str], ...]:
    expected = {
        (mode, "recoverable", seed, 13, 13, 211, 2, 25.0)
        for mode in MODES
        for seed in SEEDS
    }
    try:
        actual = {
            (
                row["mode"],
                row["scenario"],
                int(row["seed"]),
                int(row["workload_seed"]),
                int(row["route_hash_seed"]),
                int(row["ecn_threshold_packets"]),
                int(row["degraded_links"]),
                float(row["degraded_capacity_gbps"]),
            )
            for row in rows
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            "outcome_recycle.csv must contain exactly the locked six recoverable M3 rows"
        ) from exc
    if len(rows) != 6 or actual != expected:
        raise ValueError(
            "outcome_recycle.csv must contain exactly the locked six recoverable M3 rows"
        )
    return tuple(rows)


def _outcome_recycle_rows() -> tuple[dict[str, str], ...]:
    with CONFIG.open(newline="", encoding="ascii") as stream:
        return _validate_outcome_recycle_rows(list(csv.DictReader(stream)))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for row in _outcome_recycle_rows():
        run._run_one(
            phase="outcome_recycle",
            output=OUTPUT,
            mode=row["mode"],
            scenario=row["scenario"],
            seed=int(row["seed"]),
            workload_seed=int(row["workload_seed"]),
            motivation_ecmp_hash_seed=int(row["route_hash_seed"]),
            motivation_ecn_threshold_packets=int(row["ecn_threshold_packets"]),
            degraded_links=int(row["degraded_links"]),
            degraded_capacity_gbps=float(row["degraded_capacity_gbps"]),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
