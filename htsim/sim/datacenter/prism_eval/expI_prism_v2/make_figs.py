#!/usr/bin/env python3
"""expI_prism_v2 figures (self-contained: only metrics + plot_style, both committed).
Validates PRISM v2 (A1 smooth + A2 hysteresis + C engage-gate): recovers the f0/incast
cost, stabilises the queue, keeps the asymmetric-f8 win.
Renders figI_a..e into ./figs from ./data.
  python3 make_figs.py --selftest   # synthetic self-check (no real data, exits 0)
  python3 make_figs.py              # render all figures from ./data (missing -> nan/skip)
Tag scheme (see repro.sh):
  flow:   expI_{incN32,incN8,incN64,m2m}_f{F}_{arm}_s{seed}.flow.txt
  ts:     expI_ts_{ref,bold,v2}_{inc,m2m}.q.txt + .idmap + .epoch.csv + .pathrtt.csv
  sweeps: expI_sw_eng{24,28,34}_{inc,m2m}_s{seed}.flow.txt
          expI_sw_beta{0.15,0.3,0.5}_inc_s{seed}.flow.txt
          expI_sw_ebeta{0.1,0.2,0.3}_{inc,m2m}_s{seed}.flow.txt
PRISM_EPOCH CSV cols (0-based): time0,flow1,base2,ccc3,cspray4,region5,cwnd6,samples7,cut8,engaged9,...
"""
import os, sys, math, statistics, tempfile, csv
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import metrics      # noqa: E402
import plot_style   # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

DATA = os.path.join(HERE, "data")
FIGS = os.path.join(HERE, "figs")

SEEDS = [13, 14, 15, 16, 17]
BASE_NS = 13945  # base RTT (ns) for end-to-end queuing delay

# (token, display_label)
ARMS = [
    ("ref",   "REPS+NSCC"),
    ("bold",  "PRISM@B (old)"),
    ("a1",    "v2-A1"),
    ("a1a2",  "v2-A1A2"),
    ("v2",    "v2-full"),
]

# Color keys per arm token (mapping into plot_style.COLORS)
ARM_COLOR = {
    "ref":   "reps",
    "bold":  "prism",
    "a1":    "mswift",
    "a1a2":  "strack",
    "v2":    "ops",
}

# Line styles per arm token
ARM_LS = {
    "ref":   "-",
    "bold":  "--",
    "a1":    "-.",
    "a1a2":  ":",
    "v2":    "-",
}

# Marker per arm token
ARM_MARKER = {
    "ref":   "o",
    "bold":  "s",
    "a1":    "^",
    "a1a2":  "D",
    "v2":    "P",
}


# ---- helpers ----

def _nan_mean(vals):
    vals = [v for v in vals if v is not None and not (isinstance(v, float) and math.isnan(v))]
    return statistics.mean(vals) if vals else float("nan")


def mean_over_seeds(metric_fn, tagfn, seeds):
    """Mean of metric_fn(flow_path) over seeds; missing files silently skipped (nan if all miss)."""
    out = []
    for s in seeds:
        fp = os.path.join(DATA, tagfn(s) + ".flow.txt")
        if os.path.exists(fp):
            try:
                out.append(metric_fn(fp))
            except Exception:
                pass
    return _nan_mean(out)


def _goodput(fp):   return metrics.aggregate_goodput_gbps(fp)
def _avgfct_us(fp): return metrics.fct_stats(fp)["avg_s"] * 1e6


# ---- renderer 1: headline ----

