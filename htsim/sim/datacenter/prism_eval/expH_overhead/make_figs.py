#!/usr/bin/env python3
"""PRISM overhead figures (measurement-only). figO1 state, figO2 compute from the microbench CSVs;
figO3/figO4 (Task 3) from reused PRISM_EPOCH logs. No FCT/goodput.
  python3 make_figs.py --selftest   # synthetic-data aggregation smoke
  python3 make_figs.py --render     # build figO1..figO4 from ./data
"""
import os, sys, csv, statistics
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import plot_style  # noqa: E402
import metrics     # noqa: E402

DATA = os.path.join(HERE, "data")
FIGS = os.path.join(HERE, "figs")

KAPPAS = [0.5, 1.0, 2.0, 4.0]
SEEDS = [13, 14, 15, 16, 17]

def read_compute(path):
    """-> {'o1': {algo: ns}, 'median': {algo: [(h, ns), ...] sorted}}. O(1) algos have h=0."""
    o1, med = {}, {}
    with open(path) as fh:
        for r in csv.DictReader(fh):
            algo, h, ns = r["algo"], int(r["h"]), float(r["ns_per_op"])
            if h == 0:
                o1[algo] = ns
            else:
                med.setdefault(algo, []).append((h, ns))
    for a in med:
        med[a].sort()
    return {"o1": o1, "median": med}

def read_state(path):
    """-> {algo: bytes}."""
    with open(path) as fh:
        return {r["algo"]: int(r["bytes"]) for r in csv.DictReader(fh)}

def render_state():
    """figO1: signal-state bytes/flow per arm (bar) + state-vs-#paths (line: prism/reps flat, bitmap O(P))."""
    import matplotlib.pyplot as plt
    os.makedirs(FIGS, exist_ok=True)
    st = read_state(os.path.join(DATA, "bench_state.csv"))
    order = [("prism", "Prism"), ("nscc", "NSCC"), ("strack", "STrack"), ("swift", "Swift"),
             ("reps", "REPS"), ("mnscc", "MNSCC"), ("mswift", "MSwift")]
    order = [(k, lab) for k, lab in order if k in st]
    plot_style.apply_style(15)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.2))
    labs = [lab for _, lab in order]; vals = [st[k] for k, _ in order]
    cols = [plot_style.COLORS.get(k, "0.5") for k, _ in order]
    ax1.bar(labs, vals, color=cols)
    ax1.set_ylabel("Signal state per flow (bytes)"); ax1.set_title("State footprint")
    for i, v in enumerate(vals):
        ax1.text(i, v, str(v), ha="center", va="bottom", fontsize=9)
    ax1.tick_params(axis="x", rotation=35)
    # state vs #paths
    with open(os.path.join(DATA, "bench_state_paths.csv")) as fh:
        rows = list(csv.DictReader(fh))
    P = [int(r["paths"]) for r in rows]
    ax2.plot(P, [int(r["prism"]) for r in rows], "o-", color=plot_style.COLORS["prism"], lw=2, label="Prism (O(1))")
    ax2.plot(P, [int(r["reps"]) for r in rows], "s-", color=plot_style.COLORS["reps"], lw=2, label="REPS (O(1))")
    ax2.plot(P, [int(r["bitmap"]) for r in rows], "^--", color="#d73027", lw=2, label="per-path design (O(#paths))")
    ax2.set_xlabel("Number of paths"); ax2.set_ylabel("State per flow (bytes)")
    ax2.set_title("State vs #paths"); ax2.legend(fontsize=9); ax2.grid(alpha=0.3)
    plt.tight_layout(); plot_style.save(fig, "figO1_state", FIGS); plt.close(fig)

