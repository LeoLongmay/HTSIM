#!/usr/bin/env python3
"""figI -- uncoordinated CC+spraying tuning is suboptimal (optimum-flip).

Spraying fixed ON (REPS). Sweep NSCC target_q_delay; the optimal setting flips between:
  Regime A (spray-removable, high C_spray / ~0 C_cc): metric = aggregate goodput (Gbps);
            lenient CC wins (aggressive CC needlessly throttles -> underutilization).
  Regime B (path-wide, high C_cc / ~0 C_spray):        metric = MEAN bottleneck-queue latency (us);
            aggressive CC wins (lenient CC lets the floor balloon; goodput is capped).
            MEAN not p99: NSCC trims to bound the queue, so the tail is pinned at the buffer
            ceiling regardless of CC; the mean tracks the sustained floor (= what C_cc measures).
No single fixed target_q_delay is optimal in both -> CC must coordinate with the regime
the LB produces. Reads mvp_runs3/cp{A,B}_tqd{Q}.s{S}.{sink.txt,q.txt,idmap}. Run:
  python3 make_coupling_fig.py            # render figI
  python3 make_coupling_fig.py --selftest # run parser self-checks
"""
import argparse, collections, os, re, statistics as st, sys
HERE = os.path.dirname(os.path.abspath(__file__))
TQD = [2, 4, 6, 8, 12, 16]
SEEDS = [13, 14, 15, 16, 17]
WIN_S = (0.5e-3, 1.5e-3)      # steady window, seconds (sink timestamps)
WIN_US = (500.0, 1500.0)      # steady window, microseconds (queue timestamps)
BYTES_TO_US = 8e-5            # 1 byte @100Gbps queueing delay
DEFAULT_TQD = 6              # the "independently chosen" default
INPUT_SUFFIX = ""
OUTPUT_SUFFIX = ""

def run_tag(prefix, q, seed):
    return f"{prefix}{INPUT_SUFFIX}_tqd{q}.s{seed}"

def output_stem(stem):
    return f"{stem}{OUTPUT_SUFFIX}"

def goodput_gbps(tag):
    """Steady-window aggregate goodput (Gbps) = sum of UEC_SINK Rate (bits/s)."""
    bt = collections.defaultdict(float)
    with open(os.path.join(HERE, f"{tag}.sink.txt")) as fh:
        for ln in fh:
            p = ln.split()
            if len(p) >= 13:
                bt[float(p[0])] += float(p[12])
    tail = [v / 1e9 for t, v in bt.items() if WIN_S[0] <= t <= WIN_S[1]]
    return st.mean(tail) if tail else 0.0

def _qid_ls0dst0(tag):
    """Resolve the receiver bottleneck downqueue (LS0->DST0) id from the run's idmap."""
    with open(os.path.join(HERE, f"{tag}.idmap")) as fh:
        for ln in fh:
            ps = ln.split(None, 1)
            if len(ps) == 2 and ps[1].strip().startswith("LS0->DST0"):
                return int(ps[0])
    return None

def mean_latency_us(tag):
    """Steady-window MEAN queueing latency (us) at the receiver bottleneck.

    MEAN, not p99: NSCC trims to bound the queue, so the tail (p99/p90) is pinned at the
    buffer ceiling regardless of CC aggressiveness; the MEAN tracks the sustained floor,
    which is exactly what C_cc represents and what a lenient CC inflates.
    """
    qid = _qid_ls0dst0(tag)
    vals = []
    with open(os.path.join(HERE, f"{tag}.q.txt")) as fh:
        for ln in fh:
            p = ln.split()
            if len(p) >= 9 and int(p[4]) == qid:
                t_us = float(p[0]) * 1e6
                if WIN_US[0] <= t_us <= WIN_US[1]:
                    vals.append(int(p[8]) * BYTES_TO_US)
    return st.mean(vals) if vals else 0.0

def across_seeds(fn, prefix):
    """(means, stds) over seeds for each target_q_delay; tags = {prefix}_tqd{Q}.s{S}."""
    means, stds = [], []
    for q in TQD:
        vals = [fn(run_tag(prefix, q, s)) for s in SEEDS]
        means.append(st.mean(vals))
        stds.append(st.stdev(vals) if len(vals) > 1 else 0.0)
    return means, stds

