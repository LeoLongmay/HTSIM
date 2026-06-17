# PRISM HOLD-leak — do-no-harm controlled experiment (design)

**Date:** 2026-06-17
**Phase:** symmetric-cost reduction attempt #2 (the f0 under-growth). A flag-gated, default-OFF,
verify-only controller prototype, in the same spirit as the (removed) persistence prototype.
**Status:** design, pending user review → writing-plans → subagent-driven execution.

## 1. Goal and framing

PRISM under-grows at f0 (symmetric / non-reroutable): it HOLDs on a cross-path spread that is real
but a self-resolving startup transient, freezing window growth while REPS+NSCC keeps growing
(f0 goodput 869 vs 997, −13%; avg-FCT +28%). Two cheaper fixes were ruled out:
- **(a) timer-reset on the spread** — redundant: the per-epoch reset already *is* that timer, and
  `kappa` (epoch length) was swept and is only a minor lever.
- **(b) avg-delay discriminator** — REFUTED by the read-only probe (`probe_avgdisc/`): in HOLD
  epochs the avg-delay does NOT separate f0 from f8 (flip fraction P(avg<T_cc|HOLD) = 0.37 at f0 vs
  0.40 at f8, separation −0.03). The f0 transient is *broad* startup congestion, so avg is elevated
  just like f8; the only true discriminator is rank-persistence, which is O(paths).

