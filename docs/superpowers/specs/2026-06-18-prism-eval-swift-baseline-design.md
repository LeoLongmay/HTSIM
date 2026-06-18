# Design: Swift CC baseline for expA_delaydriven (phase A of Swift/LSwift/MSwift)

**Date:** 2026-06-18
**Scope:** Port **Swift** (Kumar et al., SIGCOMM 2020 — Algorithm 1 + §3.5 flow-scaled target delay) into the
`UecSrc` CC framework as `-sender_cc_algo swift`, and wire it as a baseline arm in
`prism_eval/expA_delaydriven/` (the `-failed` sweep, the offered-load sweep, the mechanism cwnd panel).
**This is phase A** of a two-phase effort; **LSwift + MSwift are phase B (a separate spec/plan), explicitly
out of scope here.**

**Why a port (not the existing swift.cpp):** the repo's `swift.cpp` is a complete, faithful Swift CC, but it
is a **separate transport stack** (`SwiftSrc`/`SwiftPacket`/`SwiftSink`, MPTCP-style subflow/PLB multipath,
`htsim_swift` binary `EXCLUDE_FROM_ALL`, emits no `FLOW_EVENT`) — not a `UecSrc` CC, and its multipath is
subflows not per-packet spraying. Using it as a PRISM baseline would be apples-to-oranges (different fabric,
spray model, and metrics pipeline). So we port Swift's **CC law** into `UecSrc` (CC-only, on the shared REPS
spray, same metrics/figures), exactly as STrack was ported (Approach A). `swift.cpp` is the **code reference**.

