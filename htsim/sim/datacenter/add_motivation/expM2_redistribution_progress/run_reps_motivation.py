#!/usr/bin/env python3
"""Run controlled REPS-only traces for the residual-spread motivation."""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[4]))

from htsim.sim.datacenter.add_motivation.common.run_case import run_case
from htsim.sim.datacenter.add_motivation.expM2_redistribution_progress.gen_workload import generate_workload


OUT = HERE / "data" / "controlled" / "reps_actual_nscc_motivation_c25"
TOPOLOGY = HERE.parents[1] / "topologies" / "fat_tree_128_1os.topo"
SEED = 101
CASES = (("recoverable", 8), ("persistent", 12))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for scenario, flows in CASES:
        run_id = f"reps_actual_nscc_c25_{scenario}_s{SEED}"
        if (OUT / f"{run_id}.manifest.json").exists():
            print(f"existing {run_id}")
            continue
        traffic = OUT / f"{run_id}.cm"
        traffic.write_text(
            generate_workload(foreground_flows=flows, seed=SEED).foreground_text,
            encoding="ascii",
        )
        run_case(
            experiment="M2_redistribution_progress",
            phase="confirmation",
            run_id=run_id,
            cc="nscc",
            seed=SEED,
            topology=TOPOLOGY,
            traffic=traffic,
            out_dir=OUT,
            trace_prefix=OUT / run_id,
            degraded_links=8,
            degraded_capacity_gbps=25.0,
            load_balancing_algo="reps_actual",
            analysis_config={
                "cell_id": f"reps-actual-nscc-c25-{scenario}",
                "scenario": scenario,
                "foreground_flows": flows,
                "degraded_links": 8,
                "degraded_capacity_gbps": 25.0,
                "seed": SEED,
            },
        )
        print(run_id)


if __name__ == "__main__":
    main()