def render_headline():
    """figI_a_headline: grouped bars — goodput + avg FCT for {ref, bold, v2}
    across {m2m f0, m2m f8, incast n32 f8}. Do-no-harm + keep-win story."""
    plot_style.apply_style(12)
    # conditions (label, tagfn_factory for arm)
    CONDITIONS = [
        ("m2m f=0",      lambda tok: (lambda s, _t=tok: f"expI_m2m_f0_{_t}_s{s}")),
        ("m2m f=8",      lambda tok: (lambda s, _t=tok: f"expI_m2m_f8_{_t}_s{s}")),
        ("incast n32 f=8", lambda tok: (lambda s, _t=tok: f"expI_incN32_f8_{_t}_s{s}")),
    ]
    # arms for headline: ref, bold, v2 only
    HL_ARMS = [("ref", "REPS+NSCC"), ("bold", "PRISM@B (old)"), ("v2", "v2-full")]

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.0))
    n_cond = len(CONDITIONS)
    n_arm = len(HL_ARMS)
    width = 0.22
    xs = list(range(n_cond))
    offsets = [(i - (n_arm - 1) / 2.0) * width for i in range(n_arm)]

    panels = [("aggregate goodput (Gbps)", _goodput),
              ("avg FCT (us)",             _avgfct_us)]

    for ax, (ylab, mfn) in zip(axes, panels):
        for i, (tok, lab) in enumerate(HL_ARMS):
            ys = []
            for _, cfac in CONDITIONS:
                ys.append(mean_over_seeds(mfn, cfac(tok), SEEDS))
            ck = ARM_COLOR[tok]
            color = plot_style.COLORS.get(ck, "tab:gray")
            bars = ax.bar([x + offsets[i] for x in xs], ys,
                          width=width * 0.92, label=lab,
                          color=color, alpha=0.85, edgecolor="white")
        ax.set_xticks(xs)
        ax.set_xticklabels([c for c, _ in CONDITIONS], fontsize=10)
        ax.set_ylabel(ylab)
        ax.grid(axis="y", alpha=0.3)
        ax.set_axisbelow(True)

    axes[0].legend(fontsize=9, loc="best")
    axes[0].set_title("aggregate goodput")
    axes[1].set_title("avg FCT")
    fig.suptitle("PRISM v2 headline: do-no-harm + keep-win", fontsize=12)
    fig.tight_layout()
    plot_style.save(fig, "figI_a_headline", FIGS)
    plt.close(fig)


# ---- renderer 2: queue stability ----

def render_queue_stability():
    """figI_b_queue_stability: incast f8 last-hop queue delay vs time for ref/bold/v2.
    Source: expI_ts_*_inc.queue + .idmap via tor_downqueue_delay_series.
    Annotates each curve with sd + mean|Δ| jitter."""
    plot_style.apply_style(12)
    fig, ax = plt.subplots(figsize=(8, 4.2))

    TS_ARMS = [("ref", "REPS+NSCC"), ("bold", "PRISM@B (old)"), ("v2", "v2-full")]
    for tok, lab in TS_ARMS:
        qp  = os.path.join(DATA, f"expI_ts_{tok}_inc.q.txt")
        ip  = os.path.join(DATA, f"expI_ts_{tok}_inc.idmap")
        if not (os.path.exists(qp) and os.path.exists(ip)):
            continue
        ser = metrics.tor_downqueue_delay_series(qp, ip, 0)
        if not ser:
            continue
        ts = [t * 1e6 for t, _ in ser]
        qs = [q for _, q in ser]
        color = plot_style.COLORS.get(ARM_COLOR[tok], "tab:gray")
        ax.plot(ts, qs, ARM_LS[tok], lw=1.6, color=color, label=lab)
        # annotate: sd + mean |Δ| jitter
        if len(qs) >= 2:
            sd = statistics.stdev(qs)
            diffs = [abs(qs[i] - qs[i - 1]) for i in range(1, len(qs))]
            mean_jitter = statistics.mean(diffs)
            ax.annotate(f"sd={sd:.1f}us\njit={mean_jitter:.1f}us",
                        xy=(ts[-1], qs[-1]), xytext=(5, 0),
                        textcoords="offset points", fontsize=7,
                        color=color, va="center")

    ax.set_xlabel("time (us)")
    ax.set_ylabel("last-hop switch queue delay (us)")
    ax.set_title("queue stability — incast n32 f=8 (time-series run, seed 13)")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    plot_style.save(fig, "figI_b_queue_stability", FIGS)
    plt.close(fig)


# ---- renderer 3: engaged fraction ----

