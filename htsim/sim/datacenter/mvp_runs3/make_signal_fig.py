#!/usr/bin/env python3
"""figS1/figS2 -- the mean-vs-floor signal conflation (PRISM motivation, Section 2).

A decoupled controller (NSCC / STrack-style) decides whether to slow down from the
AVERAGE queuing delay across paths -- avg_delay = traffic-weighted MEAN of per-ACK q
(STrack Algorithm 4: cut window when avg_delay > target_Qdelay). PRISM instead reads the
FLOOR = min over a flow's paths of the per-path queuing delay (an order statistic).

Because avg_delay = floor + (traffic-weighted spread), the mean a decoupled controller
reacts to is inflated by the REROUTABLE spread whenever path diversity exists -- which is
intrinsic to multipath packet spray. So a single average cannot represent the floor that
actually determines whether slowing is needed.

figS1 (distribution): at one representative condition, the per-path queuing-delay
  distribution, with min (floor, PRISM) and the traffic-weighted mean (avg_delay, the
  decoupled signal) marked against the slow-down target. The mean sits up in the congested
  bulk; the floor is the clean-minority paths below the target.
figS2 (load sweep): floor and avg_delay vs offered load at fixed asymmetry. The mean
  crosses the target while there is still spare capacity (floor below target) -- the
  decoupled signal would slow on reroutable spread; only at heavy load do the two converge
  (genuine fabric congestion, slowing is warranted).

Reads mvp_runs3/sigL_n{N}.s{S}.pathrtt.csv (6-col PRISM_PATHRTT, failed=12 fixed). Run:
  python3 make_signal_fig.py            # render figS1 + figS2
  python3 make_signal_fig.py --selftest # parser/metric self-checks

SCOPE (honest): this is a SIGNAL-representation result. It shows the two control signals
diverge and what the mean conflates. It does NOT claim a controller is "wrong" or measure
a throughput/latency cost (that needs running both controllers = Evaluation).
"""
import os, sys, math, collections, statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))
LOADS = [4, 8, 16, 32, 64]   # offered load = #senders -> 16 pod0 receivers
DIST_LOAD = 16               # the load level shown as the per-path distribution (figS1)
SEEDS = [13, 14, 15, 16, 17]
BPROP_US = 13.945            # const propagation floor (us); topology constant
TARGET_US = 6.0              # NSCC target_q_delay (slow-down threshold)
WIN_NS = 14000               # decision window ~ 1 base RTT
STEADY_US = (500.0, 1500.0)
MIN_PATH_SAMPLES = 3         # min ACKs on a (flow,path) in-window to use its mean
# Shared canvas + axes box so figS1/figS2 plot boxes are the same size and align.
# subplots_adjust pins the axes box identically in both; savefig(bbox_inches="tight")
# then trims the surrounding whitespace (no large white border).
FIGSIZE = (6.4, 4.8)
FRAME = dict(left=0.17, right=0.95, top=0.93, bottom=0.16)


def parse6(path):
    """-> list of (t_ns, flow, path, rtt_ns, ecn, cwnd), ints, sorted by time."""
    rows = []
    if not os.path.exists(path):
        return rows
    for line in open(path):
        p = line.split(",")
        if len(p) < 6:
            continue
        try:
            rows.append((int(p[0]), int(p[1]), int(p[2]), int(p[3]), int(p[4]), int(p[5])))
        except ValueError:
            continue
    rows.sort(key=lambda r: r[0])
    return rows


