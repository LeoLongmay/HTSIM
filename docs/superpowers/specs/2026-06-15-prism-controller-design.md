# PRISM Controller (P1) — Design Spec

**Date:** 2026-06-15
**Status:** Approved (sections 1–3 confirmed by user)
**Parent:** `docs/superpowers/specs/2026-06-15-prism-eval-roadmap-design.md` (P1 of the roadmap)
**Source design:** `Skeleton_of_III.md` §3.1–3.3 (congestion decomposition, epoch estimation, floor-driven CC)

PRISM is a new sender-side CC algorithm in the htsim/UEC transport (`htsim/sim/uec.cpp`,
`uec.h`). It adds **only a window-decision path**: it decomposes per-epoch multipath
congestion into a floor `C_cc` and spread `C_spray`, then drives NSCC's existing
increase/decrease *formulas* from that decomposition instead of from NSCC's per-ACK
`avg_delay`/ECN signals. Spraying (REPS) and NACK/loss handling are reused unchanged.

## Resolved decisions

| Decision | Choice |
|---|---|
| PRISM↔NSCC reuse | **Core formulas, fed the decomposition** — reuse NSCC's `proportional_increase`/`fast_increase`/`fulfill_adjustment`/`set_cwnd_bounds`/`quick_adapt`/NACK; replace only the per-ACK decision tree with an epoch four-quadrant rule; add one floor-fed MD (NSCC's MD formula with input `C_cc`, target `T_cc`). |
| Floor `C_cc` | **Raw epoch-min of q** (two scalars/flow, O(1); no EWMA gains, no per-path table). |
| Decrease driver | **Floor `C_cc`**, via NSCC's MD formula (same γ, same shape) — not `_avg_delay`. |
| Spraying | Unchanged: `_mp->processEv(ev, PATH_ECN/PATH_GOOD)` at `uec.cpp:1138` runs regardless of CC algo. |
| NACK/loss | Reuse `updateCwndOnNack_NSCC` verbatim. |

## 1. Integration & state

**Enum / parse / dispatch (minimal):**
- `uec.h:219`: `enum Sender_CC { DCTCP, NSCC, CONSTANT, PRISM };`
- `main_uec.cpp` and `main_uec_sf.cpp` arg parse: `else if (!strcmp(argv[i+1],"prism")) UecSrc::_sender_cc_algo = UecSrc::PRISM;`
- `uec.cpp:583` dispatch switch: `case PRISM: updateCwndOnAck = &UecSrc::updateCwndOnAck_PRISM; updateCwndOnNack = &UecSrc::updateCwndOnNack_NSCC; break;`

