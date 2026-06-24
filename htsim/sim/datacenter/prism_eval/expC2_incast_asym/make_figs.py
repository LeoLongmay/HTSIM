#!/usr/bin/env python3
"""expC2_incast_asym figures (self-contained: only metrics + plot_style, both committed).
Asymmetric structured incast (-failed): does PRISM (esp. @B) win when the incast has
reroutable fabric structure? Renders figC2a..g into ./figs from ./data.
  python3 make_figs.py --selftest   # synthetic aggregation self-check (no real data)
  python3 make_figs.py              # render all figures from ./data (missing cells -> nan/skip)
Tag scheme: expC2_{arm}_f{F}_n{N}_s{seed}.flow.txt  (see plan).
"""
import os, sys, math, statistics, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import metrics      # noqa: E402
import plot_style   # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

DATA = os.path.join(HERE, "data")
FIGS = os.path.join(HERE, "figs")

# (token, label, color_key, linestyle). Two PRISM lines share the green color, differ by style.
ARMS = [
    ("ops",       "OPS+NSCC",         "ops",    "-"),
    ("reps",      "REPS+NSCC",        "reps",   "-"),
    ("mnscc",     "REPS+MNSCC",       "mnscc",  "-"),
    ("strack",    "STrack",           "strack", "-"),
    ("prism_def", "PRISM (default)",  "prism",  "--"),
    ("prism_b",   "PRISM (B 7/10/2)", "prism",  "-"),
]
FAILEDS = [0, 2, 4, 8, 12]   # slice 1 x-axis (fan-in fixed 32)
FANINS  = [8, 32, 64]        # slice 2 x-axis (failed fixed 8)
CENTER_N, CENTER_F = 32, 8
SEEDS = [13, 14, 15, 16, 17]

BASE_NS = 13945              # base RTT (ns) for end-to-end queuing delay
TARGET_US_B = 10.0           # PRISM@B target_q_delay (T_cc) for the figC2d reference line
TS_PRISMB_CENTER = "expC2_ts_prismb_center"
TS_REPS_CENTER   = "expC2_ts_reps_center"
TS_PRISMB_FANIN  = {8: "expC2_ts_prismb_n8", 32: TS_PRISMB_CENTER, 64: "expC2_ts_prismb_n64"}

MSG_SIZES = [("128k", 128_000), ("512k", 512_000), ("2m", 2_000_000), ("8m", 8_000_000)]
MSG_SEEDS = [13, 14, 15]
TSPRAY_VALS = [5, 7, 10, 14, 20, 28]   # 14 = default center, 7 = B center
N_PERFLOW = 8                           # number of representative connections to plot

def _nan_mean(vals):
    vals = [v for v in vals if v is not None and not (isinstance(v, float) and math.isnan(v))]
    return statistics.mean(vals) if vals else float("nan")

def mean_over_seeds(metric_fn, tagfn, seeds):
    """Mean of metric_fn(flow_path) over seeds for one cell; missing files skipped (nan if all miss)."""
    out = []
    for s in seeds:
        fp = os.path.join(DATA, tagfn(s) + ".flow.txt")
        if os.path.exists(fp):
            try:
                out.append(metric_fn(fp))
            except Exception:
                pass
    return _nan_mean(out)

def _goodput(fp):    return metrics.aggregate_goodput_gbps(fp)
def _avgfct_us(fp):  return metrics.fct_stats(fp)["avg_s"] * 1e6
def _p99fct_us(fp):  return metrics.fct_stats(fp)["p99_s"] * 1e6

def _render_perf_panels(xs, xlabel, cellfn, stem, title):
    """3-panel (goodput | avg FCT | p99 FCT) vs xs; one line per arm. cellfn(arm_token, x) -> tagfn."""
    plot_style.apply_style(13)
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 3.6))
    panels = [("aggregate goodput (Gbps)", _goodput),
              ("avg FCT (us)", _avgfct_us),
              ("p99 FCT (us)", _p99fct_us)]
    for ax, (ylab, mfn) in zip(axes, panels):
        for tok, lab, ck, ls in ARMS:
            ys = [mean_over_seeds(mfn, cellfn(tok, x), SEEDS) for x in xs]
            ax.plot(xs, ys, ls, marker="o", ms=5, lw=2.0,
                    color=plot_style.COLORS[ck], label=lab)
        ax.set_xlabel(xlabel); ax.set_ylabel(ylab); ax.grid(alpha=0.3)
    axes[1].set_title(title)
    axes[0].legend(fontsize=8, ncol=2, loc="best")
    fig.tight_layout()
    plot_style.save(fig, stem, FIGS); plt.close(fig)

def render_main_failed():
    cellfn = lambda tok, F: (lambda s: f"expC2_{tok}_f{F}_n{CENTER_N}_s{s}")
    _render_perf_panels(FAILEDS, "failed core->agg downlinks", cellfn,
                        "figC2a_main_failed", f"asymmetric incast (fan-in {CENTER_N}, 2MB)")

