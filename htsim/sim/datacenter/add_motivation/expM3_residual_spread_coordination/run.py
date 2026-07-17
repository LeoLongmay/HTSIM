#!/usr/bin/env python3
"""Run the fixed M3 residual-spread coordination trial matrix."""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[4]))

from htsim.sim.datacenter.add_motivation.common.run_case import run_case
from htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.gen_workload import write_workload


SCENARIOS = {
    "recoverable": {"foreground_flows": 8, "offered_load_gbps": 744.0},
    "persistent": {"foreground_flows": 12, "offered_load_gbps": 931.0},
}
MODES = ("original_prism", "prism_recycle", "full_prism")
SEEDS = (13, 14, 15)
FORMAL_CONFIG = HERE / "configs" / "formal.csv"
TOPOLOGY = HERE.parents[1] / "topologies" / "fat_tree_128_1os.topo"


def _formal_rows() -> tuple[dict, ...]:
    with FORMAL_CONFIG.open(newline="", encoding="ascii") as stream:
        rows = tuple(csv.DictReader(stream))
    expected = {
        (mode, scenario, seed, 8, 25.0)
        for scenario in SCENARIOS for seed in SEEDS for mode in MODES
    }
    actual = {
        (row["mode"], row["scenario"], int(row["seed"]), int(row["degraded_links"]), float(row["degraded_capacity_gbps"]))
        for row in rows
    }
    if len(rows) != 18 or actual != expected:
        raise ValueError("formal.csv must contain exactly the locked 18 M3 rows")
    return rows


def _run_one(*, phase: str, output: Path, mode: str, scenario: str, seed: int,
             degraded_links: int = 8, degraded_capacity_gbps: float = 25.0) -> None:
    scenario_config = SCENARIOS[scenario]
    workload = output / "workloads" / f"{scenario}_s{seed}.cm"
    if not workload.exists():
        write_workload(workload, foreground_flows=scenario_config["foreground_flows"], seed=seed)
    run_id = f"{phase}_{mode}_{scenario}_s{seed}"
    run_case(
        experiment="M3_residual_spread_coordination",
        phase=phase,
        run_id=run_id,
        cc="prism",
        seed=seed,
        topology=TOPOLOGY,
        traffic=workload,
        out_dir=output,
        trace_prefix=output / run_id,
        load_balancing_algo="reps_actual",
        prism_coordination_mode=mode,
        degraded_links=degraded_links,
        degraded_capacity_gbps=degraded_capacity_gbps,
        analysis_config={
            "cell_id": f"m3-{scenario}",
            "scenario": scenario,
            "foreground_flows": scenario_config["foreground_flows"],
            "degraded_links": degraded_links,
            "degraded_capacity_gbps": degraded_capacity_gbps,
            "seed": seed,
        },
    )
    print(run_id)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("smoke", "formal"), required=True)
    parser.add_argument("--smoke-seed", type=int, default=13)
    parser.add_argument("--case", nargs=3, metavar=("MODE", "SCENARIO", "SEED"))
    args = parser.parse_args(argv)
    output = HERE / "data" / args.phase
    output.mkdir(parents=True, exist_ok=True)
    if args.case is not None:
        mode, scenario, seed_text = args.case
        if mode not in MODES or scenario not in SCENARIOS:
            raise ValueError("case must use a locked M3 mode and scenario")
        _run_one(phase=args.phase, output=output, mode=mode, scenario=scenario, seed=int(seed_text))
        return 0
    if args.phase == "smoke":
        rows = (
            {"mode": mode, "scenario": scenario, "seed": args.smoke_seed,
             "degraded_links": "8", "degraded_capacity_gbps": "25"}
            for scenario in SCENARIOS for mode in MODES
        )
    else:
        rows = _formal_rows()
    for row in rows:
        subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--phase", args.phase,
             "--case", row["mode"], row["scenario"], str(row["seed"])],
            check=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
