#!/usr/bin/env python3
"""Message-size-sweep CCT figures for prism_eval (separate module: cct_figs.py and perf_figs.py hold
uncommitted WIP and must not be touched; metrics.py is reused unchanged). Line chart of collective
CCT relative to a reference transport (REPS+NSCC, the UEC baseline) vs per-flow message size, at a
fixed failed-links level. Faithful to STrack's line-chart-vs-message-size form; the y-axis is a
relative-CCT normalization (each arm / the reference arm, paired per seed), with the reference at 1.0.

(An earlier analytical zero-queue lower bound was replaced by this relative-to-baseline normalization:
the analytical k*(base_rtt+size*8/rate) bound was non-physical here -- it undercounts A2A's per-wave
NIC serialization (slowdown 15-65) and overcounts Butterfly's short, overlapping steps (slowdown < 1).
The relative-to-baseline ratio cancels any such modeling error and is exact.)
  python3 msgsweep_figs.py --selftest   # math self-check
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

def aggregate_relative(data_dir, tag_prefix, label, ref_label, sizes, seeds, token="sz"):
    """Per-size CCT of one arm RELATIVE to a reference arm: {size:(mean_ratio, sem_ratio, min_cr)};
    omit sizes with no paired data. Reads {tag_prefix}_{label}_{token}{size}_s{seed}.flow.txt and the
    matching {ref_label} file. The ratio is computed PER SEED (same random placement / topology
    realization) = collective_makespan[label] / collective_makespan[ref_label], then mean +/- SEM over
    seeds (paired, so per-seed placement variance cancels). `min_cr` = worst completion-rate across the
    label's counted seeds; min_cr < 1 means the collective did not fully finish in some seed and the
    mean ratio is a lower bound (render marks such points hollow)."""
    out = {}
    for sz in sizes:
        ratios = []; crs = []
        for s in seeds:
            f  = os.path.join(data_dir, f"{tag_prefix}_{label}_{token}{sz}_s{s}.flow.txt")
            rf = os.path.join(data_dir, f"{tag_prefix}_{ref_label}_{token}{sz}_s{s}.flow.txt")
            if not (os.path.exists(f) and os.path.exists(rf)):
                continue
            mk, cr   = metrics.collective_makespan(f)
            rmk, _rc = metrics.collective_makespan(rf)
            if mk == mk and rmk == rmk and rmk > 0:     # both completed, ref non-zero
                ratios.append(mk / rmk)
                crs.append(cr)
        if not ratios:
            continue
        mean_r, sem_r = _sem(ratios)
        out[sz] = (mean_r, sem_r, min(crs) if crs else float("nan"))
    return out

def _size_label(b):
    """Bytes -> short binary label: 16384 -> '16K', 1048576 -> '1M'."""
    if b >= (1 << 20) and b % (1 << 20) == 0:
        return f"{b >> 20}M"
    if b >= (1 << 10) and b % (1 << 10) == 0:
        return f"{b >> 10}K"
    return str(b)

def render_relative_lines(data_dir, figs_dir, tag_prefix, baselines, ref_label, sizes, seeds,
                          fig_stem, xlabel="Message size", ylabel="CCT relative to REPS+NSCC",
                          token="sz"):
    """Line chart of collective CCT relative to the reference arm vs message size: x = message size
    (log2) with _size_label ticks, y = CCT / reference-arm CCT (linear, autoscaled; a dashed line at
    1.0 marks the reference), one errorbar line per arm with SEM. Points whose min completion-rate < 1
    are overplotted with a hollow marker. baselines = (label, display, color_key) triples. No inline
    legend (use render_legend for a shared standalone legend)."""
    import matplotlib.pyplot as plt
    plot_style.apply_style(12)
    NA = (float("nan"), 0.0, float("nan"))
    aggs = {lab: aggregate_relative(data_dir, tag_prefix, lab, ref_label, sizes, seeds, token)
            for lab, _d, _c in baselines}
    fig, ax = plt.subplots(figsize=(4.2, 3.0))
    ax.axhline(1.0, color="0.6", ls="--", lw=1.0, zorder=1)
    any_incomplete = False
    for lab, disp, ck in baselines:
        means = [aggs[lab].get(sz, NA)[0] for sz in sizes]
        sems  = [aggs[lab].get(sz, NA)[1] for sz in sizes]
        crs   = [aggs[lab].get(sz, NA)[2] for sz in sizes]
        ax.errorbar(sizes, means, yerr=sems, marker="o", ms=4, capsize=2,
                    color=plot_style.COLORS.get(ck), label=disp, zorder=3)
        hollow_x = [sz for sz, cr in zip(sizes, crs) if cr == cr and cr < 1.0]
        hollow_y = [m for m, cr in zip(means, crs) if cr == cr and cr < 1.0]
        if hollow_x:
            ax.scatter(hollow_x, hollow_y, facecolors="white",
                       edgecolors=plot_style.COLORS.get(ck), s=55, zorder=5)
            any_incomplete = True
    ax.set_xscale("log", base=2)
    ax.set_xticks(sizes); ax.set_xticklabels([_size_label(s) for s in sizes])
    ax.minorticks_off()
    ax.set_xlabel(xlabel); ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.3)
    if any_incomplete:
        ax.text(0.99, 0.03, "hollow = cr<1 (lower bound)", transform=ax.transAxes,
                ha="right", va="bottom", fontsize=6, color="0.3")
    plt.tight_layout(); plot_style.save(fig, fig_stem, figs_dir); plt.close(fig)

def render_legend(figs_dir, baselines, fig_stem):
    """Standalone shared legend (one row of arm swatches) for the message-size panels."""
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    plot_style.apply_style(12)
    handles = [Line2D([0], [0], color=plot_style.COLORS.get(ck), marker="o", ms=4, label=disp)
               for _lab, disp, ck in baselines]
    fig = plt.figure(figsize=(1.1 * len(baselines), 0.5))
    fig.legend(handles=handles, ncol=len(baselines), loc="center", frameon=False, fontsize=8)
    plot_style.save(fig, fig_stem, figs_dir); plt.close(fig)

def _write_flow(path, start_us, finish_us):
    """Write a 2-flow synthetic collective log: both flows start at start_us, finish at finish_us
    (us). collective_makespan = (finish_us - start_us) us. Used by selftest only."""
    s = start_us * 1e-6; f = finish_us * 1e-6
    with open(path, "w") as fh:
        fh.write(f"{s:.9f} Type FLOW_EVENT SrcID 1 Ev START FlowID 1 Flowsize 1000\n")
        fh.write(f"{s:.9f} Type FLOW_EVENT SrcID 2 Ev START FlowID 2 Flowsize 1000\n")
        fh.write(f"{f:.9f} Type FLOW_EVENT SrcID 1 Ev FINISH FlowID 1 Bytes 1000 Pkts 1\n")
        fh.write(f"{f:.9f} Type FLOW_EVENT SrcID 2 Ev FINISH FlowID 2 Bytes 1000 Pkts 1\n")

def selftest():
    import tempfile, shutil
    d = tempfile.mkdtemp()
    try:
        # (1) ratio math + <1 ratios (no clipping): ref makespan 1.0 ms every seed;
        #     prism makespan 2.0 ms at 16K (ratio 2.0) and 0.5 ms at 1M (ratio 0.5).
        seeds = [13, 14, 15, 16, 17]
        for s in seeds:
            _write_flow(os.path.join(d, f"expG2a2a_reps_sz16384_s{s}.flow.txt"), 1, 1001)    # 1.0 ms
            _write_flow(os.path.join(d, f"expG2a2a_reps_sz1048576_s{s}.flow.txt"), 1, 1001)  # 1.0 ms
            _write_flow(os.path.join(d, f"expG2a2a_prism_sz16384_s{s}.flow.txt"), 1, 2001)   # 2.0 ms
            _write_flow(os.path.join(d, f"expG2a2a_prism_sz1048576_s{s}.flow.txt"), 1, 501)  # 0.5 ms
        agg = aggregate_relative(d, "expG2a2a", "prism", "reps", [16384, 1048576], seeds)
        assert abs(agg[16384][0] - 2.0) < 1e-9, agg            # 2.0ms / 1.0ms
        assert abs(agg[1048576][0] - 0.5) < 1e-9, agg          # 0.5ms / 1.0ms  (ratio < 1, not clipped)
        assert agg[16384][1] == 0.0 and agg[1048576][1] == 0.0, agg   # identical seeds -> SEM 0
        assert agg[16384][2] == 1.0, agg                       # all complete -> min_cr 1.0
        ref = aggregate_relative(d, "expG2a2a", "reps", "reps", [16384, 1048576], seeds)
        assert abs(ref[16384][0] - 1.0) < 1e-9, ref            # ref / ref == 1.0

        # (2) PER-SEED pairing (not ratio-of-means): seed13 ref=1/prism=1 (r=1.0);
        #     seed14 ref=2/prism=4 (r=2.0). paired mean = 1.5; ratio-of-means = 2.5/1.5 = 1.667.
        _write_flow(os.path.join(d, "expG2bfly_reps_sz16384_s13.flow.txt"), 1, 1001)   # 1.0 ms
        _write_flow(os.path.join(d, "expG2bfly_prism_sz16384_s13.flow.txt"), 1, 1001)  # 1.0 ms  -> 1.0
        _write_flow(os.path.join(d, "expG2bfly_reps_sz16384_s14.flow.txt"), 1, 2001)   # 2.0 ms
        _write_flow(os.path.join(d, "expG2bfly_prism_sz16384_s14.flow.txt"), 1, 4001)  # 4.0 ms  -> 2.0
        p = aggregate_relative(d, "expG2bfly", "prism", "reps", [16384], [13, 14])
        assert abs(p[16384][0] - 1.5) < 1e-9, p                # paired mean (1.0+2.0)/2, NOT 1.667
        assert abs(p[16384][1] - 0.5) < 1e-9, p                # SEM of [1.0,2.0] = stdev/sqrt(2)
    finally:
        shutil.rmtree(d)
    assert _size_label(16384) == "16K" and _size_label(1048576) == "1M", "size label"
    m, se = _sem([10.0, 20.0, 30.0])
    assert abs(m - 20.0) < 1e-9 and abs(se - 10.0 / math.sqrt(3)) < 1e-9, (m, se)
    print("ok msgsweep_figs selftest")

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
