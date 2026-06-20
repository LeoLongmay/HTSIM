# Spec: PRISM spread-persistence gate (Scheme A, pure O(1) version)

**Date:** 2026-06-20
**Status:** design approved (user), spec under review
**Branch:** prism-motivation-redesign (local only; origin = spcl/HTSIM public upstream — never push)

## 1. Goal

Prototype the **cleanest O(1) version** of a persistence-aware spread gate for PRISM, run it on the
f0 (cost) and f8 (win) cells, and **rigorously close** the question of whether making the HOLD-entry
spread signal persistence-aware can recover the symmetric/f0 cost without eroding the asymmetric win.

This is an opt-in, **default-off, rollback-able** probe (like the ρ-gate). The expected outcome is a
**fourth honest-null** (see §1.2); the deliverable is the measured result plus a correction to the
f0-diagnosis record. Nothing is merged to `main` and no default changes until the user reviews the
result.

### 1.1 Why "pure" and why O(1)

Two prior persistence-related attempts are on record in `../expA_f0_diagnosis/`:
- A per-path EWMA of the per-path queuing delay that computed **both** `C_cc=min` and `C_spray=max−min`
  from the smoothed per-path values. It **backfired** (f0 −18%): EWMA-smoothing also **lagged the
  floor `C_cc` high**, pushing freed epochs into DECREASE (more cutting). It was O(paths) and removed.
- The diagnosis's "sharpened lesson": a persistence signal must keep `C_cc` **instantaneous** and
  smooth **only** the spread. The diagnosis claimed that cleaner design is "per-path, O(paths)
  regardless."

**That O(paths) claim is wrong, and correcting it is part of this project.** The current PRISM
`C_spray` is already an **O(1) scalar** — `_prism_epoch_max − _prism_epoch_min`, the within-epoch
range of observed queuing delays (`uec.cpp:1547,1553–1554`); it does not track path identity. So the
"pure" design (smooth only the spread, keep `C_cc` instantaneous) can be done with **one extra
per-flow scalar** — a slow EWMA of the scalar `C_spray` — and a trend test. No per-path state. O(1).

### 1.2 Prior that predicts a null (carried in honestly)

The ρ-gate (`docs/superpowers/specs/2026-06-20-prism-ratio-gate-design.md`) — a different O(1)
HOLD-entry tightening — was a flat null: at f0 it released ~57% of transient HOLD epochs (by the
log screen) yet recovered **no** goodput (868→858, avg-FCT flat). The released epochs did run
`proportional_increase` (floor low → real window growth) and still no throughput gain — evidence
that at f0, *which* epochs enter HOLD is not the binding constraint; the under-growth is an
equilibrium of the closed loop against the transient/shared bottleneck. Scheme A is the **same
hypothesis class** (a smarter signal that releases transient HOLDs), so it is **expected to null
too**. We run it anyway to close the cheap-persistence variant definitively and to correct the
record.

### 1.3 Honest scope caveat (stated, not hidden)

The O(1) scalar-trend signal is a **weaker** persistence proxy than per-path: the scalar `C_spray`
range cannot distinguish "the same paths stay congested" (reroutable) from "different paths take
turns" (not). The faithful per-path version remains formally untested — **but it is O(paths), which
PRISM's O(1) tenet disallows from shipping anyway**, so the O(1) probe is the complete closure for
fixes PRISM could actually adopt. The per-path version is moot for PRISM; this caveat is documented,
not resolved.

## 2. The signal and rule (Approach A1, approved)

Per epoch close, after `c_cc = _prism_epoch_min` and `c_spray = _prism_epoch_max − _prism_epoch_min`
are computed (`uec.cpp:1553–1554`), gated by `_prism_spread_persist > 0` (δ; 0 = OFF):

```
persistent ⟺ (first epoch, no baseline) OR (c_spray ≥ δ · S_slow)
spread_high (effective) ⟺ (c_spray ≥ t_spray) AND persistent
S_slow ← β · c_spray + (1 − β) · S_slow          // update AFTER deciding (compare-then-update)
```

- `S_slow` = `_prism_cspray_slow`, a **per-flow scalar** slow EWMA of the scalar `C_spray`.
- `C_cc` stays the **instantaneous** `_prism_epoch_min` (this is the whole point — do not smooth the
  floor; that was the backfire).