def render_compute():
    """figO2: per-ACK signal-extraction ns (bar, O(1) arms vs median@default H) + ns-vs-H line."""
    import matplotlib.pyplot as plt
    os.makedirs(FIGS, exist_ok=True)
    c = read_compute(os.path.join(DATA, "bench_compute.csv"))
    plot_style.apply_style(15)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.2))
    bars = [("prism", "Prism"), ("nscc", "NSCC"), ("strack", "STrack"), ("swift", "Swift")]
    labs = [lab for k, lab in bars if k in c["o1"]]; vals = [c["o1"][k] for k, _ in bars if k in c["o1"]]
    cols = [plot_style.COLORS.get(k, "0.5") for k, _ in bars if k in c["o1"]]
    # add median schemes at their default H (mnscc@32, mswift@64)
    for k, lab, H in [("mnscc", "MNSCC@32", 32), ("mswift", "MSwift@64", 64)]:
        pts = dict(c["median"].get(k, []))
        if H in pts:
            labs.append(lab); vals.append(pts[H]); cols.append(plot_style.COLORS.get(k, "0.5"))
    ax1.bar(labs, vals, color=cols)
    ax1.set_ylabel("ns per ACK (signal extraction)"); ax1.set_title("Per-ACK compute")
    ax1.tick_params(axis="x", rotation=35)
    for i, v in enumerate(vals):
        ax1.text(i, v, f"{v:.1f}", ha="center", va="bottom", fontsize=8)
    # ns vs H
    for k, lab, col in [("mnscc", "MNSCC median", plot_style.COLORS.get("mnscc", "#1a9850")),
                        ("mswift", "MSwift median", plot_style.COLORS.get("mswift", "#d1495b"))]:
        if k in c["median"]:
            xs = [h for h, _ in c["median"][k]]; ys = [v for _, v in c["median"][k]]
            ax2.plot(xs, ys, "o-", color=col, lw=2, label=lab)
    ax2.axhline(c["o1"].get("prism", 0), ls="--", color=plot_style.COLORS["prism"], lw=2, label="Prism O(1)")
    ax2.set_xlabel("Median window H (samples)"); ax2.set_ylabel("ns per ACK")
    ax2.set_title("Compute scales O(H log H)"); ax2.legend(fontsize=9); ax2.grid(alpha=0.3)
    plt.tight_layout(); plot_style.save(fig, "figO2_compute", FIGS); plt.close(fig)

def epoch_stats(path):
    """One PRISM_EPOCH csv -> (cadence_us, base_rtt_us, [samples...]). Cadence = median of
    consecutive same-flow time_ns deltas (= inter-decision interval = reaction latency)."""
    rows = metrics.parse_prism_epoch(path)
    base_us = (rows[0]["base_rtt_ns"] / 1000.0) if rows else float("nan")
    by_flow = {}
    for r in rows:
        by_flow.setdefault(r["flow_id"], []).append(r["time_ns"])
    deltas = []
    for ts in by_flow.values():
        ts.sort()
        deltas += [(b - a) / 1000.0 for a, b in zip(ts, ts[1:]) if b > a]
    cad_us = statistics.median(deltas) if deltas else float("nan")
    samp = [r["samples"] for r in rows]
    return cad_us, base_us, samp

def _epoch_files(kappa):
    import glob
    return sorted(glob.glob(os.path.join(DATA, f"epoch_k{'%g' % kappa}_s*.epoch.csv")))

def render_samples():
    """figO3: histogram of PRISM_EPOCH `samples` (work aggregated per control decision) at kappa=1,
    with the median-scheme fixed windows (32, 64) marked as references."""
    import matplotlib.pyplot as plt
    os.makedirs(FIGS, exist_ok=True)
    samp = []
    for fp in _epoch_files(1.0):
        samp += epoch_stats(fp)[2]
    plot_style.apply_style(15)
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    if samp:
        ax.hist(samp, bins=range(0, max(samp) + 2), color=plot_style.COLORS["prism"], alpha=0.85,
                align="left", rwidth=0.9)
        med = statistics.median(samp)
        ax.axvline(med, color="0.2", ls="-", lw=1.5, label=f"Prism median = {med:.0f}")
    ax.axvline(32, color=plot_style.COLORS.get("mnscc", "#1a9850"), ls="--", lw=1.8, label="MNSCC window = 32")
    ax.axvline(64, color=plot_style.COLORS.get("mswift", "#d1495b"), ls=":", lw=1.8, label="MSwift window = 64")
    ax.set_xlabel("Samples aggregated per control decision"); ax.set_ylabel("Count (epochs)")
    ax.set_title("Prism: bounded work per decision (kappa=1)"); ax.legend(fontsize=9); ax.grid(alpha=0.3)
    plt.tight_layout(); plot_style.save(fig, "figO3_samples", FIGS); plt.close(fig)