So no instantaneous O(1) aggregate (floor/spread/avg) can selectively un-hold f0. The **only**
remaining O(1) lever is a **blunt** one: let the window grow a little during HOLD. This experiment
tests whether such a leak recovers part of the f0 cost **without** eroding the asymmetric win
(f8/f12) — knowing up front it is a tradeoff dial, not a free fix. If no leak satisfies both, that is
an honest negative recorded like the loss-decomp and persistence negatives, and PRISM keeps `leak=0`
(O(1), today's behavior).

This is the user-chosen path (2026-06-17), with explicit constraints: default OFF, success = f0
partial recovery AND f8/f12 do-no-harm, keep O(1), report failure/net-negative straight.

## 2. Mechanism (the leak)

**One static scalar** `_prism_hold_leak ∈ [0,1]` (flag `-prism_hold_leak`, default **0 = today's
PRISM, byte-identical**). When `> 0`, in the **HOLD region only** (DECREASE keeps cutting via
`md_factor`, untouched; INCREASE untouched):

- **Per-ACK** (uec.cpp `updateCwndOnAck_PRISM`, the in-epoch action block ~1513): add a HOLD branch
  that accumulates a *scaled proportional increase*, mirroring `proportional_increase`'s core line
  but scaled by `leak` and **without `fast_increase` and without `_eta`**:
  ```cpp
  } else if (_prism_region == prism::HOLD && _prism_hold_leak > 0.0) {
      simtime_picosec inc_delay = _prism_ccc;
      if (_target_Qdelay > 0 && inc_delay > _target_Qdelay - 1) inc_delay = _target_Qdelay - 1;
      _inc_bytes += (mem_b)(_prism_hold_leak * _alpha * newly_acked_bytes * (_target_Qdelay - inc_delay));
  }
  ```
- **Apply** (the fulfill block ~1580): add a HOLD branch that applies the leaked budget *without*
  the periodic `_eta`:
  ```cpp
  } else if (_prism_region == prism::HOLD && _prism_hold_leak > 0.0
             && (_received_bytes > _adjust_bytes_threshold
                 || eventlist().now() - _last_adjust_time > _adjust_period_threshold)) {
      _cwnd += _inc_bytes / _cwnd;   // leaked proportional budget only -- NO _eta
      _inc_bytes = 0;
      _received_bytes = 0;
  }
  ```
- **Epoch boundary** (~1539–1546): UNCHANGED. It still zeroes `_inc_bytes`/`_increase`/`_fi_count`
  when `region != INCREASE`; this drops the prior INCREASE epoch's full budget and any HOLD-epoch
  leftover at the boundary (negligible: < one ACK's worth), while the per-epoch leak re-accumulates
  fresh via the per-ACK branch and is applied by the fulfill branch within the epoch.

Properties: `leak=0` → both new branches are skipped → **byte-identical** to committed PRISM.
`leak=1` → HOLD grows at ~the proportional-AI rate (≈ removing the spread gate; the upper endpoint).
Leaks only the proportional AI (calibrated to NSCC's own growth), never `fast_increase` (no
cold-start explosion) nor `_eta` (no return of the creep the gate was added to stop). **O(1)**: one
scalar, reuses existing `_inc_bytes`; no per-path state. DECREASE and the floor-driven cut are
untouched, so real overload (high floor) is still handled.

## 3. Deliverables

### 3.1 Controller change (flag-gated, default OFF)
- `htsim/sim/uec.h`: declare `static double _prism_hold_leak;` near the other PRISM statics (~372).
- `htsim/sim/uec.cpp`: define `double UecSrc::_prism_hold_leak = 0.0;` (~99); the two HOLD branches
  in §2.
- `htsim/sim/datacenter/main_uec.cpp` (and `main_uec_sf.cpp` if it parses the other `-prism_*`
  flags): parse `-prism_hold_leak <float>` setting `UecSrc::_prism_hold_leak`, with a `cout` echo,
  mirroring `-prism_t_spray`/`-prism_kappa`.

### 3.2 New experiment group `htsim/sim/datacenter/prism_eval/expA_holdleak/`
- `repro.sh` — build check; selftest; generate the 2 MB many2many workload (same as expA); sweep
  `leak ∈ {0, 0.1, 0.25, 0.5, 0.75, 1.0}` × `failed ∈ {0, 2, 4, 8, 12}` × seeds {13–17} (PRISM arm only,
  via `EXTRA_ARGS="-disable_trim -prism_hold_leak <leak>"`); plus REPS+NSCC at the same failed/seeds
  as the do-no-harm reference; render figs.
- `make_figs.py` / analysis — aggregate goodput + avg-FCT per (leak, failed); compute, vs `leak=0`
  PRISM: f0 recovery fraction toward REPS, and f8/f12 deltas; emit the verdict + a figure
  (goodput vs leak, one line per failed; REPS reference lines). `--selftest`.
- `README.md` — setup, the do-no-harm table, the pre-registered verdict (honest).
- `figs/` — `figHL_holdleak.{png,pdf}`.

## 4. Sweep and pre-registered success criteria

- Arms: PRISM (`prism reps`, swept `-prism_hold_leak ∈ {0, 0.1, 0.25, 0.5, 0.75, 1.0}`), REPS+NSCC
  (`nscc reps`, reference). Failed ∈ {0, 2, 4, 8, 12} (f0 target + f2 mixed + f4/f8/f12 win). All
  delay-driven (`-disable_trim`), 2 MB many2many 64→16, `PATHS=8`, `END_MS=8` (cr≈1.0), seeds {13–17}.
- **Win must hold (do-no-harm):** at the chosen `leak`, PRISM f8 AND f12 goodput within **3% or 1 SD**
  (whichever larger) of `leak=0` PRISM.
- **Target must improve:** f0 goodput recovers **≥ 1/3** of the (869→997) gap, i.e. f0 goodput ≥ ~912.
- **Verdict:** if some `leak` meets BOTH → positive (report which, and the tradeoff curve). If NONE →
  honest negative; do NOT change the `leak=0` default; PRISM stays O(1). Either way report the full
  leak×failed table straight.

## 5. Verification (rollback-safe)

- **leak=0 byte-identical:** under the sweep's own settings (END=8), a `prism reps failed=0 seed=13`
  run with the flag absent and one with `-prism_hold_leak 0` produce the **exact same** per-seed
  goodput float (assert equality of the two flow.txt-derived values), confirming default-off is a
  no-op. (The plan computes both and compares; no hard-coded literal.)
- **Monotonicity:** higher `leak` → higher f0 mean window / goodput (sanity that the leak does what
  it says).
- **Rollback:** `git checkout` the touched controller files (uec.cpp, uec.h, main_uec.cpp[, _sf])
  restores byte-identical O(1) PRISM; the flag then no longer exists.

## 6. Grounding & honesty rules (binding)
- Default OFF == today's PRISM, verified byte-identical. The flag is a *prototype*; shipping it (a
  non-zero default) requires the pre-registered criteria to pass — otherwise it is removed/kept-off.
- O(1) preserved (one scalar; no per-path state) regardless of outcome.
- Results reported straight: the leak×failed goodput/FCT table, the f0-recovery and f8/f12-erosion
  numbers, and a clear positive/negative verdict. No forced positive; a tradeoff with net cost is
  recorded as a negative, like loss-decomp and persistence.
- Reuse expA infrastructure (run_lib.sh, generators, metrics.py, plot_style.py).

## 7. Non-goals
- No discriminator (a)/(b) — both already ruled out (probe + kappa/epoch).
- No `_eta`/`fast_increase` leak; no leak in INCREASE or DECREASE.
- No new default unless criteria pass; no 1024-scale; no trimming-regime variant.
- Not the expB/expC continuation (separate, deferred until this concludes).

## 8. Execution & honesty
- Subagent-driven: controller change as one task (impl + spec-review + code-quality-review),
  the group/sweep as following tasks, plus a final holistic review (does the leak truly default to a
  no-op? is it O(1)? is the verdict honest?). Rebuild `htsim_uec` before the sweep.
- Commit batched to a milestone **only on explicit user approval** (standing rule). Communicate in
  Chinese.
- Next step after approval: invoke writing-plans.
