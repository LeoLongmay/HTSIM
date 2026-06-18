#!/usr/bin/env python3
"""Open-loop Poisson many-to-many .cm for offered-load sweeps. Senders (hosts OUTSIDE
pod0) send fixed-size flows INTO receivers (first n_recv pod0 hosts), arriving as a
Poisson process over a measurement window [1, window_us]. Each sender keeps its fixed
paired receiver (matches many2many.py 'pairs'), so only the temporal density changes
with load, not the spatial pattern.

Offered load rho is relative to aggregate receiver-access capacity C = n_recv*link_rate.
  lambda = rho * (ref_gbps*1e9) / (size*8)   flows/sec   (ref_gbps in Gbps, size in bytes)
Inter-arrivals ~ Exponential(lambda); start times are PICOSECONDS (the -tm loader interprets
the .cm `start` token as ps -- de-risked 2026-06-18: start 1000 -> 1 ns, 8e9 -> 8 ms, no
overflow). The human-facing `window_us` arg is converted x1e6 to ps. Flows never start at
t=0 (the simulator drops the START FLOW_EVENT), so the first start is clamped to >= 1 ps.

Usage: poisson_load.py <out.cm> <n_send> <n_recv> <size> <nodes> <hpp> <rho> <window_us> <ref_gbps> <seed>
       poisson_load.py --selftest
"""
import sys, random


def build(n_send, n_recv, size, nodes, hpp, rho, window_us, ref_gbps, seed):
    if n_recv < 1 or n_recv > hpp:
        raise ValueError(f"n_recv must be in [1,{hpp}], got {n_recv}")
    if rho <= 0 or ref_gbps <= 0 or size <= 0 or window_us <= 0:
        raise ValueError("rho, ref_gbps, size, window_us must all be > 0")
    senders = [h for h in range(nodes) if h // hpp != 0][:n_send]
    if len(senders) != n_send:
        raise ValueError(f"need {n_send} senders outside pod0, have {len(senders)}")
    receivers = list(range(n_recv))
    rng = random.Random(seed)
    lam_per_ps = rho * (ref_gbps * 1e9) / (size * 8) / 1e12   # flows per picosecond
    window_ps = window_us * 1e6                               # window_us is human-facing; emit ps
    conns = []
    t, i = 0.0, 0
    while True:
        t += rng.expovariate(lam_per_ps)        # inter-arrival, picoseconds
        if t > window_ps:
            break
        s_idx = i % n_send
        conns.append((max(1, int(round(t))), senders[s_idx], receivers[s_idx % n_recv]))
        i += 1
    conns.sort()
    lines = [f"Nodes {nodes}", f"Connections {len(conns)}"]
    lines += [f"{s}->{d} start {st} size {size}" for (st, s, d) in conns]
    return "\n".join(lines) + "\n", conns


def _selftest():
    # lambda = 0.5*1600e9/(2e6*8) = 5e4 flows/s; window 8000us = 8e9 ps -> ~400 flows.
    text, conns = build(64, 16, 2_000_000, 128, 16, 0.5, 8000, 1600, 13)
    n = len(conns)
    assert 320 <= n <= 480, f"flow count {n} outside ~400 +/-20%"
    lines = text.strip().split("\n")
    assert lines[0] == "Nodes 128", lines[0]
    assert lines[1] == f"Connections {n}", lines[1]
    assert len(lines) == n + 2, (len(lines), n)
    starts = [c[0] for c in conns]
    assert starts == sorted(starts), "starts not monotonic"
    assert starts[0] >= 1 and starts[-1] <= 8000 * 1_000_000, (starts[0], starts[-1])  # ps
    for st, s, d in conns:
        assert s // 16 != 0, f"sender {s} is inside pod0"
        assert 0 <= d < 16, f"receiver {d} out of range"
    # determinism
    text2, _ = build(64, 16, 2_000_000, 128, 16, 0.5, 8000, 1600, 13)
    assert text2 == text, "non-deterministic for fixed seed"
    # rho scaling: doubling rho ~doubles flow count
    _, c_low = build(64, 16, 2_000_000, 128, 16, 0.25, 8000, 1600, 13)
    assert len(c_low) < n, (len(c_low), n)
    print(f"ok poisson_load selftest: {n} flows @rho=0.5, window=8000us (=8e9 ps)")


def main():
    if "--selftest" in sys.argv:
        _selftest()
        return
    a = sys.argv
    out = a[1]
    text, conns = build(int(a[2]), int(a[3]), int(a[4]), int(a[5]), int(a[6]),
                        float(a[7]), float(a[8]), float(a[9]), int(a[10]))
    with open(out, "w") as fh:
        fh.write(text)
    print(f"wrote {out}: {len(conns)} flows, rho={a[7]} window={a[8]}us ref={a[9]}Gbps seed={a[10]}")


if __name__ == "__main__":
    main()
