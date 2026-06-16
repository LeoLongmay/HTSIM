#!/usr/bin/env python3
"""Figures + criterion for the PRISM T_spray tuning experiment.
  python3 make_figs.py --selftest             # aggregation + selector smoke
  python3 make_figs.py --stage1               # knee fig + criterion table + recommended T_spray*
  python3 make_figs.py --stage2 --ts-star N   # 4-arm compare fig (reuses delay-driven baselines)
Reads local sweep data from ./data; reuses OPS/REPS/STrack/PRISM-default from ../expA_delaydriven/data.
"""
import os, sys, statistics
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import metrics          # noqa: E402
import plot_style       # noqa: E402
import tspray_select    # noqa: E402  (same dir)

DATA   = os.path.join(HERE, "data")
FIGS   = os.path.join(HERE, "figs")
REUSE  = os.path.join(HERE, "..", "expA_delaydriven", "data")  # committed baseline data (read-only)
SEEDS  = [13, 14, 15, 16, 17]
TSLIST = [2, 3, 4, 6, 9, 14]
F0_FLOOR_LABEL = "OPS+NSCC f0"   # f0 recovery bar = OPS+NSCC f0 goodput (no longer the worst arm)

def _mean(xs):
    return statistics.mean(xs) if xs else float("nan")

def agg_arm(data_dir, tag, failed_list, seeds):
    """{failed: {'goodput':mean, 'avg_fct':mean, 'p99_fct':mean, 'cr':mean}} for files
    {data_dir}/{tag}_f{f}_s{s}.flow.txt ; skips missing cells."""
    out = {}
    for f in failed_list:
        g, a, p, c = [], [], [], []
        for s in seeds:
            fp = os.path.join(data_dir, f"{tag}_f{f}_s{s}.flow.txt")
            if not os.path.exists(fp):
                continue
            st = metrics.fct_stats(fp)
            g.append(metrics.aggregate_goodput_gbps(fp))
            a.append(st["avg_s"] * 1e6); p.append(st["p99_s"] * 1e6); c.append(st["completion_rate"])
        if g:
            out[f] = {"goodput": _mean(g), "avg_fct": _mean(a), "p99_fct": _mean(p), "cr": _mean(c)}
    return out

