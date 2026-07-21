# expB_oversub_asym_1024 — 1024-node 4:1 oversub (split figures), scale contrast vs expB 128

## 1. What this group shows

The three split performance figures (`figs/figBb_4os_{goodput,avg_fct,p99_fct}`) for the **1024-node
4:1-oversubscribed asymmetric** fabric, in the same style as `../expB_oversub_asym`'s 128-node
`figBa_4os_*`. The contrast is **scale**: at 128 the 4:1 knob is degenerate (the 32-link core means
`-failed` barely degrades anything → PRISM ≈ tied), whereas at 1024 the 256-link core makes 4:1 a
**real PRISM win window**.

This group **reuses** the `expD2_4os` data already produced by `../expD_scale1024/repro.sh` — it runs
**no sweep**. `bash repro.sh` verifies the data exists and renders.

## 2. Setup (data reused from expD2_4os)

| Parameter | Value |
|---|---|
| Topology | `fat_tree_1024_4os_100g.topo` (3-tier, 1024-node, 4:1 oversub at ToR↔Agg: Radix_Down 8 / Radix_Up 2; 100 G) |
| Workload | many2many 256→64 pod0, 2 MB (4:1 fan-in; the 1024-scale of expB's 64→16) |
| Failed-link sweep | `{0,1,2,3,4}` → actual degraded core→agg links `{0,1,2,4,6}` (of 256) |
| Arms | OPS+NSCC, REPS+NSCC, REPS+Swift, REPS+MSwift, REPS+MNSCC, STrack, **Prism** (7) |
| Seeds | 13–17 (5); delay-driven (`-disable_trim`), PATHS=8 |

## 3. Why the failed axis stops at 4

`{0,1,2,3,4}` is the **full cr=1 win window**, not an arbitrary cap. The 4:1-oversubscribed core has
little spare capacity, and `-failed` degrades core→agg links on pod0's ingress path (where the 256→64
fan-in concentrates), so a few failures bite hard. A probe (REPS, seed 13) shows saturation just
beyond f4:

| requested failed | degraded core links (/256) | completion rate | goodput |
|---|---|---|---|
| 0–4 | 0 / 1 / 2 / 4 / 6 | 1.00 | 1.33 → 0.59 Tbps |
| 6 | 12 | 0.90 | 0.46 Tbps |
| 8 | 20 | 0.55 | 0.28 Tbps |
| 12 | 36 | 0.05 | collapse |

Beyond f4 the core saturates and all arms collapse (cr<1) — uninformative, the same phenomenon
`../expB_oversub_asym` notes for its 8:1 case.

## 4. Results (5-seed mean)

**1024 4:1 is a real PRISM win window:** PRISM leads all three metrics from f2 on, and the goodput
gap over REPS+NSCC grows monotonically with failures.

| goodput (Tbps) | f0 | f1 | f2 | f3 | f4 |
|---|---|---|---|---|---|
| OPS+NSCC | 1.23 | 0.71 | 0.60 | 0.49 | 0.38 |
| REPS+NSCC | 1.33 | 0.92 | 0.80 | 0.68 | 0.59 |
| REPS+MNSCC | 1.34 | 0.97 | 0.86 | 0.72 | 0.62 |
| STrack | 1.34 | 0.88 | 0.78 | 0.67 | 0.58 |
| **Prism** | 1.29 | 0.95 | **0.88** | **0.84** | **0.77** |
| Prism vs REPS+NSCC | −3 % | +4 % | +10 % | +24 % | **+31 %** |

| avg-FCT (ms) | f0 | f2 | f4 | | P99-FCT (ms) | f0 | f2 | f4 |
|---|---|---|---|---|---|---|---|---|
| REPS+NSCC | 2.45 | 2.85 | 4.34 | | REPS+NSCC | 3.03 | 5.00 | 6.77 |
| **Prism** | 2.74 | **2.79** | **3.43** | | **Prism** | 3.11 | **4.56** | **5.18** |

PRISM carries the usual small symmetric cost at f0 (−3 % goodput, slightly higher FCT); from f2 on it
is the fastest and highest-goodput arm, reaching **+31 % goodput** and **~20 % lower FCT** than the
UEC reference at f4. The larger 1024 core retains enough capacity for spread-aware rerouting to pay
off — which the degenerate 128 4:1 core does not (`../expB_oversub_asym`).

## 5. Caveat (honest)

**OPS+NSCC** (oblivious, no rerouting) does not fully drain at f3 / f4 — completion rate **0.95 /
0.74** (some flows unfinished at END = 8 ms). Its goodput/FCT there are computed over completed flows
only and are thus a **lower bound** (OPS is even worse than the table shows); it is the worst arm
regardless. **Every other arm — including PRISM and all REPS arms — is cr = 1.00 at all five failed
levels.** The figures plot the requested `-failed` on x without a per-bar cr annotation (shared
renderer); this caveat states the OPS completion rates explicitly.
