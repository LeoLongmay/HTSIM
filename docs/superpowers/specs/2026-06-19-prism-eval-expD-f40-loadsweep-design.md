# Spec: expD_scale1024 — add failed=40 point + 1024-node offered-load figure

**Date:** 2026-06-19
**Status:** design approved (user), spec under review
**Branch:** prism-motivation-redesign (local only; origin = spcl/HTSIM public upstream — never push)

## 1. Goal

Two additions to the 1024-node scale group `expD_scale1024`, both on the D1 (1:1 `fat_tree_1024.topo`) fabric:

- **A. failed=40 point** — densify the D1 failed-sweep x-axis from `{0,8,16,24,32,48}` to
  `{0,8,16,24,32,40,48}`, filling the 32→48 gap in the high-asymmetry region.
- **B. offered-load figure** — a 1024-node open-loop Poisson FCT-vs-load study mirroring
  `expA_delaydriven`'s `figA3dd_load`, at fixed asymmetry **failed=16**.

## 2. Invariants (non-negotiable)

- **No controller change.** `htsim/sim/uec.cpp`, `uec.h`, `prism_decompose.h` byte-identical to HEAD. PRISM stays O(1).
- **7 arms, REPS spray for all non-OPS arms; only the CC varies.** Arm→(CC,LB): ops=(nscc,oblivious), reps=(nscc,reps), prism=(prism,reps), strack=(strack,reps), swift=(swift,reps), mswift=(mswift,reps), mnscc=(mnscc,reps). BASELINES order unchanged (ops, reps, swift, mswift, mnscc, strack, prism — Prism last, STrack second-to-last).
- **Reproducibility:** seeds {13,14,15,16,17}; `EXTRA_ARGS="-disable_trim"`; pinned branch; raw data gitignored; figures `git add -f`; selftests gate the run; repro.sh remains the canonical from-scratch reproducer.
- **Communication in Chinese; no git commit unless the user explicitly authorizes; never push.**

## 3. Scope (approved)

| Item | x-axis | Fabric | Fixed asymmetry | New sims |
|---|---|---|---|---|
| A. failed=40 | `-failed` (add 40) | D1 1:1 `fat_tree_1024.topo` | n/a (it IS the swept axis) | 7 arms × 5 seeds = **35** |
| B. offered-load | ρ ∈ {10,30,50,70,90}% | D1 1:1 `fat_tree_1024.topo` | **failed=16** | 7 arms × 5 ρ × 5 seeds = **175** |

Out of scope: D2 (4:1/8:1) — failed is nonlinear on oversub topos, 40 does not apply; mechanism panels (figD1_mech_*, figD2_mech) — unchanged; controller; other folders.

## 4. Item A — failed=40

- **make_figs.py:** `FAILED_D1 = [0, 8, 16, 24, 32, 48]` → `[0, 8, 16, 24, 32, 40, 48]`. This automatically adds the f40 column to `figD1_{goodput,avg_fct,p99_fct}` (render_main_perf_split) and `figD1_fairness`. The D1 mechanism call (`render_mechanism_split`, fixed `mech_failed=32`) is untouched.
- **repro.sh:** the D1 sweep loop header `for f in 0 8 16 24 32 48` → `for f in 0 8 16 24 32 40 48`. All 7 arms already run inside that loop, so f40 is produced for every arm. Data tags: `expD1_{arm}_f40_s{seed}`.

## 5. Item B — offered-load figure

- **Generator (reuse, no new code):** `common/gen/poisson_load.py` with 1024-scaled args:
  `poisson_load.py <out.cm> 256 64 2000000 1024 64 <rho_frac> 8000 6400 <seed>`
  (n_send=256, n_recv=64, size=2 MB, nodes=1024, hpp=64, window_us=8000, **ref_gbps=6400** = 64 receivers × 100 G receiver-access capacity = 6.4 Tbps; emits picosecond starts). Identical machinery to expA's load sweep, scaled 4× in node/group count and 4× in ref capacity.