**Honest framing (binding):** Swift is a genuine competitor CC (pure-delay AIMD with a flow-scaled target),
not a strawman. The result is reported straight (PRISM's floor decomposition vs Swift's instantaneous-delay
AIMD). Parameters are **Algorithm-1-faithful in structure**; the values `ai/β/max_mdf` are htsim's defaults
(the Swift paper does not publish production values — confidential), and the target is calibrated to our
regime (operating point ≈ NSCC/PRISM's ~14 µs), which is stated.

---

## Background / current state (verified against the paper + swift.cpp)

- **Swift Algorithm 1 (paper §3.2, lines 109–161):** on ACK, `target = TargetDelay()`; if `delay < target` →
  **AI** `cwnd += (ai/cwnd)·num_acked` (cumulative +ai per RTT); else if `can_decrease` (MD once per RTT,
  `now − t_last_decrease ≥ rtt`) → **MD** `cwnd ← max(1 − β·(delay−target)/delay, 1 − max_mdf)·cwnd`. RTO →
  `cwnd = min_cwnd` (or `(1−max_mdf)·cwnd`); fast-recovery (SACK hole) → `(1−max_mdf)·cwnd`. `clamp(min,cwnd,max)`;
  if `cwnd ≤ cwnd_prev` then `t_last_decrease = now`; if `cwnd < 1` pace at `rtt/cwnd`.
- **Target delay (paper §3.5, lines 260–268):** `t = base_target + #hops·ℏ + max(0, min(α/√fcwnd + β, fs_range))`,
  `α = fs_range/(1/√fs_min_cwnd − 1/√fs_max_cwnd)`, `β = −α/√fs_max_cwnd`. (cwnd in packets.)
- **`swift.cpp` is a faithful reference** (verified line-by-line): `SwiftSubflowSrc::adjust_cwnd` matches
  Algorithm 1 (byte-domain: `cwnd += mss·ai·num_acked/cwnd`, `num_acked` = ackno byte-delta; MD identical,
  once-per-RTT via `_can_decrease`); `SwiftSrc::targetDelay` matches §3.5 exactly. Default params (htsim
  "guess", flagged as such in comments): `ai=1.0, β=0.8, max_mdf=0.5`, `fs_range=5·base, ℏ=base/6.55,
  fs_min_cwnd=0.1, fs_max_cwnd=100 (pkts)`, `min_cwnd=10 B, max_cwnd=1000·mss`.
- **UecSrc hooks:** dispatch `uec.cpp:592` (`Sender_CC` enum `uec.h:219`, currently `{DCTCP,NSCC,CONSTANT,
  PRISM,STRACK,MNSCC}`); `updateCwndOnAck_X(bool skip, simtime_picosec delay, mem_b newly_acked_bytes)` with
  caller `delay = raw_rtt − _base_rtt` (instantaneous queuing delay), `newly_acked_bytes` = bytes acked;
  `_cwnd` in bytes; `_mtu` (uint16_t), `_base_rtt`, `_target_Qdelay` available; `quick_adapt`, `set_cwnd_bounds`
  reusable; `_last_dec_time` is PRISM's (Swift gets its own `_swift_last_dec`).

---

## Component 1 — pure logic `swift_cc.h` + unit test

**`htsim/sim/swift_cc.h`** (header-only, no side effects, unit-tested; mirrors `strack_cc.h`/`mnscc_median.h`):
- `inline simtime_picosec swift::target_delay_q(double cwnd_pkts, simtime_picosec base_q, double fs_alpha,
  double fs_beta, double fs_range)` = `base_q + clamp(fs_alpha/sqrt(cwnd_pkts) + fs_beta, 0.0, fs_range)`.
  `cwnd_pkts ≤ 0` → returns `base_q` (no scaling). The `#hops·ℏ` term is **folded into base_q** (fixed-depth
  topology; `base_rtt` already removes propagation), so the queuing-domain target = base_q + flow-scaling.
- `inline double swift::md_factor(simtime_picosec delay, simtime_picosec target, double beta, double max_mdf)`
  = `max(1.0 − beta·((double)(delay − target))/(double)delay, 1.0 − max_mdf)`. Caller guarantees
  `delay ≥ target` and `delay > 0` (only called on the MD branch).
- `inline void swift::fs_coeffs(double fs_range, double fs_min_cwnd, double fs_max_cwnd, double& a, double& b)`
  derives `a = fs_range/(1/sqrt(fs_min_cwnd) − 1/sqrt(fs_max_cwnd))`, `b = −a/sqrt(fs_max_cwnd)` (paper §3.5).
- **Unit test** `tests/test_swift_cc.cpp` (compiled in repro.sh self-test, like `test_strack_cc.cpp`):
  with fs_range=R, fs_min=0.1, fs_max=100: `target_delay_q` at high cwnd (=100) → `base_q` (fs term ≈ 0); at
  low cwnd (=0.1) → `base_q + R` (clamped); monotonic decreasing in cwnd. `md_factor`: `delay==target` → 1.0;
  `delay` slightly > target → just below 1.0; `delay ≫ target` → clamped at `1 − max_mdf`.

## Component 2 — controller (`uec.h` / `uec.cpp`)

- `uec.h`: append `SWIFT` to `Sender_CC` (scoped `UecSrc::SWIFT`; no clash with the global `SWIFT` packet
  type). Declare `updateCwndOnAck_SWIFT` + `updateCwndOnNack_SWIFT`. Per-flow `simtime_picosec
  _swift_last_dec = 0;`. Statics: `_swift_ai`, `_swift_beta`, `_swift_max_mdf` (double), `_swift_base_q`,
  `_swift_fs_range` (simtime_picosec; 0 = derive from `_target_Qdelay`), `_swift_fs_min_cwnd`,
  `_swift_fs_max_cwnd` (double).
- `uec.cpp`: `#include "swift_cc.h"`; static definitions (`ai=1.0, beta=0.8, max_mdf=0.5, base_q=0,
  fs_range=0, fs_min_cwnd=0.1, fs_max_cwnd=100`); dispatch `case SWIFT: updateCwndOnAck =
  &UecSrc::updateCwndOnAck_SWIFT; updateCwndOnNack = &UecSrc::updateCwndOnNack_SWIFT; break;`.
- `updateCwndOnAck_SWIFT(bool skip, simtime_picosec delay, mem_b newly_acked_bytes)`:
  1. `if (quick_adapt(false, skip, delay)) return;` (reuse NSCC loss/quick-adapt, as PRISM/STrack).
  2. `simtime_picosec base_q = _swift_base_q > 0 ? _swift_base_q : _target_Qdelay;`
     `simtime_picosec fs_range = _swift_fs_range > 0 ? _swift_fs_range : _target_Qdelay/2;`
     `double a,b; swift::fs_coeffs(fs_range, _swift_fs_min_cwnd, _swift_fs_max_cwnd, a, b);`
     `double cwnd_pkts = _mtu > 0 ? (double)_cwnd/_mtu : 0.0;`
     `simtime_picosec target = swift::target_delay_q(cwnd_pkts, base_q, a, b, (double)fs_range);`
  3. `bool can_decrease = (eventlist().now() − _swift_last_dec) >= _base_rtt;`
  4. `if (delay < target) { if (_cwnd > 0) _cwnd += (mem_b)((double)_mtu * _swift_ai * (double)newly_acked_bytes
     / (double)_cwnd); }` (byte-domain AI; cumulative +ai pkts/RTT — verified dimensionally against swift.cpp).
  5. `else if (can_decrease) { mem_b before=_cwnd; _cwnd=(mem_b)(_cwnd*swift::md_factor(delay,target,_swift_beta,
     _swift_max_mdf)); if (_cwnd <= before) _swift_last_dec = eventlist().now(); }`
  6. **ECN `skip` ignored** (Swift is pure-delay; no ECN term — a faithful distinction from NSCC's ECN-gated MD).
  7. `set_cwnd_bounds();`
- `updateCwndOnNack_SWIFT(uint32_t ev, mem_b nacked_bytes, bool last_hop)`: Swift loss MD —
  `if ((now − _swift_last_dec) >= _base_rtt) { _cwnd = (mem_b)(_cwnd*(1.0 − _swift_max_mdf)); _swift_last_dec
  = now; } set_cwnd_bounds();` — the faithful Swift loss MD (flat `max_mdf` cut, once per RTT); rarely fires
  in the no-trim headline regime.
- **No change to NSCC/PRISM/STrack/MNSCC paths** — additive only; existing arms byte-identical.

## Component 3 — target calibration (faithful flow-scaled, regime-matched)

- Default `base_q = _target_Qdelay` (≈14 µs at 100G) so the **high-cwnd operating point matches NSCC/PRISM**;
  `fs_range = _target_Qdelay/2` (≈7 µs) gives Swift's signature extra headroom only at low cwnd. With
  fs_min=0.1, fs_max=100: target = base_q at cwnd≥100 pkt, base_q+fs_range at cwnd≤0.1 pkt; at a representative
  cwnd≈42 pkt (1×BDP) fs adds ≈0.1 µs → effective target ≈14.1 µs (fair same-operating-point vs NSCC).
- **Empirical calibration step (plan):** run Swift at `-failed 0` (symmetric) and confirm its steady-state
  queuing delay tracks the target (~14 µs) and goodput is sane (not collapsed, not line-rate-cheating). If the
  operating point is far off, tune `-swift_base_q` / `-swift_fs_range` and note the chosen values. All four
  fs/target knobs are flags (`-swift_ai/-swift_beta/-swift_max_mdf/-swift_base_q/-swift_fs_range/
  -swift_fs_min_cwnd/-swift_fs_max_cwnd`), defaulting to the above.

## Component 4 — eval wiring (7 arms)

- `plot_style.py`: `COLORS["swift"] = "tab:pink"`.
- `expA_delaydriven/make_figs.py`: append `("swift", "Swift", "swift")` to `BASELINES` → Swift enters the
  `-failed` sweep (`figA1dd_*`, fairness) and the offered-load sweep (`figA3dd_load_*`) — now **7 arms**
  (ops/reps/strack/prism/ecmp/mnscc/swift).
- `expA_delaydriven/repro.sh`: add `swift reps` to the `-failed` loop (`expA_swift_f${f}_s${s}`) and the
  offered-load loop (`expAload_swift_L${rho}_s${s}`); add a mechanism run `expA_swift_mech` at failed=8 on
  `$CM_MECH` with `PRISM_PATHRTT="$OUT/expA_swift_mech.pathrtt.csv"`.
- Mechanism figure: Swift joins the **cwnd panel + per-ACK rate-reduction count** (guarded by file existence,
  like MNSCC — backward-compatible). **No new signal line** (Swift acts on the instantaneous per-ACK delay =
  the raw per-path data, not a distinct aggregate).
- **Figure-curation note:** 7 arms is near the readable limit; phase B (LSwift+MSwift → 9 arms) will need a
  figure-grouping/curation decision — deferred to phase B's spec.

## Component 5 — files

- **Create:** `htsim/sim/swift_cc.h`; `htsim/sim/datacenter/prism_eval/common/tests/test_swift_cc.cpp`.
- **Modify (controller):** `uec.h` (enum SWIFT; decls; `_swift_last_dec`; statics), `uec.cpp` (include,
  static defs, dispatch, `updateCwndOnAck_SWIFT`, `updateCwndOnNack_SWIFT`), `datacenter/main_uec.cpp`
  (`-sender_cc_algo swift` + the `-swift_*` flags). `main_uec_sf.cpp` parity optional (flag-inert default).
- **Modify (eval):** `prism_eval/common/plot_style.py`, `prism_eval/common/perf_figs.py`
  (`render_mechanism_split` Swift cwnd entry + cut count, backward-compatible), `prism_eval/expA_delaydriven/
  {make_figs.py,repro.sh}`, `prism_eval/expA_delaydriven/README.md`, `prism_eval/NARRATIVE.md`.

## Component 6 — testing & reproducibility

- **C++ unit test** `test_swift_cc.cpp` (target_delay_q monotonicity + clamp endpoints; md_factor endpoints),
  compiled+run in repro.sh's self-test block (like `test_strack_cc.cpp`/`test_mnscc_median.cpp`).
- **Regression (binding):** NSCC/PRISM/STrack/MNSCC arms byte-identical (Swift touches no existing CC path) —
  goodput spot-check unchanged; `render_mechanism_split` change guarded so MNSCC-less/Swift-less mech figures
  (expB/C/D) stay byte-identical (expD selftest the proof).
- **Swift sanity:** Swift runs at failed=0 and failed=8 with cr=1 and finite, sane goodput; behaves as a
  delay-AIMD sawtooth (cwnd panel); the f0 target-calibration check passes (queuing delay ≈ target).
- Figures `git add -f`; `data/` gitignored; seeds {13–17}; one-command repro; pinned commit; **no change to
  PRISM (O(1) intact)**. Built subagent-driven with two-stage review + a final whole-branch review.

---

## Out of scope (YAGNI / phase B)

- **LSwift + MSwift** — phase B (separate spec/plan): reordering resilience (MD trigger 2→5 consecutive
  delayed packets) + median + Nyquist `H=max(W/2,1)` on the Swift base built here.
- **Sub-1-packet pacing** (Algorithm 1 lines 29–32) — the BDP here is ~42 pkts; cwnd rarely < 1. Skip;
  `set_cwnd_bounds()`'s `_min_cwnd` floor stands in. (Note in README.)
- **Separate `#hops·ℏ` term** — folded into `base_q` (fixed-depth fabric; base_rtt removes propagation).
- **Fabric/endpoint split (fcwnd/ecwnd, §3.3)** — simulation has no host/endpoint congestion; only the
  fabric (queuing) delay matters, so a single cwnd on the fabric delay suffices (matches the MNSCC paper's
  Swift usage).
- **Figure curation for 9 arms** — deferred to phase B.
- **Production parameter values** — not published; htsim defaults used and noted.