def render_main_fanin():
    cellfn = lambda tok, N: (lambda s: f"expC2_{tok}_f{CENTER_F}_n{N}_s{s}")
    _render_perf_panels(FANINS, "incast fan-in (senders : 1)", cellfn,
                        "figC2b_main_fanin", f"asymmetric incast (failed {CENTER_F}, 2MB)")

def render_qdelay_time():
    """figC2c: two panels, both PRISM@B vs REPS+NSCC at the center cell.
    Left  = last-hop switch queue delay (tor_downqueue), Right = end-to-end queuing delay (PATHRTT)."""
    plot_style.apply_style(13)
    fig, (axl, axr) = plt.subplots(1, 2, figsize=(11, 3.8))
    pairs = [(TS_PRISMB_CENTER, "PRISM (B)", "prism", "-"),
             (TS_REPS_CENTER,   "REPS+NSCC", "reps", "-")]
    # left: switch queue delay
    for tag, lab, ck, ls in pairs:
        qp = os.path.join(DATA, tag + ".q.txt")
        ip = os.path.join(DATA, tag + ".idmap")
        if os.path.exists(qp) and os.path.exists(ip):
            ser = metrics.tor_downqueue_delay_series(qp, ip, 0)
            if ser:
                ts = [t * 1e6 for t, _ in ser]; qs = [q for _, q in ser]
                axl.plot(ts, qs, ls, lw=1.6, color=plot_style.COLORS[ck], label=lab)
    axl.set_xlabel("time (us)"); axl.set_ylabel("last-hop switch queue delay (us)")
    axl.set_title("switch queue (LS->DST0)"); axl.legend(fontsize=9); axl.grid(alpha=0.3)
    # right: end-to-end queuing delay (binned mean)
    for tag, lab, ck, ls in pairs:
        prp = os.path.join(DATA, tag + ".pathrtt.csv")
        if os.path.exists(prp):
            bins = metrics.qdelay_bins(prp, base_ns=BASE_NS, bin_us=20)
            axr.plot([b[0] for b in bins], [b[2] for b in bins], ls, lw=1.6,
                     color=plot_style.COLORS[ck], label=lab)
    axr.set_xlabel("time (us)"); axr.set_ylabel("end-to-end queuing delay (us)")
    axr.set_title("end-to-end (PATHRTT)"); axr.legend(fontsize=9); axr.grid(alpha=0.3)
    fig.tight_layout()
    plot_style.save(fig, "figC2c_qdelay_time", FIGS); plt.close(fig)

def render_qdelay_fanin():
    """figC2d: PRISM@B end-to-end queuing delay vs time, one line per fan-in {8,32,64};
    horizontal reference at PRISM@B's target_q_delay (T_cc=10us)."""
    plot_style.apply_style(14)
    fig, ax = plt.subplots(figsize=(6.6, 4.0))
    shades = {8: "#9ecae1", 32: "#4292c6", 64: "#08519c"}
    for N in FANINS:
        prp = os.path.join(DATA, TS_PRISMB_FANIN[N] + ".pathrtt.csv")
        if os.path.exists(prp):
            bins = metrics.qdelay_bins(prp, base_ns=BASE_NS, bin_us=20)
            ax.plot([b[0] for b in bins], [b[2] for b in bins], "-", lw=1.8,
                    color=shades[N], label=f"{N} : 1")
    ax.axhline(TARGET_US_B, color="0.5", ls=":", lw=1.4, label=f"target T_cc={TARGET_US_B:g}us")
    ax.set_xlabel("time (us)"); ax.set_ylabel("end-to-end queuing delay (us)")
    ax.set_title("PRISM@B incast queue stability vs fan-in"); ax.legend(fontsize=10); ax.grid(alpha=0.3)
    fig.tight_layout()
    plot_style.save(fig, "figC2d_qdelay_fanin", FIGS); plt.close(fig)

def render_perflow_goodput():
    """figC2e: two panels (PRISM@B | REPS+NSCC) at the center; up to N_PERFLOW per-connection
    goodput-over-time lines (label Flow 1..N), STrack Fig.17/18 style."""
    plot_style.apply_style(13)
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8), sharey=True)
    panels = [(TS_PRISMB_CENTER, "PRISM (B)"), (TS_REPS_CENTER, "REPS+NSCC")]
    for ax, (tag, title) in zip(axes, panels):
        sp = os.path.join(DATA, tag + ".sink.txt")
        if os.path.exists(sp):
            series = metrics.sink_rate_series(sp)
            ids = sorted(series.keys())[:N_PERFLOW]
            for i, sid in enumerate(ids):
                ts = [t * 1e6 for t, _ in series[sid]]; rs = [r for _, r in series[sid]]
                ax.plot(ts, rs, lw=1.2, label=f"Flow {i+1}")
        ax.set_xlabel("time (us)"); ax.set_title(title); ax.grid(alpha=0.3)
    axes[0].set_ylabel("per-flow goodput (Gbps)")
    axes[1].legend(fontsize=7, ncol=2, loc="upper right")
    axes[0].legend(fontsize=7, ncol=2, loc="upper right")
    fig.tight_layout()
    plot_style.save(fig, "figC2e_perflow_goodput", FIGS); plt.close(fig)

