#!/usr/bin/env python3
"""Run one motivation experiment case with a fixed, auditable configuration."""

import argparse
import hashlib
import json
import math
import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path

try:
    from htsim.sim.datacenter.add_motivation.common.trace_schema import load_trace
except ModuleNotFoundError:
    from trace_schema import load_trace


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
VALID_PHASES = {"calibration", "smoke", "coarse", "confirmation", "formal"}
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
VALID_LOAD_BALANCERS = {"reps", "reps_actual"}
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
TRACE_SUFFIXES = (
    "ack", "token", "epoch", "background", "pathmap", "linkmap", "coordination",
)
M2_EXPERIMENT = "M2_redistribution_progress"
M2_SIMULATION_END_MS = 3
ANALYSIS_CONFIG_FIELDS = (
    "cell_id",
    "scenario",
    "foreground_flows",
    "degraded_links",
    "degraded_capacity_gbps",
    "seed",
)


def validate_identifier(value, field):
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


def _validate_output_parent(path, field):
    parent = path.parent.resolve(strict=False)
    try:
        parent.relative_to(ADD_MOTIVATION_DIR)
    except ValueError as error:
        raise ValueError(f"{field} parent must remain inside {ADD_MOTIVATION_DIR}") from error


def _reject_existing_outputs(outputs):
    for name, path in outputs.items():
        _validate_output_parent(path, name)
        if not os.path.lexists(path):
            continue
        mode = os.lstat(path).st_mode
        if stat.S_ISLNK(mode):
            kind = "symlink"
        elif not stat.S_ISREG(mode):
            kind = "non-regular file"
        else:
            kind = "stale file"
        raise FileExistsError(f"refusing to overwrite {kind} for {name}: {path}")


def _open_exclusive_stdout(path):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o644)
    return os.fdopen(descriptor, "w", encoding="ascii")


