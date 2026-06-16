# PRISM Eval P3 — STrack coupled-SOTA baseline (design)

**Date:** 2026-06-16
**Phase:** P3 of the PRISM Section IV roadmap (`prism-eval-roadmap`).
**Status:** design, pending user review → writing-plans → subagent-driven execution.

## 1. Goal & role in the evaluation

Add **STrack** as the *coupled, SOTA* congestion-control baseline for the PRISM
evaluation. Today the eval compares PRISM (decomposed floor/spread signal) against the
*decoupled* REPS+NSCC and the oblivious OPS+NSCC. The first positive result
(`expA_delaydriven`, commits `9c841ae`/`00846b1`) shows PRISM beats decoupled REPS+NSCC
under asymmetry **in the delay-driven regime**. The natural next question — and the one a
reviewer asks first — is: **does PRISM's decomposition also beat a strong coupled CC that
keys off the *averaged* delay signal?** STrack (Nvidia, hardware-offloaded reliable
transport; `Strack/paper/`) is exactly that: CC+LB co-designed, with a window controller
that uses **average RTT across paths** as the congestion indicator. It is the embodiment
of the signal *conflation* that PRISM's motivation (figS) critiques, in a published SOTA
system. Beating it in the delay-driven regime is the decisive test of the decomposition
thesis.

## 2. Key finding that shapes the design: NSCC already *is* a Swift/STrack-family CC

Cross-reading STrack's Algorithm 4 (paper §3.2) against the existing
`UecSrc::updateCwndOnAck_NSCC` shows heavy overlap — NSCC is itself a Swift-derived,
ECN-gated, avg-delay controller:

| STrack Algorithm 4 | NSCC today (`uec.cpp`) |
|---|---|
| MD `cwnd *= max(1−γ(avg−target)/avg, 1−max_mdf)` | `multiplicative_decrease()` — *byte-identical shape* (uses `get_avg_delay()`, `_gamma`, floor 0.5), once per `_base_rtt` |
| increase `cwnd += α(target−delay)/cwnd` when delay<target | `proportional_increase()` (`_inc_bytes += _alpha·acked·(target−delay)`) |
| ECN marked + low RTT → switch path, hold window | NSCC `skip && delay<target` → NOOP (path switch) |
| fast-converge `cwnd = achievedBDP` (heavy congestion) | `quick_adapt()` (sets `_cwnd = _achieved_bytes`) |
| periodic fairness `cwnd += η` | `fulfill_adjustment()` `_cwnd += _eta` |

**Implication:** a naive STrack port risks producing a near-clone of NSCC, which would be a
worthless baseline. The design must port the **genuinely STrack-specific** behaviour that
makes it a *distinct, more delay-conservative, coupled* controller, and we must **prove the
port differs measurably from NSCC** (§6 distinctness check). The standalone in-tree
`htsim/sim/strack.{h,cpp}` is **not** used: it is a half-finished, separate transport stack
(own sink/trimming/loss-recovery/pacing), its increase line `cwnd = α(target−rtt)/cwnd` is a
bug (assignment, not `+=`), and running it would confound the fabric/sink comparison. We port
the *CC core* into `UecSrc` (Approach A, user-selected), so STrack runs on the **same**
spray (REPS), sink, trimming and loss machinery as NSCC/PRISM — isolating the CC decision
tree as the only variable.

### The three STrack-specific deltas we DO port (what makes it ≠ NSCC)

