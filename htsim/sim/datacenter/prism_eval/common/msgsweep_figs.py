#!/usr/bin/env python3
"""Message-size-sweep CCT figures for prism_eval (separate module: cct_figs.py and perf_figs.py hold
uncommitted WIP and must not be touched; metrics.py is reused unchanged). Grouped bar chart of
collective CCT relative to a reference transport (REPS+NSCC, the UEC baseline) vs per-flow message
size, at a fixed failed-links level. The y-axis is a relative-CCT normalization (each arm / the
reference arm, paired per seed, then the GEOMETRIC MEAN over seeds); bars are linear from 0 with a
dashed reference line at 1.0, so a bar below 1.0 is faster than the UEC baseline.

The geometric mean is the appropriate average for normalized ratios: it is symmetric under inversion
(swapping numerator/denominator inverts it cleanly) and unbiased for multiplicative quantities, unlike
the arithmetic mean which over-weights ratios > 1. It also tames the bimodal "knee" point where a
collective step sits at ~1.5 BDP: there the per-seed ratio is bimodal and one seed-pair can land in
opposite regimes (e.g. ratios 4.95 and 0.23, near-reciprocals), which the arithmetic mean inflates but
the geometric mean cancels in log space. The spread is still reported, as a multiplicative (geometric)
SEM drawn as an asymmetric error bar.

(An earlier analytical zero-queue lower bound was replaced by this relative-to-baseline normalization:
the analytical k*(base_rtt+size*8/rate) bound was non-physical here -- it undercounts A2A's per-wave
NIC serialization (slowdown 15-65) and overcounts Butterfly's short, overlapping steps (slowdown < 1).
The relative-to-baseline ratio cancels any such modeling error and is exact.)
  python3 msgsweep_figs.py --selftest   # math self-check
"""
import os, sys, math, statistics
import matplotlib as mpl
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import metrics          # noqa: E402
import plot_style       # noqa: E402

# Keep editable TrueType text in every PDF produced by this shared renderer.
mpl.rcParams["pdf.fonttype"] = 42
mpl.rcParams["ps.fonttype"] = 42

def _geomean(v):
    """(geometric mean, lower error distance, upper error distance) of a list of POSITIVE ratios;
    NaNs and non-positive values dropped. The geometric mean is the right average for normalized
    ratios (symmetric under inversion). The spread is the geometric (multiplicative) SEM: with
    sem_log = stdev(log v)/sqrt(n), the interval is [exp(mu-sem_log), exp(mu+sem_log)], returned as
    asymmetric distances (gmean - lo, hi - gmean) so they drop straight into matplotlib yerr. Both
    distances are 0.0 for n<2 or a degenerate (all-equal) sample."""
    clean = [x for x in v if not math.isnan(x) and x > 0]
    if not clean:
        return (float("nan"), 0.0, 0.0)
    logs = [math.log(x) for x in clean]
    mu = statistics.mean(logs)
    g = math.exp(mu)
    if len(logs) < 2:
        return (g, 0.0, 0.0)
    sem_log = statistics.stdev(logs) / math.sqrt(len(logs))
    lo = math.exp(mu - sem_log); hi = math.exp(mu + sem_log)
    return (g, g - lo, hi - g)

def aggregate_relative(data_dir, tag_prefix, label, ref_label, sizes, seeds, token="sz"):
    """Per-size CCT of one arm RELATIVE to a reference arm: {size:(gmean_ratio, err_lo, err_hi,
    min_cr)}; omit sizes with no paired data. Reads {tag_prefix}_{label}_{token}{size}_s{seed}.flow.txt
    and the matching {ref_label} file. The ratio is computed PER SEED (same random placement /
    topology realization) = collective_makespan[label] / collective_makespan[ref_label], then summarized
    over seeds by the GEOMETRIC MEAN (paired, so per-seed placement variance cancels). `err_lo`/`err_hi`
    are the asymmetric geometric-SEM distances below/above the geometric mean (see _geomean). `min_cr` =
    worst completion-rate across the label's counted seeds; min_cr < 1 means the collective did not
    fully finish in some seed and the ratio is a lower bound (render marks such points hatched)."""
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
        g, elo, ehi = _geomean(ratios)
        out[sz] = (g, elo, ehi, min(crs) if crs else float("nan"))
    return out

