#!/usr/bin/env python3
"""Figures + table for the PRISM parameter-sensitivity (robustness) study.
  python3 make_figs.py --selftest   # aggregation + tag-format + default-reuse smoke (synthetic data)
  python3 make_figs.py --render      # build figK_sensitivity.{pdf,png} + print the robustness table
Reads local sweep data from ./data; reuses default-center PRISM/REPS cells read-only from
../expA_delaydriven/data (expA_prism_f{0,8}, expA_reps_f{0,8}). No controller code, no perf_figs change.
"""
import os, sys, statistics
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import metrics       # noqa: E402
import plot_style    # noqa: E402

DATA  = os.path.join(HERE, "data")
FIGS  = os.path.join(HERE, "figs")
REUSE = os.path.join(HERE, "..", "expA_delaydriven", "data")  # committed default-center data (read-only)
SEEDS = [13, 14, 15, 16, 17]
FAILED = [0, 8]  # f0 = symmetric cost anchor; f8 = headline asymmetric win anchor

# OFAT knob configs. Dense grids span ~0.35-3x the default to expose the full curve shape; 'default'
# x reuses the expA_* center cell. kappa is a multiplier -> plotted on a log x-axis ("logx").
KNOBS = [
    {"name": "tspray", "title": "T_spray (us)",        "token": "ts", "default": 14,  "xs": [5, 7, 10, 14, 17, 20, 24, 28, 40]},
    {"name": "tcc",    "title": "T_cc (us)",           "token": "q",  "default": 14,  "xs": [5, 7, 10, 14, 17, 20, 24, 28, 40]},
    {"name": "kappa",  "title": "epoch  k x base_rtt", "token": "k",  "default": 1.0, "logx": True,
     "xs": [0.125, 0.25, 0.375, 0.5, 0.75, 1.0, 1.5, 2, 3, 4, 6, 8]},
]

def _mean(xs):
    return statistics.mean(xs) if xs else float("nan")

def agg_arm(data_dir, tag, failed_list, seeds):
    """{failed: {'goodput','avg_fct'(us),'p99_fct'(us),'cr','jain'}} for {data_dir}/{tag}_f{f}_s{s}.flow.txt;
    skips missing cells. Based on expA_tspray_tuning/make_figs.py, plus Jain fairness for the kappa tradeoff."""
    out = {}
    for f in failed_list:
        g, a, p, c, j = [], [], [], [], []
        for s in seeds:
            fp = os.path.join(data_dir, f"{tag}_f{f}_s{s}.flow.txt")
            if not os.path.exists(fp):
                continue
            st = metrics.fct_stats(fp)
            g.append(metrics.aggregate_goodput_gbps(fp))
            a.append(st["avg_s"] * 1e6); p.append(st["p99_s"] * 1e6); c.append(st["completion_rate"])
            j.append(metrics.jain_fairness(fp))
        if g:
            out[f] = {"goodput": _mean(g), "avg_fct": _mean(a), "p99_fct": _mean(p),
                      "cr": _mean(c), "jain": _mean(j)}
    return out

def _tag(knob_name, arm, token, x):
    """Local sweep tag for one (knob, arm, value); '%g' matches the bash loop token exactly."""
    return f"expSens_{knob_name}_{arm}_{token}{'%g' % x}"

def arm_point(knob, arm, x, reuse_tag):
    """Aggregated {failed:{metrics}} for one swept value x. At x==default the point is the reused
    expA_* center cell (reuse_tag in REUSE); otherwise the local expSens_* cell in DATA."""
    if x == knob["default"]:
        return agg_arm(REUSE, reuse_tag, FAILED, SEEDS)
    return agg_arm(DATA, _tag(knob["name"], arm, knob["token"], x), FAILED, SEEDS)

def knob_series(knob):
    """For one knob: {'prism': {x: {failed:{metrics}}}, and 'reps': {...} for the T_cc knob only}.
    Normalization is applied at plot time, not here."""
    out = {"prism": {x: arm_point(knob, "prism", x, "expA_prism") for x in knob["xs"]}}
    if knob["name"] == "tcc":
        out["reps"] = {x: arm_point(knob, "reps", x, "expA_reps") for x in knob["xs"]}
    return out

