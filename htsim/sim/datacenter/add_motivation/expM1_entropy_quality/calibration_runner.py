#!/usr/bin/env python3
"""Run real M1 calibration with one bounded-memory child process per trace."""

from __future__ import annotations

import csv
import argparse
import fcntl
import subprocess
import sys
from pathlib import Path

try:
    from htsim.sim.datacenter.add_motivation.expM1_entropy_quality import analyze
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[5]))
    from htsim.sim.datacenter.add_motivation.expM1_entropy_quality import analyze


HERE = Path(__file__).resolve().parent
CALIBRATION_DIR = HERE / "data" / "calibration"
SUMMARY = CALIBRATION_DIR / "summary.csv"
CHECKPOINT = CALIBRATION_DIR / ".summary_checkpoint.csv"
LOCK = CALIBRATION_DIR / ".calibration_runner.lock"


def _read_rows(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(newline="", encoding="ascii") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None:
            raise ValueError(f"missing CSV header: {path}")
        return list(reader.fieldnames), list(reader)


def _expected_run_ids() -> list[str]:
    run_ids = []
    for manifest_path in sorted(CALIBRATION_DIR.glob("*.manifest.json")):
        manifest = analyze._read_manifest(manifest_path)
        metadata = analyze._manifest_metadata(manifest_path, "calibration", manifest)
        run_ids.append(metadata["run_id"])
    if not run_ids:
        raise ValueError(f"no calibration manifests found in {CALIBRATION_DIR}")
    if len(set(run_ids)) != len(run_ids):
        raise ValueError("duplicate calibration run IDs")
    return run_ids


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-runs", type=int,
        help="process at most this many missing traces, then leave the checkpoint for resume",
    )
    args = parser.parse_args(argv)
    if args.max_runs is not None and args.max_runs <= 0:
        parser.error("--max-runs must be positive")
    lock_stream = LOCK.open("w", encoding="ascii")
    try:
        fcntl.flock(lock_stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        lock_stream.close()
        raise ValueError("another M1 calibration runner is already active") from exc
    expected = _expected_run_ids()
    expected_set = set(expected)
    header: list[str] = []
    rows_by_id: dict[str, dict] = {}
    if CHECKPOINT.exists():
        header, checkpoint_rows = _read_rows(CHECKPOINT)
        for row in checkpoint_rows:
            run_id = row.get("run_id", "")
            if run_id not in expected_set or run_id in rows_by_id:
                raise ValueError(f"invalid calibration checkpoint row: {run_id!r}")
            rows_by_id[run_id] = row

    print(f"M1 calibration: {len(rows_by_id)}/{len(expected)} summaries already complete", flush=True)
    manifests = {
        analyze._manifest_metadata(path, "calibration", analyze._read_manifest(path))["run_id"]: path
        for path in CALIBRATION_DIR.glob("*.manifest.json")
    }
    processed = 0
    for index, run_id in enumerate(expected, start=1):
        if run_id in rows_by_id:
            continue
        if args.max_runs is not None and processed >= args.max_runs:
            print("M1 calibration: checkpoint saved; resume to continue", flush=True)
            return 0
        subprocess.run(
            [
                sys.executable, str(HERE / "analyze.py"), "--calibration",
                "--manifest", str(manifests[run_id]),
            ],
            check=True,
        )
        child_header, child_rows = _read_rows(SUMMARY)
        if len(child_rows) != 1 or child_rows[0].get("run_id") != run_id:
            raise ValueError(f"single-run analysis did not produce expected summary: {run_id}")
        if header and child_header != header:
            raise ValueError("calibration summary schema changed during run")
        header = child_header
        rows_by_id[run_id] = child_rows[0]
        processed += 1
        analyze._atomic_csv(
            CHECKPOINT, header, [rows_by_id[item] for item in expected if item in rows_by_id]
        )
        print(f"M1 calibration: {index}/{len(expected)} {run_id}", flush=True)

    rows = [rows_by_id[run_id] for run_id in expected]
    analyze._atomic_csv(SUMMARY, header, rows)
    CHECKPOINT.unlink(missing_ok=True)
    selection = analyze.select_formal(rows, analyze.FORMAL_CONFIG, CALIBRATION_DIR / "calibration_selection.csv")
    if not selection.selected:
        print("calibration selection failed: no qualifying cell", file=sys.stderr)
        return 1
    print(f"selected {selection.scenario_id} with control {selection.control_scenario_id}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
