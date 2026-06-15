#!/usr/bin/env python3
"""Incast .cm: N senders (all OUTSIDE the dest's pod) -> one dest host. Optional
per-flow start stagger (picoseconds) so senders ramp in slightly offset. Senders
outside the dest pod force traffic across the core into the (possibly -failed) ingress.
Usage: incast.py <out.cm> [n] [dest] [size] [nodes] [hpp] [stagger_ps]
"""
import sys

# Flows must not start at t=0: the simulator drops the START FLOW_EVENT for a
# t=0 flow, which breaks FCT accounting. Offset every flow by 1 ns (negligible).
START_PS = 1000

def build(n=32, dest=0, size=2_000_000, nodes=128, hpp=16, stagger_ps=0):
    dest_pod = dest // hpp
    if dest >= nodes:
        raise ValueError(f"dest {dest} >= nodes {nodes}")
    if stagger_ps < 0:
        raise ValueError(f"stagger_ps must be >= 0 (negative could yield t<=0 start), got {stagger_ps}")
    senders = [h for h in range(nodes) if h // hpp != dest_pod][:n]
    if len(senders) != n:
        raise ValueError(f"need {n} senders outside pod{dest_pod}, have {len(senders)}")
    conns = [(s, dest) for s in senders]
    lines = [f"Nodes {nodes}", f"Connections {n}"]
    lines += [f"{s}->{dest} start {START_PS + i * stagger_ps} size {size}"
              for i, s in enumerate(senders)]
    return "\n".join(lines) + "\n", conns

def main():
    out = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 32
    dest = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    size = int(sys.argv[4]) if len(sys.argv) > 4 else 2_000_000
    nodes = int(sys.argv[5]) if len(sys.argv) > 5 else 128
    hpp = int(sys.argv[6]) if len(sys.argv) > 6 else 16
    stagger_ps = int(sys.argv[7]) if len(sys.argv) > 7 else 0
    text, conns = build(n, dest, size, nodes, hpp, stagger_ps)
    with open(out, "w") as fh:
        fh.write(text)
    print(f"wrote {out}: {n} senders -> host{dest}, stagger={stagger_ps}ps")

if __name__ == "__main__":
    main()
