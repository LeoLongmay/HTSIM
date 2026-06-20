# Spec: PRISM ρ-gate — persistence-correlated spread test to remove the symmetric/incast cost

**Date:** 2026-06-20
**Status:** design approved (user), spec under review
**Branch:** prism-motivation-redesign (local only; origin = spcl/HTSIM public upstream — never push)

## 1. Goal

Prototype a controller variant — the **ρ-gate** — that shrinks PRISM's symmetric-fabric /
shared-bottleneck cost (the `failed=0` penalty and the `expC_incast` cost) **without eroding the
asymmetric win** (`failed≥2` delay-driven). The variant tightens the HOLD entry condition so PRISM
stops freezing window growth on the small, transient cross-path spread that a symmetric incast
produces, while still holding on the large, persistent spread that a degraded fabric produces.

This is an **opt-in, default-off, rollback-able** prototype. Default builds are byte-identical to
today's PRISM. The variant is validated on the f0 (cost) and f8 (win) cells only; nothing is merged
to `main` and no defaults change until the user reviews the results.

### 1.1 Motivating measurement (read-only, already done)

From the per-epoch PRISM logs (`*.epoch.csv`, columns
`time_ns,flow_id,base_rtt_ns,c_cc_ns,c_spray_ns,region,cwnd_bytes,epoch_samples,cut` — `uec.cpp:1576`),
pooled over 5 seeds, **within the HOLD epochs** (the costly region):

| cell | HOLD `c_spray/c_cc` median (p25 / p75) |
|---|---|
| f0 — symmetric many2many (**cost**) | **3.93** (2.30 / 8.38) |
| f8 — asymmetric many2many (**win**)  | **16.51** (9.83 / 39.72) |
| incast fan-in 64 (**cost**) | 3.43 (2.31 / 5.59) |

The win HOLDs are driven by spread that **massively dominates** the floor (~16×: a genuinely clean
path at ~2.6 µs vs ~58 µs elsewhere — persistent structural asymmetry); the cost HOLDs by spread
only ~3–4× the floor (a modest, self-draining startup transient). A ratio gate at ρ≈5 separates them:

| ρ | f0 cost HOLDs removed | incast cost HOLDs removed | **f8 win HOLDs lost** |
|---|---|---|---|
| 3.0 | 36.2% | 40.5% | 2.0% |
| 5.0 | 57.1% | 66.8% | 6.0% |

(Anchor: the all-epoch ratio-of-means reproduces the README's incast 0.72 exactly — method verified.)

**Caveat carried into the prototype:** this is an *observational* first-order screen on logs from the
*current* controller. Changing the gate changes the window trajectory, hence the very `c_cc/c_spray`
distribution it reads. The flip-% is a viability estimate, **not** a performance guarantee — §6
acceptance is decided by re-running, not by these numbers.

## 2. The rule (combined-AND, approved)

Today (`prism_decompose.h:15`): `spread_high ⟺ c_spray ≥ t_spray` (absolute, default `t_spray = T_cc ≈ 14 µs`).

ρ-gate (combined-AND — **only tightens HOLD, never creates a new HOLD**):

```
spread_high ⟺ (c_spray ≥ t_spray) AND (c_spray ≥ ρ·c_cc)
```

Implemented by extending the pure, unit-tested `decide_region` with a **defaulted** parameter
(approach **B**, chosen over the call-site `max()` approach A):

```cpp
inline Region decide_region(uint64_t c_cc, uint64_t c_spray,
                            uint64_t t_cc, uint64_t t_spray,
                            double spread_ratio = 0.0) {
    bool floor_high  = c_cc >= t_cc;
    bool spread_high = (c_spray >= t_spray) &&
                       (spread_ratio <= 0.0 || (double)c_spray >= spread_ratio * (double)c_cc);
    if (!floor_high && !spread_high) return INCREASE;
    if (!floor_high &&  spread_high) return HOLD;
    return DECREASE;
}
```

- `spread_ratio = 0.0` (default) ⇒ second clause is vacuously true ⇒ **identical to today's rule**.
- The default parameter keeps every existing caller and every existing
  `test_prism_decompose.cpp` assertion valid unchanged.
- The header comment already anticipates this: *"P5 ablation variants will branch here (left as the
  single decision point)."*

## 3. Invariants (non-negotiable)

- **Default-off byte-identical.** With `_prism_spread_ratio = 0.0` (the default), `decide_region`
  returns the same region as today on every input. The shipped/default controller is unchanged.
- **O(1) preserved.** The change adds exactly **one static scalar** (`_prism_spread_ratio`) and a
  multiply-compare inside the existing per-epoch close. **Zero** new per-flow / per-path / per-packet
  state. The controller still reads only the two epoch scalars (`min`, `max`).