def decomp(tag):
    """(C_spray, C_cc) in us for a pathrtt run, const baseline. None if unavailable.

    Uses the WIDE (1000,7000)us window (decomp runs are END=8) so enough in-window ACKs
    pass the sample gate; falls back to a relaxed gate if the strict one yields nothing.
    """
    sys.path.insert(0, HERE)
    import pathrtt_analyze as A
    BPROP = 13945.0   # uncontended propagation floor (ns); topology constant (min raw RTT of N=1 run)
    csv = os.path.join(HERE, f"{tag}.pathrtt.csv")
    if not os.path.exists(csv):
        return None
    rows = A.parse_csv(csv)
    for ms in (200, 100, 50):
        g = A.aggregate_rows(rows, min_samples=ms, baseline="const", const_base=BPROP, win=(1000.0, 7000.0))
        if g:
            return (g["cspray_med"], g["ccc_med"])
    return None

def render():
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    gm, gs = across_seeds(goodput_gbps, "cpA")        # Regime A goodput
    lm, ls = across_seeds(mean_latency_us, "cpB")     # Regime B mean queue latency
    dA, dB = decomp("cpA_decomp"), decomp("cpB_decomp")
    qA_best = TQD[gm.index(max(gm))]                  # lenient end expected
    qB_best = TQD[lm.index(min(lm))]                  # aggressive end expected

    XLBL = "NSCC target_q_delay (us)"
    default_w, default_h = plt.rcParams["figure.figsize"]

    # One figure, two stacked panels (figI1 top = Regime A goodput, figI2 bottom = Regime B latency),
    # sharing the x-axis so the top panel's x-ticks + x-label are dropped; small gap between panels.
    # Width and per-panel height kept as before (default_w+2.0 wide, 4 tall each -> 8 total).
    with plt.rc_context({"font.size": 18}):
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(default_w + 2.0, 5.0), sharex=True)
        # ---- figI1 (top): Regime A (spray-removable) -- goodput, lenient CC wins ----
        ax1.errorbar(TQD, gm, yerr=gs, marker='o', lw=2.5, ms=10, capsize=5, color='tab:green')
        ax1.fill_between(TQD, gm, max(gm), color='tab:red', alpha=0.10)
        ax1.axvline(DEFAULT_TQD, color='gray', ls='--', lw=1.5)
        ax1.scatter([qA_best], [max(gm)], s=260, facecolors='none', edgecolors='tab:green', lw=2.5, zorder=5)
        ax1.annotate("Best", xy=(qA_best, max(gm)), xytext=(11, 30),
                     va='center', ha='center', arrowprops=dict(arrowstyle='->', color='tab:green'))
        ax1.annotate("default", xy=(DEFAULT_TQD, min(gm) - 3), color='gray', rotation=90, va='bottom', ha='right')
        ax1.set_ylabel("Goodput (Gbps)")
        ax1.yaxis.set_label_coords(-0.08, 0.45)
        ax1.grid(alpha=0.3)
        # ---- figI2 (bottom): Regime B (path-wide) -- mean queue latency, aggressive CC wins ----
        ax2.errorbar(TQD, lm, yerr=ls, marker='s', lw=2.5, ms=10, capsize=5, color='tab:purple')
        ax2.fill_between(TQD, lm, max(lm), color='tab:red', alpha=0.10)
        ax2.axvline(DEFAULT_TQD, color='gray', ls='--', lw=1.5)
        ax2.scatter([qB_best], [min(lm)], s=260, facecolors='none', edgecolors='tab:purple', lw=2.5, zorder=5)
        ax2.annotate("Best", xy=(qB_best, min(lm)), xytext=(10, 10),
                     va='center', ha='center', arrowprops=dict(arrowstyle='->', color='tab:purple'))
        ax2.annotate("default", xy=(DEFAULT_TQD, max(lm)), color='gray', rotation=90, va='top', ha='right')
        ax2.set_xlabel(XLBL); ax2.set_ylabel("Latency (us)")
        ax2.yaxis.set_label_coords(-0.08, 0.4)
        ax2.set_xticks(TQD); ax2.grid(alpha=0.3)
        plt.tight_layout(h_pad=0.3)   # small h_pad -> reduced gap between the two panels
        fig.savefig(os.path.join(HERE, "figI_cc_lb_tuning_coupled.png"), dpi=140, bbox_inches="tight", pad_inches=0.12)
        fig.savefig(os.path.join(HERE, "figI_cc_lb_tuning_coupled.pdf"), bbox_inches="tight", pad_inches=0.12)
        plt.close(fig)
    print("figI: RegimeA goodput vs tqd =", [round(x,1) for x in gm], "argmax tqd", qA_best)
    print("figI: RegimeB mean-lat vs tqd =", [round(x,1) for x in lm], "argmin tqd", qB_best)
    print("figI: decomp A", dA, " B", dB)