def _read_engaged_fraction_bins(epoch_csv, bin_us=20):
    """Read expI_ts_v2_*.epoch.csv; col 9 = engaged flag (1=engaged, 0=disengaged/NSCC).
    (col 5 = region, which is -1 on a disengaged epoch — do NOT use col 5 here.)
    Return [(t_mid_us, frac_engaged), ...] binned at bin_us resolution.
    Robust: skips rows with fewer than 10 columns."""
    bin_ns = int(bin_us * 1000)
    acc_engaged = {}
    acc_total   = {}
    with open(epoch_csv) as fh:
        for ln in fh:
            p = ln.strip().split(",")
            if len(p) < 10:
                continue
            try:
                t_ns    = int(p[0])
                engaged = int(p[9])   # col 9: 1 = engaged, 0 = disengaged (NSCC mode)
            except ValueError:
                continue
            b = t_ns // bin_ns
            acc_total[b]   = acc_total.get(b, 0) + 1
            acc_engaged[b] = acc_engaged.get(b, 0) + (1 if engaged == 1 else 0)
    out = []
    for b in sorted(acc_total):
        t_mid = (b * bin_ns + bin_ns / 2) / 1000.0
        frac  = acc_engaged[b] / acc_total[b]
        out.append((t_mid, frac))
    return out


def render_engaged_fraction():
    """figI_c_engaged_fraction: engaged-fraction over time (20us bins) from
    expI_ts_v2_inc.epoch.csv and expI_ts_v2_m2m.epoch.csv.
    Expects incast ≈ disengaged, m2m ≈ engaged."""
    plot_style.apply_style(12)
    fig, ax = plt.subplots(figsize=(8, 4.0))

    SERIES = [
        ("expI_ts_v2_inc.epoch.csv",  "incast (expect ≈0)",  "reps"),
        ("expI_ts_v2_m2m.epoch.csv",  "m2m (expect ≈1)",     "prism"),
    ]
    for fname, lab, ck in SERIES:
        fp = os.path.join(DATA, fname)
        if not os.path.exists(fp):
            continue
        bins = _read_engaged_fraction_bins(fp, bin_us=20)
        if not bins:
            continue
        ts   = [b[0] for b in bins]
        fracs = [b[1] for b in bins]
        color = plot_style.COLORS.get(ck, "tab:gray")
        ax.plot(ts, fracs, "-", lw=1.8, color=color, label=lab)

    ax.set_xlabel("time (us)")
    ax.set_ylabel("fraction of epochs engaged")
    ax.set_ylim(-0.05, 1.05)
    ax.set_title("PRISM v2 engage-gate: engaged fraction over time (seed 13)")
    ax.legend(fontsize=10)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    plot_style.save(fig, "figI_c_engaged_fraction", FIGS)
    plt.close(fig)


# ---- renderer 4: ablation ----

def render_ablation():
    """figI_d_ablation: incast n32 f8 goodput + avg FCT + queue-sd bars for
    {ref, a1, a1a2, v2}. Shows which ablation components matter."""
    plot_style.apply_style(12)
    ABL_ARMS = [("ref", "REPS+NSCC"), ("a1", "v2-A1"), ("a1a2", "v2-A1A2"), ("v2", "v2-full")]

    # goodput + avg FCT from flow files
    goodputs = []
    avgfcts  = []
    for tok, _ in ABL_ARMS:
        tagfn = lambda s, _t=tok: f"expI_incN32_f8_{_t}_s{s}"
        goodputs.append(mean_over_seeds(_goodput,   tagfn, SEEDS))
        avgfcts.append( mean_over_seeds(_avgfct_us, tagfn, SEEDS))

    # queue-sd from the time-series runs (only ref, bold, v2 have ts runs; a1/a1a2 absent)
    TS_ARMS_SET = {"ref", "bold", "v2"}
    queue_sds = []
    for tok, _ in ABL_ARMS:
        if tok not in TS_ARMS_SET:
            queue_sds.append(float("nan"))
            continue
        qp = os.path.join(DATA, f"expI_ts_{tok}_inc.q.txt")
        ip = os.path.join(DATA, f"expI_ts_{tok}_inc.idmap")
        if os.path.exists(qp) and os.path.exists(ip):
            ser = metrics.tor_downqueue_delay_series(qp, ip, 0)
            if ser and len(ser) >= 2:
                queue_sds.append(statistics.stdev([q for _, q in ser]))
            else:
                queue_sds.append(float("nan"))
        else:
            queue_sds.append(float("nan"))

    fig, axes = plt.subplots(1, 3, figsize=(12, 4.2))
    labels = [lab for _, lab in ABL_ARMS]
    xs = list(range(len(ABL_ARMS)))
    colors = [plot_style.COLORS.get(ARM_COLOR[tok], "tab:gray") for tok, _ in ABL_ARMS]

    for ax, ys, ylab, title in [
        (axes[0], goodputs,  "aggregate goodput (Gbps)",    "goodput"),
        (axes[1], avgfcts,   "avg FCT (us)",                "avg FCT"),
        (axes[2], queue_sds, "queue delay stdev (us)",      "queue stability"),
    ]:
        ax.bar(xs, ys, color=colors, alpha=0.85, edgecolor="white")
        ax.set_xticks(xs)
        ax.set_xticklabels(labels, fontsize=9, rotation=15, ha="right")
        ax.set_ylabel(ylab)
        ax.set_title(title)
        ax.grid(axis="y", alpha=0.3)
        ax.set_axisbelow(True)

    fig.suptitle("Ablation: incast n32 f=8", fontsize=12)
    fig.tight_layout()
    plot_style.save(fig, "figI_d_ablation", FIGS)
    plt.close(fig)