- **Rollback-able (the user's hard requirement).** (a) runtime A/B = pass / omit
  `-prism_spread_ratio`; (b) permanent revert = the ~7-line diff across the 4 source/plumbing files
  (+ its unit-test additions), `git revert`; (c) **all work stays on the feature branch — no FF to
  `main`, no default change — until the user reviews results.**
- **Spray unchanged.** Only the CC HOLD-entry test changes. REPS spraying, the loss path, kappa,
  T_spray semantics, and the epoch CSV schema are untouched.
- **Communication in Chinese; no git commit unless the user explicitly asks; never push.**

## 4. Change set (4 source/plumbing files + unit tests + 1 new script)

| File | Change |
|---|---|
| `prism_decompose.h` | `decide_region` gains `double spread_ratio = 0.0`; combined-AND `spread_high`. |
| `datacenter/prism_eval/common/tests/test_prism_decompose.cpp` | Add ρ-variant assertions (cost-type epoch → not HOLD; win-type epoch → HOLD; ρ=0 → unchanged). |
| `uec.h` | `static double _prism_spread_ratio;` (next to `_prism_kappa`, line ~379). |
| `uec.cpp` | `double UecSrc::_prism_spread_ratio = 0.0;` default; pass it as the 5th arg at the `decide_region` call (~line 1555). |
| `datacenter/main_uec_sf.cpp` | Parse `-prism_spread_ratio` → `UecSrc::_prism_spread_ratio = atof(argv[i+1])` + echo (mirror `-prism_kappa`, line ~182). |
| **new** `datacenter/prism_eval/expA_f0_diagnosis/ratio_gate_sweep.sh` | Validation sweep (see §5). Reuses `run_lib.sh`; **`run_lib.sh` itself is unchanged** — the flag rides `EXTRA_ARGS` (forwarded at `run_lib.sh:41`). |

Epoch CSV columns are **unchanged**: the `region` column already reflects the new decision, so
existing log/plot tooling keeps working.

## 5. Validation harness (`ratio_gate_sweep.sh`)

- Arm = `prism` (CC=prism, LB=reps). Workload = the byte-identical `m2m.cm` (64→16 cross-pod
  many2many, 2 MB) used by `expA_delaydriven` / `expA_f0_diagnosis`. Regime `-disable_trim`, END=8.
- Grid: `failed ∈ {0, 8}` × `ρ ∈ {0, 3, 5, 8}` × `seed ∈ {13,14,15,16,17}` → 40 runs.
  `EXTRA_ARGS="-disable_trim -prism_spread_ratio $rho"` (ρ=0 ⇒ flag still passed but no-op, also
  serves as the in-band regression replica of current PRISM).
- Aggregate goodput (Gbps) + avg-FCT (µs) via the existing `perf_figs.aggregate` / `metrics`
  (flow-based). Emit a plain-text table: per `(failed, ρ)` the 5-seed mean goodput & avg-FCT, with
  Δ vs ρ=0 and the REPS+NSCC reference (reuse `expA_delaydriven/data` REPS numbers).
- Self-tests gate the run (`make_figs.py --selftest`, common metrics selftest) as in every repro.
- Raw data gitignored; the summary table is the deliverable for the user's results review.

## 6. Acceptance criteria

- **(a) Regression gate:** ρ=0 f0/f8 goodput+avg-FCT match current PRISM (within seed noise).
- **(b) O(1):** diff adds one static scalar, no per-flow state (code inspection + the controller diff
  reviewed in the final whole-branch review).
- **(c) Effect:** at the chosen ρ, **f0 cost decreases** (goodput up toward REPS+NSCC, avg-FCT down)
  vs ρ=0 **AND f8 win is preserved** (goodput/avg-FCT within seed noise of ρ=0). Report the knee ρ.
- **(d)** `decide_region` unit tests pass (existing + ρ-variant).
- **(e)** common metrics selftest passes.
- **Honest-null outcome is acceptable:** if no ρ achieves (c), the prototype is reported as a
  negative result and reverted — the default-off design means this costs nothing downstream. This is
  exactly the rollback guarantee the user asked for.

## 7. Out of scope / deferred

- **Scheme A** (EWMA / temporal persistence detector) — deferred; the more principled fix, revisited
  only if the ρ-gate is insufficient.
- incast (`expC`) and full `expA` failed-sweep re-validation + figure re-render — deferred (minimal
  f0+f8 validation only).
- Changing any default, FF to `main`, permutation workload, 400/800G variants — none in this prototype.