def render_latency():
    """figO4: reaction latency = control-decision cadence vs kappa; reference line y = kappa*base_rtt;
    NSCC per-RTT (= base_rtt) lower bound."""
    import matplotlib.pyplot as plt
    os.makedirs(FIGS, exist_ok=True)
    xs, ys, base = [], [], None
    for k in KAPPAS:
        cads = []
        for fp in _epoch_files(k):
            cad, b, _ = epoch_stats(fp)
            if cad == cad:  # not NaN
                cads.append(cad)
                if base is None:
                    base = b
        if cads:
            xs.append(k); ys.append(statistics.mean(cads))
    plot_style.apply_style(15)
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    ax.plot(xs, ys, "o-", color=plot_style.COLORS["prism"], lw=2.2, ms=7, label="Prism reaction latency (measured)")
    if base:
        ax.plot(xs, [k * base for k in xs], "k--", lw=1.4, label="kappa x base_rtt")
        ax.axhline(base, color=plot_style.COLORS["reps"], ls=":", lw=1.6, label="per-ACK (NSCC) ~ 1 base_rtt")
    ax.set_xlabel("epoch length (kappa x base_rtt)"); ax.set_ylabel("Reaction latency / decision cadence (us)")
    ax.set_title("Reaction latency: the bounded cost of O(1) sampling"); ax.legend(fontsize=9); ax.grid(alpha=0.3)
    plt.tight_layout(); plot_style.save(fig, "figO4_latency", FIGS); plt.close(fig)

def print_tables():
    """Complexity + wire table to stdout (the README backbone; sourced from the spec §2)."""
    st = read_state(os.path.join(DATA, "bench_state.csv"))
    print("\n== Complexity / wire (state bytes measured; O-notation from source) ==")
    rows = [("Prism", "prism", "O(1)", "O(1) min/max", "none"),
            ("NSCC", "nscc", "O(1)", "O(1)", "none"),
            ("STrack", "strack", "O(1)", "O(1)", "none"),
            ("Swift", "swift", "O(1)", "O(1)", "none"),
            ("MNSCC", "mnscc", "O(1) [32-win]", "O(H log H)", "none"),
            ("MSwift", "mswift", "O(1) [64-win]", "O(H log H)", "none"),
            ("REPS(LB)", "reps", "O(8)", "O(1)", "none")]
    print(f"  {'arm':9} {'state B':>8} {'state':>14} {'per-ACK':>12} {'wire':>6}")
    for lab, k, sO, cO, wire in rows:
        print(f"  {lab:9} {st.get(k,0):>8} {sO:>14} {cO:>12} {wire:>6}")

def selftest():
    import tempfile, shutil
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "c.csv"), "w") as fh:
        fh.write("algo,h,ns_per_op\nprism,0,1.5\nmnscc,2,5.0\nmnscc,32,40.0\n")
    c = read_compute(os.path.join(d, "c.csv"))
    assert abs(c["o1"]["prism"] - 1.5) < 1e-9, c
    assert c["median"]["mnscc"] == [(2, 5.0), (32, 40.0)], c
    with open(os.path.join(d, "s.csv"), "w") as fh:
        fh.write("algo,bytes\nprism,56\nmnscc,264\n")
    s = read_state(os.path.join(d, "s.csv"))
    assert s["prism"] == 56 and s["mnscc"] == 264, s
    # figO3/figO4 aggregation on a synthetic PRISM_EPOCH csv (cols: time_ns,flow_id,base_rtt_ns,
    # c_cc_ns,c_spray_ns,region,cwnd_bytes,samples,cut). Two decisions 14000ns apart -> cadence 14us.
    e = os.path.join(d, "epoch_k1_s13.epoch.csv")
    with open(e, "w") as fh:
        fh.write("0,1,14000,5,1,0,100000,4,0\n")
        fh.write("14000,1,14000,5,1,2,90000,6,1\n")
        fh.write("28000,1,14000,5,1,0,95000,5,0\n")
    cad_us, base_us, samp = epoch_stats(e)
    assert abs(cad_us - 14.0) < 1e-6, cad_us       # 14000 ns deltas -> 14 us cadence
    assert abs(base_us - 14.0) < 1e-6, base_us
    assert sorted(samp) == [4, 5, 6], samp
    shutil.rmtree(d)
    print("ok expH_overhead make_figs selftest")

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--render" in sys.argv:
        render_state(); render_compute(); render_samples(); render_latency(); print_tables()
    else:
        print("usage: make_figs.py [--selftest | --render]")
