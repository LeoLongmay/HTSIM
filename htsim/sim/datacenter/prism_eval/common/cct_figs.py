#!/usr/bin/env python3
"""MSwift-style collective figures for prism_eval (kept separate from perf_figs.py, which holds
uncommitted WIP). CCT-inflation grouped bar chart + FCT CDF; aggregation reuses metrics.py.
  python3 cct_figs.py --selftest   # math self-check
"""
import os, sys, math, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import metrics          # noqa: E402
import plot_style       # noqa: E402

def _sem(v):
    """(mean, standard error of the mean) of a non-empty list; NaNs dropped. SEM = sample_std/sqrt(n)
    (ddof=1; 0.0 for n<2). Matches MSwift's error bars (standard error of the mean)."""
    clean = [x for x in v if not math.isnan(x)]
    if not clean:
        return (float("nan"), 0.0)
    m = statistics.mean(clean)
    sd = statistics.stdev(clean) if len(clean) > 1 else 0.0
    return (m, sd / math.sqrt(len(clean)))

def aggregate_cct(data_dir, tag_prefix, label, failed, seeds, size_bytes,
                  link_gbps=100.0, base_rtt_s=14e-6, token="f"):
    """Per-failed CCT-inflation aggregate for one arm: {f:(mean_infl_pct, sem_infl_pct)}; omit f
    with no data. Reads {tag_prefix}_{label}_{token}{f}_s{seed}.flow.txt."""
    out = {}
    for f in failed:
        infl = []
        for s in seeds:
            flow = os.path.join(data_dir, f"{tag_prefix}_{label}_{token}{f}_s{s}.flow.txt")
            if not os.path.exists(flow):
                continue
            _, pct = metrics.cct_inflation(flow, size_bytes, link_gbps, base_rtt_s)
            infl.append(pct)
        if not infl:
            continue
        out[f] = _sem(infl)
    return out

def selftest():
    import tempfile, shutil
    d = tempfile.mkdtemp()
    failed = [0, 4, 8, 12]; seeds = [13, 14, 15, 16, 17]
    for f in failed:
        for s in seeds:
            with open(os.path.join(d, f"expF_ops_f{f}_s{s}.flow.txt"), "w") as fh:
                fh.write("0.000000000 Type FLOW_EVENT SrcID 1 Ev START FlowID 1 Flowsize 1000000\n")
                fh.write("0.000000000 Type FLOW_EVENT SrcID 2 Ev START FlowID 2 Flowsize 1000000\n")
                fh.write("0.001000000 Type FLOW_EVENT SrcID 1 Ev FINISH FlowID 1 Bytes 1000000 Pkts 1\n")
                fh.write("0.001000000 Type FLOW_EVENT SrcID 2 Ev FINISH FlowID 2 Bytes 1000000 Pkts 1\n")
    ac = aggregate_cct(d, "expF", "ops", failed, seeds, size_bytes=1_000_000)
    lb = 14e-6 + 1_000_000 * 8.0 / 1e11
    exp = (0.001 - lb) / lb * 100.0
    assert abs(ac[0][0] - exp) < 1e-6, ac[0]
    assert ac[0][1] == 0.0, ac[0]            # identical seeds -> SEM 0
    shutil.rmtree(d)
    m, se = _sem([10.0, 20.0, 30.0])         # mean 20, sample stdev 10, n 3
    assert abs(m - 20.0) < 1e-9, (m, se)
    assert abs(se - 10.0 / math.sqrt(3)) < 1e-9, (m, se)
    nan_m, nan_se = _sem([float("nan")])     # all-nan -> (nan, 0.0), no crash
    assert nan_m != nan_m and nan_se == 0.0, (nan_m, nan_se)
    print("ok cct_figs selftest")

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