def render():
    """Inline 3-panel figure: per knob, goodput normalized to the PRISM default vs the knob value;
    two Prism series (f0 cost, f8 win); the T_cc panel adds a REPS+NSCC f8 reference line."""
    import matplotlib.pyplot as plt
    os.makedirs(FIGS, exist_ok=True)
    plot_style.apply_style(15)
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.2), sharey=True)
    handles = {}
    for ax, knob in zip(axes, KNOBS):
        ser = knob_series(knob); prism = ser["prism"]
        denom = {f: prism[knob["default"]][f]["goodput"] for f in FAILED}
        for f, style, lab in [(0, "o--", "Prism @f0 (cost)"), (8, "s-", "Prism @f8 (win)")]:
            xs = [x for x in knob["xs"] if f in prism[x]]
            ys = [prism[x][f]["goodput"] / denom[f] for x in xs]
            ln, = ax.plot(xs, ys, style, lw=2, ms=6, color=plot_style.COLORS["prism"], label=lab)
            handles[lab] = ln
        if knob["name"] == "tcc":
            reps = ser["reps"]; rdenom = reps[knob["default"]][8]["goodput"]
            xs = [x for x in knob["xs"] if 8 in reps[x]]
            ys = [reps[x][8]["goodput"] / rdenom for x in xs]
            ln, = ax.plot(xs, ys, "^:", lw=1.8, ms=6, color=plot_style.COLORS["reps"], label="REPS+NSCC @f8 (ref)")
            handles["REPS+NSCC @f8 (ref)"] = ln
        ax.axhline(1.0, color="0.4", lw=0.9, zorder=0)
        ax.axvline(knob["default"], color="0.7", ls=":", lw=1.0, zorder=0)
        if knob.get("logx"):
            ax.set_xscale("log", base=2)
            ax.set_xticks(knob["xs"])
            ax.set_xticklabels([("%g" % x) for x in knob["xs"]], fontsize=10)
        ax.set_title(knob["title"], fontsize=14)
        ax.set_xlabel(f"{knob['title']}  (default = {'%g' % knob['default']})")
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("Goodput (norm. to Prism default)")
    fig.legend(handles.values(), handles.keys(), ncol=3, fontsize=12,
               loc="lower center", bbox_to_anchor=(0.5, 1.0), frameon=False)
    plt.tight_layout(rect=(0, 0, 1, 0.93))
    plot_style.save(fig, "figK_sensitivity", FIGS); plt.close(fig)
    render_kappa_tradeoff()
    print_table()

def render_kappa_tradeoff():
    """Why default kappa=1: the headline (f8 asymmetric) regime is a throughput<->fairness tradeoff.
    For kappa<=1 both f8 goodput and f8 Jain sit on a flat high plateau (insensitive); kappa=1 is the
    largest epoch on that plateau (the 'knee'). For kappa>1 goodput rises but f8 fairness falls off a
    cliff. Single twin-axis figure: f8 goodput (left) and f8 Jain (right) vs kappa (log2)."""
    import matplotlib.pyplot as plt
    os.makedirs(FIGS, exist_ok=True)
    plot_style.apply_style(15)
    knob = next(k for k in KNOBS if k["name"] == "kappa")
    prism = {x: arm_point(knob, "prism", x, "expA_prism") for x in knob["xs"]}
    xs = [x for x in knob["xs"] if 8 in prism[x]]
    good = [prism[x][8]["goodput"] for x in xs]
    jain = [prism[x][8]["jain"] for x in xs]
    fig, axg = plt.subplots(figsize=(7.0, 4.4))
    axj = axg.twinx()
    axg.axvspan(min(xs), knob["default"], color="0.85", alpha=0.5, zorder=0)  # k<=1 plateau
    lg, = axg.plot(xs, good, "s-", lw=2.2, ms=7, color=plot_style.COLORS["prism"], label="f8 goodput (Gbps)")
    lj, = axj.plot(xs, jain, "o--", lw=2.2, ms=7, color="#d1495b", label="f8 Jain fairness")
    axg.axvline(knob["default"], color="0.35", ls=":", lw=1.4, zorder=1)
    axg.set_xscale("log", base=2); axg.set_xticks(knob["xs"])
    axg.set_xticklabels([("%g" % x) for x in knob["xs"]], fontsize=10)
    axg.set_xlabel("epoch length  kappa x base_rtt   (default = 1)")
    axg.set_ylabel("f8 goodput (Gbps)", color=plot_style.COLORS["prism"])
    axj.set_ylabel("f8 Jain fairness", color="#d1495b")
    axg.tick_params(axis="y", labelcolor=plot_style.COLORS["prism"])
    axj.tick_params(axis="y", labelcolor="#d1495b")
    axg.set_title("Why default kappa=1: headline-regime throughput vs fairness", fontsize=13)
    axg.text(0.04, 0.30, "kappa<=1: high-fairness\nplateau (knee at 1)",
             transform=axg.transAxes, fontsize=10, color="0.25", va="center")
    axg.text(0.62, 0.16, "kappa>1: trade fairness\nfor throughput",
             transform=axg.transAxes, fontsize=10, color="0.25", va="center")
    axg.grid(alpha=0.3)
    fig.legend([lg, lj], ["f8 goodput (Gbps)", "f8 Jain fairness"], ncol=2, fontsize=11,
               loc="lower center", bbox_to_anchor=(0.5, 0.99), frameon=False)
    plt.tight_layout(rect=(0, 0, 1, 0.95))
    plot_style.save(fig, "figK2_kappa_tradeoff", FIGS); plt.close(fig)

