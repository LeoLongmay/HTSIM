# expB_oversub_asym — Asymmetric Win Under Oversubscription

## 1. What this tests

**Question:** Does PRISM's delay-driven asymmetric win — established in `../expA_delaydriven/`
(1:1 non-blocking fabric, +19–22% goodput over both REPS+NSCC and STrack at failed ≥ 4) —
extend to an oversubscribed core?

This experiment adds the **asymmetry axis** (varying `-failed`) on top of the oversubscribed
topologies from `../expB_oversub/` (which tested failed=0 only). The two oversub ratios are:
- **4:1** (`fat_tree_128_4os`): a moderately-oversubscribed core — the main result.
- **8:1** (`fat_tree_128_8os`): a heavily-oversubscribed core — a saturation boundary check.

The controller is **unchanged** from `expA_delaydriven`; only the topology and the `-failed`
sweep are new. This is Axis-2 (oversub) ✕ Axis-1 (asymmetry) in the PRISM evaluation.
See `../NARRATIVE.md` and `../TARGET_REGIME.md`.

---

## 2. Setup

| Parameter | Value |
|---|---|
| Topologies | `fat_tree_128_4os.topo` (4:1), `fat_tree_128_8os.topo` (8:1) — 128 nodes, podsize 16 |
| Asymmetry sweep | 4:1: `-failed {0, 4, 8, 12}`; 8:1: `-failed {0, 2, 4, 8}` |
| Workload | `many2many.py 64 16 pairs 2000000 128 16` — 64 senders → 16 pod0 receivers, 2 MB each |
| Arms | OPS+NSCC, REPS+NSCC, STrack, PRISM |
| Seeds | {13, 14, 15, 16, 17} |
| `PATHS` | 8 |
| `EXTRA_ARGS` | `-disable_trim` (delay-driven regime; 5× BDP buffers) |
| `EXP_END` | 8 ms (4:1 all cr = 1.00); 12 ms used for 8:1 (still saturated, see below) |

### Critical: `-failed N` is nonlinear on oversub topologies

`-failed N` does **not** degrade N core links on these topologies. The failure index interacts
with the reduced core radix. Total core→agg links: 1:1 = 128, **4:1 = 32, 8:1 = 16**.

Actual degraded core links (from the degraded-link report in each run):

| Topo | `-failed` | Core links degraded | Fraction of core |
|---|---|---|---|
| 4:1 (32 total) | 0 | 0 | 0% |
| 4:1 (32 total) | 4 | 1 | 3% |
| 4:1 (32 total) | 8 | 2 | 6% |
| 4:1 (32 total) | 12 | 3 | 9% |
| 8:1 (16 total) | 0 | 0 | 0% |
| 8:1 (16 total) | 2 | 3 | 19% |
| 8:1 (16 total) | 4 | 7 | 44% |
| 8:1 (16 total) | 8 | 15 | 94% |

At 4:1, `-failed {4, 8, 12}` degrades only 1–3 of 32 core links (3–9%) — a **sparse
asymmetry** comparable to expA's 8/128 = 6%. At 8:1, `-failed 8` degrades 15 of 16 links —
near-total core loss.

**One-command repro** (from `sim/datacenter/`):

```
bash prism_eval/expB_oversub_asym/repro.sh
```

---

## 3. Results — 4:1 oversub (the win)

**32 core links; all cells cr = 1.00.**

See `figs/figBa_4os_main`.

### Goodput (Gbps) / avg-FCT (µs)

| Arm | -failed 0 (0 deg) | -failed 4 (1 deg) | -failed 8 (2 deg) | -failed 12 (3 deg) |
|---|---|---|---|---|
| OPS+NSCC | 326.2 / 2430 | 130.3 / 4497 | 103.6 / 7067 | 93.6 / 8428 |
| REPS+NSCC | 343.5 / 2334 | 180.7 / 3412 | 138.4 / 4970 | 116.4 / 6450 |
| STrack | 341.3 / 2288 | 175.6 / 3498 | 138.5 / 4994 | 116.2 / 6429 |
| PRISM | 339.2 / 2625 | 205.4 / 3109 | 182.5 / 3755 | 145.9 / 4843 |

### PRISM vs REPS+NSCC deltas

| `-failed` | Degraded links | Goodput delta | Avg-FCT delta |
|---|---|---|---|
| 0 | 0/32 | −1.3% | +12.5% (known symmetric cost) |
| 4 | 1/32 | **+13.7%** | **−8.9%** |
| 8 | 2/32 | **+31.9%** | **−24.4%** |
| 12 | 3/32 | **+25.3%** | **−24.9%** |

### PRISM vs STrack deltas

| `-failed` | Degraded links | Goodput delta | Avg-FCT delta |
|---|---|---|---|
| 0 | 0/32 | −0.6% | +14.7% (known symmetric cost) |
| 4 | 1/32 | **+17.0%** | **−11.1%** |
| 8 | 2/32 | **+31.8%** | **−24.8%** |
| 12 | 3/32 | **+25.6%** | **−24.7%** |

**Pattern:** failed=0 shows the known small symmetric penalty (PRISM holds spray when there is
no reroutable benefit — identical to expA f0). Once even a single core link is degraded
(failed=4, 1 of 32 = 3%), PRISM leads both REPS+NSCC and STrack by double digits on both
metrics. This is **expA's exact asymmetric pattern reproduced on a 4:1 oversubscribed core**.

