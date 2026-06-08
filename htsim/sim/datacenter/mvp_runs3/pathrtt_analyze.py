#!/usr/bin/env python3
"""Decompose per-path RTT into C_cc = min_i q_i and C_spray = max_i q_i - min_i q_i,
where q_i = (latest raw_rtt on path i) - (historical min raw_rtt on path i), per flow.
Reads the PRISM_PATHRTT CSV: time_ns,flow_id,path_id,raw_rtt_ns
Usage: python3 pathrtt_analyze.py <tag> [<tag> ...]   (reads mvp_runs3/<tag>.pathrtt.csv)
"""
import sys, os, collections, math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
BIN_NS = 10_000          # 10 us bins
WIN = (500.0, 1500.0)    # steady window, us

def parse_csv(path):
    """-> list of (t_ns, flow, path, rtt_ns), all ints, sorted by time."""
    rows = []
    with open(path) as f:
        for line in f:
            p = line.split(",")
            if len(p) != 4:
                continue
            try:
                rows.append((int(p[0]), int(p[1]), int(p[2]), int(p[3])))
            except ValueError:
                continue
    rows.sort(key=lambda r: r[0])
    return rows

def rtt_min_per_path(rows):
    """(flow,path) -> min raw_rtt over the whole run."""
    m = {}
    for t, flow, path, rtt in rows:
        k = (flow, path)
        if k not in m or rtt < m[k]:
            m[k] = rtt
    return m

def rtt_min_per_flow(rows):
    """flow -> min raw_rtt over ALL paths and time (the flow's empty-network floor B_flow)."""
    m = {}
    for t, flow, path, rtt in rows:
        if flow not in m or rtt < m[flow]:
            m[flow] = rtt
    return m

