#!/usr/bin/env python3
"""AI-training collective .cm: one inter-server ring step of Llama-70B HSDP (FSDP2 2D), as in
MSwift (Gerstein et al. 2026, Fig. 7). N GPUs = servers x gpus_per_server; each GPU i sends to
GPU (i+stride) mod nodes. Faithful config (nodes=128, servers=16, gpus_per_server=8, stride=8):
a single 16-server ring traversed by 8 parallel GPU lanes; every flow is inter-server (intra-server
traffic lives off the fabric, and a single i->i+8 step has no intra-server flow). Random server
placement per seed: a random permutation sigma of the server slots maps logical GPU i to physical
host sigma[i//gpus_per_server]*gpus_per_server + i%gpus_per_server. Connection-matrix `start` is in
picoseconds; flows start together at START_PS=1000 (not 0 -- the simulator drops the START event for
a t=0 flow). No triggers (single ring step).
Usage: ai_ring.py <out.cm> [nodes=128] [servers=16] [gpus_per_server=8] [stride=8] [size=13697024] [seed=0]
"""
import sys, random

START_PS = 1000  # 1 ns floor; a t=0 flow has its START FLOW_EVENT dropped by the simulator.

def build(nodes=128, servers=16, gpus_per_server=8, stride=8, size=13697024, seed=0):
    if servers * gpus_per_server != nodes:
        raise ValueError(f"servers*gpus_per_server must equal nodes: "
                         f"{servers}*{gpus_per_server} != {nodes}")
    if not (0 < stride < nodes):
        raise ValueError(f"stride must be in (0,nodes): {stride}")
    rng = random.Random(seed)
    sigma = list(range(servers))
    rng.shuffle(sigma)                       # random server placement
    def phys(logical):
        srv, local = divmod(logical, gpus_per_server)
        return sigma[srv] * gpus_per_server + local
    conns = [(phys(i), phys((i + stride) % nodes)) for i in range(nodes)]
    lines = [f"Nodes {nodes}", f"Connections {len(conns)}"]
    lines += [f"{s}->{d} start {START_PS} size {size}" for s, d in conns]
    return "\n".join(lines) + "\n", conns

def main():
    out = sys.argv[1]
    nodes   = int(sys.argv[2]) if len(sys.argv) > 2 else 128
    servers = int(sys.argv[3]) if len(sys.argv) > 3 else 16
    gpus    = int(sys.argv[4]) if len(sys.argv) > 4 else 8
    stride  = int(sys.argv[5]) if len(sys.argv) > 5 else 8
    size    = int(sys.argv[6]) if len(sys.argv) > 6 else 13697024
    seed    = int(sys.argv[7]) if len(sys.argv) > 7 else 0
    text, _ = build(nodes, servers, gpus, stride, size, seed)
    with open(out, "w") as fh:
        fh.write(text)
    print(f"wrote {out}: {nodes} nodes, stride {stride}, {size} B/flow, seed {seed}")

if __name__ == "__main__":
    main()
