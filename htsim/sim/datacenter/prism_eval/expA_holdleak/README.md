# expA_holdleak — HOLD-leak prototype (NEGATIVE)

## 1. What this tests

This group tests a flag-gated prototype (`-prism_hold_leak`, default `0`) that lets
PRISM's window grow a leak-scaled fraction of the proportional-AI signal **during HOLD**
epochs, rather than freezing the window entirely as today's PRISM does.

**Default OFF = today's PRISM, byte-identical.**  Setting `leak=0` reproduces the
baseline PRISM result exactly; the flag is a strict extension with a scalar O(1) cost
(one multiplication per epoch, no state added).

**Motivation.**  In symmetric (f0) traffic PRISM frequently enters HOLD because all paths
look similar; the window freezes below the REPS+NSCC level and goodput suffers.  The
question: can a small leak during HOLD let f0 grow enough to close that gap without
eroding the f8/f12 asymmetric win?

**Why this is the only remaining O(1) lever.**  Four prior O(1) attempts have already
been closed:

- `T_spray` tuning (`../expA_tspray_tuning/`) — negative.
- `kappa` sweep (`../expA_f0_diagnosis/`) — negative (the cost is structural, not
  kappa-driven).
- Persistence-EWMA — refuted; requires O(paths) state.
- Avg-delay discriminator (`../probe_avgdisc/`) — refuted; the read-only probe showed
  that average delay does not separate f0 HOLD epochs from f8 HOLD epochs.

HOLD-leak is therefore the last cheap fix examined before concluding that the symmetric
cost is intrinsic to the O(1) design.

**This is a blunt tradeoff dial.**  `leak` cannot distinguish a transient spread
(symmetric traffic, no real bad paths) from a structural spread (asymmetric traffic,
genuinely congested paths).  That discrimination requires O(paths) rank-persistence state.

---

## 2. Setup

| Parameter | Value |
|-----------|-------|
| Flag | `-prism_hold_leak ∈ {0, 0.1, 0.25, 0.5, 0.75, 1.0}` |
| Failed links | `{0, 2, 4, 8, 12}` |
| Seeds | `{13, 14, 15, 16, 17}` |
| References | PRISM (leak=0), REPS+NSCC |
| Mode | delay-driven (`-disable_trim`) |
| Workload | 2 MB many2many, 64→16 hosts |
| Paths | `PATHS=8` |
| Sim duration | `EXP_END=8` ms |
| Fabric | all cells `cr=1.0`; 128 `FLOW_EVENT` lines |

One-command repro:

```
bash repro.sh
```

Raw per-seed data is gitignored.  The figure is force-added (`git add -f`).

---

## 3. Pre-registered criteria

**Admissible** (do-no-harm): for every `leak > 0`, f8 AND f12 goodput must each remain
within `max(3%, 1 SD)` of the `leak=0` baseline.

- leak=0 baseline (mean ± pop-SD over 5 seeds): f8 = 504 Gbps (SD 37), f12 = 434 Gbps (SD 13).
- Do-no-harm thresholds `max(3%, 1 SD)`: f8 ≥ 468 Gbps (1 SD = 37 dominates 3% = 15), f12 ≥ 421 Gbps
  (1 SD = 13 ≈ 3% = 13).

**Positive** (meaningful f0 recovery): at least one admissible leak value must recover
≥ 1/3 of the f0 goodput gap.

- leak=0 PRISM f0 = 869 Gbps; REPS+NSCC f0 = 997 Gbps; gap = 128 Gbps.
- Positive threshold: f0 ≥ 911 Gbps.

---

## 4. Results

See figure `figs/figHL_holdleak` (f0 flat well below the REPS reference across all leak
values; f8 and f12 declining monotonically with leak).

**Reference baselines (leak=0)**

| Metric | PRISM (leak=0) | REPS+NSCC |
|--------|---------------|-----------|
| f0 goodput | 869 Gbps | 997 Gbps |
| f8 goodput | 504 Gbps (SD 37) | — |
| f12 goodput | 434 Gbps (SD 13) | — |

**Leak sweep**

