#!/usr/bin/env python3
"""Analyze the HOLD-leak sweep: does a leak recover f0 without eroding the f8/f12 win? Reads
hl_prism_l{code}_f{failed}_s{seed}.flow.txt (code = round(leak*100)) and hl_reps_f{failed}_s{seed}
.flow.txt. Pre-registered verdict: a leak is ADMISSIBLE iff f8 AND f12 goodput stay within
max(3% of leak=0, 1 SD) of leak=0; POSITIVE iff some admissible leak recovers >= 1/3 of the f0
goodput gap (leak=0 -> REPS+NSCC). Reuses common/metrics.py + plot_style.py.
  python3 holdleak_analyze.py            # verdict + figHL_holdleak
  python3 holdleak_analyze.py --selftest # logic self-check
"""
import os, sys, statistics
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import metrics       # noqa: E402
import plot_style    # noqa: E402

LEAKS = [(0, 0.0), (10, 0.1), (25, 0.25), (50, 0.5), (75, 0.75), (100, 1.0)]  # (code, leak)
FAILEDS = [0, 2, 4, 8, 12]
SEEDS = [13, 14, 15, 16, 17]

def _ms(v):
    return (statistics.mean(v), statistics.pstdev(v)) if v else (float("nan"), float("nan"))

def _agg_goodput(data_dir, name_of):
    """{failed: (mean,std)} aggregating goodput over seeds; name_of(failed,seed)->flow filename."""
    out = {}
    for f in FAILEDS:
        gs = []
        for s in SEEDS:
            fp = os.path.join(data_dir, name_of(f, s))
            if os.path.exists(fp):
                gs.append(metrics.aggregate_goodput_gbps(fp))
        if gs:
            out[f] = _ms(gs)
    return out

def analyze(data_dir):
    prism = {code: _agg_goodput(data_dir, lambda f, s, c=code: f"hl_prism_l{c}_f{f}_s{s}.flow.txt")
             for code, _leak in LEAKS}
    reps = _agg_goodput(data_dir, lambda f, s: f"hl_reps_f{f}_s{s}.flow.txt")
    return prism, reps

def evaluate(prism, reps):
    """Return (rows, admissible, best, (g0_f0,g_reps_f0,gap))."""
    base = prism.get(0, {})
    g0_f0 = base.get(0, (float("nan"), 0))[0]
    g_reps_f0 = reps.get(0, (float("nan"), 0))[0]
    gap = g_reps_f0 - g0_f0
    rows, admissible = [], []
    for code, leak in LEAKS:
        if code == 0:
            continue
        ok, notes = True, []
        for f in (8, 12):
            b = base.get(f); cur = prism.get(code, {}).get(f)
            if not b or not cur:
                ok = False; notes.append(f"f{f} missing"); continue
            tol = max(0.03 * b[0], b[1])
            if cur[0] < b[0] - tol:
                ok = False; notes.append(f"f{f}:{cur[0]:.0f}<{b[0]-tol:.0f}")
        gf0 = prism.get(code, {}).get(0, (float("nan"), 0))[0]
        rec = (gf0 - g0_f0) / gap if gap > 0 else float("nan")
        row = {"leak": leak, "f0": gf0, "recovery": rec,
               "f8": prism.get(code, {}).get(8, (float("nan"), 0))[0],
               "f12": prism.get(code, {}).get(12, (float("nan"), 0))[0],
               "ok": ok, "notes": notes}
        rows.append(row)
        if ok and rec == rec and rec >= 1.0 / 3.0:
            admissible.append(row)
    best = max(admissible, key=lambda r: r["recovery"]) if admissible else None
    return rows, admissible, best, (g0_f0, g_reps_f0, gap)

def verdict(prism, reps):
    rows, admissible, best, (g0_f0, g_reps_f0, gap) = evaluate(prism, reps)
    out = [f"f0: leak=0 PRISM={g0_f0:.0f}  REPS+NSCC={g_reps_f0:.0f}  gap={gap:.0f} Gbps "
           f"(recover >=1/3 => f0 >= {g0_f0 + gap/3:.0f})"]
    for r in rows:
        out.append(f"  leak={r['leak']:<4}: f0={r['f0']:.0f} (recovery {r['recovery']:.0%})  "
                   f"f8={r['f8']:.0f}  f12={r['f12']:.0f}  do-no-harm="
                   + ("OK" if r["ok"] else "VIOLATED " + ";".join(r["notes"])))
    if best:
        out.append(f"VERDICT: POSITIVE -- leak={best['leak']} recovers {best['recovery']:.0%} of the "
                   f"f0 gap with f8/f12 do-no-harm.")
    else:
        out.append("VERDICT: NEGATIVE -- no leak both recovers >=1/3 of f0 AND keeps f8/f12 "
                   "do-no-harm. Keep _prism_hold_leak=0 (O(1) PRISM unchanged).")
    return "\n".join(out)

def render(prism, reps, figs_dir):
    import matplotlib.pyplot as plt
    plot_style.apply_style(13)
    fig, ax = plt.subplots(1, 1, figsize=(6.4, 4.0))
    leaks = [lk for _c, lk in LEAKS]
    colors = {0: "tab:gray", 2: "tab:purple", 4: "tab:blue", 8: "tab:green", 12: "tab:red"}
    for f in FAILEDS:
        ys = [prism.get(c, {}).get(f, (float("nan"), 0))[0] for c, _lk in LEAKS]
        ax.plot(leaks, ys, marker="o", lw=2.0, color=colors[f], label=f"Prism failed={f}")
        if f in reps:
            ax.axhline(reps[f][0], color=colors[f], ls="--", lw=1.0, alpha=0.7)
    ax.set_xlabel("HOLD-leak  (-prism_hold_leak)")
    ax.set_ylabel("Goodput (Gbps)")
    ax.set_title("HOLD-leak sweep (dashed = REPS+NSCC reference)", fontsize=11)
    ax.grid(alpha=0.3); ax.legend(fontsize=8, ncol=2)
    plt.tight_layout()
    plot_style.save(fig, "figHL_holdleak", figs_dir)
    plt.close(fig)

def selftest():
    prism = {
        0:   {0: (900, 5), 8: (500, 5), 12: (430, 5)},
        50:  {0: (960, 5), 8: (498, 5), 12: (431, 5)},
        100: {0: (1000, 5), 8: (300, 5), 12: (250, 5)},
    }
    reps = {0: (1000, 5), 8: (505, 5), 12: (435, 5)}
    for c, _lk in LEAKS:
        prism.setdefault(c, {0: (900, 5), 8: (500, 5), 12: (430, 5)})
    rows, admissible, best, _ = evaluate(prism, reps)
    by = {r["leak"]: r for r in rows}
    assert by[0.5]["ok"] and by[0.5]["recovery"] >= 1.0 / 3.0, by[0.5]
    assert not by[1.0]["ok"], by[1.0]
    assert best is not None and best["leak"] == 0.5, best
    print("ok holdleak_analyze selftest")

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        DATA = os.path.join(HERE, "data"); FIGS = os.path.join(HERE, "figs")
        os.makedirs(FIGS, exist_ok=True)
        prism, reps = analyze(DATA)
        print(verdict(prism, reps))
        render(prism, reps, FIGS)
        print(f"[holdleak] wrote {FIGS}/figHL_holdleak.{{png,pdf}}")
