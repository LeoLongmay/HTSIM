#!/usr/bin/env python3
"""Run the fixed M4 Prism performance-ablation matrix directly in htsim_uec."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Sequence


HERE = Path(__file__).resolve().parent
if __package__ in (None, ""):
    sys.path.insert(0, str(HERE.parents[4]))
    from htsim.sim.datacenter.add_motivation.expM4_performance_ablation.gen_workload import workload_text
else:
    from .gen_workload import workload_text


DATACENTER_DIR = HERE.parents[1]
HTSIM_UEC = DATACENTER_DIR / "htsim_uec"
PARSE_OUTPUT = DATACENTER_DIR.parent / "build" / "parse_output"
TOPOLOGY = DATACENTER_DIR / "topologies" / "fat_tree_128_1os.topo"
SCHEMA = "m4_performance_ablation_runner"
SCHEMA_VERSION = 1
SEEDS = (13, 14, 15)
END_MS = 40
FLOW_SIZE_BYTES = 32_000_000


@dataclasses.dataclass(frozen=True)
class Arm:
    sender_cc: str
    coordination_mode: str | None


@dataclasses.dataclass(frozen=True)
class Scenario:
    foreground_flows: int
    degraded_links: int
    offered_ceiling_gbps: int
    healthy_capacity_gbps: int


@dataclasses.dataclass(frozen=True)
class Case:
    arm: str
    scenario: str
    seed: int


ARMS = {
    "reps_nscc": Arm("nscc", None),
    "original_prism": Arm("prism", "original_prism"),
    "residual_prism": Arm("prism", "prism_recycle"),
    "full_prism": Arm("prism", "full_prism"),
}
SCENARIOS = {
    "recoverable": Scenario(6, 2, 600, 800),
    "persistent": Scenario(12, 8, 1200, 800),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_case(case: Case) -> Case:
    if case.arm not in ARMS or case.scenario not in SCENARIOS or case.seed not in SEEDS:
        raise ValueError("case must use a locked M4 arm, scenario, and seed")
    return case


def parse_case(values: Sequence[str]) -> Case:
    if len(values) != 3:
        raise ValueError("case must provide ARM SCENARIO SEED")
    try:
        seed = int(values[2])
    except ValueError as exc:
        raise ValueError("case seed must be an integer") from exc
    return _validate_case(Case(values[0], values[1], seed))


def cases_for_phase(phase: str) -> tuple[Case, ...]:
    if phase == "formal":
        seeds = SEEDS
    elif phase == "smoke":
        seeds = (13,)
    else:
        raise ValueError("phase must be smoke or formal")
    return tuple(Case(arm, scenario, seed) for arm in ARMS for scenario in SCENARIOS for seed in seeds)


def _run_id(phase: str, case: Case) -> str:
    return f"{phase}_{case.arm}_{case.scenario}_s{case.seed}"


def _ensure_workload(path: Path, *, foreground_flows: int, seed: int) -> str:
    expected = workload_text(foreground_flows=foreground_flows, seed=seed)
    if path.exists():
        if not path.is_file() or path.read_text(encoding="ascii") != expected:
            raise ValueError(f"conflicting workload: {path}")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="ascii", newline="") as stream:
            stream.write(expected)
    return _sha256(path)


def _command(case: Case, workload: Path, dat_path: Path) -> list[str]:
    arm = ARMS[case.arm]
    scenario = SCENARIOS[case.scenario]
    command = [
        str(HTSIM_UEC),
        "-topo", str(TOPOLOGY),
        "-tm", str(workload),
        "-nodes", "128",
        "-seed", str(case.seed),
        "-sender_cc_only",
        "-sender_cc_algo", arm.sender_cc,
        "-load_balancing_algo", "reps_actual",
        "-paths", "8",
        "-mtu", "4150",
        "-q", "211",
        "-disable_trim",
        "-target_q_delay", "14",
        "-prism_t_spray", "14",
        "-prism_kappa", "1",
        "-prism_n_min", "3",
        "-degraded_links", str(scenario.degraded_links),
        "-degraded_capacity_gbps", "25",
        "-end", str(END_MS),
        "-o", str(dat_path),
    ]
    if arm.coordination_mode is not None:
        command.extend(("-prism_coordination_mode", arm.coordination_mode))
    return command


def _expected_manifest(*, phase: str, case: Case, run_id: str, workload: Path,
                       workload_hash: str, dat_path: Path) -> dict:
    scenario = SCENARIOS[case.scenario]
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "experiment": "M4_performance_ablation",
        "phase": phase,
        "run_id": run_id,
        "arm": case.arm,
        "scenario": case.scenario,
        "seed": case.seed,
        "flow_size_bytes": FLOW_SIZE_BYTES,
        "end_ms": END_MS,
        "scenario_config": dataclasses.asdict(scenario),
        "config": {"argv": _command(case, workload, dat_path)},
        "workload": {"filename": workload.name, "sha256": workload_hash},
        "binary": {"filename": HTSIM_UEC.name, "sha256": _sha256(HTSIM_UEC)},
        "output_files": {
            "flow": f"{run_id}.flow.txt",
            "stdout": f"{run_id}.stdout",
            "manifest": f"{run_id}.manifest.json",
        },
    }


def _reuse_or_reject(*, manifest_path: Path, flow_path: Path, stdout_path: Path,
                     dat_path: Path, ascii_path: Path, expected: dict) -> bool:
    paths = (manifest_path, flow_path, stdout_path, dat_path, ascii_path)
    if not any(path.exists() for path in paths):
        return False
    if dat_path.exists() or ascii_path.exists():
        raise FileExistsError("incomplete prior run left simulator temporary output")
    if not (manifest_path.is_file() and flow_path.is_file() and stdout_path.is_file()):
        raise FileExistsError("incomplete prior run output")
    if flow_path.stat().st_size == 0:
        raise ValueError("existing flow output is empty")
    try:
        actual = json.loads(manifest_path.read_text(encoding="ascii"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("existing manifest is invalid") from exc
    for field in (
        "schema", "schema_version", "experiment", "phase", "run_id", "arm", "scenario", "seed",
        "flow_size_bytes", "end_ms", "scenario_config", "config", "workload", "binary", "output_files",
    ):
        if actual.get(field) != expected[field]:
            raise ValueError(f"existing manifest identity conflicts at {field}")
    return True


def run_one(case: Case, *, phase: str, output_root: Path) -> Path:
    if phase not in ("smoke", "formal"):
        raise ValueError("phase must be smoke or formal")
    case = _validate_case(case)
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    scenario = SCENARIOS[case.scenario]
    workload = output_root / "workloads" / f"{case.scenario}_s{case.seed}.cm"
    workload_hash = _ensure_workload(workload, foreground_flows=scenario.foreground_flows, seed=case.seed)
    run_id = _run_id(phase, case)
    flow_path = output_root / f"{run_id}.flow.txt"
    stdout_path = output_root / f"{run_id}.stdout"
    manifest_path = output_root / f"{run_id}.manifest.json"
    dat_path = output_root / f"{run_id}.dat"
    ascii_path = output_root / f"{run_id}.ascii.tmp"
    expected = _expected_manifest(
        phase=phase,
        case=case,
        run_id=run_id,
        workload=workload,
        workload_hash=workload_hash,
        dat_path=dat_path,
    )
    if _reuse_or_reject(
        manifest_path=manifest_path,
        flow_path=flow_path,
        stdout_path=stdout_path,
        dat_path=dat_path,
        ascii_path=ascii_path,
        expected=expected,
    ):
        return manifest_path

    if not HTSIM_UEC.is_file() or not PARSE_OUTPUT.is_file() or not TOPOLOGY.is_file():
        raise FileNotFoundError("htsim_uec, parse_output, or the M4 topology is missing")
    command = expected["config"]["argv"]
    with tempfile.TemporaryDirectory(prefix=f".{run_id}.", dir=output_root) as working_directory:
        with stdout_path.open("x", encoding="ascii") as stdout:
            subprocess.run(
                command,
                cwd=working_directory,
                stdout=stdout,
                stderr=subprocess.STDOUT,
                check=True,
            )
        if not dat_path.is_file():
            raise RuntimeError("htsim_uec did not create its .dat output")
        with ascii_path.open("x", encoding="ascii") as ascii_output:
            subprocess.run(
                [str(PARSE_OUTPUT), str(dat_path), "-ascii"],
                cwd=working_directory,
                stdout=ascii_output,
                stderr=subprocess.PIPE,
                check=True,
                text=True,
            )
    flow_events = [
        line for line in ascii_path.read_text(encoding="ascii").splitlines(keepends=True)
        if " FLOW_EVENT " in line
    ]
    if not flow_events:
        raise RuntimeError("decoder produced no FLOW_EVENT records")
    with flow_path.open("x", encoding="ascii", newline="") as flow_output:
        flow_output.writelines(flow_events)
    dat_path.unlink()
    ascii_path.unlink()
    with manifest_path.open("x", encoding="ascii", newline="") as manifest_output:
        json.dump(expected, manifest_output, indent=2, sort_keys=True, ensure_ascii=True)
        manifest_output.write("\n")
    print(run_id)
    return manifest_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("smoke", "formal"), required=True)
    parser.add_argument("--case", nargs=3, metavar=("ARM", "SCENARIO", "SEED"))
    parser.add_argument("--output-root", type=Path, default=HERE / "data")
    args = parser.parse_args(argv)
    output = args.output_root / args.phase
    cases = (parse_case(args.case),) if args.case is not None else cases_for_phase(args.phase)
    for case in cases:
        run_one(case, phase=args.phase, output_root=output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