- **Combined-AND, only tightens HOLD:** a draining transient (current spread far below its own slow
  baseline ⇒ not persistent) is released; a sustained spread (current ≈ baseline) keeps HOLD.
- Direction: higher δ ⇒ stricter persistence requirement ⇒ more HOLD release.

**Implementation keeps `decide_region` PURE and UNCHANGED** (cleaner than the ρ-gate, which extended
it). The persistence state lives in the flow, so we apply it at the call site via an effective
threshold:

```cpp
bool persistent = true;
if (_prism_spread_persist > 0.0)
    persistent = (_prism_cspray_slow == 0) ||
                 ((double)c_spray >= _prism_spread_persist * (double)_prism_cspray_slow);
simtime_picosec t_spray_eff = persistent ? t_spray
                                         : std::numeric_limits<simtime_picosec>::max();
int region = prism::decide_region(c_cc, c_spray, _target_Qdelay, t_spray_eff);
// ... existing region/cut logic unchanged ...
if (_prism_spread_persist > 0.0)                       // keep δ=0 byte-identical: no state churn when off
    _prism_cspray_slow = (_prism_cspray_slow == 0)
        ? c_spray
        : (simtime_picosec)(_prism_spread_persist_beta * (double)c_spray
                          + (1.0 - _prism_spread_persist_beta) * (double)_prism_cspray_slow);
```

When δ=0: `persistent` stays `true`, `t_spray_eff = t_spray`, no `S_slow` update ⇒ **byte-identical
to today's PRISM**.

### 2.1 β as a second knob (refinement for rigor)

