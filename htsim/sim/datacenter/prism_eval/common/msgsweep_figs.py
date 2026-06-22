#!/usr/bin/env python3
"""Message-size-sweep CCT-slowdown figures for prism_eval (separate module: cct_figs.py and
perf_figs.py hold uncommitted WIP and must not be touched; metrics.py is reused unchanged). Line
chart of collective CCT slowdown (makespan / collective-aware zero-queue lower bound) vs per-flow
message size, at a fixed failed-links level. Faithful to STrack's line-chart-vs-message-size form and
MSwift's normalized CCT-inflation y-axis.
  python3 msgsweep_figs.py --selftest   # math self-check
"""
import os, sys, math, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import metrics          # noqa: E402
import plot_style       # noqa: E402

def _sem(v):
    """(mean, standard error of the mean) of a non-empty list; NaNs dropped. SEM = sample_std/sqrt(n)
    (ddof=1; 0.0 for n<2)."""
    clean = [x for x in v if not math.isnan(x)]
    if not clean:
        return (float("nan"), 0.0)
    m = statistics.mean(clean)
    sd = statistics.stdev(clean) if len(clean) > 1 else 0.0
    return (m, sd / math.sqrt(len(clean)))

def _lower_bound_s(k_steps, size_bytes, base_rtt_s, link_gbps):
    """Zero-queue lower bound (s) for a k_steps-deep barriered collective whose every step transfers
    size_bytes on one path: k_steps * (base_rtt + serialization). A true lower bound on the dependent-
    message chain, so makespan/LB >= 1."""
    return k_steps * (base_rtt_s + size_bytes * 8.0 / (link_gbps * 1e9))

def aggregate_slowdown(data_dir, tag_prefix, label, k_steps, sizes, seeds,
                       base_rtt_s=14e-6, link_gbps=100.0, token="sz"):
    """Per-size CCT-slowdown aggregate for one arm: {size:(mean_sd, sem_sd, min_cr)}; omit sizes with
    no data. Reads {tag_prefix}_{label}_{token}{size}_s{seed}.flow.txt; slowdown = collective_makespan
    / lower_bound(k_steps,size). `min_cr` = worst completion-rate across the seeds counted; min_cr < 1
    means the collective did not fully finish in some seed and the mean slowdown is a LOWER BOUND
    (render marks such points hollow)."""
    out = {}
    for sz in sizes:
        sds = []; crs = []
        lb = _lower_bound_s(k_steps, sz, base_rtt_s, link_gbps)
        for s in seeds:
            flow = os.path.join(data_dir, f"{tag_prefix}_{label}_{token}{sz}_s{s}.flow.txt")
            if not os.path.exists(flow):
                continue
            mk, cr = metrics.collective_makespan(flow)
            if mk == mk and lb > 0:             # drop nan (no completion)
                sds.append(mk / lb)
                crs.append(cr)
        if not sds:
            continue
        mean_sd, sem_sd = _sem(sds)
        out[sz] = (mean_sd, sem_sd, min(crs) if crs else float("nan"))
    return out

def _size_label(b):
    """Bytes -> short binary label: 16384 -> '16K', 1048576 -> '1M'."""
    if b >= (1 << 20) and b % (1 << 20) == 0:
        return f"{b >> 20}M"
    if b >= (1 << 10) and b % (1 << 10) == 0:
        return f"{b >> 10}K"
    return str(b)

def selftest():
    import tempfile, shutil
    d = tempfile.mkdtemp()
    sizes = [16384, 1048576]; seeds = [13, 14, 15, 16, 17]; k = 4
    # synthetic: every flow starts at 1us, finishes at 1001us -> makespan 1.0 ms at every size/seed
    for sz in sizes:
        for s in seeds:
            with open(os.path.join(d, f"expG2a2a_prism_sz{sz}_s{s}.flow.txt"), "w") as fh:
                fh.write("0.000001000 Type FLOW_EVENT SrcID 1 Ev START FlowID 1 Flowsize 1000\n")
                fh.write("0.000001000 Type FLOW_EVENT SrcID 2 Ev START FlowID 2 Flowsize 1000\n")
                fh.write("0.001001000 Type FLOW_EVENT SrcID 1 Ev FINISH FlowID 1 Bytes 1000 Pkts 1\n")
                fh.write("0.001001000 Type FLOW_EVENT SrcID 2 Ev FINISH FlowID 2 Bytes 1000 Pkts 1\n")
    try:
        agg = aggregate_slowdown(d, "expG2a2a", "prism", k, sizes, seeds)
        for sz in sizes:
            lb = _lower_bound_s(k, sz, 14e-6, 100.0)
            exp = 1.0e-3 / lb                     # makespan 1.0 ms / lower bound
            assert abs(agg[sz][0] - exp) < 1e-6, (sz, agg[sz], exp)
            assert agg[sz][1] == 0.0, agg[sz]     # identical seeds -> SEM 0
            assert agg[sz][2] == 1.0, agg[sz]     # all complete -> min_cr 1.0
        # slowdown must fall as message grows (lower bound rises, makespan fixed)
        assert agg[sizes[0]][0] > agg[sizes[1]][0], agg
    finally:
        shutil.rmtree(d)
    lb = _lower_bound_s(4, 16384, 14e-6, 100.0)
    assert abs(lb - 4 * (14e-6 + 16384 * 8.0 / 1e11)) < 1e-15, lb
    assert _size_label(16384) == "16K" and _size_label(1048576) == "1M", "size label"
    m, se = _sem([10.0, 20.0, 30.0])
    assert abs(m - 20.0) < 1e-9 and abs(se - 10.0 / math.sqrt(3)) < 1e-9, (m, se)
    print("ok msgsweep_figs selftest")

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