def flow_metrics(rows, flow):
    """Steady-window means of floor (min over paths), avg_delay (mean over ACKs), and
    spread (max-min over paths) for one flow. None if too few samples."""
    evs = [(r[0], r[2], r[3] / 1000.0 - BPROP_US) for r in rows if r[1] == flow]
    if len(evs) < 30:
        return None
    evs.sort()
    t0 = (evs[0][0] // WIN_NS) * WIN_NS
    t1 = evs[-1][0] + 1
    floors, avgs, spreads = [], [], []
    b, idx = t0, 0
    while b < t1:
        be = b + WIN_NS
        acc = collections.defaultdict(list)
        ackqs = []
        while idx < len(evs) and evs[idx][0] < be:
            _, p, q = evs[idx]
            acc[p].append(q)
            ackqs.append(q)
            idx += 1
        if acc and STEADY_US[0] <= b / 1000.0 <= STEADY_US[1]:
            mv = [st.mean(acc[p]) for p in acc]
            floors.append(min(mv))
            spreads.append(max(mv) - min(mv))
            avgs.append(st.mean(ackqs))      # traffic-weighted mean = STrack avg_delay
        b = be
    if not floors:
        return None
    return st.mean(floors), st.mean(avgs), st.mean(spreads)


def seed_point(tag):
    """Cross-flow median of (floor, avg_delay, spread) for one run, or None."""
    rows = parse6(os.path.join(HERE, f"{tag}.pathrtt.csv"))
    if not rows:
        return None
    fl, av, sp = [], [], []
    for flow in set(r[1] for r in rows):
        m = flow_metrics(rows, flow)
        if m:
            fl.append(m[0]); av.append(m[1]); sp.append(m[2])
    if not fl:
        return None
    return st.median(fl), st.median(av), st.median(sp)


def path_means(tag):
    """All per-(flow,path) steady-window mean q values for one run (the per-path
    distribution that PRISM's min and the decoupled mean both summarize)."""
    rows = parse6(os.path.join(HERE, f"{tag}.pathrtt.csv"))
    byfp = collections.defaultdict(list)
    for r in rows:
        if STEADY_US[0] <= r[0] / 1000.0 <= STEADY_US[1]:
            byfp[(r[1], r[2])].append(r[3] / 1000.0 - BPROP_US)
    return [st.mean(v) for v in byfp.values() if len(v) >= MIN_PATH_SAMPLES]


def across_seeds(n, failed=12):
    """((floor m,std),(avg m,std)) over seeds for load level n."""
    fl, av = [], []
    for s in SEEDS:
        pt = seed_point(f"sigL_n{n}.s{s}")
        if pt:
            fl.append(pt[0]); av.append(pt[1])
    fm = (st.mean(fl), st.stdev(fl) if len(fl) > 1 else 0.0) if fl else (0.0, 0.0)
    am = (st.mean(av), st.stdev(av) if len(av) > 1 else 0.0) if av else (0.0, 0.0)
    return fm, am


def render_dist():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    vals = []
    for s in SEEDS:
        vals += path_means(f"sigL_n{DIST_LOAD}.s{s}")
    floor = min(vals) if vals else 0.0
    pt = [seed_point(f"sigL_n{DIST_LOAD}.s{s}") for s in SEEDS]
    pt = [p for p in pt if p]
    floor_m = st.mean([p[0] for p in pt]) if pt else floor
    avg_m = st.mean([p[1] for p in pt]) if pt else 0.0

    with plt.rc_context({"font.size": 24}):
        fig, ax = plt.subplots(figsize=FIGSIZE)
        ax.hist(vals, bins=40, color="tab:gray", alpha=0.55, edgecolor="white") # label="per-path queuing delay distribution"
        ax.axvspan(floor_m, avg_m, color="tab:orange", alpha=0.25)   # conflated spread C_spray (same orange as figS2)
        ax.axvline(floor_m, color="tab:red", lw=2.8,
                   label=r"$C_{cc}$")
        ax.axvline(avg_m, color="tab:blue", lw=2.8,
                   label="avg queuing delay")
        ax.axvline(TARGET_US, color="gray", ls="--", lw=1.8, label="target queuing delay")
        ax.set_xlabel("Per-path queuing delay (us)")
        ax.set_ylabel("Number of paths")
        ax.grid(alpha=0.3)
        plt.subplots_adjust(**FRAME)
        fig.savefig(os.path.join(HERE, "figS1_path_distribution.png"), dpi=140,
                    bbox_inches="tight", pad_inches=0.02)
        fig.savefig(os.path.join(HERE, "figS1_path_distribution.pdf"),
                    bbox_inches="tight", pad_inches=0.02)
        plt.close(fig)
    print(f"figS1 (n={DIST_LOAD}, failed=12): floor={floor_m:.2f} avg_delay={avg_m:.2f} "
          f"target={TARGET_US} npaths={len(vals)}")


def render_cdf():
    """figS3 -- CDF of the per-path delay distribution (clearer y-axis than figS1's count).
    Same condition/markers as figS1; the bimodal valley shows up as a flat plateau, and the
    avg RTT marker lands on that plateau (a delay value almost no path actually has)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    vals = []
    for s in SEEDS:
        vals += path_means(f"sigL_n{DIST_LOAD}.s{s}")
    vals.sort()
    n = len(vals)
    cdf = [(i + 1) / n for i in range(n)]
    pt = [seed_point(f"sigL_n{DIST_LOAD}.s{s}") for s in SEEDS]
    pt = [p for p in pt if p]
    floor_m = st.mean([p[0] for p in pt]) if pt else 0.0
    avg_m = st.mean([p[1] for p in pt]) if pt else 0.0

    with plt.rc_context({"font.size": 18}):
        fig, ax = plt.subplots(figsize=(8.5, 5.0))
        ax.plot(vals, cdf, color="tab:gray", lw=3.0, label="per-path queuing delay (CDF)")
        ax.axvline(floor_m, color="tab:red", lw=2.8, label=r"floor $=\min_i q_i$ (PRISM)")
        ax.axvline(avg_m, color="tab:blue", lw=2.8, label="avg queuing delay (NSCC / STrack)")
        ax.axvline(TARGET_US, color="gray", ls="--", lw=1.8, label="slow-down target")
        ax.set_xlabel("per-path queuing delay (us)")
        ax.set_ylabel("CDF (fraction of paths)")
        ax.set_ylim(0, 1)
        ax.grid(alpha=0.3)
        ax.legend(fontsize=12, loc="lower right")
        plt.tight_layout()
        fig.savefig(os.path.join(HERE, "figS3_path_cdf.png"), dpi=140,
                    bbox_inches="tight", pad_inches=0.05)
        fig.savefig(os.path.join(HERE, "figS3_path_cdf.pdf"),
                    bbox_inches="tight", pad_inches=0.05)
        plt.close(fig)
    print(f"figS3 (n={DIST_LOAD}, failed=12) CDF: floor={floor_m:.2f} avg_delay={avg_m:.2f} "
          f"target={TARGET_US} npaths={n}")


def render_sweep():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fm, fs, am, as_ = [], [], [], []
    for n in LOADS:
        (f_m, f_s), (a_m, a_s) = across_seeds(n)
        fm.append(f_m); fs.append(f_s); am.append(a_m); as_.append(a_s)

    with plt.rc_context({"font.size": 24}):
        fig, ax = plt.subplots(figsize=FIGSIZE)
        x = list(range(len(LOADS)))
        ax.fill_between(x, fm, am, color="tab:orange", alpha=0.25,
                        label=r"conflated spread $C_{spray}$")
        ax.errorbar(x, am, yerr=as_, marker='s', lw=2.5, ms=9, capsize=5,
                    color="tab:blue", label="avg queuing delay")
        ax.errorbar(x, fm, yerr=fs, marker='o', lw=2.5, ms=9, capsize=5,
                    color="tab:red", label=r"$C_{cc}$")
        ax.axhline(TARGET_US, color="gray", ls="--", lw=1.8)
        ax.set_xlabel("Number of senders")
        ax.set_ylabel("Queuing delay (us)")
        # ax.yaxis.set_label_coords(-0.08, 0.45)
        ax.set_xticks(x); ax.set_xticklabels([str(n) for n in LOADS])
        ax.set_ylim(bottom=0)
        ax.grid(alpha=0.3)
        plt.subplots_adjust(**FRAME)
        fig.savefig(os.path.join(HERE, "figS2_load_sweep.png"), dpi=140,
                    bbox_inches="tight", pad_inches=0.02)
        fig.savefig(os.path.join(HERE, "figS2_load_sweep.pdf"),
                    bbox_inches="tight", pad_inches=0.02)
        plt.close(fig)
    print("figS2 floor (min) :", [round(v, 2) for v in fm])
    print("figS2 avg_delay   :", [round(v, 2) for v in am])


def render_legend():
    """Standalone shared legend for figS1 + figS2 (own image file, like figGH_legend).
    Colors match both panels: C_cc = red line, avg = blue line, target = gray dashed line,
    conflated spread C_spray = orange band (tab:orange, alpha 0.25, same as both figures)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    handles = [
        Line2D([], [], color="tab:red", lw=2.8, label=r"$C_{cc}$"),
        Line2D([], [], color="tab:blue", lw=2.8, label="avg queuing delay"),
        Line2D([], [], color="gray", ls="--", lw=1.8, label="target queuing delay"),
        Patch(facecolor="tab:orange", alpha=0.25, label=r"$C_{spray}$"),
    ]
    with plt.rc_context({"font.size": 24}):
        figL = plt.figure(figsize=(22, 0.9))
        figL.legend(handles=handles, loc="center", ncol=4, frameon=False)
        figL.savefig(os.path.join(HERE, "figS_legend.png"), dpi=140,
                     bbox_inches="tight", pad_inches=0.02)
        figL.savefig(os.path.join(HERE, "figS_legend.pdf"),
                     bbox_inches="tight", pad_inches=0.02)
        plt.close(figL)
    print("figS_legend: C_cc | avg queuing delay | target queuing delay | conflated spread C_spray")


def render():
    render_dist()
    render_sweep()
    render_legend()


def _selftest():
    import tempfile
    d = tempfile.mkdtemp()
    global HERE
    HERE = d
    # one flow, 2 paths: path0 clean (q=0), path1 congested (q=10). Each burst 1+3 ACKs.
    # per window: floor=0, spread=10, avg (traffic-weighted, 4 acks) = 7.5. >=30 ACKs.
    with open(os.path.join(d, "sigL_n16.s13.pathrtt.csv"), "w") as fh:
        for t in range(550000, 1000001, 50000):    # 10 bursts in steady window (ns)
            fh.write(f"{t},0,0,13945,0,1\n")          # path0 q=0.0
            fh.write(f"{t+1},0,1,23945,1,1\n")        # path1 q=10.0
            fh.write(f"{t+2},0,1,23945,1,1\n")        # path1 q=10.0
            fh.write(f"{t+3},0,1,23945,1,1\n")        # path1 q=10.0
    pt = seed_point("sigL_n16.s13")
    assert pt is not None, "seed_point returned None"
    floor, avg, spread = pt
    assert abs(floor - 0.0) < 1e-6, f"floor {floor}"
    assert abs(spread - 10.0) < 1e-6, f"spread {spread}"
    assert abs(avg - 7.5) < 1e-6, f"avg {avg}"
    pm = sorted(path_means("sigL_n16.s13"))
    assert len(pm) == 2 and abs(pm[0]) < 1e-6 and abs(pm[1] - 10.0) < 1e-6, f"path_means {pm}"
    print("ok make_signal_fig: floor=%.1f avg=%.1f spread=%.1f path_means=%s" %
          (floor, avg, spread, [round(x, 1) for x in pm]))


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        render()
