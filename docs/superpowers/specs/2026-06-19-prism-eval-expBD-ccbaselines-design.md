# Spec: backfill Swift / MSwift / MNSCC into expB_oversub_asym + expD_scale1024

**Date:** 2026-06-19
**Status:** design approved (user), spec under review
**Branch:** prism-motivation-redesign (local only; origin = spcl/HTSIM public upstream — never push)

## 1. Goal

Extend the two PRISM-eval **generalization** experiment groups — `expB_oversub_asym`
(asymmetric oversubscription) and `expD_scale1024` (1024-node scale) — with the three
delay-CC competitors already used in the headline `expA_delaydriven`:

- `swift`  → legend **REPS+Swift**
- `mswift` → legend **REPS+MSwift**
- `mnscc`  → legend **REPS+MNSCC**

so that the head-to-head CC comparison made in F1 (expA) is shown to **generalize** to an
oversubscribed core (expB 4:1/8:1) and to 8× scale (expD D1/4:1/8:1). This was the deferred
"PAPER MAIN-PERFORMANCE SET" follow-on; the user locked the main-performance set to exactly
these three folders, and chose full-zoo (all three new arms, not just MSwift).

## 2. Invariants (non-negotiable)

- **No controller change.** All three CCs are already implemented in `uec.cpp` and exercised by
  expA. PRISM stays O(1); `prism_decompose.h`, the PRISM dispatch, and `uec.{h,cpp}` are untouched.
- **All new arms run on REPS spray** (`CC={swift,mswift,mnscc} LB=reps`) — only the CC varies, exactly
  as in expA. The apples-to-apples comparison holds the spray fixed.
- **Reproducibility standard carried over:** pinned branch, seeds {13,14,15,16,17}, one-command
  `repro.sh` that regenerates ALL arms from scratch, raw data gitignored, figures `git add -f`,
  selftests gate the run.
- **Communication in Chinese; no git commit unless the user explicitly asks; never push.**

## 3. Scope decision (approved)

| Figure class | Gets the 3 new arms? |
|---|---|
| Main performance panels (goodput / avg-FCT / p99-FCT) | **Yes**, both folders, all oversub cases |
| Fairness panels | **Yes** |
| Mechanism panels (figBa_mech, figD1_mech, figD2_mech) | **No** — stay at OPS/REPS+NSCC/STrack/Prism |

Rationale for excluding mechanism panels: those panels demonstrate PRISM's floor-MD mechanism vs
averaging baselines (cut-counts, floor-MD fraction, C_cc binned signal). They do not need the CC
zoo, adding three more cwnd/cut lines clutters them, and it avoids extra 1024-node mechanism runs.

Explicitly **out of scope:** mechanism-panel arms; permutation workload; 400G/800G link-rate
variant; any controller/spray change.

## 4. Legend / ordering (match expA exactly)

`BASELINES` in both `make_figs.py` becomes, in this order:

```
("ops",    "OPS+NSCC",   "ops"),
("reps",   "REPS+NSCC",  "reps"),
("swift",  "REPS+Swift", "swift"),
("mswift", "REPS+MSwift","mswift"),
("mnscc",  "REPS+MNSCC", "mnscc"),
("strack", "STrack",     "strack"),
("prism",  "Prism",      "prism"),
```

Prism last, STrack second-to-last, every REPS-sprayed CC arm labeled `REPS+…`. Colors already
exist in `common/plot_style.py` (swift=tab:pink, mswift=tab:olive, mnscc=tab:brown). No plot_style
change needed.

## 5. File-level changes

### 5.1 `expB_oversub_asym/` (128-node, fast)
- **make_figs.py:** replace the 4-arm `BASELINES` with the 7-arm list (§4). This automatically
  feeds `render_main_perf` (figBa_8os_main, figBa_4os_main) and `render_fairness`
  (figBa_4os_fairness). The `render_mechanism` call (figBa_mech) is left unchanged → still 4 arms.
- **repro.sh:** in the `for R in 8os 4os / for f / for s` main-sweep loop, append three runs per
  `(R,f,s)`:
  - `run_lib.sh swift  reps "$f" "$T" "$s" "$CM" flow,sink "expBa${R}_swift_f${f}_s${s}"  "$OUT"`
  - `run_lib.sh mswift reps "$f" "$T" "$s" "$CM" flow,sink "expBa${R}_mswift_f${f}_s${s}" "$OUT"`
  - `run_lib.sh mnscc  reps "$f" "$T" "$s" "$CM" flow,sink "expBa${R}_mnscc_f${f}_s${s}"  "$OUT"`
  Mechanism block unchanged. Selftest block gains the two CC unit tests (see §6).

