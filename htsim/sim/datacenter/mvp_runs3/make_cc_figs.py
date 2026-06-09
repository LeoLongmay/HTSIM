#!/usr/bin/env python3
"""figG / figH -- "CC alone is insufficient under topological asymmetry".

Complement of figA-F (which showed "spraying alone can't remove the floor -> need CC").
Here OBLIVIOUS LB = "CC alone": the source can't reroute, so the ONLY adaptive lever is
NSCC's rate control. REPS = CC + adaptive spraying (the co-designed-ish baseline).

Both figures come from the SAME runs: whole-pod overload (64 senders OUTSIDE pod0 ->
16 pod0 hosts, greedy/backlogged), NSCC, -failed in {0,4,8,12} (0 = symmetric control),
5 seeds {13..17}. failed=F degrades ceil(F/4) of pod0's 4 ingress aggs to 25% -> a healthy
path (US3) still exists, so the congestion is REROUTABLE (Regime A): the right lever is LB.

  figG (underutilization): aggregate goodput vs asymmetry. OBLIVIOUS plateaus BELOW REPS and
       the gap grows with asymmetry -> CC-alone throttles the whole flow instead of moving it
       off degraded paths, leaving healthy capacity idle. failed=0 control (REPS=OBL) proves
       the gap is asymmetry-induced, and CC is identical across the pair so the gap is purely
       the cost of having no adaptive LB.

  figH (congestion/retransmission storm): retransmitted packets (% of new = trim storm) vs
       asymmetry, same runs. OBLIVIOUS suffers far more trims: CC reacts to congestion on the
       degraded paths it CANNOT relieve (no reroute), so those paths keep overflowing ->
       trim/retransmit. REPS relieves them by rerouting. Second, distinct cost of CC-alone.

Reads mvp_runs3/cc_{reps,obl}_f{F}.s{S}.{sink.txt,stdout}. Run:  python3 make_cc_figs.py
"""
import os, re, collections, statistics as st
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
SEEDS = [13, 14, 15, 16, 17]
FAILED = [0, 4, 8, 12]
WIN = (0.5e-3, 1.5e-3)            # steady-state window, seconds


def goodput_gbps(tag):
    """Steady-window aggregate goodput (Gbps) = sum over receivers of UEC_SINK Rate (bits/s)."""
    bt = collections.defaultdict(float)
    with open(os.path.join(HERE, f"{tag}.sink.txt")) as fh:
        for ln in fh:
            p = ln.split()
            # t Type UEC_SINK ID <id> Ev RATE CAck n ReorderBuffer n Rate <bits/s>
            if len(p) >= 13:
                bt[float(p[0])] += float(p[12])
    tail = [v / 1e9 for t, v in bt.items() if WIN[0] <= t <= WIN[1]]
    return st.mean(tail) if tail else 0.0


def retx_pct(tag):
    """Retransmission fraction (% of new packets) from the run's final summary line."""
    txt = open(os.path.join(HERE, f"{tag}.stdout")).read()
    m = re.search(r'New:\s*(\d+)\s*Rtx:\s*(\d+)', txt)
    if not m:
        return 0.0
    new, rtx = int(m.group(1)), int(m.group(2))
    return 100.0 * rtx / max(new, 1)


def across_seeds(fn, lb):
    """(means, stds) over seeds for each failed value."""
    means, stds = [], []
    for f in FAILED:
        vals = [fn(f"cc_{lb}_f{f}.s{s}") for s in SEEDS]
        means.append(st.mean(vals))
        stds.append(st.stdev(vals) if len(vals) > 1 else 0.0)
    return means, stds


def main():
    REPS_LBL = "REPS  (CC + adaptive spraying)"
    OBL_LBL = "OBLIVIOUS  (CC alone, no adaptive spraying)"
    GREEN, RED = "tab:green", "tab:red"
    plt.rcParams.update({"font.size": 24})   # paper styling: axes/ticks/labels 24pt (legend & callouts set to 18 below)

    # ---- figG: goodput / underutilization ----
    gm_r, gs_r = across_seeds(goodput_gbps, "reps")
    gm_o, gs_o = across_seeds(goodput_gbps, "obl")
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.errorbar(FAILED, gm_r, yerr=gs_r, marker='o', capsize=3, lw=2, label=REPS_LBL, color=GREEN)
    ax.errorbar(FAILED, gm_o, yerr=gs_o, marker='s', capsize=3, lw=2, label=OBL_LBL, color=RED)
    ax.fill_between(FAILED, gm_o, gm_r, color=RED, alpha=0.12)
    # in-figure gap callout removed for the paper (shaded band shows it; magnitude in caption)
    ax.set_xlabel("topological asymmetry (Number of failed links)")
    ax.set_ylabel("aggregate goodput (Gbps)")
    # ax.set_title("figG: CC alone underutilizes under asymmetry\nwhole-pod overload 64→16, NSCC, mean±std over 5 seeds")
    ax.set_xticks(FAILED); ax.set_ylim(bottom=50); ax.legend(loc="lower left", fontsize=18); ax.grid(alpha=0.3)
    plt.tight_layout(); plt.savefig(os.path.join(HERE, "figG_cc_alone_underutilization.png"), dpi=140, bbox_inches="tight", pad_inches=0.05); plt.savefig(os.path.join(HERE, "figG_cc_alone_underutilization.pdf"), bbox_inches="tight", pad_inches=0.05); plt.close()

    # ---- figH: retransmission / congestion storm ----
    rm_r, rs_r = across_seeds(retx_pct, "reps")
    rm_o, rs_o = across_seeds(retx_pct, "obl")
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.errorbar(FAILED, rm_r, yerr=rs_r, marker='o', capsize=3, lw=2, label=REPS_LBL, color=GREEN)
    ax.errorbar(FAILED, rm_o, yerr=rs_o, marker='s', capsize=3, lw=2, label=OBL_LBL, color=RED)
    ax.fill_between(FAILED, rm_r, rm_o, color=RED, alpha=0.12)
    # in-figure callout removed for the paper (shaded band shows it; magnitude in caption)
    ax.set_xlabel("topological asymmetry (Number of failed links)")
    ax.set_ylabel(r"retransmitted packets ($\%$)")
    # ax.set_title("figH: CC alone → congestion / retransmission storm\nsame runs as figG; adaptive LB relieves hot paths CC cannot")
    ax.set_xticks(FAILED); ax.set_ylim(bottom=0); ax.legend(loc="upper left", fontsize=18); ax.grid(alpha=0.3)
    plt.tight_layout(); plt.savefig(os.path.join(HERE, "figH_cc_alone_congestion.png"), dpi=140, bbox_inches="tight", pad_inches=0.05); plt.savefig(os.path.join(HERE, "figH_cc_alone_congestion.pdf"), bbox_inches="tight", pad_inches=0.05); plt.close()

    print("figG goodput (Gbps)  failed -> (REPS, OBL, gap):")
    for i, f in enumerate(FAILED):
        print(f"  f{f:<2}: REPS {gm_r[i]:6.1f}±{gs_r[i]:.1f}  OBL {gm_o[i]:6.1f}±{gs_o[i]:.1f}  gap {gm_r[i]-gm_o[i]:5.1f}")
    print("figH retransmit %    failed -> (REPS, OBL):")
    for i, f in enumerate(FAILED):
        print(f"  f{f:<2}: REPS {rm_r[i]:5.1f}±{rs_r[i]:.1f}  OBL {rm_o[i]:5.1f}±{rs_o[i]:.1f}")


if __name__ == "__main__":
    main()
