#!/usr/bin/env python3
"""Run the locked M5 Prism real-asymmetry ablation through run_lib.sh."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence


HERE = Path(__file__).resolve().parent
DATACENTER = HERE.parents[1]
PRISM_EVAL_COMMON = DATACENTER / "prism_eval" / "common"
if str(PRISM_EVAL_COMMON) not in sys.path:
    sys.path.insert(0, str(PRISM_EVAL_COMMON))
from metrics import fct_stats, parse_flow_events  # noqa: E402


SCHEMA = "m5_real_asymmetry_ablation_runner"
SCHEMA_VERSION = 1
ARMS = {
    "reps_nscc": ("nscc", "reps", None),
    "original_prism": ("prism", "reps", "original_prism"),
    "residual_prism": ("prism", "reps", "prism_recycle"),
    "full_prism": ("prism", "reps", "full_prism"),
}
FAILED_LINKS = (0, 4, 8)
SEEDS = tuple(range(13, 23))
SMOKE_FAILED = 4
SMOKE_SEED = 13
TOPOLOGY_NAME = "fat_tree_128_1os.topo"
PATHS = 8
END_MS = 8
NODES = 128
MTU = 4150
FLOW_COUNT = 64
FLOW_SIZE_BYTES = 2_000_000
WORKLOAD_PARAMETERS = (64, 16, "pairs", FLOW_SIZE_BYTES, NODES, 16)

TOPOLOGY = DATACENTER / "topologies" / TOPOLOGY_NAME
HTSIM_UEC = DATACENTER / "htsim_uec"
PARSE_OUTPUT = DATACENTER.parent / "build" / "parse_output"
RUN_LIB = PRISM_EVAL_COMMON / "run_lib.sh"


@dataclasses.dataclass(frozen=True)
class Case:
    arm: str
    failed: int
    seed: int


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_case(case: Case, *, phase: str | None = None) -> Case:
    if case.arm not in ARMS or case.seed not in SEEDS:
        raise ValueError("case must use a locked M5 arm and seed")
    allowed_failed = (SMOKE_FAILED,) if phase == "smoke" else FAILED_LINKS
    if case.failed not in allowed_failed:
        raise ValueError("case must use a locked M5 failed-link count")
    return case


def parse_case(values: Sequence[str], *, phase: str) -> Case:
    if len(values) != 3:
        raise ValueError("case must provide ARM FAILED SEED")
    try:
        case = Case(values[0], int(values[1]), int(values[2]))
    except ValueError as exc:
        raise ValueError("failed links and seed must be integers") from exc
    return _validate_case(case, phase=phase)


def cases_for_phase(phase: str) -> tuple[Case, ...]:
    if phase == "formal":
        failed_links, seeds = FAILED_LINKS, SEEDS
    elif phase == "smoke":
        failed_links, seeds = (SMOKE_FAILED,), (SMOKE_SEED,)
    else:
        raise ValueError("phase must be smoke or formal")
    return tuple(Case(arm, failed, seed) for arm in ARMS for failed in failed_links for seed in seeds)


def case_id(case: Case) -> str:
    return f"m5_{case.arm}_f{case.failed}_s{case.seed}"


def _workload_text() -> str:
    lines = [f"Nodes {NODES}", f"Connections {FLOW_COUNT}"]
    lines.extend(
        f"{sender}->{receiver} start 1000 size {FLOW_SIZE_BYTES}"
        for sender, receiver in ((16 + index, index % 16) for index in range(FLOW_COUNT))
    )
    return "\n".join(lines) + "\n"


def ensure_workload(path: Path) -> str:
    expected = _workload_text()
    if path.exists():
        if not path.is_file() or path.read_text(encoding="ascii") != expected:
            raise ValueError(f"conflicting M5 workload: {path}")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="ascii", newline="") as stream:
            stream.write(expected)
    return _sha256(path)


def fixed_environment(case: Case) -> dict[str, str]:
    cc, _, coordination_mode = ARMS[case.arm]
    del cc
    env = os.environ.copy()
    for name in (
        "TQD", "MTU", "NODES", "KEEPDAT", "PRISM_EPOCH", "PRISM_PATHRTT",
        "PRISM_HOLD_TRACE", "PRISM_LOSS",
    ):
        env.pop(name, None)
    extra_args = ["-disable_trim"]
    if coordination_mode is not None:
        extra_args.extend(("-prism_coordination_mode", coordination_mode))
    env.update(
        {
            "PATHS": str(PATHS),
            "END_MS": str(END_MS),
            "MTU": str(MTU),
            "NODES": str(NODES),
            "EXTRA_ARGS": " ".join(extra_args),
        }
    )
    return env


def run_lib_command(case: Case, workload: Path, output_root: Path) -> list[str]:
    cc, lb, _ = ARMS[case.arm]
    return [
        "bash", str(RUN_LIB), cc, lb, str(case.failed), TOPOLOGY_NAME,
        str(case.seed), str(workload), "flow", case_id(case), str(output_root),
    ]


def _required_outputs(output_root: Path, run_id: str) -> dict[str, Path]:
    return {
        "flow": output_root / f"{run_id}.flow.txt",
        "stdout": output_root / f"{run_id}.stdout",
        "idmap": output_root / f"{run_id}.idmap",
        "manifest": output_root / f"{run_id}.manifest.json",
        "dat": output_root / f"{run_id}.dat",
        "ascii": output_root / f"{run_id}.ascii.tmp",
    }


def _validate_flow(path: Path) -> None:
    try:
        starts, finishes = parse_flow_events(path)
        stats = fct_stats(path)
    except (OSError, ValueError, IndexError) as exc:
        raise ValueError("unreadable flow output") from exc
    if (
        len(starts) != FLOW_COUNT
        or len(finishes) != FLOW_COUNT
        or starts.keys() != finishes.keys()
        or stats["total_started"] != FLOW_COUNT
        or stats["completed"] != FLOW_COUNT
        or stats["completion_rate"] != 1.0
    ):
        raise ValueError("incomplete flow output")
    if any(nbytes != FLOW_SIZE_BYTES for _, nbytes in finishes.values()):
        raise ValueError("flow output has an unexpected completion size")


def _expected_manifest(*, phase: str, case: Case, workload: Path, workload_hash: str,
                       output_root: Path) -> dict:
    run_id = case_id(case)
    outputs = _required_outputs(output_root, run_id)
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "experiment": "M5_real_asymmetry_ablation",
        "phase": phase,
        "run_id": run_id,
        "arm": case.arm,
        "scenario": "real_expa_many_to_many",
        "failed_links": case.failed,
        "seed": case.seed,
        "fixed_parameters": {
            "topology": TOPOLOGY_NAME,
            "paths": PATHS,
            "end_ms": END_MS,
            "nodes": NODES,
            "mtu": MTU,
            "disable_trim": True,
            "flow_count": FLOW_COUNT,
            "flow_size_bytes": FLOW_SIZE_BYTES,
            "workload_generator": {
                "path": "prism_eval/common/gen/many2many.py",
                "parameters": list(WORKLOAD_PARAMETERS),
            },
        },
        "config": {
            "run_lib_argv": run_lib_command(case, workload, output_root),
            "environment": {
                name: fixed_environment(case)[name]
                for name in ("PATHS", "END_MS", "MTU", "NODES", "EXTRA_ARGS")
            },
        },
        "workload": {"filename": workload.name, "sha256": workload_hash},
        "topology": {"filename": TOPOLOGY.name, "sha256": _sha256(TOPOLOGY)},
        "htsim_uec": {"filename": HTSIM_UEC.name, "sha256": _sha256(HTSIM_UEC)},
        "parse_output": {"filename": PARSE_OUTPUT.name, "sha256": _sha256(PARSE_OUTPUT)},
        "output_files": {name: path.name for name, path in outputs.items() if name not in ("dat", "ascii")},
    }


def _reuse_or_reject(outputs: dict[str, Path], expected: dict) -> bool:
    all_paths = tuple(outputs.values())
    if not any(path.exists() for path in all_paths):
        return False
    if outputs["dat"].exists() or outputs["ascii"].exists():
        raise FileExistsError("stale simulator temporary output")
    required = ("flow", "stdout", "idmap", "manifest")
    if any(not outputs[name].is_file() or outputs[name].stat().st_size == 0 for name in required):
        raise FileExistsError("incomplete prior output")
    try:
        actual = json.loads(outputs["manifest"].read_text(encoding="ascii"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("existing manifest is invalid") from exc
    if actual != expected:
        raise ValueError("existing manifest identity conflicts")
    try:
        _validate_flow(outputs["flow"])
    except ValueError as exc:
        raise ValueError(f"existing flow output is invalid: {exc}") from exc
    return True


def run_one(case: Case, *, phase: str, output_root: Path) -> Path:
    if phase not in ("smoke", "formal"):
        raise ValueError("phase must be smoke or formal")
    case = _validate_case(case, phase=phase)
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    workload = output_root / "m2m.cm"
    workload_hash = ensure_workload(workload)
    run_id = case_id(case)
    outputs = _required_outputs(output_root, run_id)
    expected = _expected_manifest(
        phase=phase, case=case, workload=workload, workload_hash=workload_hash, output_root=output_root,
    )
    if _reuse_or_reject(outputs, expected):
        return outputs["manifest"]
    if not all(path.is_file() for path in (TOPOLOGY, HTSIM_UEC, PARSE_OUTPUT, RUN_LIB)):
        raise FileNotFoundError("M5 topology, htsim_uec, parse_output, or run_lib is missing")
    subprocess.run(
        run_lib_command(case, workload, output_root),
        cwd=DATACENTER,
        env=fixed_environment(case),
        check=True,
    )
    required = ("flow", "stdout", "idmap")
    if any(not outputs[name].is_file() or outputs[name].stat().st_size == 0 for name in required):
        raise RuntimeError("run_lib produced incomplete output")
    if outputs["dat"].exists() or outputs["ascii"].exists():
        raise RuntimeError("run_lib left stale simulator temporary output")
    try:
        _validate_flow(outputs["flow"])
    except ValueError as exc:
        raise RuntimeError(f"incomplete flow output: {exc}") from exc
    with outputs["manifest"].open("x", encoding="ascii", newline="") as stream:
        json.dump(expected, stream, indent=2, sort_keys=True, ensure_ascii=True)
        stream.write("\n")
    print(run_id)
    return outputs["manifest"]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("smoke", "formal"), required=True)
    parser.add_argument("--case", nargs=3, metavar=("ARM", "FAILED", "SEED"))
    parser.add_argument("--output-root", type=Path, default=HERE / "data")
    args = parser.parse_args(argv)
    output_root = args.output_root / args.phase
    cases = (parse_case(args.case, phase=args.phase),) if args.case else cases_for_phase(args.phase)
    for case in cases:
        run_one(case, phase=args.phase, output_root=output_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
