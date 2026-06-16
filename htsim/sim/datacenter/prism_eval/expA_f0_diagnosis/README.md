# Experiment A — f0 (symmetric) penalty diagnosis (delay-driven regime)

**Why.** The delay-driven Exp A result has one honest weak spot: at **failed=0 (symmetric
fabric)** PRISM is the *worst* arm (goodput 869 vs REPS+NSCC 997 / STrack 912 / OPS 906; avg-FCT
945 vs 737 µs). `../expA_tspray_tuning` already showed the spread tolerance `T_spray` **cannot**
fix it (f0 is insensitive to T_spray; lowering it makes f0 *worse*). This group localizes the
root cause with **read-only logs — no controller change** — and reports it straight, including
where an early hypothesis was **refuted by the data** and corrected.

## Setup
Delay-driven regime (`EXTRA_ARGS="-disable_trim"`, END=8), same 128-node many2many 64→16 pod0
2 MB workload as `expA_delaydriven` (byte-identical `m2m.cm`).
- **f0 mechanism slice (seed 13):** PRISM and REPS+NSCC each with `PRISM_PATHRTT` (per-ACK cwnd
  *and* per-path RTT); PRISM also with `PRISM_EPOCH` (per-epoch region/cut).
- **kappa sweep:** PRISM `-prism_kappa ∈ {0.25, 0.5, 1.0}` × failed {0, 8} × seeds {13..17}
  (epoch = `kappa · base_rtt`; 1.0 = default, reused from `../expA_delaydriven/data`, as are the
  REPS+NSCC reference and the failed=8 PRISM/REPS mechanism logs used as the f8 contrast).

## Figures
- `figs/figD1_undergrowth` — (a) cwnd(t) PRISM vs NSCC @f0 with each arm's mean window; (b) PRISM
  region share f0 vs f8 (INCREASE / HOLD / DECREASE).
- `figs/figD2_kappa` — goodput and avg-FCT vs kappa, f0 (penalty) and f8 (win), with NSCC refs.
- `figs/figD3_stability` — per-path mean q, 1st vs 2nd half of the steady window (REPS+NSCC
  control). f0 points fall below y=x (spread drains → transient); f8 holds near/above it (persists).

## Result

### Proximate cause (solid): under-growth, not over-cutting
PRISM's window can be low for two opposite reasons — it over-CUTS, or it under-GROWS. The fair
per-ACK cwnd-decrease count (same method both arms) settles it:

| metric @f0 seed13 | PRISM | REPS+NSCC |
|---|---|---|
| goodput / avg-FCT | 887 Gbps / 902 µs | 1018 Gbps / 705 µs |
| per-ACK cwnd-decreases | **488** (1.94% of acks) | **772** (3.74%) |
| mean cwnd | **123 KB** | **136 KB** (ratio 0.91) |

