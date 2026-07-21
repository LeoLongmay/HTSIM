#!/usr/bin/env python3
"""Run the minimal residual-recycling M2 A/B smoke experiment."""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[4]))

from htsim.sim.datacenter.add_motivation.common.run_case import run_case
from htsim.sim.datacenter.add_motivation.expM2_redistribution_progress.gen_workload import generate_workload


OUT = HERE / "data" / "controlled" / "intervention" / "confirmation"
TOPOLOGY = HERE.parents[1] / "topologies" / "fat_tree_128_1os.topo"
SEEDS = (101, 102, 103)
WORKLOAD_SEED = 101
CASES = (
    ("recoverable", 8, 8, 50.0),
    ("persistent", 12, 8, 50.0),
)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for seed in SEEDS:
        for scenario, flows, degraded_links, capacity in CASES:
            for treatment in ("baseline", "recycle"):
                run_id = f"ab_{treatment}_{scenario}_s{seed}"
                if (OUT / f"{run_id}.manifest.json").exists():
                    print(f"existing {run_id}")
                    continue
                traffic = OUT / f"{run_id}.cm"
                traffic.write_text(
                    generate_workload(foreground_flows=flows, seed=WORKLOAD_SEED).foreground_text,
                    encoding="ascii",
                )
                run_case(
                experiment="M2_redistribution_progress",
                phase="confirmation",
                run_id=run_id,
                cc="prism",
                seed=seed,
                topology=TOPOLOGY,
                traffic=traffic,
                out_dir=OUT,
                trace_prefix=OUT / run_id,
                degraded_links=degraded_links,
                degraded_capacity_gbps=capacity,
                analysis_config={
                    "cell_id": f"ab-{scenario}",
                    "scenario": scenario,
                    "foreground_flows": flows,
                    "degraded_links": degraded_links,
                    "degraded_capacity_gbps": capacity,
                    "seed": seed,
                },
                motivation_residual_recycle=treatment == "recycle",
                motivation_residual_threshold_us=10.0,
                )
                print(run_id)


if __name__ == "__main__":
    main()
