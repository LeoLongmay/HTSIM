#!/usr/bin/env python3
"""Generate deterministic M4 foreground traffic into pod 0."""

from __future__ import annotations

import argparse
import dataclasses
import random
from pathlib import Path
from typing import Sequence


NODE_COUNT = 128
HOSTS_PER_POD = 16
TARGET_POD = 0
FOREGROUND_SIZE_BYTES = 32_000_000
FOREGROUND_START_PS = 1


@dataclasses.dataclass(frozen=True, order=True)
class ForegroundFlow:
    src: int
    dst: int
    flow_id: int
    size_bytes: int = FOREGROUND_SIZE_BYTES
    start_ps: int = FOREGROUND_START_PS


def generate_workload(*, foreground_flows: int, seed: int) -> tuple[ForegroundFlow, ...]:
    if type(foreground_flows) is not int or not 0 < foreground_flows <= NODE_COUNT - HOSTS_PER_POD:
        raise ValueError("foreground_flows must fit unique sources outside target pod 0")
    if type(seed) is not int or not 0 <= seed <= 2**31 - 1:
        raise ValueError("seed must be an integer in [0, 2147483647]")
    target_hosts = list(range(TARGET_POD * HOSTS_PER_POD, (TARGET_POD + 1) * HOSTS_PER_POD))
    source_hosts = list(range(HOSTS_PER_POD, NODE_COUNT))
    rng = random.Random(seed)
    sources = rng.sample(source_hosts, foreground_flows)
    rng.shuffle(target_hosts)
    return tuple(
        ForegroundFlow(src=src, dst=target_hosts[index % HOSTS_PER_POD], flow_id=index + 1)
        for index, src in enumerate(sorted(sources))
    )


def workload_text(*, foreground_flows: int, seed: int) -> str:
    flows = generate_workload(foreground_flows=foreground_flows, seed=seed)
    lines = [f"Nodes {NODE_COUNT}", f"Connections {len(flows)}"]
    lines.extend(
        f"{flow.src}->{flow.dst} id {flow.flow_id} start {flow.start_ps} size {flow.size_bytes}"
        for flow in flows
    )
    return "\n".join(lines) + "\n"


def write_workload(path: Path, *, foreground_flows: int, seed: int) -> None:
    path = Path(path)
    if path.suffix != ".cm":
        raise ValueError("workload must use the .cm suffix")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(workload_text(foreground_flows=foreground_flows, seed=seed), encoding="ascii", newline="")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--foreground-flows", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args(argv)
    write_workload(args.output, foreground_flows=args.foreground_flows, seed=args.seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