| leak | f0 (Gbps) | f0 recovery | f8 (Gbps) | f12 (Gbps) | do-no-harm |
|------|-----------|-------------|-----------|------------|------------|
| 0.0  | 869       | baseline    | 504       | 434        | OK (baseline) |
| 0.1  | 876       | 6%          | 524       | 425        | OK |
| 0.25 | 877       | 6%          | 489       | 417        | VIOLATED (f12 417 < 421) |
| 0.5  | 873       | 4%          | 486       | 405        | VIOLATED (f12 405 < 421) |
| 0.75 | 870       | 1%          | 447       | 388        | VIOLATED (f8 447 < 468; f12 388 < 421) |
| 1.0  | 865       | −3%         | 450       | 382        | VIOLATED (f8 450 < 468; f12 382 < 421) |

**VERDICT: NEGATIVE** — no leak value both recovers ≥ 1/3 of the f0 gap AND keeps f8/f12
within the do-no-harm band.

---

## 5. Verdict: NEGATIVE

This experiment fails on both counts, and the failure pattern is informative.

**Count 1 — f0 recovery is negligible and non-monotonic.**  Maximum recovery is ~6%
(f0 869 → 877 at leak=0.1 and leak=0.25), far below the 33% bar (target: f0 ≥ 911 Gbps).
The recovery is also non-monotonic: at leak=1.0 — HOLD growing at the full proportional-AI
rate, approximately removing the spread gate — f0 is actually *worse* (865 Gbps, −3%)
than frozen HOLD (869 Gbps).  Un-freezing HOLD does not recover f0.

**Count 2 — the asymmetric win erodes monotonically with leak.**  f8 falls 524 → 450,
f12 falls 425 → 382 as leak rises from 0.1 to 1.0.  f12 breaks do-no-harm at
leak=0.25, f8 by leak=0.75.  Only leak=0.1 stays admissible, and it buys just 6% of
the gap — less than one-fifth of the 33% bar.

**There is no useful tradeoff here.**  Even the single admissible setting (leak=0.1)
does not come close to the positive threshold.

**Mechanism — why even leak=1.0 fails to recover f0.**  Two compounding reasons:

1. The leak omits `fast_increase` and `_eta`, so it grows the window more slowly than
   REPS+NSCC's full increase machinery.  Equality of growth is never reached.
2. Growing the window during HOLD raises queue occupancy, which pushes more subsequent
   epochs into DECREASE (floor-driven cuts).  The extra growth is partly self-cancelling:
   the window that grows during HOLD is cut back more aggressively afterward.

"Frozen HOLD" is therefore not the primary cause of the f0 deficit.  Simply un-freezing
does not fix it.

---

## 6. Disposition

**The prototype controller change was REVERTED** (user decision, 2026-06-17). After this
negative result, `git checkout` restored `uec.h` / `uec.cpp` / `main_uec.cpp` / `main_uec_sf.cpp`
to the committed, byte-identical O(1) PRISM (reverted f0 seed13 goodput = 886.9632854367, exact
match), and the `-prism_hold_leak` flag no longer exists. This group is kept as the **recorded
negative**: its `figs/`, README, and analyzer stand on their own. **To reproduce**, first re-apply
the controller patch in `docs/superpowers/plans/2026-06-17-prism-holdleak.md` (Task 1), rebuild
`htsim_uec`, then run `repro.sh` (which passes `-prism_hold_leak`). PRISM ships O(1) with HOLD frozen.

**The f0 symmetric cost is now thoroughly characterized.**  Five O(1) levers have been
attempted and all fail to recover f0 without breaking the asymmetric win or exceeding
O(1) complexity:

1. T_spray tuning — `../expA_tspray_tuning/`
2. kappa sweep — `../expA_f0_diagnosis/`
3. Persistence-EWMA — refuted (O(paths))
4. Avg-delay discriminator — `../probe_avgdisc/` (avg does not separate f0 from f8 HOLD epochs)
5. HOLD-leak — this experiment (fails both counts, non-monotonic, mechanism above)

The symmetric cost is intrinsic to PRISM's O(1) decomposition.  The only true
discriminator — rank-persistence across epochs — is O(paths) by nature.  This cost
is a known, now-thoroughly-probed property of the design.

**Cross-links:**
- `../expA_f0_diagnosis/` — kappa sweep and f0 under-growth diagnosis
- `../probe_avgdisc/` — avg-delay discriminator probe (refuted)
- `../NARRATIVE.md` — full evaluation narrative and motivation arc
- `../TARGET_REGIME.md` — target fabric regime and scope of PRISM's claims
