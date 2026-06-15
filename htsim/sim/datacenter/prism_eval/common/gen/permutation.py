#!/usr/bin/env python3
"""Permutation .cm: a random one-to-one matching of active hosts (each active host
sends to exactly one distinct active host; no self-pairs). Deterministic given seed.
Uses Sattolo's algorithm so the matching is a single cycle (guaranteed derangement).
Connection-matrix `start` is in picoseconds; all flows start together at START_PS
(1 ns, not 0 — the simulator drops the START event for a t=0 flow).
Usage: permutation.py <out.cm> [active_frac] [size] [nodes] [seed]
"""
import sys, random

# Flows must not start at t=0: the simulator drops the START FLOW_EVENT for a
# t=0 flow, which breaks FCT accounting. Offset every flow by 1 ns (negligible).
START_PS = 1000

def _sattolo(items, rng):
    """In-place single-cycle shuffle (no fixed points for len>=2)."""
    a = items[:]
    for i in range(len(a) - 1, 0, -1):
        j = rng.randint(0, i - 1)   # strictly j < i -> no element stays in place
        a[i], a[j] = a[j], a[i]
    return a

def build(active_frac=1.0, size=2_000_000, nodes=128, seed=0):
    if not (0 < active_frac <= 1.0):
        raise ValueError(f"active_frac must be in (0,1], got {active_frac}")
    k = max(2, int(round(active_frac * nodes)))
    if k > nodes:
        k = nodes
    rng = random.Random(seed)
    senders = rng.sample(range(nodes), k)
    receivers = _sattolo(senders, rng)   # derangement of the same active set
    conns = list(zip(senders, receivers))
    lines = [f"Nodes {nodes}", f"Connections {len(conns)}"]
    lines += [f"{s}->{d} start {START_PS} size {size}" for s, d in conns]
    return "\n".join(lines) + "\n", conns

def main():
    out = sys.argv[1]
    active_frac = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
    size = int(sys.argv[3]) if len(sys.argv) > 3 else 2_000_000
    nodes = int(sys.argv[4]) if len(sys.argv) > 4 else 128
    seed = int(sys.argv[5]) if len(sys.argv) > 5 else 0
    text, conns = build(active_frac, size, nodes, seed)
    with open(out, "w") as fh:
        fh.write(text)
    print(f"wrote {out}: {len(conns)} flows, active_frac={active_frac}, nodes={nodes}, seed={seed}")

if __name__ == "__main__":
    main()
