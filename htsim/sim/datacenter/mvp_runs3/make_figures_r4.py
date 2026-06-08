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