β (the slow-baseline weight) controls how much memory the baseline keeps. **Too fast (large β)** and
`S_slow` tracks the draining spread down, current ≈ baseline always ⇒ the gate silently behaves like
OFF (a false null). **Too slow (tiny β)** and the baseline never adapts. To keep a null from being a
β artifact, β is a **second static knob** `_prism_spread_persist_beta` (default `0.03125 = 1/32`,
≈ a 32-epoch ≈ 450 µs memory at kappa=1), and the validation sweeps **two** β values. β only matters
when δ>0. (A2 — a fast/slow EWMA crossover, +1 more scalar, more noise-robust — is the documented
fallback if A1's single-epoch `c_spray` proves too noisy; not built unless A1 is inconclusive.)

## 3. Invariants (non-negotiable)

- **Default-off byte-identical.** δ=0 (default) ⇒ no persistence check, no `S_slow` update, `decide_region`
  called with the same `t_spray` as today ⇒ same region on every input.
- **O(1) preserved.** Adds **two static scalars** (δ, β) and **one per-flow scalar** (`_prism_cspray_slow`).
  Zero per-path state. `C_cc` stays instantaneous.
- **`decide_region` (prism_decompose.h) is UNCHANGED.** The gate is applied at the call site via the
  effective `t_spray`.
- **Rollback-able.** Runtime A/B = pass / omit `-prism_spread_persist`; permanent revert = the
  localized diff across the source/plumbing files (+ harness), `git revert`. **No FF to `main`, no
  default change, until the user reviews results.**
- **Spray unchanged.** Only the CC HOLD-entry test changes. REPS, loss path, kappa, T_spray semantics,
  epoch CSV schema untouched.
- **Communication in Chinese; no git commit unless the user explicitly asks (per-task local commits
  ARE authorized for the subagent-driven run); never push.**

## 4. Change set (4 source/plumbing files + unit-coverage + 1 sweep + 1 summary)

| File | Change |
|---|---|
| `uec.h` | Declare `static double _prism_spread_persist;` and `static double _prism_spread_persist_beta;` (near `_prism_kappa`); add per-flow `simtime_picosec _prism_cspray_slow = 0;` (near `_prism_cspray`). |
| `uec.cpp` | Define `_prism_spread_persist = 0.0;`, `_prism_spread_persist_beta = 0.03125;`; at the epoch-close (~1553–1555) compute `persistent` + `t_spray_eff`, pass `t_spray_eff` to `decide_region`, update `_prism_cspray_slow` (guarded by δ>0). `#include <limits>` if not present. |
| `datacenter/main_uec.cpp` | Parse `-prism_spread_persist` and `-prism_spread_persist_beta` (atof + echo), mirroring `-prism_kappa`. **(htsim_uec builds from this file — CMakeLists.txt:48.)** |
| `datacenter/main_uec_sf.cpp` | Same two parse blocks (mirror convention, as `-prism_kappa` lives in both). |
| **new** `datacenter/prism_eval/expA_f0_diagnosis/persist_sweep.sh` | Validation sweep (see §5); reuses `run_lib.sh` (unchanged) via `EXTRA_ARGS`. |
| **new** `datacenter/prism_eval/expA_f0_diagnosis/persist_summary.py` | Acceptance table via `perf_figs.aggregate` (tags `persist_d{δ}_b{β}_f{failed}_s{seed}`). |

`decide_region` and the epoch CSV schema are unchanged. Unit coverage: the existing
`test_prism_decompose.cpp` still passes unchanged (decide_region untouched); the new logic is covered
by the δ=0 regression cell (byte-identical) and the smoke in the plan.

## 5. Validation harness (`persist_sweep.sh`)

- Arm = `prism` (CC=prism, LB=reps). Workload = byte-identical `m2m.cm` (`many2many.py … 64 16 pairs
  2000000 128 16`). Regime `-disable_trim`, END=8. Selftest gate first (decide_region unit test +
  common metrics selftest).
- Grid: `failed ∈ {0, 8}`, with
  - δ=0 baseline (β irrelevant): 1 config — the in-band regression replica of today's PRISM;
  - β ∈ {0.0625 = 1/16, 0.015625 = 1/64} (bracketing the 1/32 code default — one faster, one slower)
    × δ ∈ {0.5, 1.0}: 4 configs.
  - × `seed ∈ {13,14,15,16,17}` → (1 + 4) × 5 × 2 failed = **50 runs**.
  - `EXTRA_ARGS="-disable_trim -prism_spread_persist $d -prism_spread_persist_beta $b"`.
- Tags: `persist_d{δ}_b{β}_f{failed}_s{seed}` so `aggregate(DATA, "persist", f"d{δ}_b{β}", [0,8], SEEDS)`
  resolves correctly. (δ=0 baseline uses a fixed sentinel β label, e.g. `persist_d0_b0_f…`.)
- `persist_summary.py` prints per-(failed, δ, β) 5-seed mean goodput (Gbps) + avg-FCT (µs), Δ vs the
  δ=0 baseline, and the REPS+NSCC reference (reused from `../expA_delaydriven/data`). Raw data
  gitignored; the table is the deliverable.

## 6. Acceptance criteria

- **(a) Regression gate:** δ=0 f0/f8 goodput+avg-FCT match current PRISM (f0 ≈ 869/945, f8 ≈ 504/1518).
- **(b) O(1):** diff adds two static scalars + one per-flow scalar, no per-path state, `C_cc` instantaneous
  (code inspection + the final review).
- **(c) Effect:** for some (δ, β), **f0 goodput rises toward REPS+NSCC and avg-FCT falls** vs δ=0
  **AND f8 win preserved** within seed noise. Report the result.
- **(d) β not an artifact:** the two β values bracket the regime; if BOTH show no f0 effect, the null
  is robust to β (not a too-fast-baseline artifact). If they diverge sharply, widen the β sweep before
  concluding.
- **Honest-null is the expected, acceptable outcome.** If no (δ, β) achieves (c), report the negative
  result and revert — the default-off design costs nothing downstream. Per §1.2 this is the predicted
  result.

## 7. Documentation (after the result)

Update `../expA_f0_diagnosis/README.md`:
- **Correct the "O(paths) regardless" claim:** show the O(1) scalar-trend construction (smooth the
  scalar `C_spray`, keep `C_cc` instantaneous) and that it was built and measured.
- Record the result as the **fourth** entry in the refuted-fix list (after T_spray, kappa, per-path
  EWMA, ρ-gate), or — if it unexpectedly recovers f0 — as the first positive and escalate to the user.

## 8. Out of scope / deferred

- The A2 fast/slow-EWMA variant (built only if A1 is inconclusive due to noise).
- The faithful **O(paths) per-path** persistence version (disallowed by PRISM's O(1) tenet; moot — see §1.3).
- Changing any default, FF to `main`, incast/full failed-sweep re-validation, figure re-render.