def aggregate_slowdown_vs_best(data_dir, tag_prefix, arm_labels, sizes, seeds, token="sz"):
    """Per-size TRUE slowdown of each arm relative to the per-seed BEST (minimum-CCT) arm:
    {label:{size:(gmean, err_lo, err_hi, min_cr)}}. For each (size, seed) the denominator is the
    smallest collective makespan across all `arm_labels` present for that placement, so every ratio is
    >= 1.0 (exactly 1.0 for the winning arm that seed). Geometric mean over seeds; asymmetric
    geometric-SEM (see _geomean). Unlike aggregate_relative (which divides by a FIXED arm, REPS+NSCC),
    the reference here is the per-seed best transport, so the axis is a genuine slowdown >= 1.0 — but
    the winning arm collapses to a zero-height bar, and the per-seed min is itself noisy at the bimodal
    knee. min_cr = worst completion-rate across the arm's counted seeds."""
    out = {lab: {} for lab in arm_labels}
    for sz in sizes:
        per_seed = {}                                   # seed -> {lab: (mk, cr)}
        for s in seeds:
            d = {}
            for lab in arm_labels:
                f = os.path.join(data_dir, f"{tag_prefix}_{lab}_{token}{sz}_s{s}.flow.txt")
                if not os.path.exists(f):
                    continue
                mk, cr = metrics.collective_makespan(f)
                if mk == mk:
                    d[lab] = (mk, cr)
            if d:
                per_seed[s] = d
        for lab in arm_labels:
            ratios = []; crs = []
            for s, d in per_seed.items():
                if lab not in d:
                    continue
                mn = min(mk for mk, _c in d.values())
                if mn > 0:
                    ratios.append(d[lab][0] / mn)
                    crs.append(d[lab][1])
            if not ratios:
                continue
            g, elo, ehi = _geomean(ratios)
            out[lab][sz] = (g, elo, ehi, min(crs) if crs else float("nan"))
    return out

def _size_label(b):
    """Bytes -> short binary label: 16384 -> '16K', 1048576 -> '1M'."""
    if b >= (1 << 20) and b % (1 << 20) == 0:
        return f"{b >> 20}M"
    if b >= (1 << 10) and b % (1 << 10) == 0:
        return f"{b >> 10}K"
    return str(b)

def render_relative_bars(data_dir, figs_dir, tag_prefix, baselines, ref_label, sizes, seeds,
                         fig_stem, xlabel="Message size", ylabel="CCT relative to REPS+NSCC",
                         token="sz", ybottom=None, vs_best=False, yticks=None):
    """Grouped bar chart of collective CCT relative to the reference arm vs message size: x-axis
    groups = message sizes (_size_label ticks), one bar per arm, linear y from 0 with a dashed
    reference line at 1.0 (a bar below 1.0 is faster than the reference arm), asymmetric geometric-SEM
    error bars. A bar whose min completion-rate < 1 is hatched (lower bound). baselines = (label,
    display, color_key) triples. The legend sits above the plot frame (3-column, fontsize 10), matching
    the expF figF1_cct_bars aesthetic, so each panel is self-contained. `ybottom` (if set)
    raises the y-axis floor above 0 to zoom in on the spread near 1.0 (the top stays auto-scaled);
    every bar must lie above it or it will be clipped at the axis bottom."""
    import matplotlib.pyplot as plt
    plot_style.apply_style(16)
    NA = (float("nan"), 0.0, 0.0, float("nan"))
    if vs_best:    # genuine slowdown vs the per-seed best arm (>=1.0); the winner is a zero bar
        aggs = aggregate_slowdown_vs_best(data_dir, tag_prefix,
                                          [lab for lab, _d, _c in baselines], sizes, seeds, token)
    else:          # ratio to a fixed reference arm (REPS+NSCC); values may be <1.0
        aggs = {lab: aggregate_relative(data_dir, tag_prefix, lab, ref_label, sizes, seeds, token)
                for lab, _d, _c in baselines}
    fig, ax = plt.subplots(figsize=(6.4, 2.8))   # common size shared with figF1_cct_bars
    n = len(baselines); group_w = 0.82; bw = group_w / n
    x = list(range(len(sizes)))
    any_incomplete = False
    for j, (lab, disp, ck) in enumerate(baselines):
        means = [aggs[lab].get(sz, NA)[0] for sz in sizes]
        elos  = [aggs[lab].get(sz, NA)[1] for sz in sizes]
        ehis  = [aggs[lab].get(sz, NA)[2] for sz in sizes]
        crs   = [aggs[lab].get(sz, NA)[3] for sz in sizes]
        offs  = [xi - group_w / 2 + bw * (j + 0.5) for xi in x]
        bars = ax.bar(offs, means, bw, yerr=[elos, ehis], capsize=2,
                      color=plot_style.COLORS.get(ck), label=disp)
        for bar, cr in zip(bars, crs):
            if cr == cr and cr < 1.0:           # incomplete -> lower bound
                bar.set_hatch("///"); any_incomplete = True
    if ybottom is None or ybottom < 0.999:   # light reference at y=1 (the bold "1" tick carries it)
        ax.axhline(1.0, color="0.5", ls="--", lw=0.9, zorder=4)
    ax.set_xticks(x); ax.set_xticklabels([_size_label(s) for s in sizes])
    ax.set_xlabel(xlabel); ax.set_ylabel(ylabel)
    ax.grid(axis="y", alpha=0.3)
    if ybottom is not None:
        ax.set_ylim(bottom=ybottom)
    if ybottom is None or ybottom < 0.999:   # show a clean "1" on the y-axis (no decimals)
        lo, hi = ax.get_ylim()
        yt = yticks if yticks is not None else list(ax.get_yticks())
        yt = [t for t in yt if lo - 1e-9 <= t <= hi + 1e-9]
        ax.set_yticks(yt)
        ax.set_yticklabels(["%g" % t for t in yt])
    if any_incomplete:
        ax.text(0.99, 0.97, "/// = cr<1 (lower bound)", transform=ax.transAxes,
                ha="right", va="top", fontsize=6, color="0.3")
    plt.tight_layout(); plot_style.save(fig, fig_stem, figs_dir); plt.close(fig)

