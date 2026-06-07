#!/usr/bin/env python3
"""Generate a 128-host cross-pod permutation .cm for htsim.
host i -> host (i+64) % 128 (a bijection; never i->i; always crosses pods).
Usage: python3 gen_perm.py <out.cm> [size_bytes] [nodes]
"""
import sys

def main():
    out = sys.argv[1]
    size = int(sys.argv[2]) if len(sys.argv) > 2 else 30_000_000  # 30 MB
    nodes = int(sys.argv[3]) if len(sys.argv) > 3 else 128
    half = nodes // 2
    lines = [f"Nodes {nodes}", f"Connections {nodes}"]
    dests = set()
    for i in range(nodes):
        d = (i + half) % nodes
        assert d != i, f"self-loop at {i}"
        dests.add(d)
        lines.append(f"{i}->{d} start 0 size {size}")
    assert len(dests) == nodes, "not a bijection"
    with open(out, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {out}: {nodes} flows, size={size} bytes each")

if __name__ == "__main__":
    main()
