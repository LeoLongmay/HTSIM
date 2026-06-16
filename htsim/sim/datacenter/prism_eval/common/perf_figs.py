#!/usr/bin/env python3
"""Generic performance + mechanism figures for prism_eval experiment groups (Experiment A and
its variants). Parameterized by data dir, figs dir, baselines, tag prefix, and the failed/seed
sets, so each group's make_figs.py is a thin wrapper. Reads logs via metrics.py; styles via
plot_style.py. Baselines are (label, display, color_key) triples; files are named
{tag_prefix}_{label}_f{failed}_s{seed}.flow.txt and {tag_prefix}_{label}_mech.* ."""
import os, sys, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import metrics          # noqa: E402
import plot_style       # noqa: E402

def _ms(v):
    """(mean, population std) of a non-empty list -- population std: full fixed seed set."""
    return (statistics.mean(v), statistics.pstdev(v))

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

def aggregate(data_dir, tag_prefix, label, failed, seeds):
    """Per-failed aggregates for one baseline: {f: {metric:(mean,std)}}; omit f with no data."""
    out = {}
    for f in failed:
        g, afct, p99, cr = [], [], [], []
        for s in seeds:
            flow = os.path.join(data_dir, f"{tag_prefix}_{label}_f{f}_s{s}.flow.txt")
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

def render_main_perf(data_dir, figs_dir, tag_prefix, baselines, failed, seeds, fig_stem, xlabel):
    """3 panels (goodput / avg-FCT us / P99-FCT us) vs `failed`, one line per baseline + error bars."""
    import matplotlib.pyplot as plt
    plot_style.apply_style(13)
    aggs = {lab: aggregate(data_dir, tag_prefix, lab, failed, seeds) for (lab, _d, _c) in baselines}
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
            f"f{f}:g={aggs[lab][f]['goodput'][0]:.1f},avgfct={aggs[lab][f]['avg_fct'][0]:.0f}us,"
            f"cr={aggs[lab][f]['cr'][0]:.2f}" for f in failed if aggs[lab].get(f)))

def render_mechanism(data_dir, figs_dir, tag_prefix, fig_stem, mech_failed, target_us=6.0, base_ns=13945):
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
    target_us = _read_target_us(data_dir, tag_prefix, target_us)
    fig, (ax_sig, ax_cw) = plt.subplots(2, 1, figsize=(5.2, 6.0), sharex=True)
    bins = metrics.qdelay_bins(reps_pr, base_ns=base_ns, bin_us=20)
    if bins:
        t = [b[0] for b in bins]; mn = [b[1] for b in bins]; av = [b[2] for b in bins]
        ax_sig.plot(t, av, color=plot_style.COLORS["reps"], lw=2.0, label="REPS+NSCC avg delay")
        ax_sig.plot(t, mn, color=plot_style.COLORS["reps"], lw=1.3, ls=":", label="REPS+NSCC floor (ignored)")
    ep = metrics.parse_prism_epoch(prism_ep)
    if ep:
        te = [r["time_ns"] / 1000.0 for r in ep]; cc = [r["c_cc_ns"] / 1000.0 for r in ep]
        ax_sig.plot(te, cc, color=plot_style.COLORS["prism"], lw=2.0, label="PRISM floor C_cc")
    ax_sig.axhline(target_us, color=plot_style.COLORS["target"], ls="--", lw=1.3, label=f"target ({target_us:.1f}us = 1 RTT)")
    ax_sig.set_ylabel("Queuing delay (us)")
    ax_sig.set_title(f"Mechanism @ -failed={mech_failed}", fontsize=11)
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
        return [b * 20000 / 1000.0 for b in xs], [sum(acc[b]) / len(acc[b]) / 1024.0 for b in xs]
    tr, cr = cwnd_series(reps_pr)
    ax_cw.plot(tr, cr, color=plot_style.COLORS["reps"], lw=2.0, label="REPS+NSCC")
    if os.path.exists(prism_pr):
        tp, cp = cwnd_series(prism_pr)
        ax_cw.plot(tp, cp, color=plot_style.COLORS["prism"], lw=2.0, label="PRISM")
    strack_pr = os.path.join(data_dir, f"{tag_prefix}_strack_mech.pathrtt.csv")
    if os.path.exists(strack_pr):
        ts, cs = cwnd_series(strack_pr)
        ax_cw.plot(ts, cs, color=plot_style.COLORS["strack"], lw=2.0, label="STrack")
    ax_cw.set_ylabel("cwnd (KB, mean/flow)")
    ax_cw.set_xlabel("time (us)")
    ax_cw.grid(alpha=0.3); ax_cw.legend(fontsize=9)
    plt.tight_layout()
    plot_style.save(fig, fig_stem, figs_dir)
    plt.close(fig)
    if not ep:
        print(f"[{fig_stem}] WARNING: prism epoch log empty -- floor-MD fraction unreliable")
    reps_dec = metrics.count_cwnd_cuts_from_pathrtt(reps_pr)
    prism_dec = metrics.count_cwnd_cuts_from_pathrtt(prism_pr) if os.path.exists(prism_pr) else -1
    prism_md = sum(r["cut"] for r in ep)
    frac = (prism_md / prism_dec) if prism_dec > 0 else float("nan")
    print(f"[{fig_stem}] cwnd-decrease events @failed={mech_failed} (FAIR, per-ACK): "
          f"PRISM={prism_dec}  REPS+NSCC={reps_dec}")
    print(f"[{fig_stem}] floor-MD fraction = PRISM epoch-MDs / PRISM cwnd-decreases = "
          f"{prism_md}/{prism_dec} = {frac:.3f}  (trimming baseline was ~0.05)")
    if os.path.exists(strack_pr):
        strack_dec = metrics.count_cwnd_cuts_from_pathrtt(strack_pr)
        print(f"[{fig_stem}] DISTINCTNESS (per-ACK cwnd-decreases @failed={mech_failed}): "
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
    shutil.rmtree(d)
    print("ok perf_figs aggregation selftest")

if __name__ == "__main__":
    selftest()