# ---- renderer 5: sweeps ----

def render_sweeps():
    """figI_e_sweeps: sensitivity sweep lines.
    Row 1: goodput (incast) and goodput (m2m) vs engage_spread {24,28,34}.
    Row 2: goodput (incast) and goodput (m2m) vs smooth_beta {0.15,0.3,0.5}.
    Row 3: goodput (incast) and goodput (m2m) vs engage_beta {0.1,0.2,0.3}.
    Each sub-panel has a REPS+NSCC horizontal reference."""
    plot_style.apply_style(11)

    ENG_VALS  = [24, 28, 34]
    BETA_VALS = [0.15, 0.3, 0.5]
    EBETA_VALS = [0.1, 0.2, 0.3]

    ref_inc_g = mean_over_seeds(_goodput, lambda s: f"expI_incN32_f8_ref_s{s}", SEEDS)
    ref_m2m_g = mean_over_seeds(_goodput, lambda s: f"expI_m2m_f8_ref_s{s}",   SEEDS)

    fig, axes = plt.subplots(3, 2, figsize=(11, 10))

    def _sweep_line(ax, xs, tagfn_inc_or_m2m, x_label, x_ticks, ref_val, title):
        ys = [mean_over_seeds(_goodput, tagfn_inc_or_m2m(x), SEEDS) for x in xs]
        ax.plot(x_ticks, ys, "-o", lw=2.0, ms=6,
                color=plot_style.COLORS["prism"], label="PRISM v2")
        if not math.isnan(ref_val):
            ax.axhline(ref_val, color=plot_style.COLORS["reps"],
                       ls="--", lw=1.5, label="REPS+NSCC ref")
        ax.set_xlabel(x_label)
        ax.set_ylabel("aggregate goodput (Gbps)")
        ax.set_title(title)
        ax.legend(fontsize=8, loc="best")
        ax.grid(alpha=0.3)

    # row 0: engage_spread — incast
    _sweep_line(axes[0, 0], ENG_VALS,
                lambda v: (lambda s, _v=v: f"expI_sw_eng{_v}_inc_s{s}"),
                "engage_spread", ENG_VALS, ref_inc_g,
                "engage_spread — incast")
    # row 0: engage_spread — m2m
    _sweep_line(axes[0, 1], ENG_VALS,
                lambda v: (lambda s, _v=v: f"expI_sw_eng{_v}_m2m_s{s}"),
                "engage_spread", ENG_VALS, ref_m2m_g,
                "engage_spread — m2m")

    # row 1: smooth_beta — incast
    _sweep_line(axes[1, 0], BETA_VALS,
                lambda v: (lambda s, _v=v: f"expI_sw_beta{_v}_inc_s{s}"),
                "smooth_beta", BETA_VALS, ref_inc_g,
                "smooth_beta — incast")
    # row 1: smooth_beta — m2m: repro.sh only sweeps smooth_beta on incast; hide this panel
    axes[1, 1].set_visible(False)

    # row 2: engage_beta — incast
    _sweep_line(axes[2, 0], EBETA_VALS,
                lambda v: (lambda s, _v=v: f"expI_sw_ebeta{_v}_inc_s{s}"),
                "engage_beta", EBETA_VALS, ref_inc_g,
                "engage_beta — incast")
    # row 2: engage_beta — m2m
    _sweep_line(axes[2, 1], EBETA_VALS,
                lambda v: (lambda s, _v=v: f"expI_sw_ebeta{_v}_m2m_s{s}"),
                "engage_beta", EBETA_VALS, ref_m2m_g,
                "engage_beta — m2m")

    fig.suptitle("PRISM v2 sensitivity sweeps (incast n32 f=8 / m2m f=8)", fontsize=12)
    fig.tight_layout()
    plot_style.save(fig, "figI_e_sweeps", FIGS)
    plt.close(fig)


