#!/usr/bin/env python3
"""Paper motivation figures (reproducible, multi-seed, with error bars).

The three figures argue that CC and spraying are BOTH necessary (hence co-design):
  FigA  C_cc floor rises with load and is LB-invariant   -> need CC
  FigB  C_spray is removed by good LB (REPS < OBL) when path diversity exists -> need LB
  FigC  whether LB helps depends on the bottleneck: shared-last-hop incast (no diversity,
        REPS~=OBL) vs path-diverse whole-pod overload (REPS<OBL) -> need both, context-aware

Honest scope: these motivate that LB and CC are each necessary; they do NOT claim that a
joint co-design beats independent LB+CC (never measured here).

Data: per (config, seed) CSV at mvp_runs3/<tag>.s<seed>.pathrtt.csv, produced by repro.sh.
Stats: per seed -> cross-flow median (aggregate_rows); across seeds -> mean +/- std (error bar).
Run: python3 make_paper_figs.py   (after repro.sh has produced the data)
"""
import os, sys, statistics, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pathrtt_analyze as A

HERE = os.path.dirname(os.path.abspath(__file__))
SEEDS = [13, 14, 15, 16, 17]
WIN_INC = (1000.0, 7000.0)   # incast runs use -end 8ms
WIN_WP  = (500.0, 1500.0)    # whole-pod overload runs use -end 2ms


def ms(base, baseline, win, key, const_base=None, min_samples=200):
    """Mean +/- std across seeds of the per-seed cross-flow median. -> (mean, std, n)."""
    vals = []
    for s in SEEDS:
        path = os.path.join(HERE, f"{base}.s{s}.pathrtt.csv")
        if not os.path.exists(path):
            continue
        agg = A.aggregate_rows(A.parse_csv(path), min_samples=min_samples,
                               baseline=baseline, win=win, const_base=const_base)
        if agg:
            vals.append(agg[key])
    if not vals:
        return (None, None, 0)
    return (statistics.mean(vals), statistics.pstdev(vals) if len(vals) > 1 else 0.0, len(vals))


def bprop():
    """True propagation floor (ns) from the uncontended N=1 incast run (seed 13)."""
    return min(r[3] for r in A.parse_csv(os.path.join(HERE, "mp_inc_reps_n1.s13.pathrtt.csv")))


BPROP = bprop()


def timeseries_median(csv, const_base, bin_ns=10000, tmax_us=2000, min_samples=200):
    """Cross-flow MEDIAN per time bin of C_spray and C_cc(const) from one run's CSV.
    Uses baseline='const': C_spray=max-min (baseline-independent), C_cc=min-const_base.
    Bins are aligned by absolute time across flows. -> (times_us, cspray_us, ccc_us)."""
    rows = A.parse_csv(csv)
    mins = A.rtt_min_per_path(rows); minf = A.rtt_min_per_flow(rows)
    counts = collections.Counter(r[1] for r in rows); t1 = tmax_us * 1000
    cs_by_bin = collections.defaultdict(list); cc_by_bin = collections.defaultdict(list)
    for flow, c in counts.items():
        if c < min_samples:
            continue
        t_ns, cs, cc = A.decompose(rows, mins, flow, baseline="const",
                                   rtt_min_flow=minf, const_base=const_base, t0=0, t1=t1)
        for tt, a, b in zip(t_ns, cs, cc):
            cs_by_bin[tt].append(a); cc_by_bin[tt].append(b)
    bins = sorted(cs_by_bin)
    return ([t/1000 for t in bins],
            [statistics.median(cs_by_bin[t])/1000 for t in bins],
            [statistics.median(cc_by_bin[t])/1000 for t in bins])


# ---- FigA: C_cc floor vs load, LB-invariant (symmetric incast) -> need CC ----
Ns = [16, 32, 64]
a_reps = [ms(f"mp_inc_reps_n{n}", "const", WIN_INC, "ccc_med", const_base=BPROP) for n in Ns]
a_obl  = [ms(f"mp_inc_obl_n{n}",  "const", WIN_INC, "ccc_med", const_base=BPROP) for n in Ns]
xpos = list(range(len(Ns)))            # categorical x -> 16/32/64 drawn evenly spaced
with plt.rc_context({"font.size": 24}):    # paper styling: all text in figA at 24pt
    plt.figure(figsize=(12, 7))
    plt.errorbar(xpos, [m for m,_,_ in a_reps], yerr=[s for _,s,_ in a_reps], fmt="s-",  lw=2.5, ms=11, capsize=6, label="REPS")
    plt.errorbar(xpos, [m for m,_,_ in a_obl],  yerr=[s for _,s,_ in a_obl],  fmt="o--", lw=2.5, ms=11, capsize=6, label="OBLIVIOUS")
    plt.xlabel("incast degree N (offered load)")
    plt.ylabel(f"C_cc cross-flow median (us)\n[vs true floor {BPROP/1000:.1f}us]")
    # no in-figure title (paper convention: describe in \caption); keeps all text at 24pt unclipped
    plt.legend(); plt.grid(alpha=0.3)
    plt.xticks(xpos, [str(n) for n in Ns]); plt.ylim(10, 12); plt.yticks([10, 10.5, 11, 11.5, 12])
    plt.tight_layout(); plt.savefig(f"{HERE}/figA_floor_vs_load.png", dpi=140); plt.savefig(f"{HERE}/figA_floor_vs_load.pdf"); plt.close()

