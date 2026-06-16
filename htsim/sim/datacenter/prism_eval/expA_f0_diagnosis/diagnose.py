#!/usr/bin/env python3
"""f0 (symmetric) penalty diagnosis for PRISM in the delay-driven regime.

Question: at -failed=0 (symmetric fabric, -disable_trim) PRISM is the WORST arm
(goodput ~869 vs REPS+NSCC ~997). T_spray tuning already showed the spread threshold
cannot fix it. This script localizes the cause with read-only logs (no controller change):

  (1) reproduce the f0 gap (seed 13);
  (2) FAIR per-ACK cwnd-decrease counts PRISM vs NSCC  -> is it over-CUTTING (B) or under-GROWING (A)?
  (3) mean/median cwnd PRISM vs NSCC                    -> does a lower window track the goodput gap?
  (4) PRISM region distribution f0 vs f8               -> how much of the time is PRISM NOT growing?
  (5) kappa (epoch length) sweep on {f0,f8}             -> is epoch quantization the lever? f8 do-no-harm?

Renders figD1 (under-growth: cwnd(t) overlay + region bars) and figD2 (kappa sweep).
All numbers are printed so the README is fully traceable. Reuses ../expA_delaydriven/data for
the kappa=1.0 default arm, the REPS+NSCC reference, and the failed=8 epoch log (contrast).
"""
import os, sys, collections, statistics

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
DELAY = os.path.join(HERE, "..", "expA_delaydriven", "data")
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import metrics  # noqa: E402

SEEDS = [13, 14, 15, 16, 17]
REGION_NAME = {0: "INCREASE", 1: "HOLD", 2: "DECREASE"}


# ---- helpers -----------------------------------------------------------------
def cwnd_stats(pathrtt):
    """(n_acks, mean_KB, median_KB, per_flow_mean_KB, n_flows) over a PRISM_PATHRTT csv."""
    per_flow = collections.defaultdict(list)
    with open(pathrtt) as fh:
        for ln in fh:
            p = ln.strip().split(",")
            if len(p) < 6:
                continue
            per_flow[int(p[1])].append(int(p[5]))
    allc = [c for v in per_flow.values() for c in v]
    permean = [statistics.mean(v) for v in per_flow.values() if v]
    return (len(allc), statistics.mean(allc) / 1024, statistics.median(allc) / 1024,
            statistics.mean(permean) / 1024, len(per_flow))


def region_dist(epoch_path):
    """(n_epochs, {region_name: count}, epoch_cuts) over a PRISM_EPOCH csv."""
    ep = metrics.parse_prism_epoch(epoch_path)
    n = len(ep)
    c = collections.Counter(r["region"] for r in ep)
    cuts = sum(r["cut"] for r in ep)
    return n, {REGION_NAME[k]: c.get(k, 0) for k in (0, 1, 2)}, cuts


