#!/usr/bin/env python3
"""Run the fixed Prism Hold-episode experiment matrix."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


SEEDS = (13, 14, 15)
T_CC_US = 14
T_SPRAY_US = 14
PATHS = 8
MTU = 4150
NODES = 128

HERE = Path(__file__).resolve().parent
COMMON = HERE.parent / "common"
DATACENTER = HERE.parents[1]
TOPOLOGY = "fat_tree_128_1os.topo"


@dataclass(frozen=True)
class Case:
    scenario: str
    seed: int
    failed: int
    fanin: int | None
    disable_trim: bool
    end_ms: int
    workload: str
    t_cc_us: int = T_CC_US
    t_spray_us: int = T_SPRAY_US
    loss_decomp: bool = False


def locked_cases() -> tuple[Case, ...]:
    """Return the approved 4-scenario by 3-seed matrix, in stable order."""
    scenario_defaults = (
        ("f0", 0, None, True, 8, "m2m"),
        ("asymmetric", 8, None, True, 8, "m2m"),
        ("incast", 0, 64, True, 8, "incast"),
        ("trimming", 8, None, False, 2, "m2m"),
    )
    return tuple(
        Case(
            scenario=scenario,
            seed=seed,
            failed=failed,
            fanin=fanin,
            disable_trim=disable_trim,
            end_ms=end_ms,
            workload=workload,
        )
        for scenario, failed, fanin, disable_trim, end_ms, workload in scenario_defaults
        for seed in SEEDS
    )


def case_tag(case: Case) -> str:
    return f"hold_{case.scenario}_s{case.seed}"


def generate_workloads(output_dir: Path) -> dict[str, Path]:
    """Generate the two fixed traffic matrices used by the locked cases."""
    m2m = output_dir / "m2m.cm"
    incast = output_dir / "incast_64.cm"
    subprocess.run(
        [
            sys.executable,
            str(COMMON / "gen" / "many2many.py"),
            str(m2m),
            "64",
            "16",
            "pairs",
            "2000000",
            "128",
            "16",
        ],
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            str(COMMON / "gen" / "incast.py"),
            str(incast),
            "64",
            "0",
            "1000000",
            "128",
            "16",
        ],
        check=True,
    )
    return {"m2m": m2m, "incast": incast}


def write_manifest(case: Case, output_dir: Path) -> Path:
    tag = case_tag(case)
    manifest = {
        "schema_version": 1,
        **asdict(case),
        "paths": PATHS,
        "mtu": MTU,
        "nodes": NODES,
        "tag": tag,
        "outputs": {
            "epoch": f"{tag}.epoch.csv",
            "hold": f"{tag}.hold.csv",
            "flow": f"{tag}.flow.txt",
        },
    }
    path = output_dir / f"{tag}.manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="ascii")
    return path


def fixed_run_environment(case: Case, output_dir: Path) -> dict[str, str]:
    """Return the complete runner environment for one locked case."""
    tag = case_tag(case)
    extra_args = ["-target_q_delay", str(case.t_cc_us)]
    if case.disable_trim:
        extra_args.insert(0, "-disable_trim")

    env = os.environ.copy()
    for name in ("TQD", "MTU", "NODES", "KEEPDAT", "PRISM_PATHRTT", "PRISM_LOSS"):
        env.pop(name, None)
    env.update(
        {
            "PATHS": str(PATHS),
            "END_MS": str(case.end_ms),
            "MTU": str(MTU),
            "NODES": str(NODES),
            "EXTRA_ARGS": " ".join(extra_args),
            "PRISM_EPOCH": str(output_dir / f"{tag}.epoch.csv"),
            "PRISM_HOLD_TRACE": str(output_dir / f"{tag}.hold.csv"),
        }
    )
    return env


def run_case(case: Case, output_dir: Path, workloads: dict[str, Path]) -> None:
    tag = case_tag(case)
    env = fixed_run_environment(case, output_dir)
    subprocess.run(
        [
            "bash",
            str(COMMON / "run_lib.sh"),
            "prism",
            "reps",
            str(case.failed),
            TOPOLOGY,
            str(case.seed),
            str(workloads[case.workload]),
            "flow",
            tag,
            str(output_dir),
        ],
        cwd=DATACENTER,
        env=env,
        check=True,
    )
    write_manifest(case, output_dir)


def run_matrix(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    workloads = generate_workloads(output_dir)
    for case in locked_cases():
        run_case(case, output_dir, workloads)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="directory for matrix outputs")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_matrix(args.output.resolve())


if __name__ == "__main__":
    main()