def render_maxfct_msgsize():
    """figC2f: max FCT (=CCT, us) vs message size (log x), one line per arm; center fan-in/failed."""
    plot_style.apply_style(14)
    fig, ax = plt.subplots(figsize=(7.0, 4.2))
    xs = [b for _, b in MSG_SIZES]
    for tok, lab, ck, ls in ARMS:
        ys = []
        for label, _ in MSG_SIZES:
            tagfn = lambda s, _l=label, _t=tok: f"expC2_{_t}_msg{_l}_s{s}"
            ys.append(mean_over_seeds(lambda fp: metrics.fct_stats(fp)["max_s"] * 1e6, tagfn, MSG_SEEDS))
        ax.plot(xs, ys, ls, marker="o", ms=5, lw=2.0, color=plot_style.COLORS[ck], label=lab)
    ax.set_xscale("log"); ax.set_xticks(xs)
    ax.set_xticklabels([l for l, _ in MSG_SIZES])
    ax.set_xlabel("message size"); ax.set_ylabel("max FCT / CCT (us)")
    ax.set_title(f"asymmetric incast (fan-in {CENTER_N}, failed {CENTER_F})")
    ax.legend(fontsize=8, ncol=2); ax.grid(alpha=0.3)
    fig.tight_layout()
    plot_style.save(fig, "figC2f_maxfct_msgsize", FIGS); plt.close(fig)

def render_tspray():
    """figC2g: PRISM goodput | avg FCT vs T_spray micro-sweep at the center cell. Mark default(14)
    and B(7); overlay REPS+NSCC center mean as a horizontal reference."""
    plot_style.apply_style(13)
    fig, (axg, axf) = plt.subplots(1, 2, figsize=(11, 3.8))
    good = [mean_over_seeds(_goodput, (lambda s, _v=v: f"expC2_tspray{_v}_s{s}"), SEEDS) for v in TSPRAY_VALS]
    fcts = [mean_over_seeds(_avgfct_us, (lambda s, _v=v: f"expC2_tspray{_v}_s{s}"), SEEDS) for v in TSPRAY_VALS]
    ref_g = mean_over_seeds(_goodput, lambda s: f"expC2_reps_f{CENTER_F}_n{CENTER_N}_s{s}", SEEDS)
    ref_f = mean_over_seeds(_avgfct_us, lambda s: f"expC2_reps_f{CENTER_F}_n{CENTER_N}_s{s}", SEEDS)
    for ax, ys, ref, ylab in [(axg, good, ref_g, "aggregate goodput (Gbps)"),
                              (axf, fcts, ref_f, "avg FCT (us)")]:
        ax.plot(TSPRAY_VALS, ys, "-o", lw=2.0, color=plot_style.COLORS["prism"], label="PRISM")
        if not math.isnan(ref):
            ax.axhline(ref, color=plot_style.COLORS["reps"], ls="--", lw=1.5, label="REPS+NSCC")
        ax.axvline(14, color="0.6", ls=":", lw=1.2); ax.axvline(7, color="tab:green", ls=":", lw=1.2)
        ax.set_xlabel("T_spray (us)  [default=14, B=7]"); ax.set_ylabel(ylab)
        ax.legend(fontsize=9); ax.grid(alpha=0.3)
    fig.suptitle(f"PRISM T_spray sweep (fan-in {CENTER_N}, failed {CENTER_F})", fontsize=12)
    fig.tight_layout()
    plot_style.save(fig, "figC2g_tspray", FIGS); plt.close(fig)

# ---- selftest: synthesize a tiny matrix and check aggregation math ----
def _write_flow(path, flows):
    """flows: list of (srcid, start_s, finish_s, bytes)."""
    with open(path, "w") as fh:
        for sid, t0, t1, b in flows:
            fh.write(f"{t0:.9f} Type FLOW_EVENT SrcID {sid} Ev START FlowID {sid} Flowsize {b}\n")
            fh.write(f"{t1:.9f} Type FLOW_EVENT SrcID {sid} Ev FINISH FlowID {sid} Bytes {b} Pkts 1\n")

