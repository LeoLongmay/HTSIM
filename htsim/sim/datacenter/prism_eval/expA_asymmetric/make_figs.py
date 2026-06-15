#!/usr/bin/env python3
"""Experiment A (asymmetric fabric) figures. Reads the sweep + mechanism logs produced by
repro.sh from ./data and renders Fig1 (main performance) and Fig2 (mechanism) into ./figs.
  python3 make_figs.py             # render Fig1 + Fig2
  python3 make_figs.py --selftest  # parser/aggregation self-checks (synthetic, no sim data)
"""
import os, sys, statistics
HERE = os.path.dirname(os.path.abspath(__file__))
COMMON = os.path.join(HERE, "..", "common")
sys.path.insert(0, COMMON)
import metrics          # noqa: E402
import plot_style       # noqa: E402

DATA = os.path.join(HERE, "data")
FIGS = os.path.join(HERE, "figs")
# label -> (cc, lb, display, color-key)
BASELINES = [("ops", "nscc", "oblivious", "OPS+NSCC", "ops"),
             ("reps", "nscc", "reps", "REPS+NSCC", "reps"),
             ("prism", "prism", "reps", "PRISM", "prism")]
FAILED = [0, 2, 4, 8, 12]
SEEDS = [13, 14, 15, 16, 17]
TARGET_US = 6.0
MECH_FAILED = 8

def _agg(label):
    """Per-failed aggregates for one baseline: dict failed -> dict of metric -> (mean,std)."""
    out = {}
    for f in FAILED:
        g, afct, p99, cr = [], [], [], []
        for s in SEEDS:
            flow = os.path.join(DATA, f"expA_{label}_f{f}_s{s}.flow.txt")
            if not os.path.exists(flow):
                continue
            st = metrics.fct_stats(flow)
            g.append(metrics.aggregate_goodput_gbps(flow))
            afct.append(st["avg_s"] * 1e6)      # us
            p99.append(st["p99_s"] * 1e6)       # us
            cr.append(st["completion_rate"])
        if not g:                       # no seed files for this cell -> omit so callers skip it
            continue
        def ms(v):                       # pstdev: full fixed seed set, so population std is right
            return (statistics.mean(v), statistics.pstdev(v))
        out[f] = {"goodput": ms(g), "avg_fct": ms(afct), "p99_fct": ms(p99), "cr": ms(cr)}
    return out

def render_fig1():
    import matplotlib.pyplot as plt
    plot_style.apply_style(13)
    aggs = {lab: _agg(lab) for (lab, _cc, _lb, _disp, _ck) in BASELINES}
    fig, axes = plt.subplots(3, 1, figsize=(5.2, 8.0), sharex=True)
    panels = [("goodput", "Goodput (Gbps)"), ("avg_fct", "Avg FCT (us)"), ("p99_fct", "P99 FCT (us)")]
    for ax, (key, ylabel) in zip(axes, panels):
        for (lab, _cc, _lb, disp, ck) in BASELINES:
            xs = [f for f in FAILED if aggs[lab].get(f)]
            ys = [aggs[lab][f][key][0] for f in xs]
            es = [aggs[lab][f][key][1] for f in xs]
            ax.errorbar(xs, ys, yerr=es, marker="o", lw=2.0, ms=6, capsize=3,
                        color=plot_style.COLORS[ck], label=disp)
        ax.set_ylabel(ylabel)
        ax.grid(alpha=0.3)
    axes[0].legend(fontsize=9)
    axes[-1].set_xlabel("# constrained core->agg links (-failed)")
    axes[-1].set_xticks(FAILED)
    # annotate any cell with completion_rate < 1 (honesty: FCT is over completed flows only)
    incomplete = []
    for (lab, _cc, _lb, _disp, _ck) in BASELINES:
        for f in FAILED:
            cell = aggs[lab].get(f)
            if cell and cell["cr"][0] < 0.999:
                incomplete.append((lab, f, cell["cr"][0]))
    if incomplete:
        note = "completion<1: " + ", ".join(f"{lab}@f{f}={cr:.2f}" for lab, f, cr in incomplete)
        fig.text(0.5, 0.005, note, ha="center", fontsize=7, color="firebrick")
    plt.tight_layout()
    plot_style.save(fig, "figA1_main_perf", FIGS)
    plt.close(fig)
    # also print the table for the README/honesty
    for (lab, _cc, _lb, disp, _ck) in BASELINES:
        print(f"[fig1] {disp}: " + " ".join(
            f"f{f}:g={aggs[lab][f]['goodput'][0]:.1f},avgfct={aggs[lab][f]['avg_fct'][0]:.0f}us,"
            f"cr={aggs[lab][f]['cr'][0]:.2f}" for f in FAILED if aggs[lab].get(f)))

