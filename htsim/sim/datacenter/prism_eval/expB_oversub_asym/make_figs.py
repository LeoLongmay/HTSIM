#!/usr/bin/env python3
"""expB asymmetric-oversub figures -- thin wrapper over common/perf_figs.py. Renders
figBa_4os_main (the WIN: 4:1 core retains enough capacity to reroute -- PRISM beats baselines once a
few core links are degraded) + figBa_8os_main (8:1 is too oversubscribed: any core loss saturates ALL
arms to cr~0) + figBa_mech (mechanism at 4:1, failed=8 = 2/32 core links degraded, the win point)
from ./data into ./figs.

NOTE: `-failed N` does NOT map to "N degraded core links" on oversub topos (the indexing interacts
with the reduced core radix). Actual degraded core links (of the topo's total): 8:1 (16 total)
failed{0,2,4,8} -> {0,3,7,15}; 4:1 (32 total) failed{0,4,8,12} -> {0,1,2,3}. The x-axis is the
REQUESTED -failed; the README documents the actual degraded counts. See repro.sh's degraded-link
report.
  python3 make_figs.py            # render
  python3 make_figs.py --selftest # aggregation self-check (shared perf_figs math)
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import perf_figs  # noqa: E402

DATA = os.path.join(HERE, "data"); FIGS = os.path.join(HERE, "figs")
BASELINES = [("ops", "OPS+NSCC", "ops"), ("reps", "REPS+NSCC", "reps"),
             ("strack", "STrack", "strack"), ("prism", "Prism", "prism")]
SEEDS = [13, 14, 15, 16, 17]
# x = requested -failed. 8:1 is the real asymmetry axis (degraded {0,3,7,15} of 16; failed=8 = near-
# total core loss). 4:1 is a degenerate reference (degraded {0,1,2,3} of 32 -- knob barely acts).
FAILED_8OS = [0, 2, 4, 8]
FAILED_4OS = [0, 4, 8, 12]

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        perf_figs.selftest()
    else:
        os.makedirs(FIGS, exist_ok=True)
        perf_figs.render_main_perf(DATA, FIGS, "expBa8os", BASELINES, FAILED_8OS, SEEDS,
                                   "figBa_8os_main", "requested -failed (8:1 oversub, delay-driven)")
        perf_figs.render_main_perf(DATA, FIGS, "expBa4os", BASELINES, FAILED_4OS, SEEDS,
                                   "figBa_4os_main", "requested -failed (4:1 oversub, delay-driven)")
        perf_figs.render_mechanism(DATA, FIGS, "expBa4os", "figBa_mech", 8,
                                   mech_label="4:1 oversub, failed=8 (2/32 core links degraded)")
