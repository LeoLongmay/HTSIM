#!/usr/bin/env python3
"""WHAT-IF re-tuning of PRISM in the delay-driven headline (expA_delaydriven / figA1dd).

PRISM's FULL failed-link sweep is re-run at two retuned configs, EVERY level consistent
(no per-point cherry-picking); all 6 other CC arms are reused read-only (symlinked):
  - A = T_spray 7us / T_cc 10us / kappa 1   (fairness-locked Pareto improvement)
  - B = T_spray 7us / T_cc 10us / kappa 2   (throughput-leaning; improves f0; mild f8-fairness give)
The original expA_delaydriven figures are NOT touched.

  python3 make_figs.py            # render figA1dd_{A,B}_* + the default/A/B overlay

DISCLOSURE: PRISM here uses tuned params while the baselines keep their defaults; T_cc is the
SHARED NSCC target, so PRISM runs at q=10 vs baselines at q=14 (each at its own setting). These
params were tuned on THIS 128-node workload (overfitting risk); cross-scale is untested. This is
an exploration, not a validated headline.
"""
import os, sys, statistics
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import perf_figs   # noqa: E402
import plot_style  # noqa: E402
import metrics     # noqa: E402

FIGS  = os.path.join(HERE, "figs")
DATA_A = os.path.join(HERE, "data_A")
DATA_B = os.path.join(HERE, "data_B")
SRC    = os.path.join(HERE, "..", "expA_delaydriven", "data")  # default PRISM + REPS reference
BASELINES = [("ops", "OPS+NSCC", "ops"), ("reps", "REPS+NSCC", "reps"),
             ("swift", "REPS+Swift", "swift"), ("mswift", "REPS+MSwift", "mswift"),
             ("mnscc", "REPS+MNSCC", "mnscc"), ("strack", "STrack", "strack"),
             ("prism", "Prism", "prism")]
FAILED = [0, 2, 4, 6, 8, 10, 12]
SEEDS  = [13, 14, 15, 16, 17]
XLABEL = "Number of failed links"

def _series(data_dir, tag):
    """(xs, goodput_tbps, avgfct_ms, p99_ms, jain) mean per failed level for one PRISM tag."""
    xs, g, a, p, j = [], [], [], [], []
    for f in FAILED:
        gg, aa, pp, jj = [], [], [], []
        for s in SEEDS:
            fp = os.path.join(data_dir, f"{tag}_f{f}_s{s}.flow.txt")
            if not os.path.exists(fp):
                continue
            st = metrics.fct_stats(fp)
            gg.append(metrics.aggregate_goodput_gbps(fp)); aa.append(st["avg_s"] * 1e3)  # ms
            pp.append(st["p99_s"] * 1e3); jj.append(metrics.jain_fairness(fp))
        if gg:
            xs.append(f); g.append(statistics.mean(gg) / 1e3); a.append(statistics.mean(aa))
            p.append(statistics.mean(pp)); j.append(statistics.mean(jj))
    return xs, g, a, p, j

def render_overlay():
    """Decision aid: PRISM default vs A vs B (+ REPS reference) across the failed-link sweep."""
    import matplotlib.pyplot as plt
    series = [
        ("REPS+NSCC (ref)", SRC, "expA_reps", plot_style.COLORS["reps"], "^:", 1.6),
        ("Prism default",   SRC, "expA_prism", "0.45", "o--", 2.0),
        ("Prism A (7,10,1)", DATA_A, "expA_prism", "#1a9850", "s-", 2.0),
        ("Prism B (7,10,2)", DATA_B, "expA_prism", "#d73027", "D-", 2.2),
    ]
    panels = [("goodput", "Goodput (Tbps)", 1), ("avg_fct", "Avg FCT (ms)", 2), ("fairness", "Jain fairness", 4)]
    plot_style.apply_style(15)
    for key, ylabel, idx in panels:
        fig, ax = plt.subplots(figsize=(5.6, 4.0))
        for lab, dirp, tag, col, sty, lw in series:
            xs, g, a, p, j = _series(dirp, tag)
            ys = {1: g, 2: a, 4: j}[idx]
            ax.plot(xs, ys, sty, color=col, lw=lw, ms=6, label=lab)
        ax.set_xlabel(XLABEL); ax.set_ylabel(ylabel); ax.set_xticks(FAILED); ax.grid(alpha=0.3)
        if key == "goodput":
            ax.legend(fontsize=9, loc="upper right")
        plt.tight_layout()
        plot_style.save(fig, f"figRetune_overlay_{key}", FIGS); plt.close(fig)

if __name__ == "__main__":
    os.makedirs(FIGS, exist_ok=True)
    # Full coherent 7-arm headline candidates (PRISM = retuned A / B; other arms reused)
    perf_figs.render_main_perf_split(DATA_A, FIGS, "expA", BASELINES, FAILED, SEEDS, "figA1dd_A", XLABEL, goodput_tbps=True)
    perf_figs.render_fairness(DATA_A, FIGS, "expA", BASELINES, FAILED, SEEDS, "figA1dd_A_fairness", XLABEL)
    perf_figs.render_main_perf_split(DATA_B, FIGS, "expA", BASELINES, FAILED, SEEDS, "figA1dd_B", XLABEL, goodput_tbps=True)
    perf_figs.render_fairness(DATA_B, FIGS, "expA", BASELINES, FAILED, SEEDS, "figA1dd_B_fairness", XLABEL)
    perf_figs.render_legend(FIGS, BASELINES, "figA1dd_legend", row_counts=[3, 4])
    render_overlay()
    print("done: figs/figA1dd_{A,B}_{goodput,avg_fct,p99_fct,fairness} + figRetune_overlay_*")
