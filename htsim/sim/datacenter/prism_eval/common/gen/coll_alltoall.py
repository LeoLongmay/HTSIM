#!/usr/bin/env python3
"""All-to-All .cm, ported from htsim's datacenter/connection_matrices/gen_serialn_alltoall.py for
prism_eval. Single group of `groupsize` ranks under a per-seed random placement; every rank sends to
all others in waves of `parallel` active connections, waves chained by send_done_trigger->trigger
(multishot) and sequenced (r->(r+1)%n, then (r+2)%n, ...) to avoid incast. First-wave flows start at
START_PS=1000 ps, not 0 (the simulator drops a t=0 flow's START event). `start` is in picoseconds.
Usage: coll_alltoall.py <out.cm> [nodes=128] [groupsize=128] [parallel=32] [flowsize=131072] [seed=0]
"""
import sys, random

START_PS = 1000

def build(nodes=128, groupsize=128, parallel=32, flowsize=131072, seed=0):
    if groupsize > nodes:
        raise ValueError(f"groupsize {groupsize} > nodes {nodes}")
    conns = groupsize                       # single group spanning all ranks
    rng = random.Random(seed)
    srcs = list(range(nodes))
    rng.shuffle(srcs)
    groupsrcs = srcs[:groupsize]
    n_conns = conns * (groupsize - 1)
    half = (groupsize - 1) // parallel
    left = (groupsize - 1) % parallel
    flow_lines = []
    fid = 0
    trig_id = 0
    for s in range(groupsize):
        for d in range(1, half + 1):
            st_trigger = trig_id
            if d != half or left > 0:
                trig_id += 1
            for crt in range(parallel):
                fid += 1
                dst = (s + d + crt * half) % groupsize
                out = f"{groupsrcs[s]}->{groupsrcs[dst]} id {fid}"
                out += (f" start {START_PS}" if d == 1 else f" trigger {st_trigger}")
                out += f" size {flowsize}"
                if d != half or left > 0:
                    out += f" send_done_trigger {trig_id}"
                flow_lines.append(out)
        if left > 0:
            st_trigger = trig_id
            for crt in range(left):
                fid += 1
                dst = (s + parallel * half + crt + 1) % groupsize
                out = f"{groupsrcs[s]}->{groupsrcs[dst]} id {fid}"
                out += f" trigger {st_trigger}"
                out += f" size {flowsize}"
                flow_lines.append(out)
    n_trig = trig_id
    trig_lines = [f"trigger id {t} multishot" for t in range(1, trig_id + 1)]
    header = [f"Nodes {nodes}", f"Connections {n_conns}", f"Triggers {n_trig}"]
    return "\n".join(header + flow_lines + trig_lines) + "\n", n_conns, n_trig

def main():
    out = sys.argv[1]
    nodes     = int(sys.argv[2]) if len(sys.argv) > 2 else 128
    groupsize = int(sys.argv[3]) if len(sys.argv) > 3 else 128
    parallel  = int(sys.argv[4]) if len(sys.argv) > 4 else 32
    flowsize  = int(sys.argv[5]) if len(sys.argv) > 5 else 131072
    seed      = int(sys.argv[6]) if len(sys.argv) > 6 else 0
    text, nc, nt = build(nodes, groupsize, parallel, flowsize, seed)
    with open(out, "w") as fh:
        fh.write(text)
    print(f"wrote {out}: all-to-all {nodes} nodes, groupsize {groupsize}, parallel {parallel}, "
          f"{nc} conns, {nt} triggers, seed {seed}")

if __name__ == "__main__":
    main()
