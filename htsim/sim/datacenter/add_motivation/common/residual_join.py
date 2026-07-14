"""Exact same-epoch residual attachment for motivation ACK observations."""

from __future__ import annotations

import dataclasses
from collections import defaultdict
from pathlib import Path

from .trace_schema import TraceBundle, TraceValidationError


@dataclasses.dataclass(frozen=True)
class ResidualAck:
    row: dict
    floor_ps: int
    spread_ps: int
    residual_ps: int
    high_residual: bool


def _source_path(row: dict, fallback: str) -> Path:
    return getattr(row, "source_path", Path(fallback))


def _raise(row: dict, fallback: str, key: str, detail: str) -> None:
    raise TraceValidationError(f"{_source_path(row, fallback)}: {key}: {detail}")


def attach_same_epoch_residuals(
    bundle: TraceBundle,
    threshold_ps: int = 14_000_000,
) -> tuple[ResidualAck, ...]:
    """Validate raw epoch extrema and attach each genuine ACK to that epoch's floor."""

    if threshold_ps < 0:
        raise ValueError("threshold_ps must be nonnegative")

    epochs = {}
    for epoch in bundle.epoch:
        identity = (epoch["flow_id"], epoch["epoch_id"])
        if identity in epochs:
            _raise(
                epoch,
                "epoch.csv",
                "epoch_id",
                f"duplicate epoch identity {identity}",
            )
        epochs[identity] = epoch

    genuine_by_epoch = defaultdict(list)
    for ack in bundle.ack:
        identity = (ack["flow_id"], ack["epoch_id"])
        if identity not in epochs:
            _raise(
                ack,
                "ack.csv",
                "epoch_id",
                f"no epoch for flow_id={identity[0]}, epoch_id={identity[1]}",
            )
        if ack["genuine_sample"]:
            genuine_by_epoch[identity].append(ack)

    extrema = {}
    for identity, epoch in epochs.items():
        genuine = genuine_by_epoch.get(identity, ())
        if epoch["sample_count"] != len(genuine):
            _raise(
                epoch,
                "epoch.csv",
                "sample_count",
                f"recorded {epoch['sample_count']}, recomputed {len(genuine)}",
            )

        if genuine:
            delays = [ack["qdelay_ps"] for ack in genuine]
            floor_ps = min(delays)
            spread_ps = max(delays) - floor_ps
        else:
            floor_ps = 0
            spread_ps = 0

        if epoch["raw_floor_ps"] != floor_ps:
            _raise(
                epoch,
                "epoch.csv",
                "raw_floor_ps",
                f"recorded {epoch['raw_floor_ps']}, recomputed {floor_ps}",
            )
        if epoch["raw_spread_ps"] != spread_ps:
            _raise(
                epoch,
                "epoch.csv",
                "raw_spread_ps",
                f"recorded {epoch['raw_spread_ps']}, recomputed {spread_ps}",
            )
        extrema[identity] = (floor_ps, spread_ps)

    attached = []
    for ack in bundle.ack:
        if not ack["genuine_sample"]:
            continue
        identity = (ack["flow_id"], ack["epoch_id"])
        floor_ps, spread_ps = extrema[identity]
        residual_ps = max(ack["qdelay_ps"] - floor_ps, 0)
        attached.append(
            ResidualAck(
                row=ack,
                floor_ps=floor_ps,
                spread_ps=spread_ps,
                residual_ps=residual_ps,
                high_residual=residual_ps >= threshold_ps,
            )
        )
    return tuple(attached)
