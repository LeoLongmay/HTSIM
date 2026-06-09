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
import os, sys, collections, statistics as st
HERE = os.path.dirname(os.path.abspath(__file__))
TQD = [2, 4, 6, 8, 12, 16]
SEEDS = [13, 14, 15, 16, 17]
WIN_S = (0.5e-3, 1.5e-3)      # steady window, seconds (sink timestamps)
WIN_US = (500.0, 1500.0)      # steady window, microseconds (queue timestamps)
BYTES_TO_US = 8e-5            # 1 byte @100Gbps queueing delay
DEFAULT_TQD = 6              # the "independently chosen" default

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
        vals = [fn(f"{prefix}_tqd{q}.s{s}") for s in SEEDS]
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

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7, 7.6), sharex=True)
    # Panel A
    ax1.errorbar(TQD, gm, yerr=gs, marker='o', lw=2, capsize=3, color='tab:green')
    ax1.axvline(DEFAULT_TQD, color='gray', ls='--', lw=1)
    ax1.scatter([qA_best], [max(gm)], s=130, facecolors='none', edgecolors='tab:green', zorder=5)
    ax1.annotate("optimum: LENIENT CC", xy=(qA_best, max(gm)), xytext=(qA_best-3.5, max(gm)),
                 fontsize=8.5, va='center', ha='right')
    ax1.annotate("default 6us", xy=(DEFAULT_TQD, min(gm)), fontsize=8, color='gray', rotation=90, va='bottom')
    annA = f"Regime A (spray-removable)\nmeasured C_spray={dA[0]:.1f} >> C_cc={dA[1]:.1f} us" if dA else "Regime A (spray-removable)"
    ax1.set_title(annA, fontsize=9)
    ax1.set_ylabel("aggregate goodput (Gbps)\nhigher better"); ax1.grid(alpha=0.3)
    ax1.fill_between(TQD, gm, max(gm), color='tab:red', alpha=0.10)
    # Panel B
    ax2.errorbar(TQD, lm, yerr=ls, marker='s', lw=2, capsize=3, color='tab:purple')
    ax2.axvline(DEFAULT_TQD, color='gray', ls='--', lw=1)
    ax2.scatter([qB_best], [min(lm)], s=130, facecolors='none', edgecolors='tab:purple', zorder=5)
    ax2.annotate("optimum: AGGRESSIVE CC", xy=(qB_best, min(lm)), xytext=(qB_best+0.5, min(lm)),
                 fontsize=8.5, va='center', ha='left')
    annB = f"Regime B (path-wide)\nmeasured C_cc={dB[1]:.1f} >> C_spray={dB[0]:.1f} us" if dB else "Regime B (path-wide)"
    ax2.set_title(annB, fontsize=9)
    ax2.set_ylabel("mean queue latency (us)\nlower better"); ax2.grid(alpha=0.3)
    ax2.fill_between(TQD, lm, max(lm), color='tab:red', alpha=0.10)
    ax2.set_xlabel("CC aggressiveness  -  NSCC target_q_delay (us)   [left = aggressive, right = lenient]")
    ax2.set_xticks(TQD)
    fig.suptitle("figI: CC and spraying tuned independently can't win both regimes\n"
                 "REPS fixed ON; optimal CC flips ends -> the fixed default is off-optimum in BOTH",
                 fontsize=10.5)
    plt.tight_layout(rect=(0, 0, 1, 0.96))
    plt.savefig(os.path.join(HERE, "figI_cc_lb_tuning_coupled.png"), dpi=140); plt.close()
    print("figI: RegimeA goodput vs tqd =", [round(x,1) for x in gm], "argmax tqd", qA_best)
    print("figI: RegimeB mean-lat vs tqd =", [round(x,1) for x in lm], "argmin tqd", qB_best)
    print("figI: decomp A", dA, " B", dB)

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
    if "--selftest" in sys.argv:
        _selftest()
    else:
        render()
