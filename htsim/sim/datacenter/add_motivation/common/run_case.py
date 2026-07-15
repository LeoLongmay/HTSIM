#!/usr/bin/env python3
"""Run one motivation experiment case with a fixed, auditable configuration."""

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
from pathlib import Path


COMMON_DIR = Path(__file__).resolve().parent
ADD_MOTIVATION_DIR = COMMON_DIR.parent
DATACENTER_DIR = ADD_MOTIVATION_DIR.parent
REPO_DIR = DATACENTER_DIR.parents[2]
BINARY = DATACENTER_DIR / "htsim_uec"

SCHEMA_VERSION = 2
MTU_BYTES = 4150
QUEUE_PACKETS = 211
QUEUE_BYTES = MTU_BYTES * QUEUE_PACKETS
NORMAL_CAPACITY_GBPS = 100.0
VALID_PHASES = {"calibration", "smoke", "formal"}
VALID_CCS = {
    "constant",
    "dctcp",
    "lswift",
    "mnscc",
    "mswift",
    "nscc",
    "prism",
    "strack",
    "swift",
}
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
TRACE_SUFFIXES = ("ack", "token", "epoch", "background", "pathmap", "linkmap")


def _safe_name(value, field):
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    if not SAFE_NAME.fullmatch(value):
        raise ValueError(f"{field} must contain only letters, digits, '.', '_', and '-'")
    return value


def _input_file(value, field):
    path = Path(value).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError(f"{field} must be a regular file: {path}")
    return path


def _contained_path(value, field):
    path = Path(value).expanduser().resolve(strict=False)
    try:
        path.relative_to(ADD_MOTIVATION_DIR)
    except ValueError as error:
        raise ValueError(f"{field} must remain inside {ADD_MOTIVATION_DIR}") from error
    return path


def _background_value(value):
    if value is None:
        return None
    if isinstance(value, (str, os.PathLike)):
        return str(_input_file(value, "background_config"))
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError("background_config must be a file path or JSON value") from error
    return value


def _git_commit():
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        cwd=REPO_DIR,
        capture_output=True,
        text=True,
    )
    commit = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-fA-F]{7,64}", commit):
        raise ValueError(f"git rev-parse returned an invalid commit: {commit!r}")
    return commit


def _number_arg(value):
    return format(value, "g")