### 5.2 `expD_scale1024/` (1024-node, slower)
- **make_figs.py:** same 7-arm `BASELINES`. Feeds `render_main_perf_split` (figD1_*),
  `render_fairness` (figD1_fairness, figD2_4os_fairness), and `render_main_perf` (figD2_4os_main,
  figD2_8os_main). The two `render_mechanism*` calls (figD1_mech, figD2_mech) unchanged → 4 arms.
- **repro.sh:** append the three new arms in each of the three sweep loops:
  - D1 (failed {0,8,16,24,32,48}, fat_tree_1024.topo, END=$END_D1): tags `expD1_{arm}_f${f}_s${s}`
  - D2 4:1 (failed {0,1,2,3,4}, fat_tree_1024_4os_100g.topo, END=$END_D1): tags `expD2_4os_{arm}_f${f}_s${s}`
  - D2 8:1 (failed {0,1,2,4}, fat_tree_1024_8os.topo, END=$END_8OS): tags `expD2_8os_{arm}_f${f}_s${s}`
  Use the existing `run()` helper (sets PATHS=8 NODES=1024 EXTRA_ARGS=-disable_trim). Mechanism
  blocks unchanged. Selftest block already compiles test_strack_cc; add the two new CC unit tests.

## 6. Reproducibility specifics

- Both `repro.sh` selftest sections compile + run the C++ logic the new arms depend on:
  `g++ -I. datacenter/prism_eval/common/tests/test_swift_cc.cpp`  and `…/test_mnscc_median.cpp`
  (expA's repro.sh is the template). This gates the run on the CC-helper logic being correct.
- The edited `repro.sh` is the canonical from-scratch reproducer (now 7 arms). For THIS session's
  execution we run **only the 3 new arms incrementally** (the existing 4-arm data is present and
  is not re-run); figures re-render from all 7. A clean-room `bash repro.sh` still reproduces all 7.
- No new generators, no topo changes (the 100G 4:1 topo `fat_tree_1024_4os_100g.topo` already
  exists / is generated by expD's repro.sh).

## 7. Documentation updates

- `expB_oversub_asym/README.md` and `expD_scale1024/README.md`: extend the results tables to the
  7-arm set; numbers taken verbatim from the re-render stdout (no hand-estimates). Keep the existing
  "requested -failed vs actual degraded core links" caveat. Report honestly whether each new arm
  beats/ties/loses to PRISM at each cell — no presupposed outcome.
- `NARRATIVE.md` Map: broaden the "Eval (vs MNSCC / vs Swift / vs MSwift)" evidence from "expA only"
  to "+ expB 4:1 + expD 1024 (generalization)", wording driven by the measured result.

## 8. Runtime estimate

- expB: 3 arms × (8os 4 failed + 4os 4 failed) × 5 seeds = **120 runs @128 nodes** → minutes.
- expD: 3 arms × (D1 6 + 4:1 5 + 8:1 4 failed) × 5 seeds = **225 runs @1024 nodes** → ≈ +20–25 min
  (the 8:1 END=12 cells are the slowest). Sequential only (run_lib writes a shared idmap.txt).
- Progress reported every ~10 minutes during the long run, with analysis of how it is going.

## 9. Execution method

- Subagent-driven development with two-stage review per task (implementer + spec review + quality
  review), then a final whole-branch review — same flow as expA / prior milestones.
- Local per-task commits ONLY if/when the user explicitly authorizes; never push.

## 10. Acceptance criteria

1. Both `make_figs.py --selftest` pass; `python3 make_figs.py` renders all affected figures with 7
   legend entries in the §4 order (Prism last, STrack second-to-last).
2. Mechanism figures (figBa_mech, figD1_mech, figD2_mech) are unchanged (still 4 arms; ideally
   byte-identical to pre-change).
3. Data files exist for all 3 new arms at every swept cell in both folders (coverage matches the
   existing arms: expB 8os{0,2,4,8}+4os{0,4,8,12}×{13–17}; expD D1{0,8,16,24,32,48}+4:1{0,1,2,3,4}+
   8:1{0,1,2,4}×{13–17}).
4. READMEs + NARRATIVE updated with measured 7-arm numbers; every cited number traceable to render
   stdout; cr reported per cell (the 8:1 saturation cells flagged where cr<1 confounds FCT).
5. PRISM controller verified unchanged (no diff in uec.{h,cpp}/prism_decompose.h vs HEAD).
