#!/usr/bin/env python3
"""Trimming-regime loss-decomposition Exp A figures. Thin wrapper over common/perf_figs.py
(figL1_main_perf + figL2_mechanism) plus a loss-HOLD-fraction print from the PRISM_LOSS log.
  python3 make_figs.py            # render
  python3 make_figs.py --selftest # aggregation self-check
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import perf_figs  # noqa: E402

DATA = os.path.join(HERE, "data"); FIGS = os.path.join(HERE, "figs")
BASELINES = [("ops", "OPS+NSCC", "ops"), ("reps", "REPS+NSCC", "reps"),
             ("prism", "PRISM (delay-only)", "prism"), ("prismL", "PRISM (+loss-decomp)", "ccc")]
FAILED = [0, 2, 4, 8, 12]; SEEDS = [13, 14, 15, 16, 17]
XLABEL = "# constrained core->agg links (-failed), trimming regime"

def loss_hold_fraction(path):
    """fabric-NACK HOLD fraction from a PRISM_LOSS csv: time,flow,ev,last_hop,action."""
    held = total = 0
    if not os.path.exists(path):
        return None
    for ln in open(path):
        p = ln.strip().split(",")
        if len(p) < 5:
            continue
        if p[3] == "0":               # fabric NACK (!last_hop)
            total += 1; held += (p[4] == "1")
    return (held, total)

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        perf_figs.selftest()
    else:
        os.makedirs(FIGS, exist_ok=True)
        perf_figs.render_main_perf(DATA, FIGS, "expL", BASELINES, FAILED, SEEDS, "figL1_main_perf", XLABEL)
        perf_figs.render_mechanism(DATA, FIGS, "expL", "figL2_mechanism", 8)
        lf = loss_hold_fraction(os.path.join(DATA, "expL_prismL_mech.loss.csv"))
        if lf:
            print(f"[figL2_mechanism] loss-HOLD fraction @failed=8 = {lf[0]}/{lf[1]} = "
                  f"{(lf[0]/lf[1] if lf[1] else float('nan')):.3f}  (>0 => loss decomposition is active)")
        else:
            print("[figL2_mechanism] no PRISM_LOSS log found for prismL mechanism run")