def render_dualaxis():
    """figI2 -- compact single-panel twin-axis variant of figI (Option A).

    Same data as figI (Regime A goodput from cpA, Regime B mean latency from cpB), but both
    curves share ONE panel on a twin y-axis. The right (latency) axis is INVERTED so that
    "better" is UP for both axes; goodput then rises to the right while latency rises to the
    left, so the two curves cross in an X -- the optimum of the *same* knob flips between
    regimes. Halves the vertical footprint and removes the sparse whitespace of the 2-panel
    layout. Writes figI2_cc_lb_tuning_coupled.{png,pdf}; does NOT touch figI.
    """
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    gm, gs = across_seeds(goodput_gbps, "cpA")        # Regime A goodput
    lm, ls = across_seeds(mean_latency_us, "cpB")     # Regime B mean queue latency
    qA_best = TQD[gm.index(max(gm))]                  # lenient end (right) wins goodput
    qB_best = TQD[lm.index(min(lm))]                  # aggressive end (left) wins latency
    GREEN, PURPLE = "tab:green", "tab:purple"

    with plt.rc_context({"font.size": 12}):
        fig, axg = plt.subplots(figsize=(5.6, 2))
        axl = axg.twinx()
        # Regime A goodput (left, green, ascending ->)
        axg.errorbar(TQD, gm, yerr=gs, marker="o", lw=2.0, ms=6, capsize=3, color=GREEN, zorder=3)
        # Regime B mean latency (right, purple); invert axis -> "better" is UP for both -> X-cross
        axl.errorbar(TQD, lm, yerr=ls, marker="s", lw=2.0, ms=6, capsize=3, color=PURPLE, zorder=3)
        axl.invert_yaxis()
        axg.margins(y=0.11); axl.margins(y=0.13)   # headroom so the "Best" markers/labels aren't clipped
        # default target_q_delay (label at top, away from the legend in the lower-center free zone)
        axg.axvline(DEFAULT_TQD, color="gray", ls="--", lw=1.2, zorder=1)
        axg.annotate("default", xy=(DEFAULT_TQD - 0.03, 0.47), xycoords=axg.get_xaxis_transform(),
                     color="gray", rotation=90, va="top", ha="right", fontsize=10)
        # "Best" markers at the two opposite ends (both plot near the TOP under the inverted axis)
        axg.scatter([qA_best], [max(gm)], s=150, facecolors="none", edgecolors=GREEN, lw=2.0, zorder=5)
        axl.scatter([qB_best], [min(lm)], s=150, facecolors="none", edgecolors=PURPLE, lw=2.0, zorder=5)
        axg.annotate("Best", xy=(qA_best - 1, max(gm) + 3.5), xytext=(-2, -14), textcoords="offset points",
                     color=GREEN, ha="center", va="top", fontsize=10)
        axl.annotate("Best", xy=(qB_best + 0.7, min(lm) + 1), xytext=(1, 14), textcoords="offset points",
                     color=PURPLE, ha="left", fontsize=10) # va="bottom"
        # color-coded axes; "(^better)" makes the inverted latency axis self-explanatory
        axg.set_xlabel("Target queueing delay (us)")
        axg.set_ylabel("Goodput (Gbps)")
        axg.yaxis.set_label_coords(-0.08, 0.45)
        axl.set_ylabel("Latency (us)")
        axg.tick_params(axis="y")
        axl.tick_params(axis="y")
        axg.set_xticks(TQD)
        axg.grid(alpha=0.3)
        handles = [Line2D([0], [0], color=GREEN, marker="o", lw=2.0, label="Goodput"),
                   Line2D([0], [0], color=PURPLE, marker="s", lw=2.0, label="Latency")]
        axg.legend(handles=handles, loc="center right", bbox_to_anchor=(1.0, 0.42), fontsize=10, framealpha=0.9, handlelength=1.6)
        plt.tight_layout()
        fig.savefig(os.path.join(HERE, output_stem("figI2_cc_lb_tuning_coupled") + ".png"), dpi=160,
                    bbox_inches="tight", pad_inches=0.04)
        fig.savefig(os.path.join(HERE, output_stem("figI2_cc_lb_tuning_coupled") + ".pdf"),
                    bbox_inches="tight", pad_inches=0.04)
        plt.close(fig)
    print("figI2: dual-axis | goodput-best tqd", qA_best, "| latency-best tqd", qB_best)