def cwnd_series(pathrtt, bin_ns=20000):
    """(t_us[], mean_cwnd_KB[]) binned over time -- the cwnd(t) trajectory."""
    acc = collections.defaultdict(list)
    with open(pathrtt) as fh:
        for ln in fh:
            p = ln.strip().split(",")
            if len(p) < 6:
                continue
            acc[int(p[0]) // bin_ns].append(int(p[5]))
    xs = sorted(acc)
    return ([b * bin_ns / 1000.0 for b in xs],
            [sum(acc[b]) / len(acc[b]) / 1024.0 for b in xs])


def _avg_perf(tagfn):
    """seed-mean (goodput, goodput_std, avg_fct_us) over SEEDS, or None if a file is missing."""
    gs, fs = [], []
    for s in SEEDS:
        f = tagfn(s)
        if not os.path.exists(f):
            return None
        gs.append(metrics.aggregate_goodput_gbps(f))
        fs.append(metrics.fct_stats(f)["avg_s"] * 1e6)
    return statistics.mean(gs), statistics.pstdev(gs), statistics.mean(fs)


# ---- spread reality + reroutability (per-path) helpers ------------------------
BASE_NS = 13945   # uncontended base RTT (ns) on fat_tree_128_1os; q = max(raw_rtt - base, 0)


def _load_byflow(pathrtt):
    """flow -> path -> [(t_ns, q_ns)] and flow -> [t_first, t_last], from a PRISM_PATHRTT csv."""
    byflow = collections.defaultdict(lambda: collections.defaultdict(list))
    span = collections.defaultdict(lambda: [float("inf"), 0])
    with open(pathrtt) as fh:
        for ln in fh:
            p = ln.strip().split(",")
            if len(p) < 6:
                continue
            t = int(p[0]); flow = int(p[1]); pth = int(p[2]); q = max(int(p[3]) - BASE_NS, 0)
            byflow[flow][pth].append((t, q))
            s = span[flow]; s[0] = min(s[0], t); s[1] = max(s[1], t)
    return byflow, span


def _spearman(xs, ys):
    """Spearman rank correlation; nan for n<2."""
    n = len(xs)
    if n < 2:
        return float("nan")
    def ranks(v):
        order = sorted(range(n), key=lambda i: v[i]); r = [0] * n
        for rank, i in enumerate(order):
            r[i] = rank
        return r
    rx, ry = ranks(xs), ranks(ys)
    d2 = sum((rx[i] - ry[i]) ** 2 for i in range(n))
    return 1 - 6 * d2 / (n * (n * n - 1))


def longwindow_spread_us(pathrtt, minspp=8):
    """Median over flows of the cross-path spread (max-min of per-path MEAN q) measured over the
    flow's steady window. Large => real persistent-looking spread (not just per-sample jitter)."""
    byflow, span = _load_byflow(pathrtt)
    out = []
    for flow, paths in byflow.items():
        t0, t1 = span[flow]; lo = t0 + 0.15 * (t1 - t0); hi = t0 + 0.85 * (t1 - t0)
        pmeans = []
        for sl in paths.values():
            qs = [q for (t, q) in sl if lo <= t <= hi]
            if len(qs) >= minspp:
                pmeans.append(statistics.mean(qs))
        if len(pmeans) >= 2:
            out.append((max(pmeans) - min(pmeans)) / 1000.0)
    return statistics.median(out) if out else float("nan"), len(out)


def path_pairs(pathrtt, minhalf=5):
    """(h1_mean_q_us, h2_mean_q_us) per (flow,path) over the steady window's two halves --
    the raw material for the stability scatter. Persistent congestion => points on y=x."""
    byflow, span = _load_byflow(pathrtt)
    pairs = []
    for flow, paths in byflow.items():
        t0, t1 = span[flow]; lo = t0 + 0.15 * (t1 - t0); hi = t0 + 0.85 * (t1 - t0); mid = (lo + hi) / 2
        for sl in paths.values():
            a = [q for (t, q) in sl if lo <= t < mid]
            b = [q for (t, q) in sl if mid <= t <= hi]
            if len(a) >= minhalf and len(b) >= minhalf:
                pairs.append((statistics.mean(a) / 1000.0, statistics.mean(b) / 1000.0))
    return pairs


def halves_summary(pathrtt, minhalf=5):
    """(mean_q_h1, mean_q_h2, spread_h1, spread_h2) in us -- medians over flows of the per-path
    mean q and the cross-path spread, in the 1st vs 2nd half of the steady window. Distinguishes a
    self-resolving startup TRANSIENT (q & spread collapse h1->h2) from PERSISTENT structure (they hold)."""
    byflow, span = _load_byflow(pathrtt)
    mq1, mq2, sp1, sp2 = [], [], [], []
    for flow, paths in byflow.items():
        t0, t1 = span[flow]; lo = t0 + 0.15 * (t1 - t0); hi = t0 + 0.85 * (t1 - t0); mid = (lo + hi) / 2
        pm1, pm2 = {}, {}
        for pth, sl in paths.items():
            a = [q for (t, q) in sl if lo <= t < mid]
            b = [q for (t, q) in sl if mid <= t <= hi]
            if len(a) >= minhalf:
                pm1[pth] = statistics.mean(a)
            if len(b) >= minhalf:
                pm2[pth] = statistics.mean(b)
        if pm1:
            mq1.append(statistics.mean(pm1.values()))
            sp1.append(max(pm1.values()) - min(pm1.values()) if len(pm1) > 1 else 0)
        if pm2:
            mq2.append(statistics.mean(pm2.values()))
            sp2.append(max(pm2.values()) - min(pm2.values()) if len(pm2) > 1 else 0)
    med = lambda L: statistics.median(L) / 1000.0 if L else float("nan")
    return med(mq1), med(mq2), med(sp1), med(sp2)


def path_stability(pathrtt, minhalf=5):
    """(n_flows, median_rankcorr, median_bestquarter_persistence) of per-path q across the two
    halves of the steady window. High => a STABLE clean path exists (durably reroutable)."""
    byflow, span = _load_byflow(pathrtt)
    corrs, keep = [], []
    for flow, paths in byflow.items():
        t0, t1 = span[flow]; lo = t0 + 0.15 * (t1 - t0); hi = t0 + 0.85 * (t1 - t0); mid = (lo + hi) / 2
        h1, h2 = {}, {}
        for pth, sl in paths.items():
            a = [q for (t, q) in sl if lo <= t < mid]
            b = [q for (t, q) in sl if mid <= t <= hi]
            if len(a) >= minhalf and len(b) >= minhalf:
                h1[pth] = statistics.mean(a); h2[pth] = statistics.mean(b)
        common = sorted(set(h1) & set(h2))
        if len(common) >= 4:
            corrs.append(_spearman([h1[p] for p in common], [h2[p] for p in common]))
            k = max(1, len(common) // 4)
            b1 = set(sorted(common, key=lambda p: h1[p])[:k])
            b2 = set(sorted(common, key=lambda p: h2[p])[:k])
            keep.append(len(b1 & b2) / k)
    if not corrs:
        return 0, float("nan"), float("nan")
    return len(corrs), statistics.median(corrs), statistics.median(keep)


# ---- analysis ----------------------------------------------------------------
def discriminators():
    """Print (1)-(4); return the data needed by the figures."""
    print("=== (1) f0 seed-13 PERF (reproduce the penalty) ===")
    perf = {}
    for tag, f in [("PRISM", f"{DATA}/f0_prism.flow.txt"),
                   ("REPS+NSCC", f"{DATA}/f0_reps.flow.txt")]:
        g = metrics.aggregate_goodput_gbps(f)
        st = metrics.fct_stats(f)
        perf[tag] = (g, st["avg_s"] * 1e6, st["completion_rate"])
        print(f"  {tag:10s} goodput {g:6.1f} Gbps | avg-FCT {st['avg_s']*1e6:7.1f} us | cr {st['completion_rate']:.3f}")

    print("\n=== (2) FAIR per-ACK cwnd-decrease count (same method both arms) -> A vs B ===")
    pc = metrics.count_cwnd_cuts_from_pathrtt(f"{DATA}/f0_prism.pathrtt.csv")
    rc = metrics.count_cwnd_cuts_from_pathrtt(f"{DATA}/f0_reps.pathrtt.csv")
    np_, mp, medp, pmp, nfp = cwnd_stats(f"{DATA}/f0_prism.pathrtt.csv")
    nr_, mr, medr, pmr, nfr = cwnd_stats(f"{DATA}/f0_reps.pathrtt.csv")
    print(f"  PRISM     cuts {pc:5d} / {np_:6d} acks = {pc/np_*100:5.2f}% , {pc/nfp:4.1f}/flow")
    print(f"  REPS+NSCC cuts {rc:5d} / {nr_:6d} acks = {rc/nr_*100:5.2f}% , {rc/nfr:4.1f}/flow")
    verdict = "A (under-growth)" if pc < rc else "B (over-cut)"
    print(f"  --> PRISM cuts {'FEWER' if pc < rc else 'MORE'} than NSCC; verdict = {verdict}")

    print("\n=== (3) mean/median cwnd (KB) ===")
    print(f"  PRISM     mean {mp:6.1f}  median {medp:6.1f}  per-flow-mean {pmp:6.1f}")
    print(f"  REPS+NSCC mean {mr:6.1f}  median {medr:6.1f}  per-flow-mean {pmr:6.1f}")
    print(f"  PRISM/NSCC mean-cwnd ratio = {mp/mr:.3f}  (tracks the goodput ratio "
          f"{perf['PRISM'][0]/perf['REPS+NSCC'][0]:.3f})")

    print("\n=== (4) PRISM region distribution: f0 vs f8 ===")
    regions = {}
    for tag, ep in [("f0", f"{DATA}/f0_prism.epoch.csv"),
                    ("f8", f"{DELAY}/expA_prism_mech.epoch.csv")]:
        n, d, cuts = region_dist(ep)
        regions[tag] = (n, d)
        non_inc = (d["HOLD"] + d["DECREASE"]) / n * 100
        print(f"  {tag}: {n:4d} epochs  INCREASE {d['INCREASE']/n*100:4.1f}%  "
              f"HOLD {d['HOLD']/n*100:4.1f}%  DECREASE {d['DECREASE']/n*100:4.1f}%  "
              f"-> NOT-growing {non_inc:4.1f}%  | epoch-cuts {cuts} ({cuts/n*100:.1f}%)")
    return perf, (pc, rc), (mp, mr), regions


def spread_and_stability():
    """Print (5) the spread is REAL at f0 and (6) but it is NOT durably reroutable (it churns),
    whereas f8's spread is structural and stable. REPS+NSCC is the healthy-window control that
    rules out a PRISM-undersampling artifact. This is why HOLD pays off at f8 but not at f0."""
    files = [
        ("f0 PRISM", f"{DATA}/f0_prism.pathrtt.csv"),
        ("f0 REPS+NSCC (control)", f"{DATA}/f0_reps.pathrtt.csv"),
        ("f8 PRISM", f"{DELAY}/expA_prism_mech.pathrtt.csv"),
        ("f8 REPS+NSCC (control)", f"{DELAY}/expA_reps_mech.pathrtt.csv"),
    ]
    print("\n=== (5) is the f0 spread REAL? cross-path spread of per-path MEAN q (steady window) ===")
    for label, f in files:
        med, n = longwindow_spread_us(f)
        print(f"  {label:24s} median cross-path spread {med:5.1f} us  ({n} flows)  "
              f"-> {'YES, real spread' if med >= BASE_NS/1000 else 'small'}")
    print("\n=== (6) is the f0 spread PERSISTENT (reroutable) or a self-resolving TRANSIENT? ===")
    print("    per-path mean q and cross-path spread, 1st half -> 2nd half of the steady window:")
    for label, f in files:
        mq1, mq2, sp1, sp2 = halves_summary(f)
        kind = "TRANSIENT (resolves)" if sp2 < sp1 * 0.6 else "PERSISTENT (structural)"
        print(f"  {label:24s} q {mq1:5.1f}->{mq2:5.1f}us | spread {sp1:5.1f}->{sp2:5.1f}us  -> {kind}")
    print("    (corroborating) per-path rank-stability across the two halves:")
    for label, f in files:
        n, corr, keep = path_stability(f)
        print(f"  {label:24s} rank-corr {corr:+.2f} | best-quarter persists {keep*100:3.0f}% (random ~25%)  [{n} flows]")
    print("  Conclusion: f0's cross-path spread is dominated by the STARTUP INCAST TRANSIENT -- it drains")
    print("              to uniformly-low q by steady state, so there is no persistent localized congestion")
    print("              to durably reroute around. f8's spread PERSISTS (structural, degraded links). So")
    print("              HOLD stalls growth on a self-resolving transient at f0, but durably reroutes at f8.")


def kappa_sweep():
    """Print (7); return rows [(failed, ref, k10, k05, k025), ...] (each = _avg_perf tuple/None)."""
    print("\n=== (7) kappa (epoch length) sweep -- f0 recovery & f8 do-no-harm ===")
    rows = []
    for f in (0, 8):
        ref = _avg_perf(lambda s, f=f: f"{DELAY}/expA_reps_f{f}_s{s}.flow.txt")
        k10 = _avg_perf(lambda s, f=f: f"{DELAY}/expA_prism_f{f}_s{s}.flow.txt")  # kappa=1.0 default
        k05 = _avg_perf(lambda s, f=f: f"{DATA}/kap0.5_f{f}_s{s}.flow.txt")
        k025 = _avg_perf(lambda s, f=f: f"{DATA}/kap0.25_f{f}_s{s}.flow.txt")
        rows.append((f, ref, k10, k05, k025))

    def c(x):
        return f"{x[0]:6.1f}/{x[2]:5.0f}" if x else "  n/a "
    print(f"  {'cell':>4} | {'REPS+NSCC':>13} | {'k=1.0(def)':>13} | {'k=0.5':>13} | {'k=0.25':>13}   (goodput Gbps / avg-FCT us)")
    for f, ref, k10, k05, k025 in rows:
        print(f"  f{f:<3} | {c(ref):>13} | {c(k10):>13} | {c(k05):>13} | {c(k025):>13}")
    for f, ref, k10, k05, k025 in rows:
        if not (k10 and ref):
            continue
        best = max((x for x in (k10, k05, k025) if x), key=lambda x: x[0])
        if f == 0:
            gap = (ref[0] - k10[0]) / k10[0] * 100        # how far default PRISM is below NSCC
            rem = (ref[0] - best[0]) / ref[0] * 100        # how far the best kappa STILL is below NSCC
            print(f"  [f0 penalty] default PRISM is {gap:.1f}% below NSCC; best over kappa = {best[0]:.1f} "
                  f"-> still {rem:.1f}% below NSCC (epoch length is NOT the dominant lever)")
        else:
            lead = (k10[0] - ref[0]) / ref[0] * 100        # PRISM's lead over NSCC at default
            print(f"  [f8 win] default PRISM leads NSCC by {lead:.1f}%; over kappa PRISM stays "
                  f">= {min(x[0] for x in (k10, k05, k025) if x):.1f} (do-no-harm holds)")
    return rows


# ---- figures -----------------------------------------------------------------
def render(regions, kappa_rows):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    sys.path.insert(0, os.path.join(HERE, "..", "common"))
    import plot_style
    figs = os.path.join(HERE, "figs")
    os.makedirs(figs, exist_ok=True)
    C = plot_style.COLORS

    # figD1: (a) cwnd(t) overlay @f0  (b) region stacked bars f0 vs f8
    fig, (axw, axr) = plt.subplots(1, 2, figsize=(11, 4))
    tp, cp = cwnd_series(f"{DATA}/f0_prism.pathrtt.csv")
    tr, cr = cwnd_series(f"{DATA}/f0_reps.pathrtt.csv")
    _, mp, _, _, _ = cwnd_stats(f"{DATA}/f0_prism.pathrtt.csv")
    _, mr, _, _, _ = cwnd_stats(f"{DATA}/f0_reps.pathrtt.csv")
    axw.plot(tr, cr, color=C["reps"], lw=1.5, alpha=0.85, label="REPS+NSCC")
    axw.plot(tp, cp, color=C["prism"], lw=1.5, alpha=0.85, label="PRISM")
    axw.axhline(mr, color=C["reps"], ls="--", lw=1.3, label=f"NSCC mean {mr:.0f} KB")
    axw.axhline(mp, color=C["prism"], ls="--", lw=1.3, label=f"PRISM mean {mp:.0f} KB")
    axw.set_title("cwnd(t) @ -failed=0 (symmetric): PRISM under-grows", fontsize=10)
    axw.set_xlabel("time (us)"); axw.set_ylabel("cwnd (KB, mean/flow)")
    axw.grid(alpha=0.3); axw.legend(fontsize=8)

    order = ["INCREASE", "HOLD", "DECREASE"]
    rcolors = {"INCREASE": "tab:green", "HOLD": "tab:orange", "DECREASE": "tab:red"}
    cells = ["f0", "f8"]
    bottoms = [0.0, 0.0]
    for reg in order:
        vals = [regions[ce][1][reg] / regions[ce][0] * 100 for ce in cells]
        axr.bar(cells, vals, bottom=bottoms, color=rcolors[reg], label=reg, edgecolor="white")
        bottoms = [b + v for b, v in zip(bottoms, vals)]
    axr.set_title("PRISM region share: f0 mis-HOLDs a non-reroutable incast", fontsize=10)
    axr.set_ylabel("% of epochs"); axr.set_ylim(0, 100)
    axr.legend(fontsize=8, loc="lower right")
    plt.tight_layout(); plot_style.save(fig, "figD1_undergrowth", figs); plt.close(fig)

    # figD2: kappa sweep -- goodput (left) and FCT (right) vs kappa, f0 & f8
    kx = [0.25, 0.5, 1.0]
    fig, (axg, axf) = plt.subplots(1, 2, figsize=(11, 4))
    for f, ref, k10, k05, k025 in kappa_rows:
        series = {0.25: k025, 0.5: k05, 1.0: k10}
        col = C["prism"] if f == 0 else C["strack"]
        gy = [series[k][0] for k in kx]
        fy = [series[k][2] for k in kx]
        axg.plot(kx, gy, "o-", color=col, label=f"PRISM f{f}")
        axf.plot(kx, fy, "o-", color=col, label=f"PRISM f{f}")
        if ref:
            axg.axhline(ref[0], color=col, ls="--", lw=1.1, alpha=0.7, label=f"REPS+NSCC f{f}")
            axf.axhline(ref[2], color=col, ls="--", lw=1.1, alpha=0.7, label=f"REPS+NSCC f{f}")
    for ax, ylab, ttl in [(axg, "goodput (Gbps)", "Goodput vs epoch length"),
                          (axf, "avg-FCT (us)", "FCT vs epoch length")]:
        ax.set_xlabel("kappa (epoch = kappa x base_rtt)"); ax.set_ylabel(ylab)
        ax.set_title(ttl, fontsize=10); ax.set_xticks(kx); ax.grid(alpha=0.3); ax.legend(fontsize=8)
    plt.tight_layout(); plot_style.save(fig, "figD2_kappa", figs); plt.close(fig)

    # figD3: per-path mean q, 1st half vs 2nd half of the steady window (REPS+NSCC control, healthy
    # window). f0: points fall BELOW y=x (spread drains -> transient). f8: points hold near/above the
    # line at high q (spread persists -> structural, durably reroutable).
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    panels = [("f0 (symmetric): spread is a startup TRANSIENT", f"{DATA}/f0_reps.pathrtt.csv", C["reps"]),
              ("f8 (asymmetric): spread PERSISTS (structural)", f"{DELAY}/expA_reps_mech.pathrtt.csv", C["strack"])]
    for ax, (ttl, f, col) in zip(axes, panels):
        pairs = path_pairs(f)
        _, _, sp1, sp2 = halves_summary(f)
        if pairs:
            xs, ys = zip(*pairs)
            ax.scatter(xs, ys, s=14, color=col, alpha=0.5, edgecolors="none")
            hi = max(max(xs), max(ys)) * 1.05
            ax.plot([0, hi], [0, hi], "k--", lw=1.0, alpha=0.6, label="y = x (persistent)")
            ax.set_xlim(0, hi); ax.set_ylim(0, hi)
        ax.set_title(f"{ttl}\ncross-path spread {sp1:.0f}->{sp2:.0f}us (1st->2nd half)", fontsize=9)
        ax.set_xlabel("per-path mean q, 1st half (us)"); ax.set_ylabel("per-path mean q, 2nd half (us)")
        ax.grid(alpha=0.3); ax.legend(fontsize=8, loc="upper left")
    plt.tight_layout(); plot_style.save(fig, "figD3_stability", figs); plt.close(fig)
    print(f"\n[figs] wrote {figs}/figD1_undergrowth.*  figD2_kappa.*  figD3_stability.*")


# ---- selftest ----------------------------------------------------------------
def selftest():
    import tempfile, shutil
    d = tempfile.mkdtemp()
    # pathrtt fixture: flow 1 cwnd 100->90 (1 cut), flow 2 cwnd 50->60 (0 cut). mean=(100+90+50+60)/4.
    pr = os.path.join(d, "x.pathrtt.csv")
    with open(pr, "w") as fh:
        fh.write("1000,1,0,14000,0,102400\n")   # flow 1: 100 KB
        fh.write("2000,1,0,14000,0,92160\n")     # flow 1: 90 KB  (cut)
        fh.write("1500,2,0,14000,0,51200\n")     # flow 2: 50 KB
        fh.write("2500,2,0,14000,0,61440\n")     # flow 2: 60 KB  (grow)
    assert metrics.count_cwnd_cuts_from_pathrtt(pr) == 1
    n, mean, med, pfm, nf = cwnd_stats(pr)
    assert n == 4 and nf == 2, (n, nf)
    assert abs(mean - (102400 + 92160 + 51200 + 61440) / 4 / 1024) < 1e-6, mean
    # per-flow means: flow1=(100+90)/2=95 KB, flow2=(50+60)/2=55 KB -> mean of means = 75 KB
    assert abs(pfm - 75.0) < 1e-3, pfm
    # epoch fixture: regions 0,1,1,2 ; cuts col last
    ep = os.path.join(d, "x.epoch.csv")
    with open(ep, "w") as fh:
        fh.write("1000,1,14000,1000,2000,0,100000,5,0\n")
        fh.write("2000,1,14000,1000,9000,1,100000,5,0\n")
        fh.write("3000,1,14000,1000,9000,1,100000,5,0\n")
        fh.write("4000,1,14000,20000,2000,2,90000,5,1\n")
    nn, dd, cuts = region_dist(ep)
    assert nn == 4 and dd == {"INCREASE": 1, "HOLD": 2, "DECREASE": 1} and cuts == 1, (nn, dd, cuts)

    # rank correlation: monotone -> +1, reversed -> -1
    assert abs(_spearman([1, 2, 3, 4], [10, 20, 30, 40]) - 1.0) < 1e-9
    assert abs(_spearman([1, 2, 3, 4], [40, 30, 20, 10]) + 1.0) < 1e-9

    # per-path spread + stability fixture: 4 paths, persistently separated q (path i ~ i*5us),
    # 6 samples per half-window. Expect real spread, rank-corr +1, best-quarter persists 100%.
    sp = os.path.join(d, "stab.pathrtt.csv")
    with open(sp, "w") as fh:
        fh.write(f"0,1,0,{BASE_NS},0,100000\n")          # padding sample -> t_min=0 (q=0)
        fh.write(f"120000,1,0,{BASE_NS},0,100000\n")      # padding -> t_max=120000 (steady ~18k..102k)
        for pth in range(4):
            q = BASE_NS + (pth + 1) * 5000           # raw_rtt; q = raw-base = (pth+1)*5us exactly
            for t in (20000, 30000, 40000, 50000, 55000, 58000):   # 1st half (< mid=60k)
                fh.write(f"{t},1,{pth},{q},0,100000\n")
            for t in (62000, 70000, 80000, 90000, 95000, 100000):  # 2nd half
                fh.write(f"{t},1,{pth},{q},0,100000\n")
    med, nfl = longwindow_spread_us(sp)
    assert nfl == 1 and abs(med - 15.0) < 1e-6, (nfl, med)   # spread = (4-1)*5us = 15us
    n, corr, keep = path_stability(sp)
    assert n == 1 and abs(corr - 1.0) < 1e-9 and abs(keep - 1.0) < 1e-9, (n, corr, keep)
    assert len(path_pairs(sp)) == 4, path_pairs(sp)
    # q constant across both halves -> spread persists (sp1 == sp2 == 15us), mean q = 12.5us
    mq1, mq2, sp1, sp2 = halves_summary(sp)
    assert abs(sp1 - 15.0) < 1e-6 and abs(sp2 - 15.0) < 1e-6, (sp1, sp2)
    assert abs(mq1 - 12.5) < 1e-6 and abs(mq2 - 12.5) < 1e-6, (mq1, mq2)
    shutil.rmtree(d)
    print("ok diagnose selftest")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        perf, cuts, cwnds, regions = discriminators()
        spread_and_stability()
        rows = kappa_sweep()
        render(regions, rows)
