#!/usr/bin/env python3
"""Collective-makespan figures for prism_eval (separate module: cct_figs.py and perf_figs.py both
hold uncommitted WIP and must not be touched). Grouped bar chart of collective completion time
(makespan, ms) vs failed-links; aggregation reuses metrics.py.
  python3 makespan_figs.py --selftest   # math self-check
"""
import os, sys, math, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import metrics          # noqa: E402
import plot_style       # noqa: E402

def _sem(v):
    """(mean, standard error of the mean) of a non-empty list; NaNs dropped. SEM = sample_std/sqrt(n)
    (ddof=1; 0.0 for n<2)."""
    clean = [x for x in v if not math.isnan(x)]
    if not clean:
        return (float("nan"), 0.0)
    m = statistics.mean(clean)
    sd = statistics.stdev(clean) if len(clean) > 1 else 0.0
    return (m, sd / math.sqrt(len(clean)))

def aggregate_makespan(data_dir, tag_prefix, label, failed, seeds, token="f"):
    """Per-failed collective-makespan aggregate for one arm: {f:(mean_ms, sem_ms)}; omit f with no
    data. Reads {tag_prefix}_{label}_{token}{f}_s{seed}.flow.txt; makespan in ms (drops nan = no
    completion)."""
    out = {}
    for f in failed:
        ms = []
        for s in seeds:
            flow = os.path.join(data_dir, f"{tag_prefix}_{label}_{token}{f}_s{s}.flow.txt")
            if not os.path.exists(flow):
                continue
            mk, _cr = metrics.collective_makespan(flow)
            if mk == mk:                       # drop nan (no completion)
                ms.append(mk * 1e3)            # s -> ms
        if not ms:
            continue
        out[f] = _sem(ms)
    return out

def render_makespan_bars(data_dir, figs_dir, tag_prefix, baselines, failed, seeds, fig_stem,
                         token="f"):
    """Grouped bar chart of collective completion time (makespan, ms) vs failed-links: x-axis groups
    = failed levels, one bar per arm, linear-y "CCT (ms)" with numeric ticks, SEM error bars, legend
    on top. baselines = (label, display, color_key) triples."""
    import matplotlib.pyplot as plt
    plot_style.apply_style(12)
    aggs = {lab: aggregate_makespan(data_dir, tag_prefix, lab, failed, seeds, token)
            for lab, _d, _c in baselines}
    fig, ax = plt.subplots(figsize=(0.95 * len(failed) + 1.6, 3.0))
    n = len(baselines); group_w = 0.66; bw = group_w / n
    x = list(range(len(failed)))
    for j, (lab, disp, ck) in enumerate(baselines):
        means = [aggs[lab].get(f, (float("nan"), 0.0))[0] for f in failed]
        sems  = [aggs[lab].get(f, (float("nan"), 0.0))[1] for f in failed]
        offs  = [xi - group_w / 2 + bw * (j + 0.5) for xi in x]
        ax.bar(offs, means, bw, yerr=sems, capsize=2, color=plot_style.COLORS.get(ck), label=disp)
    ax.set_xticks(x); ax.set_xticklabels([str(f) for f in failed])
    ax.set_xlabel("Number of failed links"); ax.set_ylabel("CCT (ms)")
    ax.grid(axis="y", alpha=0.3)
    ax.legend(ncol=min(len(baselines), 3), fontsize=8, loc="lower center",
              bbox_to_anchor=(0.5, 1.02), frameon=False)
    plt.tight_layout(); plot_style.save(fig, fig_stem, figs_dir); plt.close(fig)

def selftest():
    import tempfile, shutil
    d = tempfile.mkdtemp()
    failed = [0, 4, 8, 12]; seeds = [13, 14, 15, 16, 17]
    for f in failed:
        for s in seeds:
            with open(os.path.join(d, f"expGring_ops_f{f}_s{s}.flow.txt"), "w") as fh:
                # flows start at 1us, finish at 1001us -> makespan = 1001us - 1us = 1.0 ms
                fh.write("0.000001000 Type FLOW_EVENT SrcID 1 Ev START FlowID 1 Flowsize 1000\n")
                fh.write("0.000001000 Type FLOW_EVENT SrcID 2 Ev START FlowID 2 Flowsize 1000\n")
                fh.write("0.001001000 Type FLOW_EVENT SrcID 1 Ev FINISH FlowID 1 Bytes 1000 Pkts 1\n")
                fh.write("0.001001000 Type FLOW_EVENT SrcID 2 Ev FINISH FlowID 2 Bytes 1000 Pkts 1\n")
    am = aggregate_makespan(d, "expGring", "ops", failed, seeds)
    assert abs(am[0][0] - 1.0) < 1e-6, am[0]   # makespan 1.0 ms
    assert am[0][1] == 0.0, am[0]              # identical seeds -> SEM 0
    shutil.rmtree(d)
    m, se = _sem([10.0, 20.0, 30.0])           # mean 20, sample stdev 10, n 3
    assert abs(m - 20.0) < 1e-9, (m, se)
    assert abs(se - 10.0 / math.sqrt(3)) < 1e-9, (m, se)
    print("ok makespan_figs selftest")

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
