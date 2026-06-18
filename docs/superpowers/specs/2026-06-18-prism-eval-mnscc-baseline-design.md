# Design: MNSCC (median@NSCC) baseline for expA_delaydriven

**Date:** 2026-06-18
**Scope:** Implement **MNSCC** — the median-based congestion-control framework of Gerstein et al. 2026
("Congestion Control for Spraying with Congested Paths", `Mswift/`) applied to UEC's NSCC — as a new
`-sender_cc_algo mnscc` arm, and add it as a head-to-head baseline in `prism_eval/expA_delaydriven/`
(the `-failed` sweep, the offered-load sweep `figA3dd_load`, and the mechanism signal panel).

**Why MNSCC (not MSwift):** MNSCC shares PRISM's NSCC base, so a PRISM-vs-MNSCC comparison isolates the
single variable that matters — **floor-decomposition (PRISM) vs median-of-recent (MNSCC) vs latest-signal
(NSCC), holding the base CCA fixed**. MSwift is Swift-based (a different base CCA whose gains are confounded
with LSwift's reordering resilience), would require porting Swift into `UecSrc`, and is out of scope here
(optional future work). This is the cleanest test of PRISM's central design choice (the floor/min statistic).

**Honest framing (binding):** MNSCC is a genuine **competitor**, not a strawman — PRISM is not guaranteed to
win. The paper itself reports MNSCC only modestly improves NSCC (NSCC's small Nyquist window H≤4 limits the
median's effect). Whichever way it lands — PRISM's floor wins under reroutable asymmetry, ties, or MNSCC's
median is better-calibrated under genuine overload (PRISM's known f0/incast over-permit cost) — the result
is reported straight. The overhead asymmetry (PRISM O(1) scalars vs MNSCC O(H) window) is stated too.

---

## Background / current state (verified)

- **Binary:** `htsim_uec` = `main_uec.cpp`. CC dispatch (`uec.cpp:592`): `_sender_cc_algo` switch → a
  `updateCwndOnAck` function pointer. Enum `Sender_CC { DCTCP, NSCC, CONSTANT, PRISM, STRACK }` (`uec.h:219`).
- **NSCC delay hook (`uec.cpp:1432`):** `updateCwndOnAck_NSCC(bool skip, simtime_picosec delay, mem_b
  newly_acked_bytes)`. The caller (`uec.cpp:1176/1180`) passes `skip = pkt.ecn_echo()` and
  `delay = raw_rtt − _base_rtt` (genuine per-path queuing delay; `get_avg_delay()` fallback when no genuine
  sample). NSCC branches on `delay` vs `_target_Qdelay` (and `skip`) for increase/decrease.
- **Patterns to mirror:** PRISM (`updateCwndOnAck_PRISM`, pure logic `prism_decompose.h`, per-flow `_prism_*`
  state, env-gated `PRISM_EPOCH` CSV via a `static std::ofstream*` from `getenv`) and STrack
  (`updateCwndOnAck_STRACK`, pure logic `strack_cc.h`, unit test `tests/test_strack_cc.cpp`,
  NACK reuses `updateCwndOnNack_NSCC`). MNSCC follows both patterns.
- **No median/MNSCC/MSwift/LSwift exists** in the tree (grep-verified). NSCC is present (MNSCC builds on it).
  A standalone `swift*` transport exists but is NOT a `UecSrc` CC (irrelevant to MNSCC).
- **Regime match:** the paper's eval (no trimming, deep buffers, delay+ECN) is PRISM's target regime =
  expA_delaydriven (`-disable_trim`, 5×BDP). Calibration at 100G: `_base_rtt ≈ _target_Qdelay ≈ 14 µs`;
  BDP ≈ 42 packets at MTU 4150, so the Nyquist H formula sits at its cap (4) almost always.

---

## Component 1 — the MNSCC controller (`-sender_cc_algo mnscc`)

**Pure logic** `htsim/sim/mnscc_median.h` (no side effects, unit-tested):
- `simtime_picosec mnscc::median_of(const simtime_picosec* buf, int n)` — median of the `n` most-recent
  samples. Odd `n`: middle element. Even `n`: average of the two middle elements. `n==1` returns the value
  (→ degenerates to plain NSCC). Computes on a local copy (does not mutate `buf`).
- `int mnscc::nyquist_h(int w_packets)` — returns `max(min(w_packets/2, 4), 1)` (the paper's
  H_MNSCC = max(min(W/2,4),1)). `w_packets < 2` → 1.

**Per-flow state** (in `UecSrc`, `uec.h`):
- `simtime_picosec _mnscc_window[MNSCC_MAX_H]` (ring buffer of recent `delay` values), `uint32_t
  _mnscc_wcount`, `uint32_t _mnscc_whead`. `MNSCC_MAX_H` = 32 (bounds the swept H; the default formula caps
  at 4). Initialized to empty in the connection setup alongside the other CC state.

**Static param** (`uec.h`, parsed in `main_uec.cpp`):
- `static uint32_t _mnscc_h` — 0 = use `nyquist_h(W)`; N>0 = fixed window N (clamped to `MNSCC_MAX_H`).
  Flag `-mnscc_h N`.

**`updateCwndOnAck_MNSCC(bool skip, simtime_picosec delay, mem_b newly_acked_bytes)`** (`uec.cpp`):
1. Push `delay` into `_mnscc_window` (ring; advance `_mnscc_whead`, grow `_mnscc_wcount` up to `MNSCC_MAX_H`).
2. `W = _cwnd / _mtu` (packets); `H = _mnscc_h > 0 ? min(_mnscc_h, MNSCC_MAX_H) : mnscc::nyquist_h(W)`.
3. `med = mnscc::median_of(<last min(H, _mnscc_wcount) entries>)`.
4. Call `updateCwndOnAck_NSCC(skip, med, newly_acked_bytes)` — **reuses NSCC verbatim** with the median
   substituted for the per-ACK delay. `skip` (ECN) stays per-ACK (the paper applies the median to the *delay*
   signal of NSCC).
5. Env-gated median log (see Component 3).

**Dispatch** (`uec.cpp:592` switch): `case MNSCC: updateCwndOnAck = &UecSrc::updateCwndOnAck_MNSCC;
updateCwndOnNack = &UecSrc::updateCwndOnNack_NSCC; break;` (NACK/loss reuse, as STrack does).

**No change to NSCC/PRISM/STrack code paths** — MNSCC is an additive new path. Existing arms must stay
byte-identical (verified).

---

## Component 2 — H policy

- Default (`-mnscc_h` absent or 0): `H = max(min(W/2, 4), 1)`, `W = _cwnd/_mtu`, recomputed per ACK.
- `-mnscc_h N` (N>0): fixed `H = min(N, MNSCC_MAX_H)`.
- `-mnscc_h 1` ≈ NSCC (median of 1 = latest) — the sanity/degeneracy check.
- Enables an optional H-sensitivity sweep and validates the paper's claim that NSCC's small H limits gains.

---

## Component 3 — mechanism logging + figure (the median-vs-floor-vs-avg panel)

- **Logging:** env-gated CSV `MNSCC_MEDIAN` (mirror `PRISM_EPOCH`: a function-static `std::ofstream*` from
  `getenv("MNSCC_MEDIAN")`, created once). One row per ACK that MNSCC decides on:
  `time_ns, flow_id, median_ns` (the `med` from step 3). Flushed like the PRISM epoch log.
- **Figure (`common/perf_figs.py` `render_mechanism_split`):** add a "MNSCC median delay" line to the signal
  panel, read from the `{tag_prefix}_mnscc_mech` median CSV (time-binned like the other signals). The signal
  panel then shows **REPS+NSCC avg (blue), STrack avg (orange), MNSCC median (brown), PRISM floor C_cc
  (green), target (dashed)** — directly visualizing the three statistics (avg / median / floor) and motivating
  PRISM's floor choice. MNSCC also joins the cwnd panel + per-ACK rate-reduction count (it is a CC arm).
- **Backward compatibility (binding):** the MNSCC line renders **only if its median/pathrtt CSVs exist**;
  every other experiment's mechanism figure (expB/expC/expD, and expA's own when run without MNSCC) is
  **byte-identical**. No change to `render_main_perf`/`render_main_perf_split`/`render_fairness` signatures.

---

## Component 4 — eval wiring (expA_delaydriven, 6 arms)

- `plot_style.py`: add `"mnscc": "tab:brown"` to `COLORS`.
- `expA_delaydriven/make_figs.py`: append `("mnscc", "MNSCC", "mnscc")` to `BASELINES` → MNSCC enters the
  `-failed` sweep (`figA1dd_*`, `figA1dd_fairness`) and the offered-load sweep (`figA3dd_load_*`)
  automatically (6 arms: ops/reps/strack/prism/ecmp/mnscc).
- `expA_delaydriven/repro.sh`:
  - main `-failed` loop: add `bash run_lib.sh mnscc reps "$f" "$TOPO" "$s" "$CM" flow,sink
    "expA_mnscc_f${f}_s${s}" "$OUT"`.
  - offered-load loop: add the mnscc arm `mnscc reps 8 … "expAload_mnscc_L${rho}_s${s}"`, reusing the same
    per-`(rho,seed)` `.cm`.
  - mechanism condition: add a mnscc run at failed=8 on the 4MB `CM_MECH` with
    `PRISM_PATHRTT="$OUT/expA_mnscc_mech.pathrtt.csv"` **and** `MNSCC_MEDIAN="$OUT/expA_mnscc_mech.median.csv"`,
    tag `expA_mnscc_mech` (so the cwnd panel, cut count, and median signal all have data).
- Arm = `CC=mnscc LB=reps` everywhere (same spray base as prism/strack — CC is the only variable).

---

## Component 5 — files

- **Create:** `htsim/sim/mnscc_median.h`; `htsim/sim/datacenter/prism_eval/common/tests/test_mnscc_median.cpp`.
- **Modify (controller):** `uec.h` (enum `MNSCC`; decl `updateCwndOnAck_MNSCC`; per-flow window members +
  `MNSCC_MAX_H`; static `_mnscc_h`), `uec.cpp` (dispatch case; `updateCwndOnAck_MNSCC`; median CSV log;
  window init in connection setup; `#include "mnscc_median.h"`), `main_uec.cpp` (`-sender_cc_algo mnscc`,
  `-mnscc_h N`). `main_uec_sf.cpp` gets the same two parse clauses for parity (optional; the holdleak change
  touched it too) — flag default 0 keeps it inert.
- **Modify (eval):** `prism_eval/common/plot_style.py`, `prism_eval/common/perf_figs.py`
  (`render_mechanism_split` MNSCC line, backward-compatible), `prism_eval/expA_delaydriven/make_figs.py`,
  `prism_eval/expA_delaydriven/repro.sh`, `prism_eval/expA_delaydriven/README.md`, `prism_eval/NARRATIVE.md`.

---

## Component 6 — testing & reproducibility

- **C++ unit test** `test_mnscc_median.cpp` (compiled+run in repro.sh's self-test block, like
  `test_strack_cc.cpp`): odd-window median, even-window (avg of two middles), `n==1` identity, `nyquist_h`
  edge cases (W=1→1, W=4→2, W=20→4, W=100→4).
- **Regression (binding):** NSCC and PRISM arms produce **byte-identical** results to before MNSCC was added
  (MNSCC touches no existing CC path) — verified by a goodput spot-check (e.g., expA reps/prism f8 unchanged).
- **H=1 sanity:** `-sender_cc_algo mnscc -mnscc_h 1` goodput ≈ `-sender_cc_algo nscc` on the same workload
  (median of one = the latest delay → NSCC). Reported in the README.
- **perf_figs selftest** extended so the mechanism-median path is exercised (synthetic MNSCC median CSV →
  signal line renders without error); existing aggregation selftest unchanged.
- Figures committed with `git add -f`; `data/` gitignored; deterministic seeds {13–17}; one-command repro;
  pinned commit. Built **subagent-driven** with two-stage review per task + a final whole-branch review.

---

## Out of scope (YAGNI)

- **MSwift** (Swift-based; needs a Swift `UecSrc` port; different base CCA) — optional future work.
- Time-based freshness eviction of the median window (the paper's "ignore signals older than 1–2 RTTs"
  adversarial-corner fix) — v1 uses the last-H-ACKs window, faithful to the paper's H-based description.
- Median framework on other signals (ECN-only, INT) — paper applies it to NSCC's delay; we do the same.
- H-sensitivity sweep as a committed figure — the `-mnscc_h` flag enables it on demand, but the headline
  uses the Nyquist default; a sweep can be a later add if wanted.
