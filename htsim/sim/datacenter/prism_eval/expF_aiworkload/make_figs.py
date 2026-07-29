#!/usr/bin/env python3
"""expF_aiworkload figures -- thin wrapper. MSwift AI-training collective (Llama-70B HSDP ring
single step) x failed-links, delay-driven, 128-node 100G fabric. Renders into ./figs:
  figF1_cct_bars           grouped bar chart of CCT inflation (%), x={f0,4,8,12}, 7 arms (headline)
  figF2_fct_cdf_f0 / _f8   per-flow FCT CDF at healthy / degraded points
  figF3_ai_msgsize         CCT slowdown vs per-flow AI-ring message size
  figF4_ai_decomp          PRISM C_cc/C_spray(t), symmetric vs asymmetric
  python3 make_figs.py            # render
  python3 make_figs.py --msgsize-only  # render only FigF3 from expFmsg sweep logs
  python3 make_figs.py --selftest # aggregation self-check (shared math)
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import cct_figs    # noqa: E402
import msgsweep_figs  # noqa: E402
import perf_figs   # noqa: E402  (read-only reuse of render_decomposition; not modified)

DATA = os.path.join(HERE, "data"); FIGS = os.path.join(HERE, "figs")
BASELINES = [("ops", "OPS+NSCC", "ops"), ("reps", "REPS+NSCC", "reps"),
             ("swift", "REPS+Swift", "swift"), ("mswift", "REPS+MSwift", "mswift"),
             ("mnscc", "REPS+MNSCC", "mnscc"), ("strack", "STrack", "strack"),
             ("prism", "Prism", "prism")]
SEEDS = [13, 14, 15, 16, 17]
FAILED = [0, 4, 8, 12]
SIZES = [16384, 65536, 262144, 1048576, 4194304]
SIZE_BYTES = 13697024   # 3344 pkts x 4096 B (FP8, 80 layers; MSwift Llama-70B HSDP ring step)

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        cct_figs.selftest()
    elif "--msgsize-only" in sys.argv:
        os.makedirs(FIGS, exist_ok=True)
        msgsweep_figs.render_relative_bars(
            DATA, FIGS, "expFmsg", BASELINES, "reps", SIZES, SEEDS,
            "figF3_ai_msgsize", ylabel="CCT slowdown", ybottom=0.0, vs_best=True)
    else:
        os.makedirs(FIGS, exist_ok=True)
        cct_figs.render_cct_bars(DATA, FIGS, "expF", BASELINES, FAILED, SEEDS,
                                 "figF1_cct_bars", SIZE_BYTES)
        cct_figs.render_fct_cdf(DATA, FIGS, "expF", BASELINES, 0, SEEDS,
                                "figF2_fct_cdf_f0", title="AI ring, failed=0 (symmetric)")
        cct_figs.render_fct_cdf(DATA, FIGS, "expF", BASELINES, 8, SEEDS,
                                "figF2_fct_cdf_f8", title="AI ring, failed=8 (asymmetric)")
        perf_figs.render_decomposition(DATA, FIGS, "expF",
            [(0, "AI ring, failed=0 (symmetric)"), (8, "AI ring, failed=8 (asymmetric)")],
            "figF4_ai_decomp", ylim_us=100)