# ---- renderer 6: OAT sensitivity (figI_f) ----

def render_sensitivity():
    """figI_f_sensitivity: 2x2 grid, one panel per OAT param (β, h, ρ, m).
    Each panel: x=param values, y=aggregate goodput as % of REPS+NSCC baseline.
    3 lines per panel: m2m f=0, incast n32 f=8, m2m f=8.
    Baseline (100%) = mean goodput of expI_{scen}_ref_s{13,14,15}.flow.txt.
    Data: expI_sens_{param}_{val}_{scen}_s{seed}.flow.txt.
    """
    plot_style.apply_style(11)

    SENS_SEEDS = [13, 14, 15]

    # Baselines (100% reference) per scenario
    ref_f0  = mean_over_seeds(_goodput, lambda s: f"expI_m2m_f0_ref_s{s}",    SENS_SEEDS)
    ref_f8  = mean_over_seeds(_goodput, lambda s: f"expI_m2m_f8_ref_s{s}",    SENS_SEEDS)
    ref_inc = mean_over_seeds(_goodput, lambda s: f"expI_incN32_f8_ref_s{s}", SENS_SEEDS)

    # (param_token, param_title, values_list)
    PARAMS = [
        ("beta", r"smooth_beta $\beta$",        [0.15, 0.3, 0.5]),
        ("h",    r"hysteresis $h$",              [0.15, 0.25, 0.4]),
        ("rho",  r"disengage_ratio $\rho$",      [0.6, 0.7, 0.8]),
        ("m",    r"engage_mult $m$",             [1.7, 2.0, 2.4]),
    ]

    # Scenarios: (scen_token, display_label, ref_goodput, color_key, marker)
    SCENS = [
        ("f0",  "m2m f=0",       ref_f0,  "reps",  "o"),
        ("inc", "incast n32 f=8", ref_inc, "prism", "s"),
        ("f8",  "m2m f=8",       ref_f8,  "strack", "^"),
    ]

    fig, axes = plt.subplots(2, 2, figsize=(10, 8))
    axes_flat = [axes[0, 0], axes[0, 1], axes[1, 0], axes[1, 1]]

    for ax, (param, title, vals) in zip(axes_flat, PARAMS):
        for scen, lab, ref_g, ck, marker in SCENS:
            color = plot_style.COLORS.get(ck, "tab:gray")
            ys = []
            for v in vals:
                # format val: use float string as it appears in tag
                vstr = str(v)
                g = mean_over_seeds(_goodput,
                                    lambda s, _p=param, _v=vstr, _sc=scen:
                                        f"expI_sens_{_p}_{_v}_{_sc}_s{s}",
                                    SENS_SEEDS)
                if not math.isnan(ref_g) and not math.isnan(g):
                    ys.append(g / ref_g * 100.0)
                else:
                    ys.append(float("nan"))
            ax.plot(vals, ys, "-" + marker, lw=1.8, ms=6, color=color, label=lab)
        ax.axhline(100.0, color="black", ls="--", lw=1.2, alpha=0.6, label="baseline (100%)")
        ax.set_xlabel("parameter value")
        ax.set_ylabel("goodput (% of REPS+NSCC)")
        ax.set_title(title)
        ax.set_xticks(vals)
        ax.legend(fontsize=8, loc="best")
        ax.grid(alpha=0.3)

    fig.suptitle("PRISM v2 parameter sensitivity (goodput % of REPS+NSCC; flat ⇒ robust)",
                 fontsize=12)
    fig.tight_layout()
    plot_style.save(fig, "figI_f_sensitivity", FIGS)
    plt.close(fig)


