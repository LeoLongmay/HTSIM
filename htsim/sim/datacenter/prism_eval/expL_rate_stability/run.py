#!/usr/bin/env python3
"""Run the locked ExpL DecMT aggregate delivery-rate stability matrix."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Sequence


HERE = Path(__file__).resolve().parent
DATACENTER = HERE.parents[1]
COMMON = HERE.parent / "common"
RUN_LIB = COMMON / "run_lib.sh"
TOPOLOGY_NAME = "fat_tree_128_1os.topo"
HTSIM_UEC = DATACENTER / "htsim_uec"

PRIMARY_ARMS = {
    "ops": ("nscc", "oblivious", "OPS", ""),
    "reps": ("nscc", "reps", "REPS", ""),
    "strack": ("strack", "reps", "STrack", ""),
    "decmt": (
        "prism",
        "reps",
        "DecMT",
        "-prism_smooth_beta 0.3 -prism_hysteresis 0.25 "
        "-prism_engage_spread 28 -prism_disengage_spread 20",
    ),
}
BETA_VALUES = (1.0, 0.5, 0.3, 0.15)
SEEDS = (13, 14, 15, 16, 17)
CONDITIONS = {"symmetric": 0, "asymmetric": 8}

PATHS = 8
END_MS = 8
NODES = 128
MTU = 4150
LOGTIME_US = 10
FLOW_COUNT = 64
FLOW_SIZE_BYTES = 32_000_000
WORKLOAD_PARAMETERS = (64, 16, "pairs", 32_000_000, 128, 16)
RETAINED_ARTIFACTS = ("sink", "stdout", "idmap")
SCHEMA = "expl_rate_stability_runner"
SCHEMA_VERSION = 1
DECMT_V2_ARGS = PRIMARY_ARMS["decmt"][3]


@dataclasses.dataclass(frozen=True)
class Case:
    """One primary controller case or one asymmetric DecMT beta case."""

    kind: str
    seed: int
    condition: str | None = None
    arm: str | None = None
    beta: float | None = None

    @property
    def case_id(self) -> str:
        return case_id(self)


def _beta_label(beta: float) -> str:
    return str(beta).replace(".", "p")


def _validate_case(case: Case, *, phase: str | None = None) -> Case:
    if case.seed not in SEEDS:
        raise ValueError("case must use a locked seed")
    if case.kind == "primary":
        if case.condition not in CONDITIONS or case.arm not in PRIMARY_ARMS or case.beta is not None:
            raise ValueError("primary case must use a locked condition and arm")
    elif case.kind == "beta":
        if case.condition is not None or case.arm is not None or case.beta not in BETA_VALUES:
            raise ValueError("beta case must use a locked smoothing value")
    else:
        raise ValueError("case kind must be primary or beta")
    if phase == "smoke" and case != cases_for_phase("smoke")[0]:
        raise ValueError("smoke phase accepts only its locked representative case")
    return case


def cases_for_phase(phase: str) -> tuple[Case, ...]:
    """Return the stable case matrix for a runner phase."""
    if phase == "smoke":
        return (Case(kind="primary", condition="asymmetric", arm="decmt", seed=13),)
    if phase != "formal":
        raise ValueError("phase must be smoke or formal")
    primary = tuple(
        Case(kind="primary", condition=condition, arm=arm, seed=seed)
        for condition in CONDITIONS
        for arm in PRIMARY_ARMS
        for seed in SEEDS
    )
    beta = tuple(Case(kind="beta", beta=value, seed=seed) for value in BETA_VALUES for seed in SEEDS)
    return primary + beta


def case_id(case: Case) -> str:
    """Return the filesystem-safe, logical identity of one locked case."""
    _validate_case(case)
    if case.kind == "primary":
        return f"{case.condition}_{case.arm}_s{case.seed}"
    return f"beta_{_beta_label(case.beta)}_s{case.seed}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _workload_text() -> str:
    """Return exactly many2many.py 64 16 pairs 32000000 128 16 output."""
    senders = [host for host in range(NODES) if host // 16 != 0][:FLOW_COUNT]
    lines = [f"Nodes {NODES}", f"Connections {FLOW_COUNT}"]
    lines.extend(
        f"{sender}->{index % 16} start 1000 size {FLOW_SIZE_BYTES}"
        for index, sender in enumerate(senders)
    )
    return "\n".join(lines) + "\n"


def ensure_workload(path: Path) -> str:
    """Create the locked workload, or reject content that differs by one byte."""
    path = Path(path)
    expected = _workload_text()
    if path.exists():
        if not path.is_file() or path.read_text(encoding="ascii") != expected:
            raise ValueError(f"conflicting ExpL workload: {path}")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="ascii", newline="") as stream:
            stream.write(expected)
    return _sha256(path)


def _run_parameters(case: Case) -> tuple[str, str, int, str]:
    _validate_case(case)
    if case.kind == "primary":
        cc, lb, _, arm_args = PRIMARY_ARMS[case.arm]
        return cc, lb, CONDITIONS[case.condition], arm_args
    beta_args = DECMT_V2_ARGS.replace("-prism_smooth_beta 0.3", f"-prism_smooth_beta {case.beta}")
    return "prism", "reps", CONDITIONS["asymmetric"], beta_args


def fixed_environment(case: Case) -> dict[str, str]:
    """Return the isolated fixed environment passed to ``run_lib.sh``."""
    _, _, _, arm_args = _run_parameters(case)
    env = os.environ.copy()
    for name in (
        "PATHS", "END_MS", "NODES", "MTU", "LOGTIME_US", "EXTRA_ARGS", "TQD", "KEEPDAT",
        "TMP", "TEMP", "TMPDIR", "PRISM_TRACE", "PRISM_TMP", "UEC_TMP", "PRISM_PATHRTT",
        "PRISM_EPOCH", "PRISM_LOSS", "MNSCC_MEDIAN",
    ):
        env.pop(name, None)
    env.update({
        "PATHS": "8",
        "END_MS": "8",
        "NODES": "128",
        "MTU": "4150",
        "LOGTIME_US": "10",
        "EXTRA_ARGS": " ".join(part for part in ("-disable_trim", arm_args) if part),
    })
    return env


def run_lib_command(case: Case, workload: Path, output_root: Path) -> list[str]:
    """Build the transient execution command for the common runner."""
    cc, lb, failed, _ = _run_parameters(case)
    return [
        "bash", str(RUN_LIB), cc, lb, str(failed), TOPOLOGY_NAME, str(case.seed),
        str(workload), "sink", f"rate_{case_id(case)}", str(output_root),
    ]


def _logical_run_lib_command(case: Case) -> list[str]:
    cc, lb, failed, _ = _run_parameters(case)
    return [
        "bash", "prism_eval/common/run_lib.sh", cc, lb, str(failed), TOPOLOGY_NAME,
        str(case.seed), "bundle:m2m.cm", "sink", f"rate_{case_id(case)}", "bundle:raw",
    ]


def _outputs(case: Case, output_root: Path) -> dict[str, Path]:
    tag = f"rate_{case_id(case)}"
    return {
        "sink": output_root / f"{tag}.sink.txt",
        "stdout": output_root / f"{tag}.stdout",
        "idmap": output_root / f"{tag}.idmap",
        "manifest": output_root / f"{case_id(case)}.manifest.json",
        "dat": output_root / f"{tag}.dat",
        "ascii": output_root / f"{tag}.ascii.tmp",
    }


def _manifest(case: Case, *, phase: str, workload: Path, output_root: Path) -> dict:
    cc, lb, failed, arm_args = _run_parameters(case)
    environment = fixed_environment(case)
    outputs = _outputs(case, output_root)
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "experiment": "ExpL_rate_stability",
        "phase": phase,
        "case_id": case_id(case),
        "kind": case.kind,
        "condition": case.condition,
        "arm": case.arm,
        "beta": case.beta,
        "seed": case.seed,
        "fixed_parameters": {
            "topology": TOPOLOGY_NAME,
            "failed_links": failed,
            "cc": cc,
            "lb": lb,
            "paths": PATHS,
            "end_ms": END_MS,
            "nodes": NODES,
            "mtu": MTU,
            "logtime_us": LOGTIME_US,
            "disable_trim": True,
            "arm_extra_args": arm_args,
            "workload_generator": {
                "path": "prism_eval/common/gen/many2many.py",
                "parameters": list(WORKLOAD_PARAMETERS),
            },
        },
        "config": {
            "run_lib_argv": _logical_run_lib_command(case),
            "environment": {name: environment[name] for name in (
                "PATHS", "END_MS", "NODES", "MTU", "LOGTIME_US", "EXTRA_ARGS",
            )},
        },
        "workload": {"filename": workload.name, "sha256": _sha256(workload)},
        "htsim_uec": {"filename": HTSIM_UEC.name, "sha256": _sha256(HTSIM_UEC)},
        "run_lib": {"path": "prism_eval/common/run_lib.sh", "sha256": _sha256(RUN_LIB)},
        "output_files": {name: {"filename": outputs[name].name} for name in RETAINED_ARTIFACTS},
    }


def _completed_manifest(manifest: dict, outputs: dict[str, Path]) -> dict:
    return manifest | {
        "output_files": {
            name: manifest["output_files"][name] | {"sha256": _sha256(outputs[name])}
            for name in RETAINED_ARTIFACTS
        }
    }


def _reuse_or_reject(manifest: dict, outputs: dict[str, Path]) -> bool:
    existing = tuple(outputs[name] for name in (*RETAINED_ARTIFACTS, "manifest"))
    if not any(path.exists() for path in existing):
        return False
    if any(not path.is_file() or path.stat().st_size == 0 for path in existing):
        raise FileExistsError("incomplete prior output")
    try:
        actual = json.loads(outputs["manifest"].read_text(encoding="ascii"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("existing manifest is invalid") from exc
    actual_files = actual.pop("output_files", None) if isinstance(actual, dict) else None
    if not isinstance(actual_files, dict):
        raise ValueError("existing manifest output metadata is invalid")
    expected = dict(manifest)
    expected.pop("output_files")
    if actual != expected:
        raise ValueError("existing manifest identity conflicts")
    for name in RETAINED_ARTIFACTS:
        metadata = actual_files.get(name)
        if not isinstance(metadata, dict) or metadata.get("filename") != outputs[name].name:
            raise ValueError(f"existing manifest artifact metadata is invalid: {name}")
        if metadata.get("sha256") != _sha256(outputs[name]):
            raise ValueError(f"artifact SHA-256 mismatch: {name}")
    return True


def run_one(case: Case, *, phase: str, output_root: Path) -> Path:
    """Execute one case and atomically record its immutable provenance bundle."""
    if phase not in ("smoke", "formal"):
        raise ValueError("phase must be smoke or formal")
    case = _validate_case(case, phase=phase)
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    workload = output_root / "m2m.cm"
    ensure_workload(workload)
    outputs = _outputs(case, output_root)
    manifest = _manifest(case, phase=phase, workload=workload, output_root=output_root)
    if _reuse_or_reject(manifest, outputs):
        return outputs["manifest"]
    if outputs["dat"].exists() or outputs["ascii"].exists():
        raise FileExistsError("stale simulator temporary output")
    if not all(path.is_file() for path in (RUN_LIB, HTSIM_UEC)):
        raise FileNotFoundError("ExpL run_lib.sh or htsim_uec is missing")
    subprocess.run(
        run_lib_command(case, workload, output_root),
        cwd=DATACENTER,
        env=fixed_environment(case),
        check=True,
    )
    if any(not outputs[name].is_file() or outputs[name].stat().st_size == 0 for name in RETAINED_ARTIFACTS):
        raise RuntimeError("run_lib produced incomplete output")
    if outputs["dat"].exists() or outputs["ascii"].exists():
        raise RuntimeError("run_lib left stale simulator temporary output")
    with outputs["manifest"].open("x", encoding="ascii", newline="") as stream:
        json.dump(_completed_manifest(manifest, outputs), stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(case_id(case))
    return outputs["manifest"]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("smoke", "formal"), required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    cases = cases_for_phase(args.phase)
    if args.dry_run:
        for case in cases:
            print(shlex.join(_logical_run_lib_command(case)))
        return 0
    output_root = args.output_root or HERE / "data" / ("smoke" if args.phase == "smoke" else "raw")
    for case in cases:
        run_one(case, phase=args.phase, output_root=output_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
