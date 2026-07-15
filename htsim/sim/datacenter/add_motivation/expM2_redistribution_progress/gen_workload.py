#!/usr/bin/env python3
"""Generate the deterministic foreground and fixed-path background for M2."""

from __future__ import annotations

import argparse
import csv
import dataclasses
import io
import random
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Sequence


NODE_COUNT = 128
HOSTS_PER_POD = 16
TARGET_POD = 0
LINK_RATE_GBPS = 100
MAX_HOT_PATH_GROUPS = 6
FOREGROUND_SIZE_BYTES = 256_000_000
FOREGROUND_START_PS = 1
BACKGROUND_START_EPOCH = 20
BACKGROUND_STOP_EPOCH = 120
BACKGROUND_CONFIG_SUFFIX = ".background-config.csv"
BACKGROUND_FIELDS = (
    "background_id",
    "src",
    "dst",
    "path_index",
    "rate_gbps",
    "start_ps",
    "stop_ps",
)


@dataclasses.dataclass(frozen=True, order=True)
class ForegroundFlow:
    src: int
    dst: int
    flow_id: int
    size_bytes: int = FOREGROUND_SIZE_BYTES
    start_ps: int = FOREGROUND_START_PS


@dataclasses.dataclass(frozen=True, order=True)
class BackgroundFlow:
    background_id: int
    src: int
    dst: int
    path_index: int
    rate_gbps: Decimal
    start_ps: int
    stop_ps: int


@dataclasses.dataclass(frozen=True)
class Workload:
    foreground_text: str
    background_config_text: str
    foreground: tuple[ForegroundFlow, ...]
    background: tuple[BackgroundFlow, ...]


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


