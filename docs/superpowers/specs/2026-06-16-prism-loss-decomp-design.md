# PRISM loss/NACK decomposition — extend PRISM to the trimming regime (design)

**Date:** 2026-06-16
**Phase:** agenda item (b) — the "trim masks the decomposition" crux (命门).
**Status:** design, pending user review → writing-plans → subagent-driven execution.

## 1. Goal & success criterion

P2 (trimming default — the UEC fabric default) found PRISM **tied** REPS+NSCC; data-mining
showed PRISM's delay floor-MD governed only **~5%** of cwnd decreases — loss/trim-NACK-driven
control dominated and **masked** the delay decomposition. Since UEC fabrics trim by design, this
is the crux question for whether PRISM is a strong contribution or a niche one. **Goal:** extend
PRISM's decomposition principle from the *delay* signal to the *loss/NACK* signal so it survives
the trimming regime. **Success (user-chosen):** re-run the trimming Exp A; under asymmetry
(failed ≥ 4) PRISM-with-loss-decomposition **beats REPS+NSCC** on goodput/FCT (vs P2's tie), and
a **loss-HOLD fraction** ≫ 0 confirms the decomposition is now active (no longer masked). Report
honestly, including a tie/negative if that is what happens.

## 2. Mechanism evidence (the pivot is well-posed)

- **Per-path loss info is available.** `processNack` (uec.cpp:1792) has the trimmed packet's
  entropy `ev = pkt.ev()`; line 1850 already passes it into `updateCwndOnNack(ev, …)` (currently
  lossily cast to a `bool skip` that the NSCC handler ignores). Line 1875 already calls
  `_mp->processEv(ev, PATH_NACK)` — so **REPS already reroutes away from a trimming path**; the
  spraying-side response to loss is in place.
- **`last_hop()` distinguishes reroutable from not.** `!last_hop` = fabric trim (reroutable —
  PATH_NACK to REPS); `last_hop` = last-hop receiver incast (NOT reroutable).
- **Current cwnd response is global/blind.** `updateCwndOnNack_NSCC` cuts on *any* NACK
  (`_trigger_qa=true` + `quick_adapt(loss)` → big cut to achievedBDP, and/or `_cwnd -=
  nacked_bytes`), ignoring whether the loss is concentrated (reroutable) or uniform. This is the
  masking. PRISM will gate the **cut** (not the retransmission, which always happens) by a loss
  four-quadrant rule.
- **Paths.** REPS sprays over `_no_of_paths` (= `-paths`, e.g. 8; power of 2) scrambled entropy
  values; within one epoch (~1 RTT) ~`_no_of_paths` distinct `ev`s are in use and stable enough
  to treat distinct `ev`s as distinct paths.

## 3. Design

### 3.1 Pure logic — `prism::decide_loss` in `htsim/sim/prism_decompose.h` (+ unit test)
```cpp
enum LossAction { LOSS_CUT = 0, LOSS_HOLD = 1 };
// Loss four-quadrant rule. Mirrors decide_region but on the loss signal.
inline LossAction decide_loss(bool last_hop, bool enough_evidence,
                              bool clean_path_exists, bool streak_exceeded) {
    if (last_hop)          return LOSS_CUT;   // receiver incast -> not reroutable
    if (!enough_evidence)  return LOSS_CUT;   // too few good-ACK paths seen yet -> safe default
    if (streak_exceeded)   return LOSS_CUT;   // safety valve: held too long, force a cut
    if (clean_path_exists) return LOSS_HOLD;  // concentrated/reroutable -> let REPS reroute, hold cwnd
    return LOSS_CUT;                          // uniform loss across paths -> genuine congestion
}
```
Header-only `selftest()` exercises all five outcomes. (Added to the existing PRISM pure-logic
header next to `decide_region`/`md_factor`.)

### 3.2 Per-epoch loss state in `UecSrc` (reuses the P1 epoch, feedback-driven)
Within the current PRISM epoch (`kappa·base_rtt`), maintain over the ~8 distinct `ev`s:
- `_prism_loss_evs_good` — set of `ev`s that received a **genuine good ACK** this epoch.
- `_prism_loss_evs_nacked` — set of `ev`s that received a **fabric NACK** (`!last_hop`) this epoch.
- `_prism_loss_hold_since` — start time of the current continuous HOLD run (0 = not holding); the
  time-based safety valve. (Revised from an epoch-counted streak after the holistic review found the
  epoch-gated valve unreachable under sustained loss — see §6.)

Updated where `ev` is available, gated on `_sender_cc_algo == PRISM && _prism_loss_decomp`:
- **good ACK:** in `processAck`'s genuine-sample branch (the `_prism_genuine_sample` path, which
  has `pkt.ev()`), add `ev` to `_prism_loss_evs_good`.
- **fabric NACK:** in `updateCwndOnNack_PRISM`, add `ev` to `_prism_loss_evs_nacked`.
- **epoch boundary** (the existing boundary code in `updateCwndOnAck_PRISM`): clear both ev sets
  (refresh evidence each closed epoch).
- **NACK handler** maintains the time-valve: on HOLD, stamp `_prism_loss_hold_since` if not already
  running; on CUT, reset it to 0 (and, if the valve forced the cut, clear the ev sets to refresh
  possibly-stale evidence — needed because under sustained loss the ACK epoch may never close).

