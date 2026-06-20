# Spec: expE_permutation — permutation traffic × failed-links (128 + 1024)

**Date:** 2026-06-20
**Status:** design approved (user), spec under review
**Branch:** prism-motivation-redesign (local only; origin = spcl/HTSIM public upstream — never push)

## 1. Goal

Test whether PRISM's delay-driven **asymmetric-fabric advantage** — shown on the incast-style
many2many workload in `expA_delaydriven` (128) and `expD_scale1024` (1024) — **generalizes to a
uniform random permutation**, the standard load-balancer benchmark used by STrack and MSwift. This
adds the comparability point those papers expect and directly addresses the "PRISM only wins on a
contrived incast" critique: a permutation has **no incast / no receiver oversubscription**, so any
behavior is attributable to the fabric (failed links), not to a fan-in hotspot.

A new experiment group `expE_permutation/` mirrors the `expA`/`expD` structure exactly, swapping only
the workload (`many2many.cm` → `permutation.cm`). **No controller change.**

## 2. Setup

| Parameter | 128-node (P1) | 1024-node (P2) |
|---|---|---|
| Topology | `fat_tree_128_1os.topo` (3-tier, 100G, 1:1) | `fat_tree_1024.topo` (3-tier, 100G, 1:1) |
| Nodes | 128 | 1024 |
| Failed-link sweep | `{0,2,4,6,8,10,12}` | `{0,8,16,24,32,40,48}` |
| Workload | full random permutation, 2 MB/flow | full random permutation, 2 MB/flow |
| Regime | delay-driven (`-disable_trim`), END=8 ms, PATHS=8 | same |
| Arms | 7 | 7 |
| Seeds | 13–17 (5) | 13–17 (5) |

- **Arms (7, same as expA):** `ops` (CC=nscc, LB=oblivious), `reps` (nscc/reps), `swift` (swift/reps),
  `mswift` (mswift/reps), `mnscc` (mnscc/reps), `strack` (strack/reps), `prism` (prism/reps). Only the
  CC varies; all non-ops arms spray with REPS. PRISM runs with `PRISM_EPOCH` logging.
- **Workload generation (reuses committed `common/gen/permutation.py`, per-seed):** a different random
  derangement per seed so results average over permutation instances as well as the simulator's
  path-randomization seed:
  - P1: `permutation.py perm128_s{seed}.cm 1.0 2000000 128 {seed}` → 128 flows (every host sends one
    2 MB message to exactly one distinct host; Sattolo single-cycle, no self-pairs).
  - P2: `permutation.py perm1024_s{seed}.cm 1.0 2000000 1024 {seed}` → 1024 flows.
- **Run count:** 7 arms × 7 failed × 5 seeds × 2 scales = **490 runs**. The 1024 runs are heavier and
  **must run sequentially** (run_lib.sh writes a shared `idmap.txt`).
- **END=8 ms** is the starting value (matches expA/expD D1); the implementation must probe completion
  (cr≈1) and override `EXP_END` if any cell is completion-stressed.

## 3. Metrics and figures (no fairness)

Per the user, only the three performance panels — **no fairness panel, no mechanism/decomp panel**:

- `figs/figE_p128_{goodput,avg_fct,p99_fct}.{pdf,png}` via
  `render_main_perf_split(DATA, FIGS, "expEp128", BASELINES, FAILED_128, SEEDS, "figE_p128",
  "Number of failed links", goodput_tbps=True)` — goodput in Tbps, FCT in ms (the shared renderer's
  conventions; identical to `figA1dd`/`figD1`).
- `figs/figE_p1024_{goodput,avg_fct,p99_fct}.{pdf,png}` via the same call with `"expEp1024"`,
  `FAILED_1024`, `"figE_p1024"`.

Tags written by `run_lib.sh` must be `expEp128_{arm}_f{failed}_s{seed}` and
`expEp1024_{arm}_f{failed}_s{seed}` so `perf_figs.aggregate` resolves the `.flow.txt` files.

## 4. Pre-registered expectation (honest, stated up front)

- **f0 (symmetric permutation):** the canonical load-balancer benchmark. The spraying arms balance
  evenly; PRISM is expected to be **do-no-harm or carry a small f0-style cost** (the transient-spread
  under-growth characterized in `expA_f0_diagnosis`) — **not a win** (no reroutable asymmetry to
  exploit).
- **f>0 (asymmetric):** PRISM's spread-aware decomposition should let it avoid degraded paths →
  **modest win or at least do-no-harm**. This is the actual test: does the asymmetric advantage
  generalize from the incast-style many2many to a uniform permutation?
- **A tie everywhere is an acceptable, publishable outcome:** do-no-harm on the standard permutation
  benchmark refutes the "only wins on contrived incast" critique. The result is reported straight
  whichever way it lands.

## 5. Honest caveat (documented in README)

`permutation.py` produces a **random derangement** (the standard permutation, as in STrack/MSwift),
not a guaranteed cross-pod matching. On 128 nodes (8 pods) ≈ 1/8 of pairs land **intra-pod** and do
not traverse the core, so failed **core** links bite only the ≈ 7/8 cross-pod flows. This is an
inherent property of a uniform permutation and is noted, not engineered around.

## 6. Invariants (non-negotiable)

- **No controller change.** Reuses the committed `permutation.py`, `run_lib.sh`, `perf_figs.py`
  unchanged. PRISM stays O(1).
- **Reproducibility standard (carried from expA/expD):** pinned branch, seeds {13..17}, one-command
  `repro.sh` that regenerates ALL arms from scratch, raw data gitignored, figures `git add -f`,
  selftests gate the run.
- **Flow-only logging** (`flow`, not `flow,sink`) — consistent with the disk-saving change applied to
  the other repro.sh.
- **Communication in Chinese; no git commit unless the user explicitly asks (per-task local commits
  ARE authorized for the subagent-driven run); never push.**

## 7. Change set (new directory only; shared code untouched)

| File | Change |
|---|---|
| `expE_permutation/repro.sh` | **new** — generates per-seed perm128/perm1024 `.cm`; runs the 490-run sweep (P1 then P2, sequential); renders figures. Selftest gate up top. |
| `expE_permutation/make_figs.py` | **new** — thin wrapper: two `render_main_perf_split` calls (P1, P2); `--selftest` delegates to `perf_figs.selftest()`. |
| `expE_permutation/README.md` | **new** — setup table, the §4 pre-registration, the §5 caveat, honest results table (filled after the run). |
| `expE_permutation/.gitignore` (or repo .gitignore) | data/ gitignored as elsewhere. |

Reused unchanged: `common/gen/permutation.py`, `common/run_lib.sh`, `common/perf_figs.py`,
`common/metrics.py`, `common/plot_style.py`, the two topology files.

## 8. Out of scope / deferred

- Fairness panel (dropped per user).
- Mechanism / C_cc–C_spray decomposition figure under permutation.
- Offered-load (Poisson) permutation variant.
- A guaranteed-cross-pod permutation variant.
- Any controller change.