def selftest():
    global DATA, FIGS
    d = tempfile.mkdtemp()
    DATA = os.path.join(d, "data"); FIGS = os.path.join(d, "figs")
    os.makedirs(DATA); os.makedirs(FIGS)
    # one cell for arm 'reps' at f8/n32/seed13: 2 flows, 1,000,000 B each, makespan 0.001s
    #   aggregate goodput = 2e6*8/0.001/1e9 = 16 Gbps ; avg FCT = 1000 us
    _write_flow(os.path.join(DATA, "expC2_reps_f8_n32_s13.flow.txt"),
                [(1, 0.0, 0.001, 1_000_000), (2, 0.0, 0.001, 1_000_000)])
    g = mean_over_seeds(_goodput, lambda s: "expC2_reps_f8_n32_s13", [13])
    a = mean_over_seeds(_avgfct_us, lambda s: "expC2_reps_f8_n32_s13", [13])
    assert abs(g - 16.0) < 1e-6, g
    assert abs(a - 1000.0) < 1e-6, a
    # missing cell -> nan, must not raise
    assert math.isnan(mean_over_seeds(_goodput, lambda s: "nope", [13]))
    # render must not crash with partial data
    render_main_failed(); render_main_fanin()
    assert os.path.exists(os.path.join(FIGS, "figC2a_main_failed.png"))
    assert os.path.exists(os.path.join(FIGS, "figC2b_main_fanin.png"))
    # synthetic time-series data for figC2c/d
    with open(os.path.join(DATA, TS_PRISMB_CENTER + ".idmap"), "w") as fh:
        fh.write("165 LS0->DST0(0)\n")
    with open(os.path.join(DATA, TS_PRISMB_CENTER + ".q.txt"), "w") as fh:
        fh.write("0.000004000 Type QUEUE_APPROX ID 165 Ev RANGE LastQ 41500 MinQ 0 MaxQ 41500\n")
        fh.write("0.000008000 Type QUEUE_APPROX ID 165 Ev RANGE LastQ 0 MinQ 0 MaxQ 0\n")
    with open(os.path.join(DATA, TS_REPS_CENTER + ".idmap"), "w") as fh:
        fh.write("165 LS0->DST0(0)\n")
    with open(os.path.join(DATA, TS_REPS_CENTER + ".q.txt"), "w") as fh:
        fh.write("0.000004000 Type QUEUE_APPROX ID 165 Ev RANGE LastQ 83000 MinQ 0 MaxQ 83000\n")
    for tag in (TS_PRISMB_CENTER, TS_REPS_CENTER, "expC2_ts_prismb_n8", "expC2_ts_prismb_n64"):
        with open(os.path.join(DATA, tag + ".pathrtt.csv"), "w") as fh:
            fh.write("1000,7,0,15000,0,100000\n")   # t=1us, q=15000-13945=1055ns
            fh.write("5000,7,0,19000,0,100000\n")   # t=5us, q=5055ns
    render_qdelay_time(); render_qdelay_fanin()
    assert os.path.exists(os.path.join(FIGS, "figC2c_qdelay_time.png"))
    assert os.path.exists(os.path.join(FIGS, "figC2d_qdelay_fanin.png"))
    # synthetic sink for figC2e (2 connections at center)
    for tag in (TS_PRISMB_CENTER, TS_REPS_CENTER):
        with open(os.path.join(DATA, tag + ".sink.txt"), "w") as fh:
            for t in ("0.000500000", "0.001000000"):
                fh.write(f"{t} Type UEC_SINK ID 100 Ev RATE CAck 1 ReorderBuffer 0 Rate 40000000000\n")
                fh.write(f"{t} Type UEC_SINK ID 101 Ev RATE CAck 1 ReorderBuffer 0 Rate 10000000000\n")
    # synthetic msg-size + tspray cells (one seed each)
    _write_flow(os.path.join(DATA, "expC2_reps_msg2m_s13.flow.txt"),
                [(1, 0.0, 0.002, 2_000_000)])
    _write_flow(os.path.join(DATA, "expC2_tspray7_s13.flow.txt"),
                [(1, 0.0, 0.001, 2_000_000), (2, 0.0, 0.001, 2_000_000)])
    render_perflow_goodput(); render_maxfct_msgsize(); render_tspray()
    for stem in ("figC2e_perflow_goodput", "figC2f_maxfct_msgsize", "figC2g_tspray"):
        assert os.path.exists(os.path.join(FIGS, stem + ".png")), stem
    print("ok selftest: aggregation + figC2a-g render")

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        os.makedirs(FIGS, exist_ok=True)
        render_main_failed()
        render_main_fanin()
        render_qdelay_time()
        render_qdelay_fanin()
        render_perflow_goodput()
        render_maxfct_msgsize()
        render_tspray()
        print("wrote figC2a_main_failed, figC2b_main_fanin, figC2c_qdelay_time, figC2d_qdelay_fanin, figC2e_perflow_goodput, figC2f_maxfct_msgsize, figC2g_tspray")
