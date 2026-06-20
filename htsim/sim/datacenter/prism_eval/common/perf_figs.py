#!/usr/bin/env python3
"""Generic performance + mechanism figures for prism_eval experiment groups (Experiment A and
its variants). Parameterized by data dir, figs dir, baselines, tag prefix, and the failed/seed
sets, so each group's make_figs.py is a thin wrapper. Reads logs via metrics.py; styles via
plot_style.py. Baselines are (label, display, color_key) triples; files are named
{tag_prefix}_{label}_f{failed}_s{seed}.flow.txt and {tag_prefix}_{label}_mech.* ."""
import os, sys, statistics, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import metrics          # noqa: E402
import plot_style       # noqa: E402

def _ms(v):
    """(mean, population std) of a non-empty list -- population std: full fixed seed set.
    NaN values (e.g. FCT from zero-completion seeds) are dropped before stats; if all NaN,
    returns (nan, 0.0) so the figure can still render the cr=0 points without crashing."""
    import math
    clean = [x for x in v if not math.isnan(x)]
    if not clean:
        return (float("nan"), 0.0)
    return (statistics.mean(clean), statistics.pstdev(clean))

def _mech_label(mech_label, mech_failed):
    """Label for the mechanism figure's stressor. Defaults to the legacy `-failed=N` form
    (so expA output is byte-identical); pass an explicit label for non-failure stressors
    (oversub ratio, incast fan-in)."""
    return mech_label if mech_label else f"-failed={mech_failed}"

