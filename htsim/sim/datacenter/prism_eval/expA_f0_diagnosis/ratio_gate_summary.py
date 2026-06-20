#!/usr/bin/env python3
"""ρ-gate acceptance table: PRISM goodput/avg-FCT at failed{0,8} for rho{0,3,5,8},
vs the rho=0 baseline and the REPS+NSCC reference (reused from expA_delaydriven/data)."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import perf_figs  # noqa: E402

DATA = os.path.join(HERE, "data")
EXPA = os.path.join(HERE, "..", "expA_delaydriven", "data")
SEEDS = [13, 14, 15, 16, 17]
FAILED = [0, 8]
RHOS = [0, 3, 5, 8]

# REPS+NSCC reference (the arm PRISM is trying to recover toward at f0).
reps = perf_figs.aggregate(EXPA, "expA", "reps", FAILED, SEEDS)
# PRISM per-rho: tag_prefix="rgate", label=f"rho{rho}", token="f".
prism = {rho: perf_figs.aggregate(DATA, "rgate", f"rho{rho}", FAILED, SEEDS) for rho in RHOS}

def g(d, f):   return d[f]["goodput"][0] if f in d else float("nan")
def a(d, f):   return d[f]["avg_fct"][0] if f in d else float("nan")

print(f"\n{'cell':>6} | {'arm':>14} | {'goodput Gbps':>13} | {'avg-FCT us':>11} | {'Δgoodput vs ρ=0':>16}")
print("-" * 78)
for f in FAILED:
    base_g = g(prism[0], f)
    print(f"{('f'+str(f)):>6} | {'REPS+NSCC':>14} | {g(reps,f):>13.1f} | {a(reps,f):>11.0f} |")
    for rho in RHOS:
        dg = g(prism[rho], f) - base_g
        tag = "PRISM ρ=0(base)" if rho == 0 else f"PRISM ρ={rho}"
        print(f"{('f'+str(f)):>6} | {tag:>14} | {g(prism[rho],f):>13.1f} | {a(prism[rho],f):>11.0f} | {dg:>+16.1f}")
    print("-" * 78)
print("\nAcceptance: at f0 some ρ raises goodput toward REPS (Δ>0, FCT down); at f8 that same ρ keeps")
print("goodput within seed-noise of ρ=0. Report the knee ρ. If none qualifies -> honest-null, revert.")