**STrack does not beat REPS+NSCC** (they overlap throughout: e.g. f8 138.5 vs 138.4 Gbps,
f12 116.2 vs 116.4 Gbps) — the win comes from decomposing the signal (floor vs average),
not from coupling CC and load balancing. Same conclusion as expA.

---

## 4. Results — 8:1 oversub (saturation boundary)

**16 core links; EXP_END = 12 ms.**

See `figs/figBa_8os_main`.

### Goodput (Gbps) / completion ratio

| Arm | -failed 0 (0 deg) | -failed 2 (3 deg) | -failed 4 (7 deg) | -failed 8 (15 deg) |
|---|---|---|---|---|
| OPS+NSCC | 178.6 / cr 1.00 | ~0.7 / cr 0.01 | ~0.7 / cr 0.01 | ~0.7 / cr 0.01 |
| REPS+NSCC | 185.4 / cr 1.00 | 0 / cr 0.00 | 0.3 / cr 0.00 | 0 / cr 0.00 |
| STrack | 184.9 / cr 1.00 | 0 / cr 0.00 | 0 / cr 0.00 | 0 / cr 0.00 |
| PRISM | 183.5 / cr 1.00 | 0 / cr 0.00 | 0.3 / cr 0.00 | 0.3 / cr 0.00 |

At failed=0 all four arms tie (~183–185 Gbps, cr = 1.00). At **failed ≥ 2** (3 or more of 16
core links degraded), **every arm collapses to completion ratio ≈ 0** — including OPS and
REPS+NSCC. Even at EXP_END = 12 ms the fabric does not drain. This is not a PRISM loss; the
fabric is saturated regardless of controller. With only 16 core links, losing 3 or more is
sufficient to make the workload insoluble at this timescale.

This bounds the extension: the asymmetric win holds while the core retains enough residual
capacity to reroute onto (4:1, 3–9% link loss); it disappears into pure overload when it
does not (8:1 + any loss).

---

## 5. Mechanism — 4:1, failed=8 (the win point)

**Seed 13, cr = 1.00.** See `figs/figBa_mech`.

| Arm | Per-ACK cwnd-decrease events |
|---|---|
| REPS+NSCC | 3885 |
| STrack | 4133 |
| PRISM | **1046** |

**Floor-MD fraction (PRISM):** floor-driven epoch-MDs / total cwnd-decreases = 137 / 1046 = **0.131**.

PRISM makes **3.7× fewer cwnd decreases** than REPS+NSCC (and 3.9× fewer than STrack). The
win is from **restraint**: PRISM detects that the degraded paths carry a high floor signal
while the remaining 30/32 core paths are still clear, holds spray (HOLD on the reroutable
spread), and lets htsim's spray naturally route around the 2 degraded links. REPS+NSCC and
STrack both see an elevated *average* delay — averaging the 2 slow paths into the 30 clean
ones — and over-decrease.

The floor-MD fraction is **low here (0.131)**, unlike expA's 4 MB mechanism run (0.374) or
expB_oversub's 8:1 (0.957). At 4:1 with only 2 of 32 links degraded, the floor rarely
crosses target — the win comes primarily from **not over-cutting** (fewer decreases total),
not from floor-driven cutting. The decomposition lever is the same as expA; the balance
between floor-cut and hold shifts with the density of the asymmetry.

---

## 6. Verdict

**The asymmetric win extends to a moderately-oversubscribed (4:1) core.**

- At 4:1, degrading as few as 1 of 32 core links (3%) triggers PRISM's asymmetric advantage:
  **+14–32% goodput** and **9–25% lower avg-FCT** over both REPS+NSCC and STrack at
  failed {4, 8, 12}. The failed=0 symmetric penalty (−1.3% / +12.5% FCT vs REPS+NSCC) is
  the expected and unchanged cost.

- At 8:1, all arms collapse at failed ≥ 2. This is a fabric-saturation boundary, not a
  controller failure. It bounds the domain of the extension: **reroutable headroom must
  exist** for the decomposition to help.

- The mechanism is identical to expA: PRISM makes ~3.7× fewer cuts because it reads the
  floor rather than the average, avoids penalizing traffic on clean paths, and lets spray
  reroute naturally. The result is lower FCT alongside higher goodput — no throughput/latency
  trade-off.

**This strengthens the thesis.** PRISM's asymmetric advantage is not an artifact of a
non-blocking fabric; it generalizes to a realistic moderately-oversubscribed (4:1) datacenter
core, as long as reroutable capacity remains. The 8:1 saturation boundary makes the scope
precise.

**Caveats:**
- The `-failed` knob is nonlinear on oversub topologies (see Section 2). The 4:1 asymmetry
  tested here is sparse (1–3/32 links, 3–9%), chosen to match expA's comparable fraction.
- 8:1 saturation may eventually drain at a much larger time horizon, but is overload-dominated
  at EXP_END = 12 ms across all controllers.
- 128-node development-scale topology; delay-driven regime only (`-disable_trim`). Trimming-regime
  oversub-asym behavior is deferred.
- Completion ratio is 1.00 for all 4:1 cells; FCT comparisons are unconfounded.

Cross-links: `../NARRATIVE.md` | `../TARGET_REGIME.md` | `../expA_delaydriven/` (1:1 win) |
`../expB_oversub/` (symmetric oversub baseline, failed=0 columns).