def render_fig2():
    """Mechanism at failed=8: (a) the signal each controller reacts to -- REPS+NSCC's avg
    queuing delay (and the floor it ignores) vs PRISM's floor C_cc, against the target; and
    (b) cwnd(t) for PRISM vs REPS+NSCC. Plus printed window-cut counts."""
    import matplotlib.pyplot as plt
    plot_style.apply_style(13)
    reps_pr = os.path.join(DATA, "expA_reps_mech.pathrtt.csv")
    prism_pr = os.path.join(DATA, "expA_prism_mech.pathrtt.csv")
    prism_ep = os.path.join(DATA, "expA_prism_mech.epoch.csv")
    if not (os.path.exists(reps_pr) and os.path.exists(prism_ep)):
        print("[fig2] mechanism logs missing; skipping Fig2")
        return
    fig, (ax_sig, ax_cw) = plt.subplots(2, 1, figsize=(5.2, 6.0), sharex=True)

    # (a) signals. REPS+NSCC avg/floor from its pathrtt (binned); PRISM C_cc from epoch.
    bins = metrics.qdelay_bins(reps_pr, base_ns=13945, bin_us=20)
    if bins:
        t = [b[0] for b in bins]; mn = [b[1] for b in bins]; av = [b[2] for b in bins]
        ax_sig.plot(t, av, color=plot_style.COLORS["reps"], lw=2.0, label="REPS+NSCC avg delay")
        ax_sig.plot(t, mn, color=plot_style.COLORS["reps"], lw=1.3, ls=":", label="REPS+NSCC floor (ignored)")
    ep = metrics.parse_prism_epoch(prism_ep)
    if ep:
        te = [r["time_ns"] / 1000.0 for r in ep]; cc = [r["c_cc_ns"] / 1000.0 for r in ep]
        ax_sig.plot(te, cc, color=plot_style.COLORS["prism"], lw=2.0, label="PRISM floor C_cc")
    ax_sig.axhline(TARGET_US, color=plot_style.COLORS["target"], ls="--", lw=1.3, label="target")
    ax_sig.set_ylabel("Queuing delay (us)")
    ax_sig.set_title(f"Mechanism @ -failed={MECH_FAILED}", fontsize=11)
    ax_sig.grid(alpha=0.3); ax_sig.legend(fontsize=8)

    # (b) cwnd(t): mean cwnd across flows per 20us bin, for PRISM vs REPS+NSCC, from pathrtt.
    def cwnd_series(path):
        import collections as _c
        acc = _c.defaultdict(list)
        with open(path) as fh:
            for ln in fh:
                p = ln.strip().split(",")
                if len(p) < 6:
                    continue
                acc[int(p[0]) // 20000].append(int(p[5]))
        xs = sorted(acc)
        return [b * 20000 / 1000.0 for b in xs], [sum(acc[b]) / len(acc[b]) / 1024.0 for b in xs]
    tr, cr = cwnd_series(reps_pr)
    ax_cw.plot(tr, cr, color=plot_style.COLORS["reps"], lw=2.0, label="REPS+NSCC")
    if os.path.exists(prism_pr):
        tp, cp = cwnd_series(prism_pr)
        ax_cw.plot(tp, cp, color=plot_style.COLORS["prism"], lw=2.0, label="PRISM")
    ax_cw.set_ylabel("cwnd (KB, mean/flow)")
    ax_cw.set_xlabel("time (us)")
    ax_cw.grid(alpha=0.3); ax_cw.legend(fontsize=9)
    plt.tight_layout()
    plot_style.save(fig, "figA2_mechanism", FIGS)
    plt.close(fig)

    # cwnd-decrease events. FAIR comparison = same measure (pathrtt cwnd drops) for BOTH. We also
    # report PRISM's floor-driven epoch-MD count separately: it is NOT comparable to the per-ACK
    # cwnd-drop count, and most of PRISM's cwnd drops actually come from the reused NACK/loss/
    # quick_adapt machinery, not the floor decision -- so the fair counts are close.
    if not ep:
        print("[fig2] WARNING: prism epoch log empty -- PRISM epoch-MD count unreliable")
    reps_dec = metrics.count_cwnd_cuts_from_pathrtt(reps_pr)
    prism_dec = metrics.count_cwnd_cuts_from_pathrtt(prism_pr) if os.path.exists(prism_pr) else -1
    prism_epoch_md = sum(r["cut"] for r in ep)
    print(f"[fig2] cwnd-decrease events @failed={MECH_FAILED} (FAIR, per-ACK pathrtt): "
          f"PRISM={prism_dec}  REPS+NSCC={reps_dec}")
    print(f"[fig2] (PRISM floor-driven epoch MDs only: {prism_epoch_md} -- not comparable to the "
          f"per-ACK counts; most PRISM cwnd drops come from reused NACK/loss, not the floor)")

def _selftest():
    import tempfile, shutil
    global DATA
    d = tempfile.mkdtemp()
    DATA = d
    # one synthetic cell: ops, f0, s13 -> 2 flows, 32 Gbps, FCT 1ms
    for lab in ("ops", "reps", "prism"):
        for f in FAILED:
            for s in SEEDS:
                with open(os.path.join(d, f"expA_{lab}_f{f}_s{s}.flow.txt"), "w") as fh:
                    fh.write("0.000000000 Type FLOW_EVENT SrcID 1 Ev START FlowID 1 Flowsize 1000000\n")
                    fh.write("0.000000000 Type FLOW_EVENT SrcID 2 Ev START FlowID 2 Flowsize 3000000\n")
                    fh.write("0.001000000 Type FLOW_EVENT SrcID 1 Ev FINISH FlowID 1 Bytes 1000000 Pkts 1\n")
                    fh.write("0.001000000 Type FLOW_EVENT SrcID 2 Ev FINISH FlowID 2 Bytes 3000000 Pkts 1\n")
    a = _agg("ops")
    assert abs(a[0]["goodput"][0] - 32.0) < 1e-6, a[0]
    assert abs(a[0]["avg_fct"][0] - 1000.0) < 1e-6, a[0]   # 1ms = 1000us
    assert abs(a[0]["cr"][0] - 1.0) < 1e-9, a[0]
    shutil.rmtree(d)
    print("ok make_figs aggregation selftest")

def render():
    os.makedirs(FIGS, exist_ok=True)
    render_fig1()
    render_fig2()

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        render()
