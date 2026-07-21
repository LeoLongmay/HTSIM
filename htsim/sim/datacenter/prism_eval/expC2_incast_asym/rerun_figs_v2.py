#!/usr/bin/env python3
"""Re-render figC2a/b/c (OVERWRITE) with the adopted design: the Prism line = original Prism
(default params) + A1 smoothing (tag expC2_prisma1_*); Prism@B dropped from C2a/C2b; a MSwift line
added to C2a/C2b; figC2c = Prism(default+A1) vs REPS+NSCC queue stability (tag expC2_ts_prisma1_center).
Imports make_figs and reuses its panel renderers via a monkeypatched ARMS; figC2d-g and make_figs.py
itself are left untouched. Run: python3 rerun_figs_v2.py
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import make_figs as mf            # has an __main__ guard, so importing does NOT render anything
import plot_style                 # noqa: E402
import metrics                    # noqa: E402
import matplotlib.pyplot as plt   # noqa: E402

# Per-figure arm lists (Prism line = default params + A1; no Prism@B, no plain default).
ARMS_A = [   # figC2a (failed sweep): OPS/REPS/MNSCC/STrack/MSwift + Prism(default+A1)
    ("ops",     "OPS+NSCC",           "ops",    "-"),
    ("reps",    "REPS+NSCC",          "reps",   "-"),
    ("mnscc",   "REPS+MNSCC",         "mnscc",  "-"),
    ("strack",  "STrack",             "strack", "-"),
    ("mswift",  "REPS+MSwift",        "mswift", "-"),
    ("prisma1", "Prism (default+A1)", "prism",  "-"),
]
ARMS_B = [   # figC2b (fan-in sweep): drop OPS+NSCC, add REPS+Swift
    ("reps",    "REPS+NSCC",          "reps",   "-"),
    ("mnscc",   "REPS+MNSCC",         "mnscc",  "-"),
    ("strack",  "STrack",             "strack", "-"),
    ("swift",   "REPS+Swift",         "swift",  "-"),
    ("mswift",  "REPS+MSwift",        "mswift", "-"),
    ("prisma1", "Prism (default+A1)", "prism",  "-"),
]
mf.ARMS = ARMS_A; mf.render_main_failed()   # OVERWRITES figC2a_main_failed (fan-in 32, failed sweep)
mf.ARMS = ARMS_B; mf.render_main_fanin()    # OVERWRITES figC2b_main_fanin  (failed 8, fan-in sweep)

def render_c2c():
    """figC2c (OVERWRITE): Prism(default+A1) vs REPS+NSCC, last-hop switch queue delay (left) and
    end-to-end queuing delay (right) over time at the center cell (fan-in 32, failed 8)."""
    plot_style.apply_style(13)
    fig, (axl, axr) = plt.subplots(1, 2, figsize=(11, 3.8))
    pairs = [("expC2_ts_prisma1_center", "Prism (default+A1)", "prism", "-"),
             (mf.TS_REPS_CENTER,         "REPS+NSCC",          "reps",  "-")]
    for tag, lab, ck, ls in pairs:
        qp = os.path.join(mf.DATA, tag + ".q.txt"); ip = os.path.join(mf.DATA, tag + ".idmap")
        if os.path.exists(qp) and os.path.exists(ip):
            ser = metrics.tor_downqueue_delay_series(qp, ip, 0)
            if ser:
                ts = [t * 1e6 for t, _ in ser]; qs = [q for _, q in ser]
                axl.plot(ts, qs, ls, lw=1.6, color=plot_style.COLORS[ck], label=lab)
    axl.set_xlabel("time (us)"); axl.set_ylabel("last-hop switch queue delay (us)")
    axl.set_title("switch queue (LS->DST0)"); axl.legend(fontsize=9); axl.grid(alpha=0.3)
    for tag, lab, ck, ls in pairs:
        prp = os.path.join(mf.DATA, tag + ".pathrtt.csv")
        if os.path.exists(prp):
            bins = metrics.qdelay_bins(prp, base_ns=mf.BASE_NS, bin_us=20)
            axr.plot([b[0] for b in bins], [b[2] for b in bins], ls, lw=1.6,
                     color=plot_style.COLORS[ck], label=lab)
    axr.set_xlabel("time (us)"); axr.set_ylabel("end-to-end queuing delay (us)")
    axr.set_title("end-to-end (PATHRTT)"); axr.legend(fontsize=9); axr.grid(alpha=0.3)
    fig.tight_layout()
    plot_style.save(fig, "figC2c_qdelay_time", mf.FIGS); plt.close(fig)

render_c2c()
print("re-rendered (OVERWRITE): figC2a_main_failed, figC2b_main_fanin, figC2c_qdelay_time")