def stage1():
    """Aggregate the T_spray x {f0,f8} sweep, render the knee figure, and print BOTH verdicts:
    the original registered f0-fix criterion (FAILED -- preserved for the audit trail) AND the
    pivot f8-maximization criterion (do-no-harm at f0). See spec §4 + §7. Real default T_spray =
    max(TSLIST) = 14us (one network RTT)."""
    import matplotlib.pyplot as plt
    plot_style.apply_style(13)
    f0_g, f8_g, f0_a, f8_a = {}, {}, {}, {}
    for ts in TSLIST:
        a = agg_arm(DATA, f"tsweep_ts{ts}", [0, 8], SEEDS)
        if 0 in a: f0_g[ts] = a[0]["goodput"]; f0_a[ts] = a[0]["avg_fct"]
        if 8 in a: f8_g[ts] = a[8]["goodput"]; f8_a[ts] = a[8]["avg_fct"]
    reps = agg_arm(REUSE, "expA_reps", [0, 8], SEEDS)
    ops  = agg_arm(REUSE, "expA_ops",  [0], SEEDS)
    if 0 not in reps or 8 not in reps or 0 not in ops:
        sys.exit(f"[stage1] ERROR: reused baseline files missing from {REUSE} "
                 f"(need expA_reps_f0/f8 and expA_ops_f0); run expA_delaydriven/repro.sh first")
    reps_f0, reps_f8 = reps[0]["goodput"], reps[8]["goodput"]
    f0_floor = ops[0]["goodput"]
    default_ts = max(TSLIST)  # 14us = real runtime default (one network RTT)
    sel_reg = tspray_select.select_tspray(f0_g, f8_g, reps_f8_goodput=reps_f8, f0_floor=f0_floor)
    sel = tspray_select.select_tspray_maximize_f8(f0_g, f8_g, f0_ref=f0_g[default_ts])
    fig, (ax_g, ax_f) = plt.subplots(2, 1, figsize=(5.4, 7.0), sharex=True)
    xs = TSLIST
    ax_g.plot(xs, [f0_g[t] for t in xs], "o-", color=plot_style.COLORS["prism"], lw=2, label="PRISM goodput @f0")
    ax_g.plot(xs, [f8_g[t] for t in xs], "s--", color=plot_style.COLORS["prism"], lw=2, label="PRISM goodput @f8")
    ax_g.axhline(reps_f0, color=plot_style.COLORS["reps"], ls=":", lw=1.3, label=f"REPS+NSCC f0 ({reps_f0:.0f})")
    ax_g.axhline(f0_floor, color=plot_style.COLORS["ops"], ls=":", lw=1.3, label=f"{F0_FLOOR_LABEL} floor ({f0_floor:.0f})")
    ax_g.axhline(f8_g[default_ts], color="tab:purple", ls="--", lw=1.3, label=f"default f8 (T_spray={default_ts}: {f8_g[default_ts]:.0f})")
    ax_g.set_ylabel("Goodput (Gbps)"); ax_g.grid(alpha=0.3); ax_g.legend(fontsize=8)
    title = (f"f8-max T_spray* = {sel['chosen']}us (default {default_ts}us)"
             if sel["chosen"] is not None else "no eligible T_spray (f0 do-no-harm fails)")
    ax_g.set_title(title, fontsize=11)
    ax_f.plot(xs, [f0_a[t] for t in xs], "o-", color=plot_style.COLORS["prism"], lw=2, label="PRISM avg-FCT @f0")
    ax_f.plot(xs, [f8_a[t] for t in xs], "s--", color=plot_style.COLORS["prism"], lw=2, label="PRISM avg-FCT @f8")
    ax_f.set_ylabel("Avg FCT (us)"); ax_f.set_xlabel(f"T_spray (us)  [{default_ts} = default = 1 RTT target]")
    ax_f.set_xticks(xs); ax_f.grid(alpha=0.3); ax_f.legend(fontsize=8)
    plt.tight_layout(); plot_style.save(fig, "figT1_knee", FIGS); plt.close(fig)
    print(f"[stage1] f0_floor={f0_floor:.0f} (OPS f0); REPS f0={reps_f0:.0f} f8={reps_f8:.0f}; "
          f"default T_spray={default_ts}us -> f0={f0_g[default_ts]:.0f} f8={f8_g[default_ts]:.0f}")
    for ts in TSLIST:
        elig = (ts in sel["eligible"])
        mark = " <-- f8-max*" if ts == sel["chosen"] else ""
        print(f"  T_spray={ts:>2}us  f0={f0_g[ts]:6.1f}  f8={f8_g[ts]:6.1f}  "
              f"f0_fct={f0_a[ts]:6.0f}us  f8_fct={f8_a[ts]:6.0f}us  {'elig' if elig else 'F0-HARM'}{mark}")
    if sel_reg["chosen"] is None:
        print("[stage1] registered f0-fix criterion: FAILED (no static T_spray recovers f0 to the "
              "OPS floor while keeping the f8 win) -- f0 is insensitive to T_spray (negative result).")
    else:
        print(f"[stage1] registered f0-fix criterion: would pick {sel_reg['chosen']}us (unexpected).")
    if sel["chosen"] is not None:
        gain = 100.0 * (f8_g[sel["chosen"]] - f8_g[default_ts]) / f8_g[default_ts]
        print(f"[stage1] PIVOT f8-max: T_spray* = {sel['chosen']}us -> f8={f8_g[sel['chosen']]:.0f} "
              f"({gain:+.1f}% vs default {f8_g[default_ts]:.0f}), f0={f0_g[sel['chosen']]:.0f} "
              f">= do-no-harm bar {sel['f0_bar']:.0f}.  Validate full grid:  TS_STAR={sel['chosen']} bash repro.sh")
    else:
        print("[stage1] PIVOT f8-max: no T_spray clears the f0 do-no-harm bar.")

