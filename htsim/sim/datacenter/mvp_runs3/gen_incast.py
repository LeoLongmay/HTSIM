#!/usr/bin/env python3
"""Generate an incast .cm: N senders (all OUTSIDE the dest's pod) -> one dest host.
Senders outside the dest pod guarantees traffic crosses the core into the dest pod,
so it traverses the (possibly -failed) core->agg ingress links.
Usage: python3 gen_incast.py <out.cm> [n_senders] [dest] [size_bytes] [nodes] [hosts_per_pod]
"""
import sys

def build(n=32, dest=0, size=20_000_000, nodes=128, hpp=16):
    dest_pod = dest // hpp
    if dest >= nodes:
        raise ValueError(f"dest {dest} >= nodes {nodes}")
    senders = [h for h in range(nodes) if h // hpp != dest_pod][:n]
    if len(senders) != n:
        raise ValueError(f"need {n} senders outside pod{dest_pod}, only {len(senders)} available")
    lines = [f"Nodes {nodes}", f"Connections {n}"]
    lines += [f"{s}->{dest} start 0 size {size}" for s in senders]
    return "\n".join(lines) + "\n", senders

def main():
    out = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 32
    dest = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    size = int(sys.argv[4]) if len(sys.argv) > 4 else 20_000_000
    nodes = int(sys.argv[5]) if len(sys.argv) > 5 else 128
    hpp = int(sys.argv[6]) if len(sys.argv) > 6 else 16
    text, senders = build(n, dest, size, nodes, hpp)
    with open(out, "w") as fh:
        fh.write(text)
    print(f"wrote {out}: {n} senders {senders[0]}..{senders[-1]} -> host{dest} (pod{dest//hpp}), size {size}")

if __name__ == "__main__":
    main()
