#!/usr/bin/env python3
"""Run the locked M7 Prism hold/state-machine ablation through run_lib.sh."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import re
import subprocess
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Sequence


HERE = Path(__file__).resolve().parent
DATACENTER = HERE.parents[1]
PRISM_EVAL_COMMON = DATACENTER / "prism_eval" / "common"
if str(PRISM_EVAL_COMMON) not in sys.path:
    sys.path.insert(0, str(PRISM_EVAL_COMMON))
from metrics import fct_stats  # noqa: E402


SCHEMA = "m7_hold_state_ablation_runner"
SCHEMA_VERSION = 1
ARMS = {
    "reps_nscc": ("nscc", "reps_actual", None, None),
    "original_prism": ("prism", "reps_actual", "original_prism", None),
    "hold_to_increase_prism": ("prism", "reps_actual", "original_prism", "hold_to_increase"),
    "observe_only_prism": ("prism", "reps_actual", None, "observe_only"),
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
UEC_IDMAP_NAME = re.compile(r"Uec_(?P<src>\d+)_(?P<dst>\d+)")


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
        raise ValueError("case must use a locked M7 arm and seed")
    allowed_failed = (SMOKE_FAILED,) if phase == "smoke" else FAILED_LINKS
    if case.failed not in allowed_failed:
        raise ValueError("case must use a locked M7 failed-link count")
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
    return f"m7_{case.arm}_f{case.failed}_s{case.seed}"


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
            raise ValueError(f"conflicting M7 workload: {path}")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="ascii", newline="") as stream:
            stream.write(expected)
    return _sha256(path)


def fixed_environment(case: Case) -> dict[str, str]:
    cc, _, coordination_mode, mode = ARMS[case.arm]
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
    if mode == "hold_to_increase":
        extra_args.append("-prism_hold_as_increase")
    elif mode == "observe_only":
        # Keep Prism's signal collection active but make engagement unreachable.
        extra_args.extend(("-prism_engage_mult", "1000000"))
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
    cc, lb, _, _ = ARMS[case.arm]
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


def _load_uec_idmap(path: Path) -> dict[int, tuple[int, int]]:
    try:
        lines = path.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError("missing or unreadable idmap") from exc
    idmap = {}
    for line in lines:
        fields = line.split(maxsplit=1)
        if len(fields) != 2:
            continue
        match = UEC_IDMAP_NAME.fullmatch(fields[1])
        if match is None:
            continue
        try:
            object_id = int(fields[0])
        except ValueError as exc:
            raise ValueError("invalid idmap object ID") from exc
        if object_id in idmap:
            raise ValueError("duplicate UEC idmap object ID")
        idmap[object_id] = (int(match["src"]), int(match["dst"]))
    return idmap


def _flow_event_number(tokens: list[str], name: str) -> int:
    positions = [index for index, token in enumerate(tokens[:-1]) if token == name]
    if len(positions) != 1:
        raise ValueError(f"missing or duplicate {name}")
    try:
        return int(tokens[positions[0] + 1])
    except ValueError as exc:
        raise ValueError(f"invalid {name}") from exc


def _parse_flow_event(line: str) -> tuple[tuple[int, int], str, Decimal]:
    fields = line.split()
    if (
        len(fields) < 11
        or fields[1:4] != ["Type", "FLOW_EVENT", "SrcID"]
        or fields[5:6] != ["Ev"]
        or fields[7:8] != ["FlowID"]
    ):
        raise ValueError("malformed FLOW_EVENT")
    try:
        event_time = Decimal(fields[0])
        src_id = int(fields[4])
        flow_id = int(fields[8])
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("invalid FLOW_EVENT time or ID") from exc
    if not event_time.is_finite() or src_id < 0 or flow_id < 0:
        raise ValueError("invalid FLOW_EVENT time or ID")
    event = fields[6]
    if event == "START":
        if _flow_event_number(fields[9:], "Flowsize") != FLOW_SIZE_BYTES:
            raise ValueError("START has an unexpected flow size")
    elif event == "FINISH":
        if _flow_event_number(fields[9:], "Bytes") != FLOW_SIZE_BYTES:
            raise ValueError("FINISH has an unexpected byte count")
    else:
        raise ValueError("unknown FLOW_EVENT type")
    return (src_id, flow_id), event, event_time


def _scan_flow_events(path: Path) -> set[tuple[int, int]]:
    try:
        lines = path.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError("unreadable flow output") from exc
    starts: dict[tuple[int, int], Decimal] = {}
    finishes: dict[tuple[int, int], Decimal] = {}
    for line in lines:
        if "FLOW_EVENT" not in line:
            continue
        event_key, event, event_time = _parse_flow_event(line)
        events = starts if event == "START" else finishes
        if event_key in events:
            raise ValueError(f"duplicate {event} FLOW_EVENT")
        events[event_key] = event_time
    if len(starts) != FLOW_COUNT or len(finishes) != FLOW_COUNT:
        raise ValueError("incomplete flow output")
    if starts.keys() != finishes.keys():
        raise ValueError("START and FINISH event keys differ")
    if any(finishes[event_key] < start_time for event_key, start_time in starts.items()):
        raise ValueError("FINISH precedes START")
    return set(starts)


def _expected_workload_endpoints() -> set[tuple[int, int]]:
    return {(16 + index, index % 16) for index in range(FLOW_COUNT)}


def _flow_event_bindings(event_keys: set[tuple[int, int]],
                         idmap: dict[int, tuple[int, int]]) -> dict[tuple[int, int], tuple[int, int]]:
    expected_endpoints = _expected_workload_endpoints()
    bindings = {}
    for event_key in event_keys:
        src_endpoint = idmap.get(event_key[0])
        flow_endpoint = idmap.get(event_key[1])
        if src_endpoint is None or flow_endpoint is None:
            raise ValueError("FLOW_EVENT ID is absent from idmap")
        if src_endpoint != flow_endpoint:
            raise ValueError("FLOW_EVENT IDs resolve to different workload endpoints")
        if src_endpoint not in expected_endpoints:
            raise ValueError("FLOW_EVENT endpoint is absent from the workload")
        bindings[event_key] = src_endpoint
    if len(bindings) != FLOW_COUNT or set(bindings.values()) != expected_endpoints:
        raise ValueError("FLOW_EVENT bindings are not a workload bijection")
    return bindings


def _serialized_event_bindings(bindings: dict[tuple[int, int], tuple[int, int]]) -> list[dict]:
    return [
        {
            "src_id": event_key[0],
            "flow_id": event_key[1],
            "workload_src": endpoint[0],
            "workload_dst": endpoint[1],
        }
        for event_key, endpoint in sorted(bindings.items())
    ]


def _manifest_event_bindings(value: object) -> dict[tuple[int, int], tuple[int, int]]:
    if not isinstance(value, list):
        raise ValueError("missing flow event bindings")
    bindings = {}
    for row in value:
        if not isinstance(row, dict):
            raise ValueError("invalid flow event binding")
        try:
            event_key = (int(row["src_id"]), int(row["flow_id"]))
            endpoint = (int(row["workload_src"]), int(row["workload_dst"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid flow event binding") from exc
        if event_key in bindings:
            raise ValueError("duplicate flow event binding")
        bindings[event_key] = endpoint
    return bindings


def _validate_flow(path: Path, idmap_path: Path) -> dict[tuple[int, int], tuple[int, int]]:
    event_keys = _scan_flow_events(path)
    try:
        stats = fct_stats(path)
    except (OSError, ValueError, IndexError) as exc:
        raise ValueError("unreadable flow output") from exc
    if (
        stats["total_started"] != FLOW_COUNT
        or stats["completed"] != FLOW_COUNT
        or stats["completion_rate"] != 1.0
    ):
        raise ValueError("incomplete flow output")
    return _flow_event_bindings(event_keys, _load_uec_idmap(idmap_path))


def _expected_manifest(*, phase: str, case: Case, workload: Path, workload_hash: str,
                       output_root: Path) -> dict:
    run_id = case_id(case)
    outputs = _required_outputs(output_root, run_id)
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "experiment": "M7_hold_state_ablation",
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
    manifest = dict(actual)
    serialized_bindings = manifest.pop("flow_event_bindings", None)
    if manifest != expected:
        raise ValueError("existing manifest identity conflicts")
    try:
        bindings = _validate_flow(outputs["flow"], outputs["idmap"])
        if _manifest_event_bindings(serialized_bindings) != bindings:
            raise ValueError("flow event bindings conflict with output")
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
        raise FileNotFoundError("M7 topology, htsim_uec, parse_output, or run_lib is missing")
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
        bindings = _validate_flow(outputs["flow"], outputs["idmap"])
    except ValueError as exc:
        raise RuntimeError(f"incomplete flow output: {exc}") from exc
    with outputs["manifest"].open("x", encoding="ascii", newline="") as stream:
        json.dump(
            expected | {"flow_event_bindings": _serialized_event_bindings(bindings)},
            stream,
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
        )
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
