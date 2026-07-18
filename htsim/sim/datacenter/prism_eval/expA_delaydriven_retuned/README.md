# expA_delaydriven — RETUNED PRISM (what-if, non-destructive)

**What this is.** An exploration: re-run PRISM's **entire** delay-driven failed-link sweep at the
grid-scan recommended configs, to see what the headline `figA1dd` would look like if PRISM's
defaults were retuned. The original `../expA_delaydriven` figures are **not touched**.

PRISM is re-run at every failure level {0,2,4,6,8,10,12} × seeds {13–17} with a **single
consistent** config (no per-point cherry-picking); all 6 other CC arms are **reused read-only**
(symlinked from `../expA_delaydriven/data`). Two configs:

| config | T_spray | T_cc | kappa | character |
|--------|---------|------|-------|-----------|
| **A** | 7 µs | 10 µs | 1 | fairness-locked Pareto improvement |
| **B** | 7 µs | 10 µs | 2 | throughput-leaning; fixes the f0 cost; mild mid-range fairness give |

Workload/topology/END identical to the headline (m2m 64→16 2 MB, fat_tree_128_1os, `-disable_trim`,
END=8). All cells cr=1.00.

## Figures (`figs/`)
- `figA1dd_A_{goodput,avg_fct,p99_fct,fairness}` — full 7-arm headline with PRISM = config A.
- `figA1dd_B_{goodput,avg_fct,p99_fct,fairness}` — full 7-arm headline with PRISM = config B.
- `figRetune_overlay_{goodput,avg_fct,fairness}` — decision aid: PRISM default vs A vs B (+ REPS ref).

## Result (PRISM vs the published default, across the sweep)

| | f0 goodput | f0 avg-FCT | f0 Jain | f8 goodput (vs REPS) | f8 Jain | mid-range (f2–f8) Jain |
|---|---|---|---|---|---|---|
| **default (14,14,1)** | 869 | 945 µs | 0.880 | 504 (+17%) | 0.979 | best (0.84→0.98) |
| **A (7,10,1)** | 863 (≈) | 951 µs (≈) | 0.890 | 539 (+25%) | 0.980 | preserved |
| **B (7,10,2)** | **926** | **735 µs** | **0.934** | **553 (+28%)** | 0.944 | **degraded** (f2 0.79, f4 0.81) |

- **B** improves goodput AND avg/p99-FCT at **every** failure level, and fixes the f0 symmetric
  cost (f0 goodput +6.6%, avg-FCT −22%, f0 Jain +0.05, REPS gap −13%→−7%). **Cost:** mid-range
  (f2–f8) fairness drops below the default and near REPS at f2/f4 — visible in `figA1dd_B_fairness`.
- **A** keeps fairness intact everywhere and boosts the f8 win to +25%, but does **not** help f0
  (kappa stays at 1).

## Honest caveats (important)
1. **Tuned on this workload.** A/B come from a grid scan on this exact 128-node m2m 2 MB workload —
   using them in the headline is overfitting unless validated cross-scale (1024) and on mixed flow
   sizes, which is **untested**.
2. **T_cc is the SHARED NSCC target.** PRISM here runs at q=10 while the baselines keep q=14, i.e.
   "each system at its own setting," not iso-parameter. The advantage is measured vs REPS@default.
3. **This is an exploration, not an adopted default.** No code default changed; the published
   `expA_delaydriven` headline is unmodified.

## Reproduce
```bash
# from sim/datacenter — re-runs PRISM A+B over the full sweep (other arms reused), then renders
bash /path/to/setup_retuned.sh   # 70 PRISM runs -> data_A/, data_B/ (+ symlinked arms)
python3 prism_eval/expA_delaydriven_retuned/make_figs.py
```
Raw data gitignored. Imports the shared `common/perf_figs.py` (WIP).
