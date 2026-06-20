#!/usr/bin/env python3
"""1024-node scale-verification figures -- thin wrapper over common/perf_figs.py.
Renders the D1 set (1:1 delay-driven, scales expA_delaydriven) and the D2 set
(oversub asymmetric, scales expB_oversub_asym) from ./data into ./figs.

D1 (fat_tree_1024.topo, 100G/1:1, 256->64 2MB, -failed {0,8,16,24,32,48}):
  figD1_{goodput,avg_fct,p99_fct}  (FCT in ms) + figD1_fairness + figD1_mech_{signal,cwnd}
D2 (oversub, same workload):
  4:1 (fat_tree_1024_4os_100g.topo, -failed {0,1,2,3,4}): figD2_4os_main + figD2_4os_fairness
  8:1 (fat_tree_1024_8os.topo, -failed {0,1,2,4}, saturation): figD2_8os_main
  mechanism (4:1, failed=4): figD2_mech

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
             ("swift", "REPS+Swift", "swift"), ("mswift", "REPS+MSwift", "mswift"),
             ("mnscc", "REPS+MNSCC", "mnscc"), ("strack", "STrack", "strack"),
             ("prism", "Prism", "prism")]
SEEDS = [13, 14, 15, 16, 17]

# D1: 1:1 delay-driven. failed = pod0 core-ingress choke {0,12.5,25,37.5,50,75}%.
FAILED_D1 = [0, 8, 16, 24, 32, 40, 48]
XLABEL_D1 = "# constrained core->agg uplinks (-failed; pod0 has 64)"
# D2: oversub. 4:1 cr=1 win window; 8:1 saturation boundary (cr reported on the figure).
FAILED_4OS = [0, 1, 2, 3, 4]
FAILED_8OS = [0, 1, 2, 4]
XLABEL_4OS = "requested -failed (4:1 oversub, 100G, delay-driven)"
XLABEL_8OS = "requested -failed (8:1 oversub, delay-driven; saturates)"
# D3: offered-load sweep (Poisson, failed=16, 1:1).
LOADS = [10, 30, 50, 70, 90]
XLABEL_LOAD = "offered load (% of receiver-access capacity, 6.4 Tbps; failed=16)"

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        perf_figs.selftest()
    else:
        os.makedirs(FIGS, exist_ok=True)
        # --- D1 (scales expA_delaydriven) ---
        perf_figs.render_main_perf_split(DATA, FIGS, "expD1", BASELINES, FAILED_D1, SEEDS, "figD1", XLABEL_D1)
        perf_figs.render_fairness(DATA, FIGS, "expD1", BASELINES, FAILED_D1, SEEDS, "figD1_fairness", XLABEL_D1)
        perf_figs.render_mechanism_split(DATA, FIGS, "expD1", "figD1_mech", 32, xlim_ms=3.0,
                                         mech_label="1:1, failed=32 (50% pod0 ingress)")
        perf_figs.render_decomposition(DATA, FIGS, "expD1",
            [(0, "1024 nodes, failed=0 (symmetric)"), (32, "1024 nodes, failed=32 (asymmetric)")],
            "figD1_mech_decomp", ylim_us=100)
        # Merged decomposition: 128 (solid) + 1024 (dashed) overlaid, binned only (no raw).
        EXPA_DATA = os.path.join(HERE, "..", "expA_delaydriven", "data")
        perf_figs.render_decomposition_merged(FIGS, "figAD_decomp", [
            ("Symmetric (failed=0)", [
                (EXPA_DATA, "expA", 0, 13, "-", "(128)", "tab:red", "tab:green"),
                (DATA, "expD1", 0, 13, "--", "(1024)", "tab:blue", "tab:orange")]),
            ("Asymmetric (128:f8 / 1024:f32)", [
                (EXPA_DATA, "expA", 8, 13, "-", "(128)", "tab:red", "tab:green"),
                (DATA, "expD1", 32, 13, "--", "(1024)", "tab:blue", "tab:orange")]),
        ], ylim_us=80)
        # --- D2 (scales expB_oversub_asym) ---
        perf_figs.render_main_perf(DATA, FIGS, "expD2_4os", BASELINES, FAILED_4OS, SEEDS,
                                   "figD2_4os_main", XLABEL_4OS)
        perf_figs.render_main_perf(DATA, FIGS, "expD2_8os", BASELINES, FAILED_8OS, SEEDS,
                                   "figD2_8os_main", XLABEL_8OS)
        perf_figs.render_fairness(DATA, FIGS, "expD2_4os", BASELINES, FAILED_4OS, SEEDS,
                                  "figD2_4os_fairness", XLABEL_4OS)
        perf_figs.render_mechanism(DATA, FIGS, "expD2_4os", "figD2_mech", 4,
                                   mech_label="4:1 oversub (100G), failed=4 (cr=1 win point)")
        # --- D3 (offered-load sweep) ---
        perf_figs.render_main_perf_split(DATA, FIGS, "expD3load", BASELINES, LOADS, SEEDS,
                                         "figD3_load", XLABEL_LOAD, token="L")
