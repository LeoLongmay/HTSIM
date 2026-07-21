#!/usr/bin/env python3
"""Generate deterministic foreground-only traffic for controlled M2."""

from __future__ import annotations

import argparse
import dataclasses
import random
from pathlib import Path
from typing import Sequence


NODE_COUNT = 128
HOSTS_PER_POD = 16
TARGET_POD = 0
FOREGROUND_SIZE_BYTES = 256_000_000
FOREGROUND_START_PS = 1


@dataclasses.dataclass(frozen=True, order=True)
class ForegroundFlow:
    src: int
    dst: int
    flow_id: int
    size_bytes: int = FOREGROUND_SIZE_BYTES
    start_ps: int = FOREGROUND_START_PS


@dataclasses.dataclass(frozen=True)
class Workload:
    foreground_text: str
    foreground: tuple[ForegroundFlow, ...]


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if parsed <= 0 or str(value).strip() != str(parsed):
        raise ValueError(f"{name} must be a positive integer")
    return parsed


def _target_pod_endpoint_pairs(
    foreground_count: int, rng: random.Random,
) -> list[tuple[int, int]]:
    """Allocate sources outside one fixed destination pod."""
    target_hosts = list(range(TARGET_POD * HOSTS_PER_POD, (TARGET_POD + 1) * HOSTS_PER_POD))
    source_hosts = sorted(set(range(NODE_COUNT)) - set(target_hosts))
    foreground_sources = rng.sample(source_hosts, foreground_count)
    destinations = target_hosts[:]
    rng.shuffle(destinations)
    return sorted(
        (src, destinations[index % HOSTS_PER_POD])
        for index, src in enumerate(foreground_sources)
    )


def _foreground_text(flows: Sequence[ForegroundFlow]) -> str:
    lines = [f"Nodes {NODE_COUNT}", f"Connections {len(flows)}"]
    lines.extend(
        f"{flow.src}->{flow.dst} id {flow.flow_id} start {flow.start_ps} size {flow.size_bytes}"
        for flow in flows
    )
    return "\n".join(lines) + "\n"


def generate_workload(*, foreground_flows: int, seed: int) -> Workload:
    """Build byte-stable M2 traffic without changing process RNG state."""
    foreground_count = _positive_int(foreground_flows, "foreground_flows")
    if foreground_count > NODE_COUNT - HOSTS_PER_POD:
        raise ValueError("not enough nodes for unique sources outside the target pod")
    pairs = _target_pod_endpoint_pairs(foreground_count, random.Random(seed))
    foreground = tuple(
        ForegroundFlow(src=src, dst=dst, flow_id=index)
        for index, (src, dst) in enumerate(pairs, start=1)
    )
    return Workload(_foreground_text(foreground), foreground)


def write_workload(
    foreground_path: Path, *, foreground_flows: int, seed: int,
) -> Workload:
    """Generate and write one foreground-only connection matrix."""
    foreground_path = Path(foreground_path)
    if foreground_path.suffix != ".cm":
        raise ValueError("foreground output must use the .cm suffix")
    workload = generate_workload(foreground_flows=foreground_flows, seed=seed)
    foreground_path.parent.mkdir(parents=True, exist_ok=True)
    foreground_path.write_text(workload.foreground_text, encoding="ascii", newline="")
    return workload


def _arg_positive_int(text: str) -> int:
    try:
        return _positive_int(text, "value")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--foreground", required=True, type=Path)
    parser.add_argument("--foreground-flows", required=True, type=_arg_positive_int)
    parser.add_argument("--seed", required=True, type=int)
    args = parser.parse_args(argv)
    try:
        write_workload(args.foreground, foreground_flows=args.foreground_flows, seed=args.seed)
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