def run_case(*, experiment, phase, run_id, cc, seed, topology, traffic,
             out_dir, trace_prefix, degraded_links=0,
             degraded_capacity_gbps=100.0, background_config=None):
    experiment = _safe_name(experiment, "experiment")
    run_id = _safe_name(run_id, "run_id")
    if phase not in VALID_PHASES:
        raise ValueError(f"phase must be one of {sorted(VALID_PHASES)}")
    if cc not in VALID_CCS:
        raise ValueError(f"cc must be one of {sorted(VALID_CCS)}")
    if type(seed) is not int or seed < 0 or seed > 2**31 - 1:
        raise ValueError("seed must be an integer in [0, 2147483647]")
    if type(degraded_links) is not int or degraded_links < 0 or degraded_links > 2**32 - 1:
        raise ValueError("degraded_links must be an integer in [0, 4294967295]")
    if isinstance(degraded_capacity_gbps, bool) or not isinstance(
        degraded_capacity_gbps, (int, float)
    ):
        raise TypeError("degraded_capacity_gbps must be numeric")
    degraded_capacity_gbps = float(degraded_capacity_gbps)
    if not math.isfinite(degraded_capacity_gbps) or not (
        0 < degraded_capacity_gbps <= NORMAL_CAPACITY_GBPS
    ):
        raise ValueError("degraded_capacity_gbps must be in (0, 100]")

    topology_path = _input_file(topology, "topology")
    traffic_path = _input_file(traffic, "traffic")
    output_dir = _contained_path(out_dir, "out_dir")
    trace_path = _contained_path(trace_prefix, "trace_prefix")
    if output_dir.exists() and not output_dir.is_dir():
        raise ValueError(f"out_dir is not a directory: {output_dir}")
    if trace_path.exists() and trace_path.is_dir():
        raise ValueError(f"trace_prefix is a directory: {trace_path}")
    background_value = _background_value(background_config)

    output_dir.mkdir(parents=True, exist_ok=True)
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    simulation_path = output_dir / f"{run_id}.dat"
    stdout_path = output_dir / f"{run_id}.stdout"
    manifest_path = output_dir / f"{run_id}.manifest.json"
    output_filenames = {
        "simulation": str(simulation_path),
        "stdout": str(stdout_path),
        **{name: f"{trace_path}.{name}.csv" for name in TRACE_SUFFIXES},
        "manifest": str(manifest_path),
    }

    argv = [
        str(BINARY),
        "-topo", str(topology_path),
        "-tm", str(traffic_path),
        "-nodes", "128",
        "-sender_cc_algo", cc,
        "-sender_cc_only",
        "-load_balancing_algo", "reps",
        "-paths", "8",
        "-mtu", str(MTU_BYTES),
        "-q", str(QUEUE_PACKETS),
        "-disable_trim",
        "-target_q_delay", "14",
        "-prism_t_spray", "14",
        "-prism_kappa", "1",
        "-prism_n_min", "3",
        "-degraded_links", str(degraded_links),
        "-degraded_capacity_gbps", _number_arg(degraded_capacity_gbps),
        "-seed", str(seed),
        "-motivation_trace_prefix", str(trace_path),
        "-motivation_run_id", run_id,
        "-motivation_scenario", experiment,
        "-end", "12",
        "-o", str(simulation_path),
    ]

    commit = _git_commit()
    traffic_sha256 = hashlib.sha256(traffic_path.read_bytes()).hexdigest()
    with stdout_path.open("w", encoding="ascii") as stdout:
        subprocess.run(
            argv,
            check=True,
            cwd=output_dir,
            stdout=stdout,
            stderr=subprocess.STDOUT,
        )

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "git_commit": commit,
        "argv": argv,
        "experiment": experiment,
        "phase": phase,
        "run_id": run_id,
        "seed": seed,
        "topology": str(topology_path),
        "traffic": str(traffic_path),
        "traffic_sha256": traffic_sha256,
        "queue_bytes": QUEUE_BYTES,
        "config": {
            "cc": cc,
            "load_balancing_algo": "reps",
            "paths": 8,
            "mtu_bytes": MTU_BYTES,
            "queue_packets": QUEUE_PACKETS,
            "queue_bytes": QUEUE_BYTES,
            "disable_trim": True,
            "ecn": "default",
            "t_cc_us": 14,
            "t_spray_us": 14,
            "kappa": 1,
            "n_min": 3,
            "sender_cc_only": True,
            "normal_capacity_gbps": NORMAL_CAPACITY_GBPS,
            "degraded_links": degraded_links,
            "degraded_capacity_gbps": degraded_capacity_gbps,
            "background_config": background_value,
            "simulation_end_ms": 12,
        },
        "output_filenames": output_filenames,
    }

    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="ascii",
            dir=output_dir,
            prefix=f".{run_id}.manifest.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_name = handle.name
            json.dump(manifest, handle, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, manifest_path)
    finally:
        if temp_name is not None and os.path.exists(temp_name):
            os.unlink(temp_name)

    return manifest_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--phase", required=True, choices=sorted(VALID_PHASES))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--cc", required=True, choices=sorted(VALID_CCS))
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--topology", required=True, type=Path)
    parser.add_argument("--traffic", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--trace-prefix", required=True, type=Path)
    parser.add_argument("--degraded-links", type=int, default=0)
    parser.add_argument("--degraded-capacity-gbps", type=float, default=NORMAL_CAPACITY_GBPS)
    parser.add_argument("--background-config", type=Path)
    args = parser.parse_args(argv)
    manifest = run_case(
        experiment=args.experiment,
        phase=args.phase,
        run_id=args.run_id,
        cc=args.cc,
        seed=args.seed,
        topology=args.topology,
        traffic=args.traffic,
        out_dir=args.out_dir,
        trace_prefix=args.trace_prefix,
        degraded_links=args.degraded_links,
        degraded_capacity_gbps=args.degraded_capacity_gbps,
        background_config=args.background_config,
    )
    print(manifest)


if __name__ == "__main__":
    main()
