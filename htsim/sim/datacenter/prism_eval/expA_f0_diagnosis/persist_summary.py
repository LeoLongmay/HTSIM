#!/usr/bin/env python3
"""Scheme A acceptance table: PRISM goodput/avg-FCT at failed{0,8} for the delta=0 baseline and
each (delta,beta), vs that baseline and the REPS+NSCC reference (reused from expA_delaydriven/data)."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import perf_figs  # noqa: E402

DATA = os.path.join(HERE, "data")
EXPA = os.path.join(HERE, "..", "expA_delaydriven", "data")
SEEDS = [13, 14, 15, 16, 17]
FAILED = [0, 8]
CONFIGS = [("d0_b0", "delta=0 (base)")] + [
    (f"d{d}_b{b}", f"delta={d} beta={b}")
    for d in ("0.5", "1.0") for b in ("0.0625", "0.015625")]

reps = perf_figs.aggregate(EXPA, "expA", "reps", FAILED, SEEDS)
prism = {lab: perf_figs.aggregate(DATA, "persist", lab, FAILED, SEEDS) for lab, _ in CONFIGS}

def g(d, f): return d[f]["goodput"][0] if f in d else float("nan")
def a(d, f): return d[f]["avg_fct"][0] if f in d else float("nan")

print(f"\n{'cell':>5} | {'config':>20} | {'goodput Gbps':>13} | {'avg-FCT us':>11} | {'Δgoodput vs base':>16}")
print("-" * 82)
for f in FAILED:
    base_g = g(prism["d0_b0"], f)
    print(f"{('f'+str(f)):>5} | {'REPS+NSCC':>20} | {g(reps,f):>13.1f} | {a(reps,f):>11.0f} |")
    for lab, name in CONFIGS:
        dg = g(prism[lab], f) - base_g
        print(f"{('f'+str(f)):>5} | {name:>20} | {g(prism[lab],f):>13.1f} | {a(prism[lab],f):>11.0f} | {dg:>+16.1f}")
    print("-" * 82)
print("\nAcceptance: some (delta,beta) raises f0 goodput toward REPS (Δ>0, FCT down) AND keeps f8 within")
print("seed-noise of delta=0. If BOTH betas show no f0 effect -> null robust to beta. Else widen beta.")
