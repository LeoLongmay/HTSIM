"""Small deterministic statistical helpers for motivation experiments."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Callable, Iterable, TypeVar


Row = TypeVar("Row")
Cluster = TypeVar("Cluster")


def cluster_bootstrap(
    rows: Iterable[Row],
    cluster_key: Callable[[Row], Cluster],
    statistic: Callable[[list[Row]], float],
    *,
    samples: int = 10_000,
    seed: int = 20260714,
) -> tuple[float, float]:
    """Return deterministic percentile bounds from whole-cluster resamples.

    Each replicate draws the same number of clusters as the observed data, with
    replacement. Selecting a cluster copies every row in that cluster.
    """

    if isinstance(samples, bool) or not isinstance(samples, int) or samples <= 0:
        raise ValueError("samples must be a positive integer")

    grouped = defaultdict(list)
    for row in rows:
        grouped[cluster_key(row)].append(row)
    if not grouped:
        raise ValueError("empty clusters: rows must contain at least one cluster")

    clusters = sorted(grouped)
    rng = random.Random(seed)
    estimates = []
    for replicate in range(samples):
        selected = [rng.choice(clusters) for _ in clusters]
        sample = [row for cluster in selected for row in grouped[cluster]]
        try:
            estimate = float(statistic(sample))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(
                f"non-finite statistic in bootstrap replicate {replicate}"
            ) from exc
        if not math.isfinite(estimate):
            raise ValueError(
                f"non-finite statistic in bootstrap replicate {replicate}: {estimate!r}"
            )
        estimates.append(estimate)

    estimates.sort()
    low_index = min(int(0.025 * samples), samples - 1)
    high_index = min(int(0.975 * samples), samples - 1)
    return estimates[low_index], estimates[high_index]
