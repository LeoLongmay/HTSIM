#!/usr/bin/env python3
"""Many-to-many .cm: a sender group (hosts OUTSIDE pod0) sends into a receiver group
(the first n_recv hosts of pod0), forcing traffic across the core into the (possibly
-failed) ingress. pattern='pairs': each sender -> one pod0 receiver, round-robin.
pattern='all': cross product (each sender -> every receiver). `start` in picoseconds.
Usage: many2many.py <out.cm> [n_send] [n_recv] [pattern] [size] [nodes] [hpp] [seed]
"""
import sys

# Flows must not start at t=0: the simulator drops the START FLOW_EVENT for a
# t=0 flow, which breaks FCT accounting. Offset every flow by 1 ns (negligible).
START_PS = 1000

def build(n_send=8, n_recv=4, pattern="pairs", size=2_000_000,
          nodes=128, hpp=16, seed=0):
    if n_recv < 1 or n_recv > hpp:
        raise ValueError(f"n_recv must be in [1,{hpp}], got {n_recv}")
    receivers = list(range(n_recv))                       # pod0 hosts 0..n_recv-1
    senders = [h for h in range(nodes) if h // hpp != 0][:n_send]  # outside pod0
    if len(senders) != n_send:
        raise ValueError(f"need {n_send} senders outside pod0, have {len(senders)}")
    if pattern == "pairs":
        conns = [(s, receivers[i % n_recv]) for i, s in enumerate(senders)]
    elif pattern == "all":
        conns = [(s, d) for s in senders for d in receivers]
    else:
        raise ValueError(f"pattern must be 'pairs' or 'all', got {pattern}")
    lines = [f"Nodes {nodes}", f"Connections {len(conns)}"]
    lines += [f"{s}->{d} start {START_PS} size {size}" for s, d in conns]
    return "\n".join(lines) + "\n", conns

def main():
    out = sys.argv[1]
    n_send = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    n_recv = int(sys.argv[3]) if len(sys.argv) > 3 else 4
    pattern = sys.argv[4] if len(sys.argv) > 4 else "pairs"
    size = int(sys.argv[5]) if len(sys.argv) > 5 else 2_000_000
    nodes = int(sys.argv[6]) if len(sys.argv) > 6 else 128
    hpp = int(sys.argv[7]) if len(sys.argv) > 7 else 16
    seed = int(sys.argv[8]) if len(sys.argv) > 8 else 0
    text, conns = build(n_send, n_recv, pattern, size, nodes, hpp, seed)
    with open(out, "w") as fh:
        fh.write(text)
    print(f"wrote {out}: {len(conns)} flows, {n_send}->{n_recv} pattern={pattern}")

if __name__ == "__main__":
    main()
