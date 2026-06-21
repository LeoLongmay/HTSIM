#!/usr/bin/env python3
"""Butterfly / recursive-doubling AllReduce .cm, ported from htsim's
datacenter/connection_matrices/gen_allreduce_butterfly.py for prism_eval. Single group of `groupsize`
(a power of 2) ranks under a per-seed random placement (shuffle ADDED vs the original); log2(groupsize)
steps at distances 1,2,4,..., chained by recv_done_trigger->trigger (oneshot). Step-0 flows start at
START_PS=1000 ps, not 0 (the simulator drops a t=0 flow's START event). `start` is in picoseconds.
Usage: coll_butterfly.py <out.cm> [nodes=128] [groupsize=128] [flowsize=131072] [seed=0]
"""
import sys, random, math

START_PS = 1000

def build(nodes=128, groupsize=128, flowsize=131072, seed=0):
    if groupsize & (groupsize - 1) != 0:
        raise ValueError(f"groupsize must be a power of 2, got {groupsize}")
    if groupsize > nodes:
        raise ValueError(f"groupsize {groupsize} > nodes {nodes}")
    rng = random.Random(seed)
    srcs = list(range(nodes))
    rng.shuffle(srcs)                       # ADDED vs original: per-seed placement
    groupsrcs = srcs[:groupsize]
    nsteps = int(math.log(groupsize, 2))
    n_conns = groupsize * nsteps
    n_trig = n_conns - groupsize
    flow_lines = []
    trigger_ids = []
    fid = 0
    trig_id = 0
    for d in range(0, nsteps):
        step = 2 ** d
        trigger_ids.append([-1] * nodes)
        last_step = (d == nsteps - 1)
        for src in range(0, groupsize):
            if int(src / step) % 2 == 0:
                dst = src + step
                fid += 1
                if not last_step:
                    trig_id += 1
                    trigger_ids[d][dst] = trig_id
                rest = (f" start {START_PS}" if d == 0 else f" trigger {trigger_ids[d-1][src]}")
                rest += f" size {flowsize}"
                if not last_step:
                    rest += f" recv_done_trigger {trig_id}"
                flow_lines.append(f"{groupsrcs[src]}->{groupsrcs[dst]} id {fid}" + rest)
                fid += 1
                if not last_step:
                    trig_id += 1
                    trigger_ids[d][src] = trig_id
                rest = (f" start {START_PS}" if d == 0 else f" trigger {trigger_ids[d-1][dst]}")
                rest += f" size {flowsize}"
                if not last_step:
                    rest += f" recv_done_trigger {trig_id}"
                flow_lines.append(f"{groupsrcs[dst]}->{groupsrcs[src]} id {fid}" + rest)
    trig_lines = [f"trigger id {t} oneshot" for t in range(1, trig_id + 1)]
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
    print(f"wrote {out}: butterfly-allreduce {nodes} nodes, groupsize {groupsize}, "
          f"{nc} conns, {nt} triggers, seed {seed}")

if __name__ == "__main__":
    main()