**New per-flow state (`uec.h` private block, near `_avg_delay` ~line 452) — all O(1) scalars:**
```cpp
enum PrismRegion { PRISM_INCREASE = 0, PRISM_HOLD = 1, PRISM_DECREASE = 2 };
simtime_picosec _prism_epoch_start   = 0;
simtime_picosec _prism_epoch_min     = TIME_INF;  // min q this epoch
simtime_picosec _prism_epoch_max     = 0;         // max q this epoch
uint32_t        _prism_epoch_samples = 0;
int             _prism_region        = PRISM_INCREASE;  // region for the CURRENT epoch
simtime_picosec _prism_ccc           = 0;  // last epoch's C_cc (for logging)
simtime_picosec _prism_cspray        = 0;  // last epoch's C_spray (for logging)
```
(`TIME_INF` = a large sentinel, e.g. the existing max-time constant; pick the codebase's idiom.)

**Threshold T_cc IS `_target_Qdelay` (no separate knob).** `decide_region` and the floor-fed
MD both compare against `_target_Qdelay`, and the existing `proportional_increase` already uses
`_target_Qdelay` internally — so reusing it keeps one consistent target and avoids splitting it
across two variables (a divergent T_cc would also trip `proportional_increase`'s
`assert(_target_Qdelay > delay)`). The eval's "T_cc sensitivity sweep (0.5/1/2/4×)" is therefore
just sweeping `-target_q_delay`. This matches the design doc ("T_cc inherited from the CC's
target queueing delay").

**New static params (`uec.h` public statics, near `_target_Qdelay` ~line 366):**
```cpp
static simtime_picosec _prism_T_spray;  // tolerated spread; default = _target_Qdelay
static double          _prism_kappa;    // epoch length = kappa * base_rtt; default 1.0
```
CLI flags (parsed in both main files): `-prism_t_spray <us>` (default = `_target_Qdelay`),
`-prism_kappa <k>` (default 1.0). Defaults applied after arg parsing so an explicit
`-target_q_delay` flows into the `T_spray` default unless `-prism_t_spray` overrides.

**Reused, unchanged:** `proportional_increase`, `fast_increase`, `fulfill_adjustment`,
`set_cwnd_bounds`, `quick_adapt`, `updateCwndOnNack_NSCC`, and the REPS spraying path.

## 2. Algorithm

`updateCwndOnAck_PRISM(bool skip, simtime_picosec delay, mem_b newly_acked_bytes)`:
```text
q = max(delay, 0)                         # delay is raw_rtt-base (or avg fallback); clamp >=0
if _prism_epoch_samples == 0: _prism_epoch_start = now
_prism_epoch_min = min(_prism_epoch_min, q)
_prism_epoch_max = max(_prism_epoch_max, q)
_prism_epoch_samples += 1

# (1) in-epoch action: only INCREASE region runs NSCC's per-ACK increase machinery.
#     Feed it the decided floor (_prism_ccc), not raw per-ACK q: the region is INCREASE
#     because _prism_ccc < _target_Qdelay, so the headroom (target - floor) drives the
#     proportional rate; the min(..., target-1) is a defensive clamp for the assert.
#     First epoch: _prism_ccc == 0 -> fast_increase ramp (cold start).
if _prism_region == PRISM_INCREASE:
    proportional_increase(newly_acked_bytes, min(_prism_ccc, _target_Qdelay - 1))

# (2) epoch boundary: decide region from the decomposition
if (now - _prism_epoch_start >= _prism_kappa * _base_rtt)
        and (_prism_epoch_samples >= PRISM_MIN_SAMPLES):     # PRISM_MIN_SAMPLES = 3
    C_cc    = _prism_epoch_min
    C_spray = _prism_epoch_max - _prism_epoch_min
    _prism_region = decide_region(C_cc, C_spray)
    if _prism_region == PRISM_DECREASE:
        prism_multiplicative_decrease(C_cc)                   # floor-driven, once per boundary
    _prism_ccc = C_cc; _prism_cspray = C_spray
    log_epoch(C_cc, C_spray, _prism_region, cut)              # env-gated (section 3)
    _prism_epoch_min = TIME_INF; _prism_epoch_max = 0
    _prism_epoch_samples = 0; _prism_epoch_start = now

# (3) reuse NSCC: apply accumulated _inc_bytes to _cwnd
set_cwnd_bounds()
if (_received_bytes > _adjust_bytes_threshold or now - _last_adjust_time > _adjust_period_threshold):
    fulfill_adjustment()
set_cwnd_bounds()
```

`decide_region(C_cc, C_spray)` — its own function (P5 variants hook here):
```text
if C_cc <  _target_Qdelay and C_spray <  _prism_T_spray: return PRISM_INCREASE  # floor safe, balanced
if C_cc <  _target_Qdelay and C_spray >= _prism_T_spray: return PRISM_HOLD      # clean path; let REPS rebalance
return PRISM_DECREASE                                                           # C_cc>=target: even best path queued
```

`prism_multiplicative_decrease(C_cc)` — NSCC's MD formula (`uec.cpp:1347`) fed the floor:
```text
if C_cc > _target_Qdelay and (now - _last_dec_time > _base_rtt):
    _cwnd *= max(1 - _gamma*(C_cc - _target_Qdelay)/C_cc, 0.5)   # same gamma, same shape
    _cwnd  = max(_cwnd, _min_cwnd)
    _last_dec_time = now
```

**Semantics (built into the above):**
- **Timescale separation:** spraying reacts per-ACK (REPS, automatic); CC reacts per-epoch — giving spraying time to reshape the path distribution before the floor is judged.
- **HOLD = suppress increase**, no decrease; rebalancing is REPS's job (no extra PRISM action).
- **Decrease magnitude is set by the floor**, not spread, not the conflated average — same γ/shape as NSCC, so gains attribute to decomposition not new tuning.
- **First epoch defaults to INCREASE** (cold-start ramp).
- `PRISM_MIN_SAMPLES = 3` guards against deciding on a near-empty epoch.

## 3. Logging, testing, attribution, ablation hooks

**Epoch log (env-gated `PRISM_EPOCH`, read-only, no behavior change),** mirroring the
existing `PRISM_PATHRTT` hook — one CSV row per epoch boundary:
```
time_ns,flow_id,base_rtt_ns,C_cc_ns,C_spray_ns,region,cwnd_bytes,samples,cut
```
`region` ∈ {0,1,2}; `cut` ∈ {0,1} (1 iff this boundary executed an MD). This is the data
source for the evaluation's internal metrics (four-region occupancy, # cwnd cuts,
`C_cc`/`C_spray`/cwnd time series). Keep `PRISM_PATHRTT` (per-ACK) for cross-validation.

**Verification (P1 done-criteria):**
1. **Offline cross-check (core):** run PRISM with both `PRISM_EPOCH` and `PRISM_PATHRTT`;
   a Python checker in `prism_eval/common/tests/` groups the per-ACK `q` from PATHRTT into
   `kappa*base_rtt` epochs, recomputes `min` / `max-min`, and asserts it matches the epoch
   log row-by-row (within rounding).
2. **Behavioral unit checks (deterministic short runs via `run_lib.sh`, assert direction not exact values):**
   - clean symmetric (failed=0, light load): mostly INCREASE; cwnd not needlessly cut.
   - asymmetric (failed=12): C_cc low + C_spray high → HOLD occupancy rises; far fewer cuts than NSCC.
   - incast (shared bottleneck): C_cc high, C_spray small → DECREASE (floor-driven fallback).
3. **No NSCC regression:** `-sender_cc_algo nscc` behavior is byte-identical (PRISM is a separate path).

**Attribution (for the paper/README):** PRISM's increase formulas (proportional/fast),
decrease formula (γ·(x−T)/x), and all gain constants (γ, α, fi, …) are identical to NSCC's.
Only the decision **input** (C_cc/C_spray vs avg_delay/ECN) and **timescale** (epoch vs per-ACK)
change. Any performance difference is therefore attributable to reading the right congestion
component, not to new tuning.

**Ablation hooks (interfaces only this phase; variants built in P5):** concentrate the logic
in `decide_region()` + `prism_multiplicative_decrease()`, and reserve a `_prism_variant` enum
slot, so P5 can add: Average-as-Floor (feed `_avg_delay`), No-Spread-Gate (ignore C_spray),
Spread-as-Decrease (decrease on C_spray), Long-Epoch (large κ), Oracle-PRISM (per-entropy
min/max). This phase implements only the default PRISM controller.

## Out of scope for P1
- The P5 ablation variants themselves (only the hook structure is built here).
- STrack (P3), experiment groups (P2+), workload generators beyond what P0 delivered.

## Next step
After user review: invoke writing-plans to produce the P1 implementation plan (TDD where the
build allows: pure-logic units — `decide_region`, the epoch-min/max accumulation, the
floor-fed MD — are unit-testable; the integration is verified via the offline cross-check and
behavioral runs above).