def _cwnd_series(path, bin_ns=20000):
    """Per-flow-averaged cwnd (KB) binned in time from a PRISM_PATHRTT csv; returns
    (times_ms, cwnd_kb). The series ends at the last RTT sample = the arm's makespan."""
    acc = collections.defaultdict(list)
    with open(path) as fh:
        for ln in fh:
            p = ln.strip().split(",")
            if len(p) < 6:
                continue
            acc[int(p[0]) // bin_ns].append(int(p[5]))
    xs = sorted(acc)
    return [b * bin_ns / 1e6 for b in xs], [sum(acc[b]) / len(acc[b]) / 1024.0 for b in xs]

def _read_mnscc_median(path, bin_us=20):
    """Read an MNSCC median CSV (time_ns,flow_id,median_ns); return (times_ms, median_us)
    averaged into bin_us-wide time bins. Used to overlay MNSCC's median delay on the signal panel."""
    acc = collections.defaultdict(list)
    with open(path) as fh:
        for ln in fh:
            p = ln.strip().split(",")
            if len(p) < 3:
                continue
            acc[int(p[0]) // (bin_us * 1000)].append(int(p[2]) / 1000.0)  # ns->us
    xs = sorted(acc)
    return [(b + 0.5) * bin_us / 1000.0 for b in xs], [sum(acc[b]) / len(acc[b]) for b in xs]  # x in ms

def _bin_series(xs, ys, bin_w):
    """Bin (xs, ys) into width-`bin_w` buckets on x; return (bucket_mid_x, mean_y). Used as a
    display-only smoother for the otherwise-unsmoothed per-epoch Prism C_cc signal."""
    acc = collections.defaultdict(list)
    for x, y in zip(xs, ys):
        acc[int(x / bin_w)].append(y)
    bs = sorted(acc)
    return [(b + 0.5) * bin_w for b in bs], [sum(acc[b]) / len(acc[b]) for b in bs]

def _read_target_us(data_dir, tag_prefix, fallback_us):
    """Read the runtime _target_Qdelay (picoseconds) from the PRISM mechanism stdout and return
    microseconds. initNsccParams sets the target to one network RTT (~14us), overriding the 6us
    static default, so the figure's target line must reflect the real value, not a constant."""
    path = os.path.join(data_dir, f"{tag_prefix}_prism_mech.stdout")
    try:
        with open(path) as fh:
            for ln in fh:
                i = ln.find("_target_Qdelay=")
                if i >= 0:
                    tok = ln[i + len("_target_Qdelay="):].split()[0]
                    return float(tok) / 1e6   # ps -> us
    except (OSError, ValueError, IndexError):
        pass
    return fallback_us

def aggregate(data_dir, tag_prefix, label, failed, seeds, token="f"):
    """Per-failed aggregates for one baseline: {f: {metric:(mean,std)}}; omit f with no data.
    `token` is the filename sweep prefix ('f' for -failed sweeps, 'L' for offered-load)."""
    out = {}
    for f in failed:
        g, afct, p99, cr = [], [], [], []
        for s in seeds:
            flow = os.path.join(data_dir, f"{tag_prefix}_{label}_{token}{f}_s{s}.flow.txt")
            if not os.path.exists(flow):
                continue
            st = metrics.fct_stats(flow)
            g.append(metrics.aggregate_goodput_gbps(flow))
            afct.append(st["avg_s"] * 1e6)
            p99.append(st["p99_s"] * 1e6)
            cr.append(st["completion_rate"])
        if not g:
            continue
        out[f] = {"goodput": _ms(g), "avg_fct": _ms(afct), "p99_fct": _ms(p99), "cr": _ms(cr)}
    return out

def render_main_perf(data_dir, figs_dir, tag_prefix, baselines, failed, seeds, fig_stem, xlabel, token="f"):
    """3 panels (goodput / avg-FCT us / P99-FCT us) vs `failed`, one line per baseline + error bars."""
    import matplotlib.pyplot as plt
    plot_style.apply_style(13)
    aggs = {lab: aggregate(data_dir, tag_prefix, lab, failed, seeds, token) for (lab, _d, _c) in baselines}
    fig, axes = plt.subplots(3, 1, figsize=(5.2, 8.0), sharex=True)
    panels = [("goodput", "Goodput (Gbps)"), ("avg_fct", "Avg FCT (us)"), ("p99_fct", "P99 FCT (us)")]
    for ax, (key, ylabel) in zip(axes, panels):
        for (lab, disp, ck) in baselines:
            xs = [f for f in failed if aggs[lab].get(f)]
            ys = [aggs[lab][f][key][0] for f in xs]
            es = [aggs[lab][f][key][1] for f in xs]
            ax.errorbar(xs, ys, yerr=es, marker="o", lw=2.0, ms=6, capsize=3,
                        color=plot_style.COLORS[ck], label=disp)
        ax.set_ylabel(ylabel)
        ax.grid(alpha=0.3)
    axes[0].legend(fontsize=9)
    axes[-1].set_xlabel(xlabel)
    axes[-1].set_xticks(failed)
    incomplete = []
    for (lab, _d, _c) in baselines:
        for f in failed:
            cell = aggs[lab].get(f)
            if cell and cell["cr"][0] < 0.999:
                incomplete.append((lab, f, cell["cr"][0]))
    if incomplete:
        note = "completion<1: " + ", ".join(f"{lab}@f{f}={cr:.2f}" for lab, f, cr in incomplete)
        fig.text(0.5, 0.005, note, ha="center", fontsize=7, color="firebrick")
    plt.tight_layout()
    plot_style.save(fig, fig_stem, figs_dir)
    plt.close(fig)
    for (lab, disp, _c) in baselines:
        print(f"[{fig_stem}] {disp}: " + " ".join(
            f"{token}{f}:g={aggs[lab][f]['goodput'][0]:.1f},avgfct={aggs[lab][f]['avg_fct'][0]:.0f}us,"
            f"cr={aggs[lab][f]['cr'][0]:.2f}" for f in failed if aggs[lab].get(f)))

def render_main_perf_split(data_dir, figs_dir, tag_prefix, baselines, failed, seeds, stem_prefix, xlabel, token="f", goodput_tbps=False):
    """Same data as render_main_perf, but emits THREE standalone figures (one metric each):
    `{stem_prefix}_goodput` (Gbps), `{stem_prefix}_avg_fct` (ms), `{stem_prefix}_p99_fct` (ms).
    aggregate() stores FCT in microseconds, so the two FCT panels scale by 1e-3 -> milliseconds."""
    import matplotlib.pyplot as plt
    plot_style.apply_style(24)
    aggs = {lab: aggregate(data_dir, tag_prefix, lab, failed, seeds, token) for (lab, _d, _c) in baselines}
    panels = [("goodput", "Goodput (Gbps)", "goodput", 1.0),
              ("avg_fct", "Avg FCT (ms)", "avg_fct", 1e-3),
              ("p99_fct", "P99 FCT (ms)", "p99_fct", 1e-3)]
    for key, ylabel, suffix, scale in panels:
        if goodput_tbps and key == "goodput":   # goodput in Tbps with plain ticks (no scientific notation)
            ylabel, scale = "Goodput (Tbps)", 1e-3
        fig, ax = plt.subplots(1, 1, figsize=(5.2, 3.8))
        for (lab, disp, ck) in baselines:
            xs = [f for f in failed if aggs[lab].get(f)]
            ys = [aggs[lab][f][key][0] * scale for f in xs]
            es = [aggs[lab][f][key][1] * scale for f in xs]
            ax.errorbar(xs, ys, yerr=es, marker="o", lw=2.0, ms=6, capsize=3,
                        color=plot_style.COLORS[ck], label=disp)
        ax.set_ylabel(ylabel)
        ax.set_xlabel(xlabel)
        if key == "goodput":
            ax.yaxis.set_label_coords(-0.2, 0.45)
            ax.xaxis.label.set_x(0.45)
        ax.set_xticks(failed)
        ax.grid(alpha=0.3)
        # ax.legend(fontsize=9)
        incomplete = [(lab, f, aggs[lab][f]["cr"][0]) for (lab, _d, _c) in baselines
                      for f in failed if aggs[lab].get(f) and aggs[lab][f]["cr"][0] < 0.999]
        if incomplete:
            note = "completion<1: " + ", ".join(f"{lab}@f{f}={cr:.2f}" for lab, f, cr in incomplete)
            fig.text(0.5, 0.005, note, ha="center", fontsize=7, color="firebrick")
        plt.tight_layout()
        plot_style.save(fig, f"{stem_prefix}_{suffix}", figs_dir)
        plt.close(fig)
    for (lab, disp, _c) in baselines:
        print(f"[{stem_prefix}] {disp}: " + " ".join(
            f"{token}{f}:g={aggs[lab][f]['goodput'][0]:.1f},avgfct={aggs[lab][f]['avg_fct'][0] / 1000:.3f}ms,"
            f"p99={aggs[lab][f]['p99_fct'][0] / 1000:.3f}ms,cr={aggs[lab][f]['cr'][0]:.2f}"
            for f in failed if aggs[lab].get(f)))

def render_legend(figs_dir, baselines, fig_stem, ncol=None, row_counts=None):
    """Standalone legend image of the baseline arms, matching the line style of
    render_main_perf_split (marker 'o', lw 2.0, ms 6, per-arm color). Saves {fig_stem}.{png,pdf}
    (legend only, tight-cropped). Default: one row (ncol=len(baselines)). Pass row_counts=[3,4]
    to stack rows of those sizes, each row horizontally centered (so the rows share a centerline)."""
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.legend import Legend
    plot_style.apply_style(10)
    handles = [Line2D([], [], marker="o", lw=2.0, ms=6, color=plot_style.COLORS[ck], label=disp)
               for (lab, disp, ck) in baselines]
    if row_counts:
        n = len(row_counts)
        fig = plt.figure(figsize=(2.6 * max(row_counts), 0.42 * n))   # short -> rows close; tight-crop trims
        ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
        i = 0
        for r, cnt in enumerate(row_counts):
            row = handles[i:i + cnt]; i += cnt
            y = 1.0 - (r + 0.5) / n   # rows top-to-bottom; each row centered on x=0.5 -> shared centerline
            leg = Legend(ax, row, [h.get_label() for h in row], ncol=cnt, loc="center",
                         bbox_to_anchor=(0.5, y), bbox_transform=ax.transAxes, frameon=False, fontsize=20,
                         handlelength=1.4, handletextpad=0.4, columnspacing=1.0, borderpad=0.1, borderaxespad=0.0)
            ax.add_artist(leg)
        desc = f"rows={row_counts}, centered"
    else:
        fig = plt.figure(figsize=(0.12, 0.1))
        fig.legend(handles=handles, ncol=(ncol or len(baselines)), loc="center", frameon=False, fontsize=20)
        desc = f"ncol={ncol or len(baselines)}, single row"
    os.makedirs(figs_dir, exist_ok=True)
    for ext in ("png", "pdf"):   # tighter crop than plot_style.save (pad 0.02 vs 0.04) for a compact legend
        fig.savefig(os.path.join(figs_dir, f"{fig_stem}.{ext}"), bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)
    print(f"[{fig_stem}] standalone legend: {len(handles)} entries, {desc}")

def render_fairness(data_dir, figs_dir, tag_prefix, baselines, failed, seeds, fig_stem, xlabel, token="f"):
    """Standalone Jain-fairness figure: fairness vs `failed`, one line per baseline + error bars.
    Self-aggregating (computes metrics.jain_fairness in its own loop) -- does NOT touch aggregate()
    or render_main_perf, so existing figures are unaffected. Skips cells with <2 completed flows."""
    import matplotlib.pyplot as plt
    plot_style.apply_style(13)
    def _fair(lab, f):
        vals = []
        for s in seeds:
            fp = os.path.join(data_dir, f"{tag_prefix}_{lab}_{token}{f}_s{s}.flow.txt")
            if not os.path.exists(fp):
                continue
            j = metrics.jain_fairness(fp)
            if j == j:   # not nan
                vals.append(j)
        return vals
    fig, ax = plt.subplots(1, 1, figsize=(5.2, 3.4))
    for (lab, disp, ck) in baselines:
        xs, ys, es = [], [], []
        for f in failed:
            vals = _fair(lab, f)
            if vals:
                xs.append(f); ys.append(statistics.mean(vals)); es.append(statistics.pstdev(vals))
        if xs:
            ax.errorbar(xs, ys, yerr=es, marker="o", lw=2.0, ms=6, capsize=3,
                        color=plot_style.COLORS[ck], label=disp)
    ax.set_ylabel("Jain fairness index"); ax.set_xlabel(xlabel)
    ax.set_xticks(failed); ax.grid(alpha=0.3); ax.legend(fontsize=9)
    plt.tight_layout()
    plot_style.save(fig, fig_stem, figs_dir)
    plt.close(fig)
    for (lab, disp, _c) in baselines:
        cells = [(f, statistics.mean(v)) for f in failed for v in [_fair(lab, f)] if v]
        print(f"[{fig_stem}] {disp}: " + " ".join(f"{token}{f}:{m:.3f}" for f, m in cells))

def render_mechanism_split(data_dir, figs_dir, tag_prefix, stem_prefix, mech_failed,
                           target_us=6.0, base_ns=13945, mech_label=None, xlim_ms=None):
    """Two STANDALONE mechanism figures (paper version of render_mechanism):
      `{stem_prefix}_signal` -- the queuing-delay signal each controller acts on: REPS+NSCC avg,
        STrack avg (both averaging families), the floor REPS+NSCC ignores, and Prism's per-epoch
        floor C_cc (raw faint + a 20us-binned overlay), vs the target line. Prism's C_cc is an
        unsmoothed per-epoch min BY DESIGN (O(1)); the binned line is a display aid only.
      `{stem_prefix}_cwnd` -- cwnd(t) for the three arms, with a marker at each arm's last sample
        (= workload makespan), so the differing line lengths read as 'when each scheme finishes'.
    Also prints the fair per-ACK cut counts, floor-MD fraction, and STrack distinctness."""
    import matplotlib.pyplot as plt
    reps_pr = os.path.join(data_dir, f"{tag_prefix}_reps_mech.pathrtt.csv")
    prism_pr = os.path.join(data_dir, f"{tag_prefix}_prism_mech.pathrtt.csv")
    prism_ep = os.path.join(data_dir, f"{tag_prefix}_prism_mech.epoch.csv")
    strack_pr = os.path.join(data_dir, f"{tag_prefix}_strack_mech.pathrtt.csv")
    if not (os.path.exists(reps_pr) and os.path.exists(prism_ep)):
        print(f"[{stem_prefix}] mechanism logs missing; skipping")
        return
    lbl = _mech_label(mech_label, mech_failed)
    target_us = _read_target_us(data_dir, tag_prefix, target_us)
    plot_style.apply_style(13)

    # --- Figure 1: control signal ---
    figS, axs = plt.subplots(1, 1, figsize=(6.4, 3.8))
    bins = metrics.qdelay_bins(reps_pr, base_ns=base_ns, bin_us=20)
    if bins:
        t = [b[0] / 1000.0 for b in bins]
        axs.plot(t, [b[2] for b in bins], color=plot_style.COLORS["reps"], lw=2.0, label="REPS+NSCC avg delay")
        axs.plot(t, [b[1] for b in bins], color=plot_style.COLORS["reps"], lw=1.2, ls=":", label="REPS+NSCC floor (ignored)")
    if os.path.exists(strack_pr):
        sb = metrics.qdelay_bins(strack_pr, base_ns=base_ns, bin_us=20)
        if sb:
            axs.plot([b[0] / 1000.0 for b in sb], [b[2] for b in sb],
                     color=plot_style.COLORS["strack"], lw=2.0, label="STrack avg delay")
    mnscc_med = os.path.join(data_dir, f"{tag_prefix}_mnscc_mech.median.csv")
    if os.path.exists(mnscc_med):
        mt, mu = _read_mnscc_median(mnscc_med, bin_us=20)
        if mt:
            axs.plot(mt, mu, color=plot_style.COLORS["mnscc"], lw=2.0, label="MNSCC median delay")
    ep = metrics.parse_prism_epoch(prism_ep)
    if ep:
        te = [r["time_ns"] / 1e6 for r in ep]; cc = [r["c_cc_ns"] / 1000.0 for r in ep]
        axs.plot(te, cc, color=plot_style.COLORS["prism"], lw=0.7, alpha=0.25, label="Prism C_cc (raw per-epoch)")
        bx, by = _bin_series(te, cc, 0.02)   # 20us-binned mean -- display aid only
        axs.plot(bx, by, color=plot_style.COLORS["prism"], lw=2.2, label="Prism C_cc (20us-binned)")
    axs.axhline(target_us, color=plot_style.COLORS["target"], ls="--", lw=1.3, label=f"target ({target_us:.1f}us = 1 RTT)")
    axs.set_xlabel("time (ms)"); axs.set_ylabel("Queuing delay (us)")
    axs.set_title(f"Mechanism @ {lbl}: control signal", fontsize=11)
    axs.grid(alpha=0.3); axs.legend(fontsize=8, ncol=2)
    if xlim_ms:
        axs.set_xlim(0, xlim_ms)
    plt.tight_layout(); plot_style.save(figS, f"{stem_prefix}_signal", figs_dir); plt.close(figS)

    # --- Figure 2: cwnd, with makespan endpoint markers ---
    figC, axc = plt.subplots(1, 1, figsize=(6.4, 3.8))
    makespans = []
    for ck, disp, path in [("reps", "REPS+NSCC", reps_pr), ("prism", "Prism", prism_pr),
                           ("strack", "STrack", strack_pr),
                           ("mnscc", "MNSCC", os.path.join(data_dir, f"{tag_prefix}_mnscc_mech.pathrtt.csv")),
                           ("swift", "Swift", os.path.join(data_dir, f"{tag_prefix}_swift_mech.pathrtt.csv")),
                           ("mswift", "MSwift", os.path.join(data_dir, f"{tag_prefix}_mswift_mech.pathrtt.csv"))]:
        if not os.path.exists(path):
            continue
        xs, ys = _cwnd_series(path)
        if not xs:
            continue
        axc.plot(xs, ys, color=plot_style.COLORS[ck], lw=2.0, label=disp)
        axc.plot(xs[-1], ys[-1], marker="o", ms=9, color=plot_style.COLORS[ck], zorder=5)  # makespan
        makespans.append((disp, xs[-1]))
    reps_dec = metrics.count_cwnd_cuts_from_pathrtt(reps_pr)
    prism_dec = metrics.count_cwnd_cuts_from_pathrtt(prism_pr) if os.path.exists(prism_pr) else -1
    strack_dec = metrics.count_cwnd_cuts_from_pathrtt(strack_pr) if os.path.exists(strack_pr) else -1
    mnscc_pr = os.path.join(data_dir, f"{tag_prefix}_mnscc_mech.pathrtt.csv")
    mnscc_dec = metrics.count_cwnd_cuts_from_pathrtt(mnscc_pr) if os.path.exists(mnscc_pr) else -1
    mnscc_part = f", MNSCC {mnscc_dec}" if mnscc_dec != -1 else ""
    swift_pr = os.path.join(data_dir, f"{tag_prefix}_swift_mech.pathrtt.csv")
    swift_dec = metrics.count_cwnd_cuts_from_pathrtt(swift_pr) if os.path.exists(swift_pr) else -1
    swift_part = f", Swift {swift_dec}" if swift_dec != -1 else ""
    mswift_pr = os.path.join(data_dir, f"{tag_prefix}_mswift_mech.pathrtt.csv")
    mswift_dec = metrics.count_cwnd_cuts_from_pathrtt(mswift_pr) if os.path.exists(mswift_pr) else -1
    mswift_part = f", MSwift {mswift_dec}" if mswift_dec != -1 else ""
    axc.text(0.02, 0.97, f"rate reductions (per-ACK cwnd cuts): Prism {prism_dec}, "
             f"REPS+NSCC {reps_dec}, STrack {strack_dec}{mnscc_part}{swift_part}{mswift_part}", transform=axc.transAxes, fontsize=7,
             va="top", bbox=dict(boxstyle="round", fc="white", ec="gray", alpha=0.85))
    axc.set_xlabel("time (ms)"); axc.set_ylabel("cwnd (KB, mean/flow)")
    axc.set_title(f"Mechanism @ {lbl}: cwnd", fontsize=11)
    axc.grid(alpha=0.3); axc.legend(fontsize=9)
    if xlim_ms:
        axc.set_xlim(0, xlim_ms)
    if makespans:
        note = "makespan (last flow finishes): " + ",  ".join(f"{d} {m:.2f}ms" for d, m in makespans)
        figC.text(0.5, 0.005, note, ha="center", fontsize=8, color="dimgray")
    plt.tight_layout(); plot_style.save(figC, f"{stem_prefix}_cwnd", figs_dir); plt.close(figC)

    # --- diagnostics (identical metrics to render_mechanism) ---
    if not ep:
        print(f"[{stem_prefix}] WARNING: prism epoch log empty -- floor-MD fraction unreliable")
    prism_md = sum(r["cut"] for r in ep)
    frac = (prism_md / prism_dec) if prism_dec > 0 else float("nan")
    print(f"[{stem_prefix}] cwnd-decrease events @{lbl} (FAIR, per-ACK): Prism={prism_dec}  REPS+NSCC={reps_dec}")
    print(f"[{stem_prefix}] floor-MD fraction = Prism epoch-MDs / Prism cwnd-decreases = "
          f"{prism_md}/{prism_dec} = {frac:.3f}  (trimming baseline was ~0.05)")
    if os.path.exists(strack_pr):
        print(f"[{stem_prefix}] DISTINCTNESS (per-ACK cwnd-decreases @{lbl}): "
              f"STrack={strack_dec}  REPS+NSCC={reps_dec}")

def render_decomposition(data_dir, figs_dir, tag_prefix, cells, fig_stem,
                         seed=13, bin_w_ms=0.02, xlim_ms=None, ylim_us=None):
    """PRISM's two decomposed signals as time series, one panel per cell.
    `cells` = [(failed, panel_label), ...]. Reads {tag_prefix}_prism_f{failed}_s{seed}.epoch.csv
    and plots, per panel: faint raw + bold 20us-binned C_cc (floor->CC) and C_spray (spread->spray),
    a target line at ~1 RTT (base_rtt), and a mean-C_spray annotation (us)."""
    import matplotlib.pyplot as plt
    plot_style.apply_style(13)
    n = len(cells)
    fig, axes = plt.subplots(1, n, figsize=(5.5 * n, 4.0), sharey=True)
    if n == 1:
        axes = [axes]
    for ax, (failed, label) in zip(axes, cells):
        path = os.path.join(data_dir, f"{tag_prefix}_prism_f{failed}_s{seed}.epoch.csv")
        ep = metrics.parse_prism_epoch(path) if os.path.exists(path) else []
        if not ep:
            ax.set_title(f"{label}\n(no data)", fontsize=11); ax.set_xlabel("time (ms)"); continue
        te = [r["time_ns"] / 1e6 for r in ep]        # ms
        cc = [r["c_cc_ns"] / 1000.0 for r in ep]      # us
        sp = [r["c_spray_ns"] / 1000.0 for r in ep]   # us
        base_us = ep[0]["base_rtt_ns"] / 1000.0       # ~14 us
        ax.plot(te, cc, color=plot_style.COLORS["ccc"], lw=0.6, alpha=0.20)
        ax.plot(te, sp, color=plot_style.COLORS["spray"], lw=0.6, alpha=0.20)
        bx, bcc = _bin_series(te, cc, bin_w_ms)
        ax.plot(bx, bcc, color=plot_style.COLORS["ccc"], lw=2.2, label="C_cc (floor -> CC)")
        sx, bsp = _bin_series(te, sp, bin_w_ms)
        ax.plot(sx, bsp, color=plot_style.COLORS["spray"], lw=2.2, label="C_spray (spread -> spray)")
        ax.axhline(base_us, color=plot_style.COLORS["target"], ls="--", lw=1.3,
                   label=f"target (~1 RTT, {base_us:.0f}us)")
        ax.text(0.97, 0.95, f"mean C_spray: {sum(sp)/len(sp):.0f} us",
                transform=ax.transAxes, ha="right", va="top", fontsize=9,
                bbox=dict(boxstyle="round", fc="white", alpha=0.7))
        ax.set_title(label, fontsize=11); ax.set_xlabel("time (ms)"); ax.grid(alpha=0.3)
        if xlim_ms:
            ax.set_xlim(0, xlim_ms)
    axes[0].set_ylabel("Queuing delay (us)")
    axes[0].legend(fontsize=8, loc="upper left")
    if ylim_us is not None:
        axes[0].set_ylim(0, ylim_us)
    plt.tight_layout(); plot_style.save(fig, fig_stem, figs_dir); plt.close(fig)

def render_decomposition_merged(figs_dir, fig_stem, panels, ylim_us=None, bin_w_ms=0.02):
    """Merged PRISM decomposition: overlay scales per panel (solid vs dashed), 20us-binned only
    (no faint raw). `panels` = [(panel_title, [(data_dir, tag_prefix, failed, seed, ls, series_label), ...])].
    Color encodes the signal (C_cc red / C_spray green); linestyle encodes the scale."""
    import matplotlib.pyplot as plt
    plot_style.apply_style(13)
    n = len(panels)
    fig, axes = plt.subplots(1, n, figsize=(5.5 * n, 4.0), sharey=True)
    if n == 1:
        axes = [axes]
    for ax, (title, series) in zip(axes, panels):
        base_us = None
        for (data_dir, tag_prefix, failed, seed, ls, slabel) in series:
            path = os.path.join(data_dir, f"{tag_prefix}_prism_f{failed}_s{seed}.epoch.csv")
            ep = metrics.parse_prism_epoch(path) if os.path.exists(path) else []
            if not ep:
                continue
            te = [r["time_ns"] / 1e6 for r in ep]
            cc = [r["c_cc_ns"] / 1000.0 for r in ep]
            sp = [r["c_spray_ns"] / 1000.0 for r in ep]
            base_us = ep[0]["base_rtt_ns"] / 1000.0
            bx, bcc = _bin_series(te, cc, bin_w_ms)
            ax.plot(bx, bcc, color=plot_style.COLORS["ccc"], lw=2.2, ls=ls, label=f"C_cc {slabel}")
            sx, bsp = _bin_series(te, sp, bin_w_ms)
            ax.plot(sx, bsp, color=plot_style.COLORS["spray"], lw=2.2, ls=ls, label=f"C_spray {slabel}")
        if base_us is not None:
            ax.axhline(base_us, color=plot_style.COLORS["target"], ls=":", lw=1.3,
                       label=f"target (~1 RTT, {base_us:.0f}us)")
        ax.set_title(title, fontsize=11); ax.set_xlabel("time (ms)"); ax.grid(alpha=0.3)
        if ylim_us is not None:
            ax.set_ylim(0, ylim_us)
    axes[0].set_ylabel("Queuing delay (us)")
    axes[0].legend(fontsize=7, loc="upper left")
    plt.tight_layout(); plot_style.save(fig, fig_stem, figs_dir); plt.close(fig)

def render_mechanism(data_dir, figs_dir, tag_prefix, fig_stem, mech_failed, target_us=6.0, base_ns=13945, mech_label=None):
    """Mechanism @ mech_failed: (a) REPS+NSCC avg/floor vs PRISM floor C_cc vs target;
    (b) cwnd(t) PRISM vs REPS+NSCC. Prints fair per-ACK cut counts + the floor-MD fraction
    (PRISM epoch-MDs / PRISM total cwnd-decreases) -- the 'is it delay-driven now?' metric."""
    import matplotlib.pyplot as plt
    plot_style.apply_style(13)
    reps_pr = os.path.join(data_dir, f"{tag_prefix}_reps_mech.pathrtt.csv")
    prism_pr = os.path.join(data_dir, f"{tag_prefix}_prism_mech.pathrtt.csv")
    prism_ep = os.path.join(data_dir, f"{tag_prefix}_prism_mech.epoch.csv")
    # reps_pr + prism_ep are required; prism_pr (PRISM cwnd panel + floor-MD fraction) is optional.
    if not (os.path.exists(reps_pr) and os.path.exists(prism_ep)):
        print(f"[{fig_stem}] mechanism logs missing; skipping")
        return
    lbl = _mech_label(mech_label, mech_failed)
    target_us = _read_target_us(data_dir, tag_prefix, target_us)
    fig, (ax_sig, ax_cw) = plt.subplots(2, 1, figsize=(5.2, 6.0), sharex=True)
    bins = metrics.qdelay_bins(reps_pr, base_ns=base_ns, bin_us=20)
    if bins:
        t = [b[0] / 1000.0 for b in bins]; mn = [b[1] for b in bins]; av = [b[2] for b in bins]  # x: us -> ms
        ax_sig.plot(t, av, color=plot_style.COLORS["reps"], lw=2.0, label="REPS+NSCC avg delay")
        ax_sig.plot(t, mn, color=plot_style.COLORS["reps"], lw=1.3, ls=":", label="REPS+NSCC floor (ignored)")
    ep = metrics.parse_prism_epoch(prism_ep)
    if ep:
        te = [r["time_ns"] / 1e6 for r in ep]; cc = [r["c_cc_ns"] / 1000.0 for r in ep]  # x: ns -> ms
        ax_sig.plot(te, cc, color=plot_style.COLORS["prism"], lw=2.0, label="Prism floor C_cc")
    ax_sig.axhline(target_us, color=plot_style.COLORS["target"], ls="--", lw=1.3, label=f"target ({target_us:.1f}us = 1 RTT)")
    ax_sig.set_ylabel("Queuing delay (us)")
    ax_sig.set_title(f"Mechanism @ {lbl}", fontsize=11)
    ax_sig.grid(alpha=0.3); ax_sig.legend(fontsize=8)
    def cwnd_series(path):
        import collections as _c
        acc = _c.defaultdict(list)
        with open(path) as fh:
            for ln in fh:
                p = ln.strip().split(",")
                if len(p) < 6:
                    continue
                acc[int(p[0]) // 20000].append(int(p[5]))
        xs = sorted(acc)
        return [b * 20000 / 1e6 for b in xs], [sum(acc[b]) / len(acc[b]) / 1024.0 for b in xs]  # x: ns -> ms
    tr, cr = cwnd_series(reps_pr)
    ax_cw.plot(tr, cr, color=plot_style.COLORS["reps"], lw=2.0, label="REPS+NSCC")
    if os.path.exists(prism_pr):
        tp, cp = cwnd_series(prism_pr)
        ax_cw.plot(tp, cp, color=plot_style.COLORS["prism"], lw=2.0, label="Prism")
    strack_pr = os.path.join(data_dir, f"{tag_prefix}_strack_mech.pathrtt.csv")
    if os.path.exists(strack_pr):
        ts, cs = cwnd_series(strack_pr)
        ax_cw.plot(ts, cs, color=plot_style.COLORS["strack"], lw=2.0, label="STrack")
    ax_cw.set_ylabel("cwnd (KB, mean/flow)")
    ax_cw.set_xlabel("time (ms)")
    reps_dec = metrics.count_cwnd_cuts_from_pathrtt(reps_pr)
    prism_dec = metrics.count_cwnd_cuts_from_pathrtt(prism_pr) if os.path.exists(prism_pr) else -1
    strack_dec = metrics.count_cwnd_cuts_from_pathrtt(strack_pr) if os.path.exists(strack_pr) else -1
    ax_cw.text(0.02, 0.97, f"rate reductions (per-ACK cwnd cuts): Prism {prism_dec}, "
               f"REPS+NSCC {reps_dec}, STrack {strack_dec}", transform=ax_cw.transAxes, fontsize=7,
               va="top", bbox=dict(boxstyle="round", fc="white", ec="gray", alpha=0.85))
    ax_cw.grid(alpha=0.3); ax_cw.legend(fontsize=9)
    plt.tight_layout()
    plot_style.save(fig, fig_stem, figs_dir)
    plt.close(fig)
    if not ep:
        print(f"[{fig_stem}] WARNING: prism epoch log empty -- floor-MD fraction unreliable")
    prism_md = sum(r["cut"] for r in ep)
    frac = (prism_md / prism_dec) if prism_dec > 0 else float("nan")
    print(f"[{fig_stem}] cwnd-decrease events @{lbl} (FAIR, per-ACK): "
          f"PRISM={prism_dec}  REPS+NSCC={reps_dec}")
    print(f"[{fig_stem}] floor-MD fraction = PRISM epoch-MDs / PRISM cwnd-decreases = "
          f"{prism_md}/{prism_dec} = {frac:.3f}  (trimming baseline was ~0.05)")
    if os.path.exists(strack_pr):
        print(f"[{fig_stem}] DISTINCTNESS (per-ACK cwnd-decreases @{lbl}): "
              f"STrack={strack_dec}  REPS+NSCC={reps_dec}  "
              f"(must differ measurably; identical => STrack collapsed to NSCC, revisit spec Approach B)")

def selftest():
    import tempfile, shutil
    d = tempfile.mkdtemp()
    failed = [0, 2, 4, 8, 12]; seeds = [13, 14, 15, 16, 17]
    for lab in ("ops", "reps", "strack", "prism"):
        for f in failed:
            for s in seeds:
                with open(os.path.join(d, f"expA_{lab}_f{f}_s{s}.flow.txt"), "w") as fh:
                    fh.write("0.000000000 Type FLOW_EVENT SrcID 1 Ev START FlowID 1 Flowsize 1000000\n")
                    fh.write("0.000000000 Type FLOW_EVENT SrcID 2 Ev START FlowID 2 Flowsize 3000000\n")
                    fh.write("0.001000000 Type FLOW_EVENT SrcID 1 Ev FINISH FlowID 1 Bytes 1000000 Pkts 1\n")
                    fh.write("0.001000000 Type FLOW_EVENT SrcID 2 Ev FINISH FlowID 2 Bytes 3000000 Pkts 1\n")
    a = aggregate(d, "expA", "ops", failed, seeds)
    assert abs(a[0]["goodput"][0] - 32.0) < 1e-6, a[0]
    assert abs(a[0]["avg_fct"][0] - 1000.0) < 1e-6, a[0]
    assert abs(a[0]["cr"][0] - 1.0) < 1e-9, a[0]
    # token="L" (offered-load sweep) names files {prefix}_{label}_L{val}_s{seed}.flow.txt
    for s in seeds:
        with open(os.path.join(d, f"expAload_ops_L50_s{s}.flow.txt"), "w") as fh:
            fh.write("0.000000000 Type FLOW_EVENT SrcID 1 Ev START FlowID 1 Flowsize 2000000\n")
            fh.write("0.002000000 Type FLOW_EVENT SrcID 1 Ev FINISH FlowID 1 Bytes 2000000 Pkts 1\n")
    al = aggregate(d, "expAload", "ops", [50], seeds, token="L")
    assert 50 in al, al
    assert abs(al[50]["avg_fct"][0] - 2000.0) < 1e-6, al[50]   # 2 ms = 2000 us
    assert abs(al[50]["cr"][0] - 1.0) < 1e-9, al[50]
    shutil.rmtree(d)
    assert _mech_label(None, 8) == "-failed=8", _mech_label(None, 8)
    assert _mech_label("oversub=8:1", 8) == "oversub=8:1", _mech_label("oversub=8:1", 8)
    assert _mech_label("fan-in=64", 64) == "fan-in=64", _mech_label("fan-in=64", 64)
    bx, by = _bin_series([0.0, 0.01, 0.05], [10.0, 20.0, 30.0], 0.02)  # buckets: {0:[10,20], 2:[30]}
    assert by == [15.0, 30.0], by
    assert abs(bx[0] - 0.01) < 1e-9 and abs(bx[1] - 0.05) < 1e-9, bx
    # MNSCC median-CSV reader: 3 rows -> mean median in us over a coarse bin
    import tempfile as _tf
    md = _tf.mkdtemp()
    with open(os.path.join(md, "x_mnscc_mech.median.csv"), "w") as fh:
        fh.write("1000,1,8000\n2000,1,10000\n3000,2,12000\n")  # ns: medians 8,10,12 us
    ts, ys = _read_mnscc_median(os.path.join(md, "x_mnscc_mech.median.csv"), bin_us=1000)
    assert ys and abs(sum(ys) / len(ys) - 10.0) < 1e-6, (ts, ys)   # mean of 8,10,12 = 10 us
    # Multi-bin aggregation test: two distinct time bins
    with open(os.path.join(md, "x2_mnscc_mech.median.csv"), "w") as fh:
        fh.write("0,1,8000\n10000,1,10000\n40000000,2,20000\n")  # bin0: [8,10]us; later bin: [20]us
    ts2, ys2 = _read_mnscc_median(os.path.join(md, "x2_mnscc_mech.median.csv"), bin_us=20)
    assert len(ys2) == 2 and abs(ys2[0] - 9.0) < 1e-6 and abs(ys2[1] - 20.0) < 1e-6, (ts2, ys2)
    shutil.rmtree(md)
    print("ok perf_figs aggregation selftest")

if __name__ == "__main__":
    selftest()