def render_legend(figs_dir, baselines, fig_stem, figure_width=None, figure_height=0.5,
                  pad_inches=None):
    """Standalone shared legend (one row of arm color patches) for the message-size bar panels."""
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    plot_style.apply_style(12)
    handles = [Patch(facecolor=plot_style.COLORS.get(ck), label=disp)
               for _lab, disp, ck in baselines]
    fig = plt.figure(figsize=(figure_width or 1.6 * len(baselines), figure_height))
    fig.legend(handles=handles, ncol=len(baselines), loc="center", frameon=False, fontsize=13)
    if pad_inches is None:
        plot_style.save(fig, fig_stem, figs_dir)
    else:
        os.makedirs(figs_dir, exist_ok=True)
        for ext in ("png", "pdf"):
            fig.savefig(os.path.join(figs_dir, f"{fig_stem}.{ext}"), bbox_inches="tight",
                        pad_inches=pad_inches)
    plt.close(fig)

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
        assert abs(agg[16384][0] - 2.0) < 1e-9, agg            # geomean(2.0 x5) = 2.0ms / 1.0ms
        assert abs(agg[1048576][0] - 0.5) < 1e-9, agg          # geomean(0.5 x5) = 0.5  (ratio < 1, not clipped)
        assert agg[16384][1] == 0.0 and agg[16384][2] == 0.0, agg     # identical seeds -> 0 spread both sides
        assert agg[16384][3] == 1.0, agg                       # all complete -> min_cr 1.0
        ref = aggregate_relative(d, "expG2a2a", "reps", "reps", [16384, 1048576], seeds)
        assert abs(ref[16384][0] - 1.0) < 1e-9, ref            # ref / ref == 1.0

        # (2) GEOMETRIC mean of per-seed ratios (not arithmetic, not ratio-of-means): seed13 r=1.0,
        #     seed14 r=2.0. geomean = sqrt(1*2) = 1.41421; arithmetic = 1.5; ratio-of-means = 2.5/1.5.
        _write_flow(os.path.join(d, "expG2bfly_reps_sz16384_s13.flow.txt"), 1, 1001)   # 1.0 ms
        _write_flow(os.path.join(d, "expG2bfly_prism_sz16384_s13.flow.txt"), 1, 1001)  # 1.0 ms  -> 1.0
        _write_flow(os.path.join(d, "expG2bfly_reps_sz16384_s14.flow.txt"), 1, 2001)   # 2.0 ms
        _write_flow(os.path.join(d, "expG2bfly_prism_sz16384_s14.flow.txt"), 1, 4001)  # 4.0 ms  -> 2.0
        p = aggregate_relative(d, "expG2bfly", "prism", "reps", [16384], [13, 14])
        assert abs(p[16384][0] - math.sqrt(2.0)) < 1e-9, p     # geomean sqrt(1*2)=1.414, NOT amean 1.5
        # geometric-SEM interval of [1.0,2.0] works out to exactly [1.0, 2.0]:
        assert abs(p[16384][1] - (math.sqrt(2.0) - 1.0)) < 1e-9, p   # err_lo = gmean - 1.0
        assert abs(p[16384][2] - (2.0 - math.sqrt(2.0))) < 1e-9, p   # err_hi = 2.0 - gmean

        # (3) reciprocal outliers CANCEL in the geometric mean (the bimodal-knee fix): ratios 4.0 and
        #     0.25 (= 1/4) -> geomean exactly 1.0, where the arithmetic mean would be 2.125.
        g, _lo, _hi = _geomean([4.0, 0.25])
        assert abs(g - 1.0) < 1e-9, g
    finally:
        shutil.rmtree(d)
    assert _size_label(16384) == "16K" and _size_label(1048576) == "1M", "size label"
    g2, _l, _h = _geomean([2.0, 8.0])
    assert abs(g2 - 4.0) < 1e-9, g2                            # sqrt(2*8) = 4
    print("ok msgsweep_figs selftest")

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