`clean_path_exists` (at NACK time, after adding the current `ev`) = `(_prism_loss_evs_good −
_prism_loss_evs_nacked)` is non-empty (some path is ACKing well and not NACKing).
`enough_evidence` = `|_prism_loss_evs_good| >= PRISM_LOSS_MIN_GOOD` (default 2).
`streak_exceeded` = held continuously too long = `_prism_loss_hold_since != 0 && now −
_prism_loss_hold_since >= _prism_loss_streak_cap · base_rtt` (cap default 4 → 4 RTTs of continuous
HOLD force a cut). This valve is computed in the NACK handler, so it is reachable independent of
ACK-epoch closure.

### 3.3 `updateCwndOnNack_PRISM(uint32_t ev, mem_b nacked_bytes, bool last_hop)`
- Signature plumbing: change the shared function-pointer first param `bool skip → uint32_t ev`
  (uec.h:323 + the `_NSCC`/`_DCTCP` decls/defs; the call site already passes `ev`; NSCC/DCTCP
  bodies ignore it). Dispatch (uec.cpp ~601) for `STRACK`/`PRISM` updated to point at the new
  handler.
- Body: add `ev` to `_prism_loss_evs_nacked`; compute the three booleans; `switch
  (prism::decide_loss(last_hop, enough, clean, streak_exceeded))`:
  - `LOSS_HOLD` → **do nothing to cwnd** (no `quick_adapt`, no `_cwnd -=`); mark the epoch HELD.
    Retransmission + `_mp->processEv(ev, PATH_NACK)` happen in `processNack` regardless.
  - `LOSS_CUT` → the existing NSCC NACK response (`_bytes_ignored += nacked_bytes`,
    `update_delay(...)`, `_trigger_qa=true`, `quick_adapt(true,true,0)`, else `_cwnd -=
    nacked_bytes; set_cwnd_bounds()`); mark the epoch CUT.
- When `_prism_loss_decomp` is OFF, `updateCwndOnNack_PRISM` is exactly `updateCwndOnNack_NSCC`
  (so PRISM with the flag off == today's PRISM).

### 3.4 Flags & constants
- `-prism_loss_decomp` (bool, **default OFF** — keeps committed delay-driven results untouched;
  the trim eval turns it ON).
- `-prism_loss_streak_cap` (default 4 — the time-based safety valve: max continuous HOLD duration
  in `base_rtt` units before a forced cut).
- `PRISM_LOSS_MIN_GOOD` = 2 (compile-time, mirrors `PRISM_MIN_SAMPLES`).

### 3.5 Logging
Extend the PRISM epoch/decision log with a per-NACK loss mark (HOLD vs CUT) and per-epoch
held/total NACK counts, so analysis can compute the **loss-HOLD fraction** (= fabric NACKs HELD /
fabric NACKs total) — the loss analog of the delay floor-MD fraction — and the mechanism figure.

## 4. Evaluation — `prism_eval/expA_lossdecomp/` (trimming regime)

Re-run the **trimming-default** Exp A (P2 setup: 128-node many2many 64→16 pod0 2 MB,
fat_tree_128_1os, `-paths 8`, NO `-disable_trim`, `-failed {0,2,4,8,12}`, seeds {13..17}). Arms:
1. OPS+NSCC, 2. REPS+NSCC (the tie reference), 3. **PRISM-delay-only** (`-prism_loss_decomp off`
= P2's PRISM), 4. **PRISM-loss-decomp** (`-prism_loss_decomp on` = new). Reuse the shared harness
(`run_lib.sh` + `perf_figs.render_main_perf` with 4 baselines). Mechanism run at failed=8.

- **Headline test:** does arm 4 beat REPS+NSCC under asymmetry where arm 3 (and P2) tied?
- **Attribution:** arm 4 vs arm 3 isolates what the loss-decomposition bought.
- **Decomposition-active metric:** loss-HOLD fraction for arm 4 ≫ 0 (and the delay floor-MD
  fraction, for contrast — expected still low in the trim regime).
- **Do-no-harm regression check (guard, not headline):** run PRISM-loss-decomp **on** in the
  delay-driven regime (`-disable_trim`) for one cell and confirm it reproduces the committed
  delay-driven PRISM (loss-decomp should be ~inert there — few/no fabric NACKs). If it diverges,
  surface it.

## 5. Honest scope & non-goals
- **In:** `prism::decide_loss` + test; per-epoch loss state + `updateCwndOnNack_PRISM`; the
  `bool skip → uint32_t ev` signature plumbing; flags; logging; the trimming-regime eval group.
- **Out (noted):** auto-enabling loss-decomp when trimming is detected (kept a manual flag);
  porting it into NSCC/STrack (PRISM-only); 1024 scale; the f0 root-cause diagnosis; touching the
  committed delay-driven/asymmetric groups.
- **Honesty:** if "no clean path" is almost always true in the trim regime (shallow queues →
  near-uniform loss), arm 4 may still tie — report that straight as a (negative) characterization
  of when the loss-decomposition can and cannot help.

## 6. Risks
- **Holding on loss is riskier than holding on delay** (loss = buffer already overflowed) → the
  §3.2 safety valve (no-clean-path → CUT; streak cap → forced CUT) + retransmission-always bound
  it. Watch completion_rate in the eval (a drop signals unsafe holding).
- **Gating `quick_adapt` is invasive** → confined to the PRISM-loss-decomp path; NSCC/STrack
  untouched; flag-off == today's PRISM.
- **`ev` scrambling / path count** → distinct `ev`s as paths is a proxy; min-evidence gate avoids
  deciding on too-few samples.
