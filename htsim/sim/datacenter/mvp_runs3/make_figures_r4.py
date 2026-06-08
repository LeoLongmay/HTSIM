#!/usr/bin/env python3
"""Round 4 demonstration figures (fig5-fig8). Kept separate from make_figures.py
(Round 3) because the in-window sample gate makes the old -end=2ms incast CSVs
ineligible at the 200-sample threshold, so the Round-3 bar figures can't be
regenerated here. Bar/sweep figures use the cross-flow median (aggregate_tag).
Run: python3 make_figures_r4.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pathrtt_analyze as A

HERE = os.path.dirname(os.path.abspath(__file__))
WB = (1000.0, 7000.0)   # Scenario B steady window (long -end=8ms runs)


def bprop():
    """Uncontended propagation+min-serialization floor (ns) from the N=1 run."""
    rows = A.parse_csv(os.path.join(HERE, "B_reps_n1.pathrtt.csv"))
    return min(r[3] for r in rows)


# ---- Scenario B (fig8): C_cc vs incast load, three baselines ----
# Shows iv-b holds ONLY against a true-propagation floor; per-flow baselines
# (own, global) self-contaminate under sustained congestion and spuriously fall.
BPROP = bprop()
Ns = [16, 32, 64]

def ccc(tag, baseline, **kw):
    a = A.aggregate_tag(tag, baseline=baseline, win=WB, **kw)
    return a["ccc_med"] if a else None

own   = [ccc(f"B_reps_n{n}", "own")                      for n in Ns]
glob  = [ccc(f"B_reps_n{n}", "global")                   for n in Ns]
const = [ccc(f"B_reps_n{n}", "const", const_base=BPROP)  for n in Ns]

plt.figure(figsize=(7.5, 4.5))
plt.plot(Ns, const, "s-",  label=f"const baseline (vs true floor {BPROP/1000:.1f}us)")
plt.plot(Ns, glob,  "o--", label="global baseline (per-flow min, contaminated)")
plt.plot(Ns, own,   "^:",  label="own baseline (per-path min, contaminated)")
plt.xlabel("incast degree N (load)"); plt.ylabel("C_cc cross-flow median (us)")
plt.title("Scenario B (symmetric, REPS): C_cc vs load\n"
          "rises only against a true floor; per-flow baselines self-contaminate")
plt.legend(fontsize=8); plt.grid(alpha=0.3); plt.xticks(Ns)
plt.tight_layout(); plt.savefig(f"{HERE}/fig8_ccc_vs_load.png", dpi=130); plt.close()
print(f"wrote fig8_ccc_vs_load.png  B_prop={BPROP}ns")
print(f"  C_cc(const)={[round(x,2) for x in const]} (iv-b) | "
      f"C_cc(global)={[round(x,2) for x in glob]} | C_cc(own)={[round(x,2) for x in own]}")


# ---- Scenario A (fig5-7): whole-pod overload into pod0, -failed sweep ----
# Default steady window [500,1500]us (these runs use -end 2ms). C_spray is
# baseline-independent (max-min raw RTT), so 'global' = 'const' for C_spray.
FAILS = [0, 4, 8, 12]

def medA(tag, baseline, key, **kw):
    a = A.aggregate_tag(tag, baseline=baseline, **kw)   # default window [500,1500]
    return a[key] if a else None

# fig5 — LB ablation: C_spray is LB-removable (REPS below OBL at every asymmetry level).
obl_s  = [medA(f"A_obl_f{f}",  "global", "cspray_med") for f in FAILS]
reps_s = [medA(f"A_reps_f{f}", "global", "cspray_med") for f in FAILS]
plt.figure(figsize=(7.5, 4.5))
plt.plot(FAILS, obl_s,  "o-",  label="OBLIVIOUS (non-adaptive)")
plt.plot(FAILS, reps_s, "s--", label="REPS (adaptive)")
plt.xlabel("-failed (asymmetry)"); plt.ylabel("C_spray cross-flow median (us)")
plt.title("Scenario A: C_spray is LB-removable\n(REPS < OBL at every asymmetry level)")
plt.legend(fontsize=8); plt.grid(alpha=0.3); plt.xticks(FAILS); plt.ylim(bottom=0)
plt.tight_layout(); plt.savefig(f"{HERE}/fig5_lb_ablation.png", dpi=130); plt.close()

# fig6 — baseline matters: per-path-own-min is artifactual; global at least trends up
# at high asymmetry. Neither is cleanly monotonic -> C_spray is spray-dominated, not
# gated by asymmetry (the iv-a caveat).
own_s  = [medA(f"A_obl_f{f}", "own",    "cspray_med") for f in FAILS]
glob_s = [medA(f"A_obl_f{f}", "global", "cspray_med") for f in FAILS]
plt.figure(figsize=(7.5, 4.5))
plt.plot(FAILS, own_s,  "^:",  label="own baseline (per-path min, artifactual)")
plt.plot(FAILS, glob_s, "o-",  label="global baseline (per-flow floor)")
plt.xlabel("-failed (asymmetry)"); plt.ylabel("C_spray cross-flow median (us)")
plt.title("Scenario A (OBL): C_spray vs asymmetry, by baseline\n"
          "global removes the own-min reversal but C_spray stays spray-dominated (large at f0)")
plt.legend(fontsize=8); plt.grid(alpha=0.3); plt.xticks(FAILS); plt.ylim(bottom=0)
plt.tight_layout(); plt.savefig(f"{HERE}/fig6_baseline_compare.png", dpi=130); plt.close()

# fig7 — C_cc vs asymmetry (const baseline): more degradation throttles load (NSCC backs
# off), so the fastest path empties and C_cc FALLS -> asymmetry and load are entangled,
# which is why a clean orthogonal driver attribution (iv) does not hold.
obl_c  = [medA(f"A_obl_f{f}",  "const", "ccc_med", const_base=BPROP) for f in FAILS]
reps_c = [medA(f"A_reps_f{f}", "const", "ccc_med", const_base=BPROP) for f in FAILS]
plt.figure(figsize=(7.5, 4.5))
plt.plot(FAILS, obl_c,  "o-",  label="OBLIVIOUS")
plt.plot(FAILS, reps_c, "s--", label="REPS")
plt.xlabel("-failed (asymmetry)"); plt.ylabel("C_cc cross-flow median (us), const baseline")
plt.title("Scenario A: C_cc falls as asymmetry throttles load\n"
          "(asymmetry & load entangled -> clean orthogonal attribution fails)")
plt.legend(fontsize=8); plt.grid(alpha=0.3); plt.xticks(FAILS); plt.ylim(bottom=0)
plt.tight_layout(); plt.savefig(f"{HERE}/fig7_ccc_vs_asymmetry.png", dpi=130); plt.close()

print(f"wrote fig5_lb_ablation.png fig6_baseline_compare.png fig7_ccc_vs_asymmetry.png")
print(f"  fig5 C_spray OBL={[round(x,2) for x in obl_s]} REPS={[round(x,2) for x in reps_s]}")
print(f"  fig6 C_spray own={[round(x,2) for x in own_s]} global={[round(x,2) for x in glob_s]}")
print(f"  fig7 C_cc   OBL={[round(x,2) for x in obl_c]} REPS={[round(x,2) for x in reps_c]}")
