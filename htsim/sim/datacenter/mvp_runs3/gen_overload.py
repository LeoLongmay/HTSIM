#!/usr/bin/env python3
"""Generate a whole-pod overload .cm: n_senders (all OUTSIDE dest_pod) -> n_dests hosts
INSIDE dest_pod, round-robin. Senders outside the pod force traffic across the core into
dest_pod, traversing the (possibly -failed) core->agg ingress. Spreading over several dest
hosts keeps the asymmetric ingress (not a single last-hop host) the differentiating
bottleneck. Usage:
  python3 gen_overload.py <out.cm> [n_senders] [dest_pod] [n_dests] [size] [nodes] [hpp]
"""
import sys

def build(n_senders=32, dest_pod=0, n_dests=8, size=20_000_000, nodes=128, hpp=16):
    if n_dests < 1:
        raise ValueError(f"n_dests must be >= 1, got {n_dests}")
    if n_dests > hpp:
        raise ValueError(f"n_dests {n_dests} > hosts_per_pod {hpp}")
    dests = [dest_pod * hpp + j for j in range(n_dests)]
    senders = [h for h in range(nodes) if h // hpp != dest_pod][:n_senders]
    if len(senders) != n_senders:
        raise ValueError(f"need {n_senders} senders outside pod{dest_pod}, "
                         f"only {len(senders)} available")
    conns = [(s, dests[i % n_dests]) for i, s in enumerate(senders)]
    lines = [f"Nodes {nodes}", f"Connections {len(conns)}"]
    lines += [f"{s}->{d} start 0 size {size}" for s, d in conns]
    return "\n".join(lines) + "\n", conns

def main():
    out = sys.argv[1]
    n_senders = int(sys.argv[2]) if len(sys.argv) > 2 else 32
    dest_pod  = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    n_dests   = int(sys.argv[4]) if len(sys.argv) > 4 else 8
    size      = int(sys.argv[5]) if len(sys.argv) > 5 else 20_000_000
    nodes     = int(sys.argv[6]) if len(sys.argv) > 6 else 128
    hpp       = int(sys.argv[7]) if len(sys.argv) > 7 else 16
    text, conns = build(n_senders, dest_pod, n_dests, size, nodes, hpp)
    with open(out, "w") as fh:
        fh.write(text)
    print(f"wrote {out}: {len(conns)} flows, {n_senders} senders -> {n_dests} hosts "
          f"in pod{dest_pod}, size {size}")

if __name__ == "__main__":
    main()
