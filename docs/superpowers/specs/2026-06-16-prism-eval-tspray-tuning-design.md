# PRISM Eval — T_spray tuning to mitigate the f0 symmetric penalty (design)

**Date:** 2026-06-16
**Phase:** sensitivity item pulled forward from P5 (addresses the f0 caveat surfaced by the
delay-driven Exp A + P3 results).
**Status:** design, pending user review → writing-plans → subagent-driven execution.

## 1. Goal

The delay-driven Exp A result (incl. P3 STrack) has one honest weak spot: at **failed=0
(symmetric fabric)** PRISM is the *worst* arm — goodput 869 Gbps vs REPS+NSCC 997 / STrack 912
/ OPS 906, avg-FCT 945 µs vs 737–789. PRISM *holds* the window when it sees path spread, even
when that spread is benign (symmetric, transient), costing throughput where there is no
reroutable benefit. Goal: tune `-prism_t_spray` (the spread tolerance `T_spray` in PRISM's
four-quadrant `decide_region` rule) so PRISM stops over-holding on benign spread, **recovering
f0 without eroding the asymmetric (failed ≥ 4) win**.

## 2. Mechanism evidence (confirms the over-hold hypothesis)

`decide_region(c_cc, c_spray, t_cc, t_spray)`: `floor_high = c_cc ≥ t_cc`; `spread_high =
c_spray ≥ t_spray`. `(!floor_high, spread_high) → HOLD` ("clean path exists, let REPS
rebalance"). Today `t_spray` defaults to `t_cc = _target_Qdelay = 6 µs`.

PRISM epoch logs (delay-driven, 5 seeds), region mix + C_spray:

| failed | INCREASE | HOLD | DECREASE | C_spray p50/p90 (µs) | C_cc p50 (µs) | spread/floor |
|---|---|---|---|---|---|---|
| 0 (symmetric) | 42% | **34%** | 22% | 13.9 / 32.5 | 6.6 | ~2× |
| 8 (asymmetric) | 27% | **61%** | 11% | 30.8 / 65.3 | 2.7 | ~11× |

At f0, ~1974 epochs (≈18% of all f0 epochs) are HOLD-with-low-floor (the benign-spread holds
this tuning targets). Of those, raising `T_spray` flips this fraction to INCREASE: 18µs→26%,
24µs→50%, 36µs→80%. At f8 the same raise flips far fewer (18µs→7%, 24µs→14%) because the
genuine reroutable spread is larger — a **favorable but not clean** separation, so the net
throughput effect must be **measured**, not predicted.

## 3. Experiment (two-stage, vertical-slice)

New group folder `prism_eval/expA_tspray_tuning/` (own repro + figs + README). Delay-driven
regime (`EXTRA_ARGS="-disable_trim -prism_t_spray <µs>"`, END=8), same 128-node many2many
workload (reuse `expA_delaydriven`'s `m2m.cm` generation), seeds {13..17}. `T_spray` candidates
**{6, 12, 18, 24, 36} µs** (1×–6× target; 6 = current default).

**Stage 1 — endpoints, find the knee.** `T_spray × {failed 0, 8} × 5 seeds = 50 sims`. f0 is
the cost end, f8 is the win end; together they define the tradeoff. Produce a **knee figure**
(goodput & avg-FCT vs `T_spray`, one line for f0 and one for f8) with reference lines for
REPS+NSCC f0 (≈997) and the f8 "+15% over REPS" bar (≈496), and a **criterion table**.

**Stage 2 — validate the chosen value.** Run PRISM at the selected `T_spray*` **and** the
default 6 over the full `failed {0,2,4,8,12} × 5 seeds`. Final figure = 4 arms: PRISM-default,
PRISM-tuned(T_spray*), REPS+NSCC, STrack — the latter two **reused from `expA_delaydriven/data`**
(not re-run). Shows whether T_spray* removes the f0 penalty while keeping the asymmetric win.

## 4. Success criterion (pre-registered; no post-hoc cherry-picking)

A static `T_spray*` is a **success** iff, on the Stage-1 endpoints (mean over 5 seeds):
1. **f0 recovered:** PRISM f0 goodput rises to **≥ the OPS+NSCC/STrack level (~906 Gbps)** —
   i.e. PRISM is no longer the worst arm at f0 (ideally closing most of the gap to REPS 997);
   **and** f0 avg-FCT moves in the same direction (reported, secondary).
2. **win preserved:** PRISM f8 goodput stays **≥ 1.15 × REPS+NSCC f8 (≈ 496 Gbps)** (the
   default already gives 504 = +17%).

**Selection rule:** among candidates satisfying (2), pick the one **maximizing f0 goodput**;
on a plateau, pick the **smallest** `T_spray` (least deviation from default, least risk to the
intermediate failure levels validated in Stage 2). State the chosen value and the table.

**Contingency (if NO candidate satisfies both):** the f0/f8 C_spray magnitudes overlap, so a
static absolute threshold may not separate benign from genuine spread. Trigger a **separate
spec+plan** for a **ratio-based spread test** in `decide_region`: `spread_high` becomes
`c_spray ≥ T_spray AND c_spray ≥ κ · c_cc` (data motivates κ≈3: f0 spread/floor ~2× → not high
→ INCREASE; f8 ~11× → high → HOLD). This is a P1-code change to `prism_decompose.h`; it is **not
built preemptively** (YAGNI) — only the trigger and direction are recorded here.

## 5. Reproducibility

Pinned build (≥ `513407c`, the P3 commit), deterministic `-seed`, seeds {13..17}, one-command
`repro.sh` (Stage 1 + knee figure + criterion print). Stage 2 driven by a `TS_STAR` env var
(set to the Stage-1 winner; documented in the README with the value used). Raw data gitignored;
figures `git add -f`; selftest of the analysis at the top of `repro.sh`. Everything under
`prism_eval/expA_tspray_tuning/`; repo root untouched. Baseline curves reused from
`expA_delaydriven/data` (read-only) for the Stage-2 figure.

## 6. Honest scope & non-goals

- **In:** `T_spray` sweep (existing knob, no controller code change), knee figure + criterion,
  validated final comparison, honest README (state T_spray*, the f0 recovery, and any residual
  f8 erosion straight). If the criterion fails, say so and hand off to the contingency.
- **Out (noted):** the ratio-based spread test (contingency, separate spec); the loss/NACK
  decomposition pivot (agenda item b); 1024-node scale; the trimming-regime; new flags. No
  tuning of `_gamma`/`_eta`/`_target_Qdelay` (only `T_spray`).
- **Risk:** if T_spray* helps f0 but measurably dents an intermediate level (f2/f4), Stage 2
  surfaces it; report the full curve, do not hide a regression to claim an f0 win.

## 7. Stage-1 outcome + AMENDMENT (2026-06-16)

Stage 1 ran (T_spray {6,12,18,24,36} × {f0,f8} × 5 seeds). **The registered f0-fix goal FAILED
and the contingency assumption was invalidated; two corrections + a pivot resulted.**

**(a) Registered result — NEGATIVE.** f0 goodput is essentially **insensitive to T_spray**
(845–880 Gbps across 6–36 µs; never reaches the 906 OPS floor). Raising T_spray does not recover
f0 — it slightly lowers it while monotonically eroding f8 (548→481). The "over-hold on benign
spread" hypothesis is **refuted**: holding was mildly *protective* at f0 (avoids overshoot →
floor-driven cuts). The contingency (ratio-based spread test) is therefore **dropped** — it
works the same "reduce HOLD" lever that f0 is insensitive to, so it would not fix f0 either.
The f0 penalty has a different root cause (likely floor-driven increase timidity / epoch ramp),
deferred to a separate diagnosis.

**(b) Methodology correction — the real target is ~14 µs, not 6 µs.** Runtime
`_target_Qdelay = 14022720 ps ≈ 14.02 µs` (set by `initNsccParams` to one network RTT, matching
the STrack paper's "target queuing delay = one network RTT"). The static `timeFromUs(6u)`
initializer is overridden at init. So PRISM's default `t_spray` (sentinel 0 → follow target) is
**~14 µs**, not 6 µs. Consequences: (i) the Stage-1 sweep brackets the true default (6/12 below,
18/24/36 above); the explicit `T_spray=6` point (f8=548) is NOT the committed default (t_spray=14,
f8=504) — fully explains the apparent discrepancy. (ii) **The committed mechanism figures
`figA2dd`/`figA2` drew the target line at 6 µs — WRONG; it should be ~14 µs.** Headline
goodput/FCT are unaffected (measured; controller always used 14 µs internally), but the mechanism
figures' target reference + the "target 6µs" README wording must be corrected. (Likely makes
PRISM's "floor stays below target" story *cleaner*, since the floor sits mostly below 14 µs.)

**(c) PIVOT (user-approved) — bank the serendipitous f8 gain.** Lowering T_spray *below* the
~14 µs default **improves the asymmetric win**: T_spray=6 → f8=548 vs default 504 (**+9%**), at no
f0 cost; f8 is monotonically better as T_spray drops. New objective: find the T_spray that
maximizes the asymmetric win without regressing f0/intermediate levels.
- **New sweep range:** {2, 3, 4, 6, 9, 14} µs (≤ default; 14 = the real default reference).
- **New criterion (`select_tspray_maximize_f8`):** among candidates, pick the one **maximizing f8
  goodput** subject to **f0 goodput ≥ default(T_spray=14) f0 − 1%** (do-no-harm to symmetric).
  Then **Stage 2 full-grid {0,2,4,8,12}** validates the pick vs the default: require f8/f4
  improved and f0/f2 **not regressed** (report the full curve straight; a mid-grid regression
  kills the pick).
- **Target-bug fix is in scope:** parameterize `perf_figs` to read the real `_target_Qdelay`
  from the mechanism stdout (fallback default), re-render `figA2dd`/`figA2`, correct READMEs.

Honest framing: this experiment did NOT achieve its registered goal (T_spray cannot fix the f0
penalty); it is reported as a negative result, plus a methodology correction, plus a modest
asymmetric-win improvement banked from the corrected understanding of the knob.