# ---- FigB: C_spray removed by LB when path diversity exists (whole-pod) -> need LB ----
fails = [0, 4, 8, 12]
b_reps = [ms(f"mp_wp_reps_f{f}", "global", WIN_WP, "cspray_med") for f in fails]
b_obl  = [ms(f"mp_wp_obl_f{f}",  "global", WIN_WP, "cspray_med") for f in fails]
plt.figure(figsize=(7, 4.5))
plt.errorbar(fails, [m for m,_,_ in b_reps], yerr=[s for _,s,_ in b_reps], fmt="s-",  capsize=4, label="REPS (adaptive)")
plt.errorbar(fails, [m for m,_,_ in b_obl],  yerr=[s for _,s,_ in b_obl],  fmt="o--", capsize=4, label="OBLIVIOUS (non-adaptive)")
plt.xlabel("-failed (link asymmetry)")
plt.ylabel("C_spray cross-flow median (us)")
plt.title("FigB. Removable spread C_spray: good LB lowers it (REPS < OBL)\n"
          "(whole-pod overload, path-diverse) -> spraying/LB is necessary")
plt.legend(); plt.grid(alpha=0.3); plt.xticks(fails); plt.ylim(bottom=0)
plt.tight_layout(); plt.savefig(f"{HERE}/figB_spray_lb_removable.png", dpi=140); plt.savefig(f"{HERE}/figB_spray_lb_removable.pdf"); plt.close()

# ---- FigC: does LB help? depends on bottleneck (incast vs whole-pod), symmetric ----
ic_r = ms("mp_inc_reps_n32", "global", WIN_INC, "cspray_med")
ic_o = ms("mp_inc_obl_n32",  "global", WIN_INC, "cspray_med")
wp_r = ms("mp_wp_reps_f0",   "global", WIN_WP,  "cspray_med")
wp_o = ms("mp_wp_obl_f0",    "global", WIN_WP,  "cspray_med")
groups = ["incast -> 1 host\n(shared bottleneck)", "whole-pod -> 8 hosts\n(path-diverse)"]
reps_v = [ic_r[0], wp_r[0]]; reps_e = [ic_r[1], wp_r[1]]
obl_v  = [ic_o[0], wp_o[0]]; obl_e  = [ic_o[1], wp_o[1]]
x = range(len(groups)); w = 0.35
plt.figure(figsize=(7, 4.5))
plt.bar([i-w/2 for i in x], reps_v, w, yerr=reps_e, capsize=4, label="REPS")
plt.bar([i+w/2 for i in x], obl_v,  w, yerr=obl_e,  capsize=4, label="OBLIVIOUS")
plt.xticks(list(x), groups); plt.ylabel("C_spray cross-flow median (us)")
plt.title("FigC. LB only removes C_spray where path diversity exists\n"
          "(symmetric load): incast REPS~=OBL; whole-pod REPS<OBL -> need both, context-aware")
plt.legend(); plt.grid(alpha=0.3, axis="y")
plt.tight_layout(); plt.savefig(f"{HERE}/figC_lb_depends_on_bottleneck.png", dpi=140); plt.savefig(f"{HERE}/figC_lb_depends_on_bottleneck.pdf"); plt.close()

# ---- FigD: REPS time series, low vs high load (asymmetric) -> LB alone limited ----
# whole-pod overload into a partly-degraded pod (failed=12, good-path cap ~400G < 800G
# receivers). At low load REPS dodges congestion (C_cc floor ~0); at high load it cannot
# (floor sustained > 0) -> spraying alone is exhausted, CC must slow the sender.
fig, (axL, axR) = plt.subplots(1, 2, figsize=(12, 4.2), sharey=True)
for ax, n, tag in ((axL, 4, "low load (4 senders): LB alone handles it"),
                   (axR, 32, "high load (32 senders): LB exhausted")):
    csv = os.path.join(HERE, f"mp_load_reps_n{n}.s13.pathrtt.csv")
    if os.path.exists(csv):
        t, cs, cc = timeseries_median(csv, const_base=BPROP)
        ax.plot(t, cs, label="C_spray = max_i q_i - min_i q_i (LB-removable)")
        ax.plot(t, cc, "--", label="C_cc = min_i q_i vs true floor (CC-only)")
    ax.axvspan(500, 1500, color="grey", alpha=0.12)
    ax.set_xlabel("time (us)"); ax.set_title(tag); ax.grid(alpha=0.3); ax.set_xlim(0, 2000)
axL.set_ylabel("per-path queueing delay (us)\ncross-flow median"); axL.legend(fontsize=8)
fig.suptitle("FigD. REPS under asymmetry (failed=12): floor C_cc stays ~0 at low load but "
             "emerges at high load -> spraying alone is limited, CC is required")
plt.tight_layout(); plt.savefig(f"{HERE}/figD_reps_floor_emerges.png", dpi=140); plt.savefig(f"{HERE}/figD_reps_floor_emerges.pdf"); plt.close()

