#!/usr/bin/env python3
"""Exp C, INCAST (delay-driven, -disable_trim) figures -- thin wrapper over common/perf_figs.py.
Renders figC1_main_perf + figC2_mechanism from ./data into ./figs. Pure shared-bottleneck
fallback: N senders -> 1 dest on the symmetric 1os topo (-failed 0). x-axis = fan-in {8,32,64},
encoded in the f{fanin} filename token.
  python3 make_figs.py            # render
  python3 make_figs.py --selftest # aggregation self-check (shared perf_figs math)
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import perf_figs  # noqa: E402

DATA = os.path.join(HERE, "data")
FIGS = os.path.join(HERE, "figs")
BASELINES = [("ops", "OPS+NSCC", "ops"), ("reps", "REPS+NSCC", "reps"),
             ("strack", "STrack", "strack"), ("prism", "PRISM", "prism")]
FANIN = [8, 32, 64]         # incast fan-in (x-axis) and the f{fanin} filename token
SEEDS = [13, 14, 15, 16, 17]
XLABEL = "incast fan-in (senders : 1), delay-driven (-disable_trim)"

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        perf_figs.selftest()
    else:
        os.makedirs(FIGS, exist_ok=True)
        perf_figs.render_main_perf(DATA, FIGS, "expC", BASELINES, FANIN, SEEDS, "figC1_main_perf", XLABEL)
        perf_figs.render_mechanism(DATA, FIGS, "expC", "figC2_mechanism", 64, mech_label="fan-in=64")