def _validate_regular_output(path, name):
    try:
        metadata = os.lstat(path)
    except OSError as error:
        raise ValueError(f"missing {name} output: {path}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"{name} output must be a regular non-symlink file: {path}")
    if metadata.st_size <= 0:
        raise ValueError(f"{name} output is empty: {path}")


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _background_value(value):
    if value is None:
        return None
    return str(_input_file(value, "background_config"))


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


def _analysis_config(value, seed):
    if not isinstance(value, dict):
        raise TypeError("analysis_config must be a dictionary")
    if set(value) != set(ANALYSIS_CONFIG_FIELDS):
        missing = [field for field in ANALYSIS_CONFIG_FIELDS if field not in value]
        extra = sorted(set(value) - set(ANALYSIS_CONFIG_FIELDS))
        raise ValueError(
            f"analysis_config must contain exactly {list(ANALYSIS_CONFIG_FIELDS)}; "
            f"missing={missing}, extra={extra}"
        )
    if not isinstance(value["cell_id"], str) or not value["cell_id"]:
        raise ValueError("analysis_config cell_id must be a nonempty string")
    if value["scenario"] not in ("", "recoverable", "persistent"):
        raise ValueError(
            "analysis_config scenario must be empty, recoverable, or persistent"
        )
    for field in ("foreground_flows", "degraded_links"):
        if type(value[field]) is not int or value[field] <= 0:
            raise ValueError(f"analysis_config {field} must be a positive integer")
    capacity = value["degraded_capacity_gbps"]
    if isinstance(capacity, bool) or not isinstance(capacity, (int, float)):
        raise TypeError("analysis_config degraded_capacity_gbps must be numeric")
    capacity = float(capacity)
    if not math.isfinite(capacity) or not 0 < capacity < NORMAL_CAPACITY_GBPS:
        raise ValueError("analysis_config degraded_capacity_gbps must be in (0, 100)")
    if type(value["seed"]) is not int or value["seed"] != seed:
        raise ValueError("analysis_config seed must equal run seed")
    return {
        "cell_id": value["cell_id"],
        "scenario": value["scenario"],
        "foreground_flows": value["foreground_flows"],
        "degraded_links": value["degraded_links"],
        "degraded_capacity_gbps": capacity,
        "seed": value["seed"],
    }


def run_case(*, experiment, phase, run_id, cc, seed, topology, traffic,
             out_dir, trace_prefix, degraded_links=0,
             degraded_capacity_gbps=100.0, background_config=None,
             analysis_config=None, motivation_residual_recycle=False,
             motivation_residual_threshold_us=10.0, load_balancing_algo="reps",
             prism_coordination_mode="disabled"):
    experiment = validate_identifier(experiment, "experiment")
    run_id = validate_identifier(run_id, "run_id")
    if phase not in VALID_PHASES:
        raise ValueError(f"phase must be one of {sorted(VALID_PHASES)}")
    if cc not in VALID_CCS:
        raise ValueError(f"cc must be one of {sorted(VALID_CCS)}")
    if load_balancing_algo not in VALID_LOAD_BALANCERS:
        raise ValueError(f"load_balancing_algo must be one of {sorted(VALID_LOAD_BALANCERS)}")
    if prism_coordination_mode not in {
        "disabled", "original_prism", "prism_recycle", "full_prism",
    }:
        raise ValueError("invalid prism_coordination_mode")
    if type(motivation_residual_recycle) is not bool:
        raise TypeError("motivation_residual_recycle must be boolean")
    if isinstance(motivation_residual_threshold_us, bool) or not isinstance(
        motivation_residual_threshold_us, (int, float)
    ):
        raise TypeError("motivation_residual_threshold_us must be numeric")
    motivation_residual_threshold_us = float(motivation_residual_threshold_us)
    if not math.isfinite(motivation_residual_threshold_us) or motivation_residual_threshold_us <= 0:
        raise ValueError("motivation_residual_threshold_us must be positive")
    if motivation_residual_recycle and cc != "prism":
        raise ValueError("motivation_residual_recycle requires cc='prism'")
    if type(seed) is not int or seed < 0 or seed > 2**31 - 1:
        raise ValueError("seed must be an integer in [0, 2147483647]")
    if experiment == M2_EXPERIMENT and analysis_config is None:
        raise ValueError("M2 runs require analysis_config")
    simulation_end_ms = M2_SIMULATION_END_MS if experiment == M2_EXPERIMENT else 12
    normalized_analysis_config = (
        _analysis_config(analysis_config, seed) if analysis_config is not None else None
    )
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
    if (degraded_links == 0) != (degraded_capacity_gbps == NORMAL_CAPACITY_GBPS):
        raise ValueError(
            "controls require degraded_links=0 and degraded_capacity_gbps=100; "
            "gray cases require degraded_links>0 and degraded_capacity_gbps<100"
        )
    if normalized_analysis_config is not None and (
        normalized_analysis_config["degraded_links"] != degraded_links
        or normalized_analysis_config["degraded_capacity_gbps"]
        != degraded_capacity_gbps
    ):
        raise ValueError(
            "M2 analysis_config degradation fields must match simulator controls"
        )

    topology_path = _input_file(topology, "topology")
    traffic_path = _input_file(traffic, "traffic")
    output_dir = _contained_path(out_dir, "out_dir")
    trace_path = _contained_path(trace_prefix, "trace_prefix")
    if output_dir.exists() and not output_dir.is_dir():
        raise ValueError(f"out_dir is not a directory: {output_dir}")
    if trace_path.exists() and trace_path.is_dir():
        raise ValueError(f"trace_prefix is a directory: {trace_path}")
    background_value = _background_value(background_config)

    simulation_path = output_dir / f"{run_id}.dat"
    stdout_path = output_dir / f"{run_id}.stdout"
    manifest_path = output_dir / f"{run_id}.manifest.json"
    output_paths = {
        "simulation": simulation_path,
        "stdout": stdout_path,
        **{name: Path(f"{trace_path}.{name}.csv") for name in TRACE_SUFFIXES},
        "manifest": manifest_path,
    }
    _reject_existing_outputs(output_paths)

    binary_path = BINARY.resolve(strict=True)
    if not binary_path.is_file():
        raise ValueError(f"htsim_uec must resolve to a regular file: {BINARY}")
    topology_sha256 = _sha256(topology_path)
    traffic_sha256 = _sha256(traffic_path)
    binary_sha256 = _sha256(binary_path)
    background_config_sha256 = (
        _sha256(Path(background_value)) if background_value is not None else None
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    output_filenames = {name: str(path) for name, path in output_paths.items()}

    argv = [
        str(BINARY),
        "-topo", str(topology_path),
        "-tm", str(traffic_path),
        "-nodes", "128",
        "-sender_cc_algo", cc,
        "-sender_cc_only",
        "-load_balancing_algo", load_balancing_algo,
        "-paths", "8",
        "-mtu", str(MTU_BYTES),
        "-q", str(QUEUE_PACKETS),
        *(
            ["-queue_type", "ecn", "-host_queue_type", "fair_prio"]
            if background_value is not None
            else []
        ),
        "-disable_trim",
        "-target_q_delay", "14",
        "-prism_t_spray", "14",
        "-prism_kappa", "1",
        "-prism_n_min", "3",
        *(
            [
                "-motivation_residual_recycle",
                "-motivation_residual_threshold_us", _number_arg(motivation_residual_threshold_us),
            ]
            if motivation_residual_recycle
            else []
        ),
        *(
            ["-prism_coordination_mode", prism_coordination_mode]
            if prism_coordination_mode != "disabled"
            else []
        ),
        *(
            [
                "-prism_smooth_beta", "1",
                "-prism_hysteresis", "0",
                "-prism_engage_spread", "0",
                "-prism_engage_mult", "0",
            ]
            if cc == "prism"
            else []
        ),
        "-degraded_links", str(degraded_links),
        "-degraded_capacity_gbps", _number_arg(degraded_capacity_gbps),
        "-seed", str(seed),
        *(
            ["-motivation_background_config", background_value]
            if background_value is not None
            else []
        ),
        "-motivation_trace_prefix", str(trace_path),
        "-motivation_run_id", run_id,
        "-motivation_scenario", experiment,
        "-end", str(simulation_end_ms),
        "-o", str(simulation_path),
    ]

    commit = _git_commit()
    with _open_exclusive_stdout(stdout_path) as stdout:
        subprocess.run(
            argv,
            check=True,
            cwd=output_dir,
            stdout=stdout,
            stderr=subprocess.STDOUT,
        )

    _validate_regular_output(stdout_path, "stdout")
    _validate_regular_output(simulation_path, "simulation")
    for kind in TRACE_SUFFIXES:
        _validate_regular_output(output_paths[kind], kind)
    bundle = load_trace(trace_path)
    if bundle.run_id != run_id:
        raise ValueError(
            f"trace run_id mismatch: expected {run_id!r}, got {bundle.run_id!r}"
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
        "topology_sha256": topology_sha256,
        "traffic": str(traffic_path),
        "traffic_sha256": traffic_sha256,
        "binary": str(binary_path),
        "binary_sha256": binary_sha256,
        "queue_bytes": QUEUE_BYTES,
        "config": {
            "cc": cc,
            "load_balancing_algo": load_balancing_algo,
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
            "simulation_end_ms": simulation_end_ms,
            "motivation_residual_recycle": motivation_residual_recycle,
            "motivation_residual_threshold_us": motivation_residual_threshold_us,
            "prism_coordination_mode": prism_coordination_mode,
        },
        "output_filenames": output_filenames,
    }
    if normalized_analysis_config is not None:
        manifest["analysis_config"] = normalized_analysis_config
    if cc == "prism":
        manifest["config"].update(
            {
                "prism_smooth_beta": 1,
                "prism_hysteresis": 0,
                "prism_engage_spread": 0,
                "prism_engage_mult": 0,
            }
        )
    if background_value is not None:
        manifest["config"].update(
            {
                "network_queue_type": "ecn",
                "host_queue_type": "fair_prio",
            }
        )
        manifest["background_config_sha256"] = background_config_sha256
        manifest["background_safety_contract"] = {
            "enforced_by": "main_uec",
            "source_distinct_from_all_foreground_endpoints": True,
            "source_unique_across_background_streams": True,
            "rate_lte_host_queue_bitrate": True,
            "stop_plus_route_drain_bound_lt_simulation_end": True,
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
        os.link(temp_name, manifest_path, follow_symlinks=False)
        os.unlink(temp_name)
        temp_name = None
    finally:
        if temp_name is not None and os.path.exists(temp_name):
            os.unlink(temp_name)

    return manifest_path


def main(argv=None):
    if argv is None:
        import sys
        argv = sys.argv[1:]
    if argv[:1] == ["--validate-identifier"]:
        validator = argparse.ArgumentParser(description="Validate a conservative identifier")
        validator.add_argument("--validate-identifier", required=True)
        args = validator.parse_args(argv)
        try:
            print(validate_identifier(args.validate_identifier, "scenario_id"))
        except (TypeError, ValueError) as error:
            validator.error(str(error))
        return

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
    parser.add_argument("--motivation-residual-recycle", action="store_true")
    parser.add_argument("--motivation-residual-threshold-us", type=float, default=10.0)
    parser.add_argument(
        "--prism-coordination-mode",
        choices=("disabled", "original_prism", "prism_recycle", "full_prism"),
        default="disabled",
    )
    parser.add_argument("--m2-cell-id")
    parser.add_argument("--m2-scenario")
    parser.add_argument("--m2-foreground-flows", type=int)
    parser.add_argument("--m2-degraded-links", type=int)
    parser.add_argument("--m2-degraded-capacity-gbps", type=float)
    args = parser.parse_args(argv)
    m2_values = (
        args.m2_cell_id,
        args.m2_scenario,
        args.m2_foreground_flows,
        args.m2_degraded_links,
        args.m2_degraded_capacity_gbps,
    )
    if any(value is not None for value in m2_values) and not all(
        value is not None for value in m2_values
    ):
        parser.error("M2 analysis arguments must be provided together")
    analysis_config = None
    if all(value is not None for value in m2_values):
        analysis_config = {
            "cell_id": args.m2_cell_id,
            "scenario": args.m2_scenario,
            "foreground_flows": args.m2_foreground_flows,
            "degraded_links": args.m2_degraded_links,
            "degraded_capacity_gbps": args.m2_degraded_capacity_gbps,
            "seed": args.seed,
        }
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
        analysis_config=analysis_config,
        motivation_residual_recycle=args.motivation_residual_recycle,
        motivation_residual_threshold_us=args.motivation_residual_threshold_us,
        prism_coordination_mode=args.prism_coordination_mode,
    )
    print(manifest)


if __name__ == "__main__":
    main()