- **repro.sh new block** (after the D2 sweeps, before the render step), mirroring expA's load block:
  ```
  LOAD_W_US=8000; LOAD_END=20; REF_GBPS=6400; LOAD_FAILED=16
  for rho in 10 30 50 70 90; do
    rhof=$(python3 -c "print($rho/100.0)")
    for s in $SEEDS; do
      LCM="$OUT/m2m256_load_L${rho}_s${s}.cm"
      python3 "$COMMON/gen/poisson_load.py" "$LCM" 256 64 2000000 1024 64 "$rhof" "$LOAD_W_US" "$REF_GBPS" "$s"
      # 7 arms, each with its (CC,LB), failed=16, fat_tree_1024.topo, END=20:
      PATHS=8 NODES=1024 END_MS="$LOAD_END" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" nscc oblivious "$LOAD_FAILED" fat_tree_1024.topo "$s" "$LCM" flow,sink "expD3load_ops_L${rho}_s${s}" "$OUT"
      ... reps(nscc,reps) prism(prism,reps) strack(strack,reps) swift(swift,reps) mswift(mswift,reps) mnscc(mnscc,reps) ...
    done
  done
  ```
  Data tags: `expD3load_{arm}_L{rho}_s{seed}` (arm = the BASELINES key).
- **make_figs.py:** add `LOADS = [10,30,50,70,90]`, `XLABEL_LOAD = "offered load (% of receiver-access capacity, 6.4 Tbps)"`, and one render call:
  `render_main_perf_split(DATA, FIGS, "expD3load", BASELINES, LOADS, SEEDS, "figD3_load", XLABEL_LOAD, token="L")`
  → outputs `figD3_load_{goodput,avg_fct,p99_fct}` (.png + .pdf).
- **Honest handling:** failed=16 = 25% pod0 ingress constrained — at high ρ some arms will saturate (cr<1), confounding avg-FCT. Flag every cr<1 cell in the README; use goodput+cr as the headline there, not FCT (same convention as the 8:1 cells). The renderer prints cr per cell — record it.

## 6. File-level changes

- `expD_scale1024/make_figs.py`: FAILED_D1 += 40; add LOADS/XLABEL_LOAD + the figD3_load render call.
- `expD_scale1024/repro.sh`: D1 loop header += 40; new offered-load block (gen + 7-arm sweep); echo the new figD3_load outputs in the final "done" line. Selftests already present (test_strack/swift/mnscc) — unchanged.
- `expD_scale1024/README.md`: D1 results table gains an f40 row (verbatim render numbers); new "Offered-load sweep (failed=16)" subsection with a 7-arm × 5-ρ table, cr flagged where <1.
- `prism_eval/NARRATIVE.md`: optionally extend the "Eval (win, load)" Map row to note the load-dependent win reproduces at 1024-node scale (wording driven by the measured result; no presupposition).

## 7. Reproducibility specifics

- The edited `repro.sh` reproduces ALL of D1 (now incl f40) + D2 + the new load sweep from scratch. For THIS session's execution we run only the NEW sims incrementally: 35 (f40, all 7 arms) + 175 (load); existing data is kept.
- No generator/topo changes (poisson_load.py + fat_tree_1024.topo already exist).

## 8. Runtime estimate

- A (f40): 35 sims @ END=8 ms, 1:1 → ≈ 6–8 min.
- B (load): 175 sims @ END=20 ms, heavier (high-ρ generates ~2880 flows/window at ρ=0.9, ~4× expA's 128-node load), 1024 nodes → ≈ **1–1.5 hours** (the dominant cost). Sequential (run_lib writes shared idmap.txt). Progress reported every ~10 min during the long run, with analysis.

## 9. Execution method

Subagent-driven with two-stage review per task, then a final whole-branch review. Local per-task commits (user-authorized this session); never push.

## 10. Acceptance criteria

1. `make_figs.py --selftest` passes; `python3 make_figs.py` renders `figD1_*` with 7 x-ticks {0,8,16,24,32,40,48} and `figD3_load_{goodput,avg_fct,p99_fct}` with 7 legend entries in BASELINES order; no traceback.
2. Mechanism figures (figD1_mech_cwnd, figD1_mech_signal, figD2_mech) unchanged (not committed/altered).
3. Data coverage: f40 = 35 sink files `expD1_{arm}_f40_s{seed}` (all 7 arms × 5 seeds); load = 175 sink files `expD3load_{arm}_L{rho}_s{seed}` (7 arms × {10,30,50,70,90} × 5 seeds).
4. README + NARRATIVE updated with measured numbers traceable to render stdout; every load-sweep cr<1 cell flagged (FCT not used as headline there).
5. PRISM controller byte-identical to HEAD (no diff in uec.{cpp,h}/prism_decompose.h).
