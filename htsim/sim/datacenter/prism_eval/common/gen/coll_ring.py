#!/usr/bin/env python3
"""Ring-AllReduce .cm (reduce-scatter + all-gather), ported from htsim's
datacenter/connection_matrices/gen_allreduce.py for prism_eval. Single group spanning `groupsize`
ranks under a per-seed random placement; groupsize concurrent serial chains of 2*groupsize-1 hops,
each chained by send_done_trigger->trigger (oneshot). The first flow of each chain starts at
START_PS=1000 ps, not 0 (the simulator drops a t=0 flow's START event). `start` is in picoseconds.
Usage: coll_ring.py <out.cm> [nodes=128] [groupsize=128] [flowsize=131072] [seed=0]
"""
import sys, random

START_PS = 1000

def build(nodes=128, groupsize=128, flowsize=131072, seed=0):
    if groupsize > nodes:
        raise ValueError(f"groupsize {groupsize} > nodes {nodes}")
    rng = random.Random(seed)
    srcs = list(range(nodes))
    rng.shuffle(srcs)
    groupsrcs = srcs[:groupsize]
    n_conns = groupsize * (2 * groupsize - 1)
    n_trig = groupsize * (2 * groupsize - 2)
    flow_lines = []
    fid = 0
    trig_id = 1
    for s in range(groupsize):
        for d in range(1, 2 * groupsize):
            fid += 1
            src = (s + d - 1) % groupsize
            dst = (s + d) % groupsize
            out = f"{groupsrcs[src]}->{groupsrcs[dst]} id {fid}"
            if d == 1:
                out += f" start {START_PS}"
            else:
                out += f" trigger {trig_id}"
                trig_id += 1
            out += f" size {flowsize}"
            if d != 2 * groupsize - 1:
                out += f" send_done_trigger {trig_id}"
            flow_lines.append(out)
    trig_lines = [f"trigger id {t} oneshot" for t in range(1, trig_id)]
    header = [f"Nodes {nodes}", f"Connections {n_conns}", f"Triggers {n_trig}"]
    return "\n".join(header + flow_lines + trig_lines) + "\n", n_conns, n_trig

def main():
    out = sys.argv[1]
    nodes     = int(sys.argv[2]) if len(sys.argv) > 2 else 128
    groupsize = int(sys.argv[3]) if len(sys.argv) > 3 else 128
    flowsize  = int(sys.argv[4]) if len(sys.argv) > 4 else 131072
    seed      = int(sys.argv[5]) if len(sys.argv) > 5 else 0
    text, nc, nt = build(nodes, groupsize, flowsize, seed)
    with open(out, "w") as fh:
        fh.write(text)
    print(f"wrote {out}: ring-allreduce {nodes} nodes, groupsize {groupsize}, "
          f"{nc} conns, {nt} triggers, seed {seed}")

if __name__ == "__main__":
    main()