1. **Conservative no-ECN-high-delay branch.** NSCC, when `!ecn && delay≥target`, runs an
   *aggressive* `fair_increase` (`_inc_bytes += _fi·acked`, a large fairness jump). STrack
   instead **holds**, except for a small **β starvation bump** (`cwnd += β/cwnd`) only when
   `delay > 2·target` (queue has drained — no ECN — but this packet still saw high delay, so
   nudge up to avoid link starvation; paper Line #7). Fairness comes only from the periodic
   `η`. This is STrack's "more purely delay-driven, less aggressive" signature.
2. **β starvation bump** as a first-class action (new `starvation_increase()`), `-strack_beta`.
3. ECN-gated decision tree taken **directly from Algorithm 4** as a pure, unit-tested
   function (mirrors PRISM's `prism_decompose.h`), rather than NSCC's hand-rolled branches.

## 3. Documented simplifications (faithful-enough, with rationale)

- **Per-hop target scaling** `target = base_delay + hops·h` → we use a **fixed
  `_target_Qdelay`** as `base_delay` and default `h = 0`. In the fat-tree topologies we
  evaluate, every flow crosses a near-uniform hop count, so `hops·h` is a constant offset
  already folded into the tuned `_target_Qdelay`. A `-strack_h` knob exists (default 0) but
  we do not plumb live `hop_count` per ACK. Recorded as a simplification.
- **target_Qhigh achieved-BDP fast-converge** → reuse `quick_adapt()`, which *is* the UEC
  achieved-BDP fast-converge machinery (triggered by `_qa_threshold`/loss). We do not add a
  second, redundant `delay > target_Qhigh` trigger.
- **Loss recovery** → reuse `updateCwndOnNack_NSCC` (exactly as PRISM does). STrack's own
  selective-retx is out of scope; holding the loss machinery fixed across all arms is what
  makes the CC comparison clean.
- **STrack's adaptive ECN-bitmap spray is NOT ported** (that was Approach B). STrack-CC runs
  on the shared REPS spray. This is deliberate: holding the spray fixed at REPS for both
  STrack-CC and PRISM isolates "does decomposing the signal help" as the single variable.
  Faithfulness to the *full* published STrack system is a possible later robustness check,
  noted in §8, not part of P3.

## 4. Controller design

### 4.1 Pure logic — `htsim/sim/strack_cc.h` (mirrors `prism_decompose.h`)

```cpp
namespace strack {
  enum Action { INCREASE_PROP, STARVATION_BUMP, MULT_DECREASE, HOLD };
  // STrack Algorithm 4 decision tree (ECN-gated). target = _target_Qdelay (base_delay).
  inline Action decide_action(bool ecn, simtime_picosec delay,
                              simtime_picosec avg_delay, simtime_picosec target) {
    if (!ecn) {                                  // no ECN -> increase branch
      if (delay > 2*target) return STARVATION_BUMP;   // drained but this pkt delayed (Line #7)
      if (delay <  target)  return INCREASE_PROP;      // proportional increase (Line #9)
      return HOLD;                                     // target<=delay<=2target: hold
    }
    if (avg_delay > target) return MULT_DECREASE;       // congested -> MD on AVG (Line #15)
    return HOLD;                                         // ECN but avg low -> path switch (Scenario #2)
  }
}
```
A header-only `selftest()` (compiled into a tiny test, like the PRISM logic test) exercises
each of the four branches and the three boundaries (`delay` vs `target`/`2·target`,
`avg_delay` vs `target`).

### 4.2 Integration in `UecSrc` (`uec.cpp` / `uec.h`)

- `enum Sender_CC { DCTCP, NSCC, CONSTANT, PRISM, STRACK };`
- dispatch (uec.cpp ~601): `case STRACK: updateCwndOnAck = &UecSrc::updateCwndOnAck_STRACK;
  updateCwndOnNack = &UecSrc::updateCwndOnNack_NSCC;` (reuse loss, as PRISM).
- arg parse: `else if (!strcmp(argv[i+1],"strack")) UecSrc::_sender_cc_algo = UecSrc::STRACK;`
  in `main_uec.cpp` (and `main_uec_sf.cpp` for consistency).
- new static params (mirror PRISM flag style, minimal): `_strack_beta` (`-strack_beta`,
  default a BDP-scaled constant per Table 1 `β = 5·bdp_sf`), `_strack_h` (`-strack_h`,
  default 0). Reuse `_gamma`, `_eta`, `_target_Qdelay`, `_min_cwnd`, `_base_rtt`.

```cpp
void UecSrc::updateCwndOnAck_STRACK(bool skip, simtime_picosec delay, mem_b acked) {
  if (quick_adapt(false, skip, delay)) return;        // achievedBDP fast-converge (reuse)
  simtime_picosec avg = get_avg_delay();
  switch (strack::decide_action(skip, delay, avg, _target_Qdelay)) {
    case strack::INCREASE_PROP:   proportional_increase(acked, delay); break;  // reuse
    case strack::STARVATION_BUMP: starvation_increase();               break;  // new: cwnd += β/cwnd
    case strack::MULT_DECREASE:   multiplicative_decrease();           break;  // reuse (keys on avg, once/base_rtt)
    case strack::HOLD:                                                 break;
  }
  set_cwnd_bounds();
  if (_received_bytes > _adjust_bytes_threshold ||
      eventlist().now() - _last_adjust_time > _adjust_period_threshold)
    fulfill_adjustment();                              // reuse: applies _inc_bytes + periodic η
  set_cwnd_bounds();
}

void UecSrc::starvation_increase() {                   // STrack Line #7: cwnd += β/cwnd
  if (_cwnd > 0) _cwnd += _strack_beta / _cwnd;
}
```
Note `multiplicative_decrease()` already self-gates on `avg_delay > _target_Qdelay` and the
once-per-`_base_rtt` limiter, so the `MULT_DECREASE` action is a no-op when ECN is marked but
the average is still below target — faithfully reproducing STrack Scenario #2 (mark ⇒ switch
path, keep window).

## 5. Experiment: delay-driven Exp A + STrack 4th arm

Scope (user-selected): land the controller **and** add STrack as a 4th baseline to
`prism_eval/expA_delaydriven` (the regime where PRISM wins). The trimming-default
`expA_asymmetric` may get STrack later; not in P3.

- **`expA_delaydriven/repro.sh`**: add a 4th run per `(failed ∈ {0,2,4,8,12}, seed ∈ {13..17})`
  cell — `strack reps` with `EXTRA_ARGS="-disable_trim" END_MS="$ENDV"` (ENDV default 8) — and a
  4th mechanism run (`failed=8, seed=13`) with `PRISM_PATHRTT`/cut logging.
- **`common/perf_figs.py`**: already generic over a `baselines` list; add the
  `("strack","STrack","strack")` triple. `figA1dd_main_perf` becomes a 4-line comparison
  (OPS+NSCC / REPS+NSCC / STrack / PRISM) on goodput / avg-FCT / P99-FCT vs #failed. Add a
  `strack` color in `plot_style.py` (distinct from REPS's orange).
- **Mechanism (`figA2dd`)**: add STrack's cwnd(t) line and its per-ACK cut count for context.
  The headline remains the 4-arm main-perf figure.

The thesis test the figure answers: PRISM (floor/decomposed) vs STrack (coupled + **avg**),
both on REPS spray, both delay-driven — does decomposition still win under asymmetry?

## 6. Validation & the mandatory distinctness check

1. **Pure-logic selftest** of `strack::decide_action` (all 4 actions, 3 boundaries).
2. **Builds & runs**: STrack completes the Exp A sweep (completion_rate reported honestly).
3. **Distinctness check (gate):** on the mechanism seed, STrack's cwnd(t) trajectory and
   per-ACK cwnd-decrease count must differ **measurably** from NSCC's (the β-bump +
   conservative-increase + delay-driven structure should be visible). If STrack comes out
   byte-identical to NSCC, the port adds nothing — that is a finding to **report**, not paper
   over, and a trigger to revisit Approach B. We will print NSCC vs STrack cut counts and
   eyeball the trajectories.
4. **Honesty:** report PRISM-vs-STrack straight — win, tie, or loss. No tuning STrack to lose
   and no tuning PRISM to win; STrack uses the same `_gamma`/`_eta`/`_target_Qdelay` as NSCC
   plus the paper's defaults for the new `β`/`h`.

## 7. Reproducibility (carry-over standard)

Pinned build commit, deterministic `-seed`, seeds {13..17} (dev slice, matching
`expA_delaydriven`), one-command `repro.sh`, raw data gitignored, figures `git add -f`,
selftests run at the top of `repro.sh` (`strack_cc` logic test + `common/tests` +
`make_figs.py --selftest`). Everything under `prism_eval/`; repo root untouched. Built
subagent-driven (implementer + spec-review + quality-review per task, plus a final holistic
review), matching P1/P2.

## 8. Honest scope & non-goals

- **In:** STrack-CC controller in `UecSrc` (`-sender_cc_algo strack`), pure-logic header +
  selftest, delay-driven Exp A 4th arm + figures, distinctness check.
- **Out (noted):** STrack's adaptive ECN-bitmap spray (Approach B — possible later "beats the
  *full* published STrack" robustness check), STrack selective-retx, per-hop target plumbing,
  the trimming-regime 4th arm, 1024-node scale. These are deliberate deferrals for clean
  attribution and de-risk, not omissions to hide.

## 9. Risks

- **Near-NSCC clone** → mitigated by the §6 distinctness gate; reported if it happens.
- **STrack underperforms badly / instability** → reuse of UEC's vetted primitives
  (`quick_adapt`, `fulfill_adjustment`, loss) bounds this; `set_cwnd_bounds` + `_min_cwnd`
  guard. Report straight.
- **β/h defaults off** → use Table 1 values; β is the only genuinely new constant; sensitivity
  to it is a P5 concern, not P3.