# ---- selftest ----

def _write_flow(path, flows):
    """flows: list of (srcid, start_s, finish_s, bytes)."""
    with open(path, "w") as fh:
        for sid, t0, t1, b in flows:
            fh.write(f"{t0:.9f} Type FLOW_EVENT SrcID {sid} Ev START FlowID {sid} Flowsize {b}\n")
            fh.write(f"{t1:.9f} Type FLOW_EVENT SrcID {sid} Ev FINISH FlowID {sid} Bytes {b} Pkts 1\n")


def selftest():
    global DATA, FIGS
    d = tempfile.mkdtemp()
    DATA = os.path.join(d, "data")
    FIGS = os.path.join(d, "figs")
    os.makedirs(DATA); os.makedirs(FIGS)

    # ---- build synthetic flow files for headline + ablation ----
    # 2 flows, 1MB each, makespan 0.001s -> goodput=16Gbps, avg FCT=1000us
    for tok in ("ref", "bold", "a1", "a1a2", "v2"):
        for f in (0, 8):
            for s in SEEDS:
                _write_flow(
                    os.path.join(DATA, f"expI_m2m_f{f}_{tok}_s{s}.flow.txt"),
                    [(1, 0.0, 0.001, 1_000_000), (2, 0.0, 0.001, 1_000_000)])
                _write_flow(
                    os.path.join(DATA, f"expI_incN32_f{f}_{tok}_s{s}.flow.txt"),
                    [(1, 0.0, 0.001, 1_000_000), (2, 0.0, 0.001, 1_000_000)])

    # spot-check the math
    g = mean_over_seeds(_goodput,   lambda s: f"expI_m2m_f0_ref_s{s}", [13])
    a = mean_over_seeds(_avgfct_us, lambda s: f"expI_m2m_f0_ref_s{s}", [13])
    assert abs(g - 16.0) < 1e-6, f"goodput wrong: {g}"
    assert abs(a - 1000.0) < 1e-6, f"avgfct wrong: {a}"
    # missing file -> nan
    assert math.isnan(mean_over_seeds(_goodput, lambda s: "nope", [13]))

    # ---- render figI_a_headline ----
    render_headline()
    assert os.path.exists(os.path.join(FIGS, "figI_a_headline.png")), "figI_a missing"

    # ---- synthetic queue / idmap for figI_b_queue_stability ----
    for tok in ("ref", "bold", "v2"):
        with open(os.path.join(DATA, f"expI_ts_{tok}_inc.idmap"), "w") as fh:
            fh.write("165 LS0->DST0(0)\n")
        with open(os.path.join(DATA, f"expI_ts_{tok}_inc.q.txt"), "w") as fh:
            fh.write("0.000004000 Type QUEUE_APPROX ID 165 Ev RANGE LastQ 41500 MinQ 0 MaxQ 41500\n")
            fh.write("0.000008000 Type QUEUE_APPROX ID 165 Ev RANGE LastQ 20750 MinQ 0 MaxQ 20750\n")
            fh.write("0.000012000 Type QUEUE_APPROX ID 165 Ev RANGE LastQ 0 MinQ 0 MaxQ 0\n")

    render_queue_stability()
    assert os.path.exists(os.path.join(FIGS, "figI_b_queue_stability.png")), "figI_b missing"

    # ---- synthetic epoch.csv for figI_c_engaged_fraction ----
    # incast: mostly disengaged (region=-1 in col5, engaged=0 in col9 — matches real C++ output)
    with open(os.path.join(DATA, "expI_ts_v2_inc.epoch.csv"), "w") as fh:
        for t in range(1000, 20000, 1000):
            fh.write(f"{t * 1000},1,13945,5000,8000,-1,65536,5,0,0,28,20\n")  # disengaged: col9=0
    # m2m: mostly engaged (region=1, col9=1)
    with open(os.path.join(DATA, "expI_ts_v2_m2m.epoch.csv"), "w") as fh:
        for t in range(1000, 20000, 1000):
            fh.write(f"{t * 1000},1,13945,5000,8000,1,65536,5,0,1,28,20\n")  # engaged

    render_engaged_fraction()
    assert os.path.exists(os.path.join(FIGS, "figI_c_engaged_fraction.png")), "figI_c missing"

    # ---- render figI_d_ablation (reuses flow files + queue files already written) ----
    render_ablation()
    assert os.path.exists(os.path.join(FIGS, "figI_d_ablation.png")), "figI_d missing"

    # ---- synthetic sweep flow files for figI_e_sweeps ----
    for eng in (24, 28, 34):
        for s in SEEDS:
            _write_flow(os.path.join(DATA, f"expI_sw_eng{eng}_inc_s{s}.flow.txt"),
                        [(1, 0.0, 0.001, 1_000_000), (2, 0.0, 0.001, 1_000_000)])
            _write_flow(os.path.join(DATA, f"expI_sw_eng{eng}_m2m_s{s}.flow.txt"),
                        [(1, 0.0, 0.001, 1_000_000), (2, 0.0, 0.001, 1_000_000)])
    for beta in (0.15, 0.3, 0.5):
        for s in SEEDS:
            _write_flow(os.path.join(DATA, f"expI_sw_beta{beta}_inc_s{s}.flow.txt"),
                        [(1, 0.0, 0.001, 1_000_000), (2, 0.0, 0.001, 1_000_000)])
    for eb in (0.1, 0.2, 0.3):
        for s in SEEDS:
            _write_flow(os.path.join(DATA, f"expI_sw_ebeta{eb}_inc_s{s}.flow.txt"),
                        [(1, 0.0, 0.001, 1_000_000), (2, 0.0, 0.001, 1_000_000)])
            _write_flow(os.path.join(DATA, f"expI_sw_ebeta{eb}_m2m_s{s}.flow.txt"),
                        [(1, 0.0, 0.001, 1_000_000), (2, 0.0, 0.001, 1_000_000)])

    render_sweeps()
    assert os.path.exists(os.path.join(FIGS, "figI_e_sweeps.png")), "figI_e missing"

    # ---- synthetic OAT sensitivity files for figI_f_sensitivity ----
    # ref arms (seeds 13-15) — reuse existing m2m/incN32 flow files already written above
    # sensitivity arms: all 4 params × 3 values × 3 scens × 3 seeds
    SENS_PARAMS = [
        ("beta", [0.15, 0.3, 0.5]),
        ("h",    [0.15, 0.25, 0.4]),
        ("rho",  [0.6, 0.7, 0.8]),
        ("m",    [1.7, 2.0, 2.4]),
    ]
    for param, vals in SENS_PARAMS:
        for v in vals:
            vstr = str(v)
            for scen in ("f0", "f8", "inc"):
                for s in [13, 14, 15]:
                    _write_flow(
                        os.path.join(DATA, f"expI_sens_{param}_{vstr}_{scen}_s{s}.flow.txt"),
                        [(1, 0.0, 0.001, 1_000_000), (2, 0.0, 0.001, 1_000_000)])

    render_sensitivity()
    assert os.path.exists(os.path.join(FIGS, "figI_f_sensitivity.png")), "figI_f missing"

    # report what was written
    figs_written = sorted(os.listdir(FIGS))
    print(f"ok selftest: {', '.join(figs_written)}")


# ---- main ----

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        selftest()
        return

    os.makedirs(FIGS, exist_ok=True)
    render_headline()
    render_queue_stability()
    render_engaged_fraction()
    render_ablation()
    render_sweeps()
    render_sensitivity()
    print("wrote figI_a_headline, figI_b_queue_stability, figI_c_engaged_fraction, "
          "figI_d_ablation, figI_e_sweeps, figI_f_sensitivity")


if __name__ == "__main__":
    main()
