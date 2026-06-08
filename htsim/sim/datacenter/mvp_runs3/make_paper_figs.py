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
import os, sys, statistics
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

# ---- FigA: C_cc floor vs load, LB-invariant (symmetric incast) -> need CC ----
Ns = [16, 32, 64]
a_reps = [ms(f"mp_inc_reps_n{n}", "const", WIN_INC, "ccc_med", const_base=BPROP) for n in Ns]
a_obl  = [ms(f"mp_inc_obl_n{n}",  "const", WIN_INC, "ccc_med", const_base=BPROP) for n in Ns]
plt.figure(figsize=(7, 4.5))
plt.errorbar(Ns, [m for m,_,_ in a_reps], yerr=[s for _,s,_ in a_reps], fmt="s-",  capsize=4, label="REPS")
plt.errorbar(Ns, [m for m,_,_ in a_obl],  yerr=[s for _,s,_ in a_obl],  fmt="o--", capsize=4, label="OBLIVIOUS")
plt.xlabel("incast degree N (offered load)")
plt.ylabel(f"C_cc cross-flow median (us)\n[vs true floor {BPROP/1000:.1f}us]")
plt.title("FigA. Irreducible floor C_cc rises with load and is LB-invariant\n"
          "(symmetric incast) -> only CC can reduce it")
plt.legend(); plt.grid(alpha=0.3); plt.xticks(Ns); plt.ylim(bottom=0)
plt.tight_layout(); plt.savefig(f"{HERE}/figA_floor_vs_load.png", dpi=140); plt.close()

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
plt.tight_layout(); plt.savefig(f"{HERE}/figB_spray_lb_removable.png", dpi=140); plt.close()

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
plt.tight_layout(); plt.savefig(f"{HERE}/figC_lb_depends_on_bottleneck.png", dpi=140); plt.close()

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
print("wrote figA_floor_vs_load.png figB_spray_lb_removable.png figC_lb_depends_on_bottleneck.png")