def stage2(ts_star):
    """5-arm compare over full failed grid: PRISM-default & PRISM-tuned vs REPS+NSCC & STrack.
    Baselines + PRISM-default are reused read-only from ../expA_delaydriven/data."""
    import matplotlib.pyplot as plt
    plot_style.apply_style(13)
    failed = [0, 2, 4, 8, 12]
    arms = [  # (display, data_dir, tag, color)
        ("OPS+NSCC", REUSE, "expA_ops", plot_style.COLORS["ops"]),
        ("REPS+NSCC", REUSE, "expA_reps", plot_style.COLORS["reps"]),
        ("STrack", REUSE, "expA_strack", plot_style.COLORS["strack"]),
        ("PRISM (default ~14us = 1 RTT)", REUSE, "expA_prism", plot_style.COLORS["prism"]),
        (f"PRISM (T_spray={ts_star})", DATA, "tsval", "tab:purple"),
    ]
    aggs = [(disp, agg_arm(d, tag, failed, SEEDS), col) for (disp, d, tag, col) in arms]
    if not aggs[-1][1]:
        print(f"[figT2_compare] WARNING: no PRISM-tuned (tsval) data in {DATA} for ts={ts_star} "
              f"-- figure will show baselines only; run Stage 2 sims first")
    fig, axes = plt.subplots(3, 1, figsize=(5.4, 8.2), sharex=True)
    for ax, (key, ylab) in zip(axes, [("goodput", "Goodput (Gbps)"), ("avg_fct", "Avg FCT (us)"), ("p99_fct", "P99 FCT (us)")]):
        for (disp, ag, col) in aggs:
            xs = [f for f in failed if f in ag]
            ax.plot(xs, [ag[f][key] for f in xs], "o-", lw=2, ms=6, color=col, label=disp)
        ax.set_ylabel(ylab); ax.grid(alpha=0.3)
    axes[0].legend(fontsize=8); axes[0].set_title(f"T_spray tuning: default vs {ts_star}us", fontsize=11)
    axes[-1].set_xlabel("# constrained core->agg links (-failed), delay-driven"); axes[-1].set_xticks(failed)
    plt.tight_layout(); plot_style.save(fig, "figT2_compare", FIGS); plt.close(fig)
    for (disp, ag, _c) in aggs:
        print(f"[figT2_compare] {disp}: " + " ".join(
            f"f{f}:g={ag[f]['goodput']:.0f},afct={ag[f]['avg_fct']:.0f},cr={ag[f]['cr']:.2f}" for f in failed if f in ag))

def selftest():
    import tempfile, shutil
    d = tempfile.mkdtemp()
    for f in (0, 8):
        for s in SEEDS:
            with open(os.path.join(d, f"tsweep_ts18_f{f}_s{s}.flow.txt"), "w") as fh:
                fh.write("0.000000000 Type FLOW_EVENT SrcID 1 Ev START FlowID 1 Flowsize 1000000\n")
                fh.write("0.001000000 Type FLOW_EVENT SrcID 1 Ev FINISH FlowID 1 Bytes 1000000 Pkts 1\n")
    a = agg_arm(d, "tsweep_ts18", [0, 8], SEEDS)
    assert abs(a[0]["goodput"] - 8.0) < 1e-6, a       # 1e6 bytes*8 / 1e-3 s = 8 Gbps
    assert abs(a[0]["avg_fct"] - 1000.0) < 1e-6, a    # 1 ms = 1000 us
    assert 99 not in agg_arm(d, "nope", [99], SEEDS), "missing cells must be skipped"
    shutil.rmtree(d)
    tspray_select.selftest()
    print("ok tspray make_figs aggregation selftest")

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--stage2" in sys.argv:
        i = sys.argv.index("--ts-star"); stage2(int(sys.argv[i + 1]))
    elif "--stage1" in sys.argv:
        stage1()
    else:
        print("usage: make_figs.py [--selftest | --stage1 | --stage2 --ts-star N]")