def decompose(rows, rtt_min, flow_id, bin_ns=BIN_NS, t0=None, t1=None,
              baseline="own", rtt_min_flow=None):
    """For one flow: (times_ns, c_spray_ns, c_cc_ns), one entry per bin in [t0,t1).
    baseline='own':    q_i = rtt_i - rtt_min[(flow,i)]   (per-path own historical min)
    baseline='global': q_i = rtt_i - rtt_min_flow[flow]  (one floor for all paths; then
                       C_spray = max_i rtt_i - min_i rtt_i, the baseline cancels).
    Per bin, latest raw_rtt carried forward per path. Empty path-set bins are skipped."""
    fr = [r for r in rows if r[1] == flow_id]
    if not fr:
        return [], [], []
    if t0 is None:
        t0 = (fr[0][0] // bin_ns) * bin_ns
    if t1 is None:
        t1 = fr[-1][0] + 1
    if baseline == "global":
        base = rtt_min_flow[flow_id]
        base_of = lambda p: base
    else:
        base_of = lambda p: rtt_min[(flow_id, p)]
    latest = {}        # path -> latest raw_rtt seen
    idx = 0
    times, cspray, ccc = [], [], []
    b = t0
    while b < t1:
        bin_end = b + bin_ns
        while idx < len(fr) and fr[idx][0] < bin_end:
            _, _, path, rtt = fr[idx]
            latest[path] = rtt
            idx += 1
        if latest:
            qs = [latest[p] - base_of(p) for p in latest]
            times.append(b)
            cspray.append(max(qs) - min(qs))
            ccc.append(min(qs))
        b = bin_end
    return times, cspray, ccc

def steady_stats(times_us, series, lo=WIN[0], hi=WIN[1]):
    w = sorted(v for t, v in zip(times_us, series) if lo <= t <= hi)
    if not w:
        return {"mean": 0.0, "median": 0.0, "p95": 0.0, "n": 0}
    n = len(w)
    return {"mean": sum(w)/n, "median": (w[(n-1)//2]+w[n//2])/2,
            "p95": w[min(n - 1, max(0, math.ceil(0.95 * n) - 1))], "n": n}

def representative_flow(rows):
    """flow_id with the most RTT samples (best per-path statistics)."""
    c = collections.Counter(r[1] for r in rows)
    return c.most_common(1)[0][0] if c else None

def analyze_tag(tag, baseline="own"):
    rows = parse_csv(os.path.join(HERE, f"{tag}.pathrtt.csv"))
    if not rows:
        print(f"{tag}: WARNING empty CSV (run may have failed) — skipping", file=sys.stderr)
        return None
    mins = rtt_min_per_path(rows)
    minf = rtt_min_per_flow(rows)
    flow = representative_flow(rows)
    t_ns, cs_ns, cc_ns = decompose(rows, mins, flow, baseline=baseline, rtt_min_flow=minf)
    t_us = [t/1000.0 for t in t_ns]
    cs_us = [x/1000.0 for x in cs_ns]
    cc_us = [x/1000.0 for x in cc_ns]
    cs_s = steady_stats(t_us, cs_us)
    cc_s = steady_stats(t_us, cc_us)
    npaths = len({p for (f, p) in mins if f == flow})

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(t_us, cs_us, label="C_spray = max-min", linewidth=1.0)
    ax.plot(t_us, cc_us, label="C_cc = min", linewidth=1.0, linestyle="--")
    ax.axvspan(WIN[0], WIN[1], color="grey", alpha=0.12)
    ax.set_xlabel("time (us)"); ax.set_ylabel("per-path queueing delay q (us)")
    ax.set_title(f"{tag} (flow {flow}, {npaths} paths)")
    ax.legend(fontsize=8); ax.grid(alpha=0.3); ax.set_xlim(0, 2000)
    plt.tight_layout(); plt.savefig(os.path.join(HERE, f"{tag}.png"), dpi=130); plt.close()

    print(f"{tag:14s} flow{flow} npaths={npaths:3d} samples={len(rows):6d}  "
          f"C_spray mean={cs_s['mean']:6.2f} p95={cs_s['p95']:6.2f}us  "
          f"C_cc mean={cc_s['mean']:6.2f} p95={cc_s['p95']:6.2f}us")
    return {"tag": tag, "cspray": cs_s, "ccc": cc_s, "flow": flow, "npaths": npaths}

def aggregate_tag(tag, min_samples=200, baseline="own", win=WIN):
    """Cross-flow robust statistic. For every flow with >= min_samples ACKs INSIDE the
    steady window `win`, compute its steady-window mean C_spray and C_cc; return the
    MEDIAN across flows. baseline selects 'own' (per-path min) or 'global' (flow floor).
    Returns {nflows, cspray_med, ccc_med} or None if no eligible flow."""
    import statistics
    rows = parse_csv(os.path.join(HERE, f"{tag}.pathrtt.csv"))
    if not rows:
        return None
    mp = rtt_min_per_path(rows)
    mf = rtt_min_per_flow(rows)
    inwin = collections.Counter(f for (t, f, p, r) in rows
                                if win[0] <= t / 1000.0 <= win[1])
    cs_list, cc_list = [], []
    for flow in inwin:
        if inwin[flow] < min_samples:
            continue
        t_ns, cs_ns, cc_ns = decompose(rows, mp, flow, baseline=baseline, rtt_min_flow=mf)
        t_us = [t / 1000.0 for t in t_ns]
        ssp = steady_stats(t_us, [x / 1000.0 for x in cs_ns], win[0], win[1])
        scc = steady_stats(t_us, [x / 1000.0 for x in cc_ns], win[0], win[1])
        if ssp["n"] > 0:
            cs_list.append(ssp["mean"]); cc_list.append(scc["mean"])
    if not cs_list:
        return None
    return {"nflows": len(cs_list),
            "cspray_med": statistics.median(cs_list),
            "ccc_med": statistics.median(cc_list)}

if __name__ == "__main__":
    for tag in sys.argv[1:]:
        analyze_tag(tag)
        agg = aggregate_tag(tag)
        if agg:
            print(f"{'':14s}   cross-flow median (n={agg['nflows']}): "
                  f"C_spray={agg['cspray_med']:6.2f}us  C_cc={agg['ccc_med']:6.2f}us")
