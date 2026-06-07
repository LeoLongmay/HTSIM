#!/usr/bin/env python3
"""Demonstration figures for the per-path-RTT congestion decomposition.
Bar/sweep figures use the cross-flow MEDIAN (aggregate_tag) — the robust statistic —
not a single run-dependent representative flow. Fig1 shows one flow's time dynamics.
Run: python3 make_figures.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pathrtt_analyze as A

HERE = os.path.dirname(os.path.abspath(__file__))

def med(tag):
    a = A.aggregate_tag(tag)
    return (a["cspray_med"], a["ccc_med"]) if a else (None, None)

# Fig 1 — decisive run time series (representative flow): both components nonzero
rows = A.parse_csv(os.path.join(HERE, "reps_a8.pathrtt.csv"))
mins = A.rtt_min_per_path(rows); flow = A.representative_flow(rows)
t, cs, cc = A.decompose(rows, mins, flow)
t_us = [x/1000 for x in t]; cs_us = [x/1000 for x in cs]; cc_us = [x/1000 for x in cc]
plt.figure(figsize=(10, 4))
plt.plot(t_us, cs_us, label="C_spray = max_i q_i - min_i q_i")
plt.plot(t_us, cc_us, "--", label="C_cc = min_i q_i")
plt.axvspan(500, 1500, color="grey", alpha=0.12)
plt.xlabel("time (us)"); plt.ylabel("per-path queueing delay q (us)")
plt.title("Decisive run (REPS, incast->host0, failed=8): both components nonzero")
plt.legend(); plt.grid(alpha=0.3); plt.xlim(0, 2000)
plt.tight_layout(); plt.savefig(f"{HERE}/fig1_decisive.png", dpi=130); plt.close()

x = [0, 1]; w = 0.35

# Fig 2 — LB contrast (cross-flow median): REPS lowers C_spray, leaves C_cc
rs, rc = med("reps_a8"); o_s, oc = med("obl_a8")
plt.figure(figsize=(7, 4))
plt.bar([i-w/2 for i in x], [rs, rc], w, label="REPS")
plt.bar([i+w/2 for i in x], [o_s, oc], w, label="OBLIVIOUS")
plt.xticks(x, ["C_spray", "C_cc"]); plt.ylabel("cross-flow median q (us)")
plt.title("LB contrast @ failed=8: REPS << OBL on C_spray; equal on C_cc")
plt.legend(); plt.grid(alpha=0.3, axis="y")
plt.tight_layout(); plt.savefig(f"{HERE}/fig2_lb_contrast.png", dpi=130); plt.close()

# Fig 3 — symmetric vs asymmetric (cross-flow median)
s0, c0 = med("reps_a0"); s8, c8 = med("reps_a8")
plt.figure(figsize=(7, 4))
plt.bar([i-w/2 for i in x], [s0, c0], w, label="failed=0 (sym)")
plt.bar([i+w/2 for i in x], [s8, c8], w, label="failed=8 (asym)")
plt.xticks(x, ["C_spray", "C_cc"]); plt.ylabel("cross-flow median q (us)")
plt.title("Symmetric vs asymmetric (REPS)")
plt.legend(); plt.grid(alpha=0.3, axis="y")
plt.tight_layout(); plt.savefig(f"{HERE}/fig3_sym_vs_asym.png", dpi=130); plt.close()

# Fig 4 — sweeps (cross-flow median): C_spray vs asymmetry; C_cc vs load
fails = [0, 4, 8, 12]; spray = [med(f"reps_a{f}")[0] for f in fails]
degs = [16, 32, 64]; cc_load = [med("reps_n16")[1], med("reps_a8")[1], med("reps_n64")[1]]
fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4))
a1.plot(fails, spray, "o-"); a1.set_xlabel("-failed (asymmetry)")
a1.set_ylabel("C_spray cross-flow median (us)"); a1.set_title("C_spray vs asymmetry"); a1.grid(alpha=0.3)
dd = [d for d, v in zip(degs, cc_load) if v is not None]
vv = [v for v in cc_load if v is not None]
a2.plot(dd, vv, "s-"); a2.set_xlabel("incast degree N")
a2.set_ylabel("C_cc cross-flow median (us)"); a2.set_title("C_cc vs load"); a2.grid(alpha=0.3)
plt.tight_layout(); plt.savefig(f"{HERE}/fig4_sweeps.png", dpi=130); plt.close()

print("wrote fig1_decisive.png fig2_lb_contrast.png fig3_sym_vs_asym.png fig4_sweeps.png")
print(f"  Fig2 LB contrast: REPS C_spray={rs:.2f} C_cc={rc:.2f} | OBL C_spray={o_s:.2f} C_cc={oc:.2f}")