def print_table():
    """Per knob: avg-FCT/P99/cr at every swept point + the f8 win-vs-REPS range over the bracket.
    For T_cc, the f8 comparison uses REPS at the SAME T_cc (apples-to-apples); for the PRISM-private
    knobs (T_spray, kappa) it uses REPS at its default."""
    reps_def = agg_arm(REUSE, "expA_reps", FAILED, SEEDS)
    for knob in KNOBS:
        ser = knob_series(knob); prism = ser["prism"]
        print(f"\n== {knob['name']} (default {'%g' % knob['default']}) ==")
        adv8 = []
        for x in knob["xs"]:
            row = []
            for f in FAILED:
                if f in prism[x]:
                    m = prism[x][f]
                    row.append(f"f{f}: g={m['goodput']:.0f} afct={m['avg_fct']:.0f}us "
                               f"p99={m['p99_fct']:.0f}us cr={m['cr']:.2f}")
            rg = (ser["reps"][x][8]["goodput"] if knob["name"] == "tcc" and 8 in ser.get("reps", {}).get(x, {})
                  else reps_def[8]["goodput"])
            if 8 in prism[x]:
                a = 100.0 * (prism[x][8]["goodput"] - rg) / rg
                adv8.append(a); row.append(f"f8 vs REPS {a:+.1f}%")
            print(f"  {knob['token']}={'%g' % x:>5}  " + "  ".join(row)
                  + ("  <-- default" if x == knob["default"] else ""))
        if adv8:
            print(f"  --> f8 win vs REPS over bracket: min {min(adv8):+.1f}%  ..  max {max(adv8):+.1f}%")

def selftest():
    import tempfile, shutil
    d = tempfile.mkdtemp(); r = tempfile.mkdtemp()
    def write(dirp, tag, f, s, bytes_, ms):
        with open(os.path.join(dirp, f"{tag}_f{f}_s{s}.flow.txt"), "w") as fh:
            fh.write(f"0.000000000 Type FLOW_EVENT SrcID 1 Ev START FlowID 1 Flowsize {bytes_}\n")
            fh.write(f"0.{int(ms * 1e6):09d} Type FLOW_EVENT SrcID 1 Ev FINISH FlowID 1 Bytes {bytes_} Pkts 1\n")
    # (a) agg_arm math: 1e6 bytes * 8 / 1e-3 s = 8 Gbps; 1 ms = 1000 us
    for f in FAILED:
        for s in SEEDS:
            write(d, "expSens_tspray_prism_ts7", f, s, 1000000, 1.0)
    a = agg_arm(d, "expSens_tspray_prism_ts7", FAILED, SEEDS)
    assert abs(a[0]["goodput"] - 8.0) < 1e-6, a
    assert abs(a[0]["avg_fct"] - 1000.0) < 1e-6, a
    assert 99 not in agg_arm(d, "nope", [99], SEEDS), "missing cells must be skipped"
    # (b) tag formatting must match the bash loop tokens exactly
    assert _tag("kappa", "prism", "k", 0.25) == "expSens_kappa_prism_k0.25"
    assert _tag("kappa", "prism", "k", 2)    == "expSens_kappa_prism_k2"
    assert _tag("tcc",   "reps",  "q", 14)   == "expSens_tcc_reps_q14"
    # (c) knob_series: default x reuses expA_prism (REUSE); off-default reads local DATA
    global DATA, REUSE
    saved = (DATA, REUSE)
    try:
        DATA, REUSE = d, r
        for f in FAILED:
            for s in SEEDS:
                write(r, "expA_prism", f, s, 1000000, 1.0)             # default center -> 8 Gbps
                write(d, "expSens_tspray_prism_ts7", f, s, 2000000, 1.0)  # off-default -> 16 Gbps
        kn = {"name": "tspray", "title": "x", "token": "ts", "default": 14, "xs": [7, 14]}
        ser = knob_series(kn)
        assert abs(ser["prism"][14][8]["goodput"] - 8.0) < 1e-6, ser   # default = reused expA_prism
        assert abs(ser["prism"][7][8]["goodput"] - 16.0) < 1e-6, ser   # off-default = local
        assert abs(ser["prism"][7][8]["goodput"] / ser["prism"][14][8]["goodput"] - 2.0) < 1e-6
    finally:
        DATA, REUSE = saved
    shutil.rmtree(d); shutil.rmtree(r)
    print("ok expA_sensitivity make_figs selftest")

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--render" in sys.argv:
        render()
    else:
        print("usage: make_figs.py [--selftest | --render]")