# ---- FigE: C_cc floor vs load under REPS+asymmetry -> the 0->positive transition ----
loads = [2, 4, 8, 16, 32]
e_cc = [ms(f"mp_load_reps_n{n}", "const", WIN_WP, "ccc_med", const_base=BPROP) for n in loads]
e_sp = [ms(f"mp_load_reps_n{n}", "global", WIN_WP, "cspray_med") for n in loads]
plt.figure(figsize=(7, 4.5))
plt.errorbar(loads, [m for m,_,_ in e_cc], yerr=[s for _,s,_ in e_cc], fmt="D-", capsize=4,
             label="C_cc (irreducible floor, CC-only)")
plt.errorbar(loads, [m for m,_,_ in e_sp], yerr=[s for _,s,_ in e_sp], fmt="o--", capsize=4,
             label="C_spray (LB-removable)")
plt.xlabel("offered load (number of senders)")
plt.ylabel("cross-flow median (us)")
plt.title("FigE. REPS + asymmetry (failed=12): C_cc floor rises from ~0 to >0 with load\n"
          "-> LB suffices at low load; beyond good-path capacity only CC can reduce the floor")
plt.legend(); plt.grid(alpha=0.3); plt.xticks(loads); plt.ylim(bottom=0)
plt.tight_layout(); plt.savefig(f"{HERE}/figE_floor_vs_load_reps_asym.png", dpi=140); plt.savefig(f"{HERE}/figE_floor_vs_load_reps_asym.pdf"); plt.close()

# ---- FigF: CC strength sets the floor (REPS, failed=12, high load) -> only CC reduces C_cc ----
# Same high-load asymmetric scenario as figD-right, but sweep NSCC's target_q_delay (CC
# aggressiveness). C_cc(const) tracks the target -> the floor IS governed by CC, and
# tightening CC drives it toward 0. C_spray (LB's domain) is not reduced by tightening CC.
TQDS = [2, 4, 6, 8, 12, 16]
f_cc = [ms(f"mp_cc_tqd{q}", "const",  WIN_WP, "ccc_med", const_base=BPROP) for q in TQDS]
f_sp = [ms(f"mp_cc_tqd{q}", "global", WIN_WP, "cspray_med") for q in TQDS]
plt.figure(figsize=(7, 4.5))
plt.errorbar(TQDS, [m for m,_,_ in f_cc], yerr=[s for _,s,_ in f_cc], fmt="D-",  capsize=4,
             label="C_cc (irreducible floor)")
plt.errorbar(TQDS, [m for m,_,_ in f_sp], yerr=[s for _,s,_ in f_sp], fmt="o--", capsize=4,
             label="C_spray (LB-removable)")
plt.xlabel("NSCC target_q_delay (us)  [larger = less aggressive CC]")
plt.ylabel("cross-flow median (us)")
plt.title("FigF. CC strength sets the floor: C_cc tracks NSCC target_q_delay\n"
          "(REPS, failed=12, high load) -> tightening CC drives the floor toward 0")
plt.legend(); plt.grid(alpha=0.3); plt.xticks(TQDS); plt.ylim(bottom=0)
plt.tight_layout(); plt.savefig(f"{HERE}/figF_cc_strength_sets_floor.png", dpi=140); plt.savefig(f"{HERE}/figF_cc_strength_sets_floor.pdf"); plt.close()

# ---- console summary (for README / verification) ----
def fmt(t): return "n/a" if t[0] is None else f"{t[0]:.2f}+/-{t[1]:.2f}(n={t[2]})"
print(f"B_prop = {BPROP} ns ({BPROP/1000:.2f} us)")
print("FigA C_cc(const) vs N:")
for n, r, o in zip(Ns, a_reps, a_obl):
    print(f"  N={n:2d}: REPS {fmt(r)}  OBL {fmt(o)}")
print("FigB C_spray(global) vs -failed:")
for f, r, o in zip(fails, b_reps, b_obl):
    print(f"  f={f:2d}: REPS {fmt(r)}  OBL {fmt(o)}")
print("FigC C_spray(global), symmetric:")
print(f"  incast  N=32: REPS {fmt(ic_r)}  OBL {fmt(ic_o)}")
print(f"  whole-pod f0: REPS {fmt(wp_r)}  OBL {fmt(wp_o)}")
print("FigE C_cc(const) vs load (REPS, failed=12):")
for n, c, s in zip(loads, e_cc, e_sp):
    print(f"  n={n:2d}: C_cc {fmt(c)}  C_spray {fmt(s)}")
print("FigF C_cc(const) vs CC target_q_delay (REPS, failed=12, high load):")
for q, c, s in zip(TQDS, f_cc, f_sp):
    print(f"  tqd={q:2d}us: C_cc {fmt(c)}  C_spray {fmt(s)}")
print("wrote figA_floor_vs_load.png figB_spray_lb_removable.png figC_lb_depends_on_bottleneck.png "
      "figD_reps_floor_emerges.png figE_floor_vs_load_reps_asym.png figF_cc_strength_sets_floor.png")