def _selftest():
    import tempfile
    d = tempfile.mkdtemp()
    global HERE; HERE = d
    # goodput: two receivers, steady within window -> sum/mean
    with open(os.path.join(d, "_g.sink.txt"), "w") as f:
        for t in ("0.000600000", "0.001000000"):
            f.write(f"{t} Type UEC_SINK ID 10 Ev RATE CAck 1 ReorderBuffer 0 Rate 40000000000\n")
            f.write(f"{t} Type UEC_SINK ID 11 Ev RATE CAck 1 ReorderBuffer 0 Rate 10000000000\n")
    assert abs(goodput_gbps("_g") - 50.0) < 1e-9, goodput_gbps("_g")
    # mean latency: idmap maps qid 164 -> LS0->DST0; q.txt LastQ bytes in window
    with open(os.path.join(d, "_p.idmap"), "w") as f:
        f.write("164 LS0->DST0(0)\n165 LS0->DST1(0)\n")
    with open(os.path.join(d, "_p.q.txt"), "w") as f:
        # 3 in-window samples on qid 164: 1000,2000,3000 bytes -> 0.08,0.16,0.24 us -> mean 0.16
        f.write("0.000600000 Type QUEUE_APPROX ID 164 Ev RANGE LastQ 1000 MinQ 0 MaxQ 0\n")
        f.write("0.000700000 Type QUEUE_APPROX ID 164 Ev RANGE LastQ 2000 MinQ 0 MaxQ 0\n")
        f.write("0.000800000 Type QUEUE_APPROX ID 164 Ev RANGE LastQ 3000 MinQ 0 MaxQ 0\n")
        f.write("0.000650000 Type QUEUE_APPROX ID 165 Ev RANGE LastQ 999999 MinQ 0 MaxQ 0\n")  # other queue ignored
    got = mean_latency_us("_p")
    assert abs(got - 0.16) < 1e-9, got
    print("ok goodput_gbps + mean_latency_us")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--input-suffix", default="",
                        help="Suffix appended to cpA/cpB raw-data tags, e.g. _s")
    parser.add_argument("--output-suffix", default="",
                        help="Suffix appended to rendered figure names, e.g. _s")
    parser.add_argument("--only-dualaxis", action="store_true",
                        help="Render figI2 only; does not require figI decomposition traces")
    args = parser.parse_args()
    if args.selftest:
        _selftest()
    else:
        for suffix in (args.input_suffix, args.output_suffix):
            if suffix and not re.fullmatch(r"_[A-Za-z0-9_]+", suffix):
                parser.error("suffixes must be empty or begin with '_' and contain only letters, digits, and '_'")
        INPUT_SUFFIX = args.input_suffix
        OUTPUT_SUFFIX = args.output_suffix
        if not args.only_dualaxis:
            render()
        render_dualaxis()