def _utilization(value: object) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("background_utilization must be in (0, 1]") from exc
    if not parsed.is_finite() or parsed <= 0 or parsed > 1:
        raise ValueError("background_utilization must be in (0, 1]")
    return parsed


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _target_pod_endpoint_pairs(
    foreground_count: int, background_count: int, rng: random.Random
) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Allocate unique sources outside one fixed destination pod."""
    target_hosts = list(range(
        TARGET_POD * HOSTS_PER_POD,
        (TARGET_POD + 1) * HOSTS_PER_POD,
    ))
    source_hosts = sorted(set(range(NODE_COUNT)) - set(target_hosts))

    foreground_sources = rng.sample(source_hosts, foreground_count)
    remaining_sources = sorted(set(source_hosts) - set(foreground_sources))
    background_sources = rng.sample(remaining_sources, background_count)

    foreground_dst_order = target_hosts[:]
    rng.shuffle(foreground_dst_order)
    foreground_pairs = sorted(
        (src, foreground_dst_order[index % HOSTS_PER_POD])
        for index, src in enumerate(foreground_sources)
    )
    background_dsts = rng.sample(target_hosts, background_count)
    background_pairs = sorted(zip(background_sources, background_dsts))
    return sorted(foreground_pairs), background_pairs


def _foreground_text(flows: Sequence[ForegroundFlow]) -> str:
    lines = [f"Nodes {NODE_COUNT}", f"Connections {len(flows)}"]
    lines.extend(
        f"{flow.src}->{flow.dst} id {flow.flow_id} start {flow.start_ps} "
        f"size {flow.size_bytes}"
        for flow in flows
    )
    return "\n".join(lines) + "\n"


def _background_text(flows: Sequence[BackgroundFlow]) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(BACKGROUND_FIELDS)
    for flow in flows:
        writer.writerow((
            flow.background_id,
            flow.src,
            flow.dst,
            flow.path_index,
            _decimal_text(flow.rate_gbps),
            flow.start_ps,
            flow.stop_ps,
        ))
    return output.getvalue()


def generate_workload(
    *,
    foreground_flows: int,
    hot_path_groups: int,
    background_utilization: object,
    seed: int,
    base_rtt_ps: int,
) -> Workload:
    """Build byte-stable M2 workload text without changing process RNG state."""
    foreground_count = _positive_int(foreground_flows, "foreground_flows")
    background_count = _positive_int(hot_path_groups, "hot_path_groups")
    if background_count > MAX_HOT_PATH_GROUPS:
        raise ValueError(
            f"hot_path_groups must be at most {MAX_HOT_PATH_GROUPS}"
        )
    base_rtt = _positive_int(base_rtt_ps, "base_rtt_ps")
    utilization = _utilization(background_utilization)
    source_capacity = NODE_COUNT - HOSTS_PER_POD
    if foreground_count + background_count > source_capacity:
        raise ValueError("not enough nodes for unique sources outside the target pod")

    background_start_ps = BACKGROUND_START_EPOCH * base_rtt
    background_stop_ps = BACKGROUND_STOP_EPOCH * base_rtt
    serialization_ps = (
        FOREGROUND_SIZE_BYTES * 8 * 1_000 // LINK_RATE_GBPS
    )
    if FOREGROUND_START_PS + serialization_ps <= background_stop_ps:
        raise ValueError("256 MB foreground does not last beyond 120E at 100 Gbps")

    rng = random.Random(seed)
    foreground_pairs, background_pairs = _target_pod_endpoint_pairs(
        foreground_count, background_count, rng
    )
    foreground = tuple(
        ForegroundFlow(src=src, dst=dst, flow_id=index)
        for index, (src, dst) in enumerate(foreground_pairs, start=1)
    )

    group_rate = utilization * Decimal(LINK_RATE_GBPS)
    background = tuple(
        BackgroundFlow(
            background_id=index,
            src=src,
            dst=dst,
            path_index=index,
            rate_gbps=group_rate,
            start_ps=background_start_ps,
            stop_ps=background_stop_ps,
        )
        for index, (src, dst) in enumerate(background_pairs)
    )
    return Workload(
        foreground_text=_foreground_text(foreground),
        background_config_text=_background_text(background),
        foreground=foreground,
        background=background,
    )


def write_workload(
    foreground_path: Path,
    background_config_path: Path,
    *,
    foreground_flows: int,
    hot_path_groups: int,
    background_utilization: object,
    seed: int,
    base_rtt_ps: int,
) -> Workload:
    """Generate and write one foreground .cm/background-config pair."""
    foreground_path = Path(foreground_path)
    background_config_path = Path(background_config_path)
    if foreground_path.suffix != ".cm":
        raise ValueError("foreground output must use the .cm suffix")
    if not background_config_path.name.endswith(BACKGROUND_CONFIG_SUFFIX):
        raise ValueError(
            f"background config output must end with {BACKGROUND_CONFIG_SUFFIX}"
        )
    workload = generate_workload(
        foreground_flows=foreground_flows,
        hot_path_groups=hot_path_groups,
        background_utilization=background_utilization,
        seed=seed,
        base_rtt_ps=base_rtt_ps,
    )
    foreground_path.parent.mkdir(parents=True, exist_ok=True)
    background_config_path.parent.mkdir(parents=True, exist_ok=True)
    foreground_path.write_text(workload.foreground_text, encoding="ascii", newline="")
    background_config_path.write_text(
        workload.background_config_text, encoding="ascii", newline=""
    )
    return workload


def _arg_positive_int(text: str) -> int:
    try:
        return _positive_int(text, "value")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--foreground", required=True, type=Path)
    parser.add_argument("--background-config", required=True, type=Path)
    parser.add_argument("--foreground-flows", required=True, type=_arg_positive_int)
    parser.add_argument("--hot-path-groups", required=True, type=_arg_positive_int)
    parser.add_argument("--background-utilization", required=True)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--base-rtt-ps", required=True, type=_arg_positive_int)
    args = parser.parse_args(argv)
    try:
        write_workload(
            args.foreground,
            args.background_config,
            foreground_flows=args.foreground_flows,
            hot_path_groups=args.hot_path_groups,
            background_utilization=args.background_utilization,
            seed=args.seed,
            base_rtt_ps=args.base_rtt_ps,
        )
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