PRISM **cuts fewer times** than NSCC yet runs a **lower window** (ratio 0.91 ≈ the 0.87 goodput
ratio). So the deficit is on the **increase/recovery** side. **Mechanism:** PRISM gates *all*
window growth (proportional_increase + `fulfill_adjustment`'s periodic `_eta`) to the INCREASE
region only (`uec.cpp:1513`, `1539–1546`, `1580–1584`); at f0 it is **outside INCREASE 59% of
epochs** (HOLD 37% + DECREASE 22%). NSCC has no such gate — it grows on essentially every ACK and
reclaims the bandwidth.

### Why PRISM HOLDs so much at f0 — the signal, not the action
The decision rule itself is sound: `C_cc < T_cc` (best path has headroom) **and** `C_spray ≥
T_spray` (paths differ) ⇒ HOLD and let REPS rebalance — that is exactly the right response to
genuinely reroutable congestion, and it is *what wins at f8*. So the question is why HOLD fires at
f0, where it does not pay off. The answer is in **how the spread signal is measured**, not in the
action.

- **The f0 cross-path spread is REAL** (refuting an earlier "it's just per-sample jitter" guess):
  the spread of per-path *mean* q over the steady window is **24 µs** (PRISM) / **26 µs** (REPS
  control) — comparable in kind to f8's 44–54 µs. There genuinely are paths with different mean
  queuing. So `C_spray` is not hallucinating spread.
- **But the f0 spread is a self-resolving STARTUP TRANSIENT, not a persistent structure.** In the
  clean REPS+NSCC control (healthy window), per-path mean q falls **62.9 → 5.7 µs** and the
  cross-path spread **31.2 → 8.3 µs** from the 1st to the 2nd half of the steady window: the incast
  builds large, uneven queues early, then drains to uniformly-low q. By steady state there is **no
  persistent localized congestion to durably reroute around** (figD3, left; rank-stability of the
  per-path ordering is weak, +0.30, and the early "best" paths do not stay best).
- **At f8 the spread PERSISTS** (REPS control: q 18.6 → 17.3 µs, spread 32.1 → 46.8 µs; figD3,
  right; rank-stability +0.79, the clean paths stay clean 100%) — it is structural (degraded vs
  healthy aggregation switches), so HOLD lets REPS durably move traffic onto a real clean path.

**So the same mechanism that wins at f8 loses at f0.** `C_spray` (a per-epoch `max−min`) measures
the *magnitude* of cross-path spread but is **blind to whether that spread persists**. At f0 it
fires HOLD on the startup incast transient — freezing window growth while waiting for a reroute
that buys nothing because the spread is draining away on its own — and the growth-gating then costs
throughput. At f8 the spread is the persistent, reroutable kind, so holding pays off. The f0
penalty and the f8 win are two faces of one mechanism.

### kappa (epoch length) is a minor lever, not the cause

| cell | REPS+NSCC | PRISM k=1.0 (def) | PRISM k=0.5 | PRISM k=0.25 |
|---|---|---|---|---|
| f0 | 996.7 / 737 | 868.6 / 945 | **884.1 / 830** | 879.6 / 881 |
| f8 | 430.8 / 1694 | 504.2 / 1518 | 515.8 / 1520 | 508.7 / 1536 |
*(goodput Gbps / avg-FCT µs, 5-seed mean)*

Shrinking the epoch 1.0→0.5 improves f0 **FCT ~12%** (945→830 µs) and goodput ~2%, and is
**do-no-harm on f8** (+2%). But the best kappa still leaves f0 **~11% below NSCC** — re-deciding
more often does not change *which* region PRISM picks (it still HOLDs on the same early spread).

## Honest verdict
- **Root cause:** the f0 penalty is **under-growth** (region-gated window growth), driven by HOLD
  firing on a startup-transient cross-path spread that `C_spray` cannot tell apart from the
  persistent, reroutable spread it detects at f8.
- **It is a signal problem, not an action problem** (this corrects the first writeup, which wrongly
  called the f0 HOLD a "misclassification of jitter / no real spread"): the spread is real, the
  HOLD rule is sound, but `C_spray` measures spread magnitude without persistence.
- **Two knobs ruled out as the fix:** `T_spray` (`../expA_tspray_tuning`) and `kappa` (this group).
- **Fix direction tried — persistence-aware spread — and REFUTED (intervention, then removed).** The
  natural fix was to make the spread signal persistence-aware so a decaying startup transient stops
  triggering HOLD while structural spread still does, **without changing the action rule** (HOLD on
  low-floor+high-spread is correct — it is the source of the f8 win). We prototyped it as a
  flag-gated (default OFF, byte-identical when off), explicitly *not-shipped* per-path EWMA of the
  per-path queuing delay (`C_cc=min`, `C_spray=max−min` over per-path EWMAs) — O(paths) state, which
  violates PRISM's O(1) tenet, so it was only ever a verification probe. **Result: it backfired.**
  Over a pre-registered α sweep, PRISM-persist was *worse than PRISM-default at every failure level*;
  at the selected α\*=0.5, f0 fell **−18%** (712 vs 869, the opposite of recovery) and f4 fell
  **−15%** (below the do-no-harm bar). **Mechanism:** the EWMA *did* drop the spread as intended
  (median `C_spray` 14.6→11.1 µs, HOLD 37→26.5%), but EWMA-smoothing also **lagged the floor `C_cc`
  high** (5.6→6.6 µs), pushing the freed-up epochs into DECREASE (21.9→29.5%, *more* cutting) →
  worse under-growth, dominating. **Sharpened lesson:** a persistence signal must keep `C_cc`
  *instantaneous* and smooth *only* the spread; smoothing the floor makes PRISM cut on stale queue.
  That cleaner design is untried and, being per-path, is O(paths) regardless — so we **kept PRISM
  O(1) and removed the prototype.** The f0 symmetric penalty therefore stands as an
  honestly-characterized cost of PRISM's O(1) decomposition, not a defect we patched over.
  (Prototype controller code reverted; the eval lives on only as this summary + `../NARRATIVE.md`.)

## Honest caveats
- The proximate cause (under-growth: cut counts, region split, cwnd) and the f8-persistent /
  f0-transient contrast are robust. The **transient-vs-persistent characterization leads with the
  REPS+NSCC control** (healthy window, 39–49 flows qualify); the **PRISM arm's own stability sample
  is thin** (14 flows — PRISM under-grows, so it logs fewer per-path samples), consistent in
  direction but under-powered. Mechanism numbers are the seed-13 slice; perf/kappa are 5-seed means.
- The half-window split still leaves part of the incast transient in the "1st half"; it is a
  steady-window decomposition, not a clean stationary measurement. The conclusion (f0 spread does
  not persist into steady state; f8's does) is what the control + figD3 support.

## Reproduce
```
bash prism_eval/expA_f0_diagnosis/repro.sh   # from sim/datacenter; reuses expA_delaydriven/data
python3 prism_eval/expA_f0_diagnosis/diagnose.py --selftest
```
Requires `../expA_delaydriven` to have been run (reused read-only). Pinned commit; deterministic
`-seed`; raw data under `data/` gitignored; figures committed with `git add -f`.
