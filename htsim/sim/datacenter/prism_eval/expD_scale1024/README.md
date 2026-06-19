# Experiment D — Scale Verification (1024 nodes)

## 1. What this tests

**Question:** Do the two PRISM headline wins — `expA_delaydriven` (1:1 asymmetric, delay-driven,
+19–22% goodput over both REPS+NSCC and STrack at failed ≥ 4) and `expB_oversub_asym` (4:1 win
+14–32%; 8:1 hard-saturation boundary) — survive on an 8× larger fabric (1024 nodes), holding
the 100 G / 14 µs calibration fixed?

**Skeptic's hypothesis:** a bigger fabric has more spare paths and could dilute a
hotspot-plus-asymmetry advantage — more reroutable headroom means less pressure on the floor
signal.

This is a **verification experiment, not a new mechanism.** The PRISM controller is byte-identical
to the committed O(1) decomposition evaluated at 128 nodes. Nothing in the controller was retuned
for scale. Any result difference is therefore a fabric-scale effect, not a controller change.

---

## 2. Setup

| Parameter | Value |
|---|---|
| D1 (1:1) topology | `fat_tree_1024.topo` — 100 G, 1:1 non-blocking, podsize 64 |
| D2 (4:1) topology | `fat_tree_1024_4os_100g.topo` — **generated** by `repro.sh` from the stock 200 G `fat_tree_1024_4os.topo` via `sed 200->100`, to hold the 100 G / 14 µs calibration (the stock 4:1 file is 200 G and would break apples-to-apples comparison) |
| D2 (8:1) topology | `fat_tree_1024_8os.topo` — stock, already 100 G |
| Arms | OPS+NSCC, REPS+NSCC, REPS+Swift, REPS+MSwift, REPS+MNSCC, STrack, Prism |
| Seeds | {13, 14, 15, 16, 17} |
| `PATHS` | 8 |
| `EXTRA_ARGS` | `-disable_trim` (delay-driven regime; 5× BDP buffers) |
| `EXP_END` | 8 ms (D1 and 4:1 sweeps); 12 ms (8:1 sweeps — saturation horizon) |
| `NODES` | 1024 |
| Workload | `many2many.py 256 64 pairs 2000000 1024 64` — 256 senders (outside pod0) → 64 pod0 receivers, 2 MB each, round-robin pairs (mechanism runs use 4 MB) |

### Calibration confirmation

At runtime, **100 Gbps links** and `_target_Qdelay = 14022720 ps` (14 µs) — byte-identical to
the 128-node experiments. The 14 µs target is one network RTT at this link rate; any scale effect
is in the topology, not in the controller calibration.

### Goodput magnitude note

Goodput is reported as a window-free aggregate over all 256 flows. With 256 simultaneous 2 MB
transfers, peak aggregate goodput runs into the thousands of Gbps — the same metric and semantics
as `expA_delaydriven` (which aggregated 64 flows), just 4× the flow count. The multi-thousand-Gbps
numbers are not surprising; they reflect aggregate fabric utilisation, not per-flow rates.

---

## 3. `-failed` calibration

### D1 (1:1): linear degradation

`-failed N` on the 1:1 fat-tree degrades exactly N core uplinks. Pod0 has 8 aggregation switches
with 8 uplinks each = 64 total pod0 core-ingress uplinks.

| `-failed` | Core uplinks degraded | Pod0 ingress choke |
|---|---|---|
| 0 | 0 | 0% |
| 8 | 8 | 12.5% |
| 16 | 16 | 25.0% |
| 24 | 24 | 37.5% |
| 32 | 32 | 50.0% |
| 48 | 48 | 75.0% |

This matches the 128-node analog precisely: failed {0, 2, 4, 6, 8, 12} were {0, 12.5, 25, 37.5,
50, 75}% of pod0's 16 uplinks. The sweep points are chosen to replicate those fractions at 1024
scale.

### D2 (oversub): nonlinear degradation

`-failed N` is **nonlinear** on oversubscribed topologies — the failure index interacts with the
reduced core radix. Total agg→core links: 4:1-100G (256 total), 8:1 (128 total).

Actual degraded core links (from the degraded-link report in each run):

| Topo | `-failed` | Core links degraded |
|---|---|---|
| 8:1 (128 total) | 8 | 14 |
| 8:1 (128 total) | 16 | 30 |
| 8:1 (128 total) | 32 | 62 |
| 8:1 (128 total) | 48 | 94 |
| 4:1-100G (256 total) | 8 | 20 |
| 4:1-100G (256 total) | 16 | 52 |
| 4:1-100G (256 total) | 32 | 116 |
| 4:1-100G (256 total) | 48 | 180 |

**Sweep windows chosen:** 4:1 sweep `-failed {0,1,2,3,4}` (the cr = 1.00 win window — all Prism
cells complete cleanly); 8:1 sweep `-failed {0,1,2,4}` (saturation boundary — probing where
averaging arms drop). The D2 sweeps stay in the low-failed, cr-viable region; the high-failed
entries above are reported for calibration only.

---

## 4. D1 results (1:1 non-blocking)

**All cells cr = 1.00. Goodput in Gbps; avg-FCT and P99-FCT in ms.**

See `figs/figD1_goodput`, `figs/figD1_avg_fct`, `figs/figD1_p99_fct`.

### Goodput / avg-FCT / P99-FCT

| Arm | f0 | f8 | f16 | f24 | f32 | f48 |
|---|---|---|---|---|---|---|
| OPS+NSCC | 3459.1 / 0.768 / 1.116 | 1489.8 / 1.421 / 2.647 | 1316.0 / 1.789 / 3.041 | 1244.2 / 2.075 / 3.228 | 1197.3 / 2.239 / 3.357 | 1139.1 / 2.494 / 3.517 |
| REPS+NSCC | 3758.3 / 0.752 / 1.060 | 1961.6 / 1.231 / 2.030 | 1839.1 / 1.470 / 2.154 | 1608.4 / 1.626 / 2.511 | 1558.7 / 1.690 / 2.545 | 1479.2 / 1.817 / 2.656 |
| REPS+Swift | 3313.9 / 1.010 / 1.205 | 1789.4 / 1.361 / 2.168 | 1746.3 / 1.550 / 2.235 | 1714.9 / 1.686 / 2.308 | 1693.2 / 1.765 / 2.358 | 1576.4 / 2.027 / 2.553 |
| REPS+MSwift | 3305.3 / 1.051 / 1.212 | 2180.0 / 1.343 / 1.819 | 2058.0 / 1.475 / 1.921 | 1909.1 / 1.528 / 2.092 | 1834.4 / 1.574 / 2.154 | 1587.9 / 1.798 / 2.467 |
| REPS+MNSCC | 3788.8 / 0.752 / 1.055 | 2105.2 / 1.194 / 1.905 | 1864.3 / 1.456 / 2.134 | 1640.3 / 1.599 / 2.421 | 1650.8 / 1.658 / 2.428 | 1528.4 / 1.798 / 2.643 |
| STrack | 3497.4 / 0.811 / 1.109 | 1910.0 / 1.288 / 2.054 | 1757.7 / 1.511 / 2.258 | 1639.2 / 1.644 / 2.402 | 1569.7 / 1.725 / 2.540 | 1465.6 / 1.839 / 2.742 |
| Prism | 3398.1 / 0.994 / 1.170 | 2237.2 / 1.302 / 1.769 | 2166.6 / 1.431 / 1.810 | 1972.5 / 1.474 / 2.060 | 1949.2 / 1.509 / 2.045 | 1676.3 / 1.723 / 2.404 |

### PRISM vs REPS+NSCC deltas

| `-failed` | Goodput delta | Avg-FCT delta | P99-FCT |
|---|---|---|---|
| 0 | −9.6% | +32.2% (known symmetric penalty) | Prism 1.170 vs REPS 1.060 |
| 8 | **+14.0%** | +5.8% (mixed — FCT not yet a win) | **Prism 1.769 vs REPS 2.030** |
| 16 | **+17.8%** | −2.7% | **Prism 1.810 vs REPS 2.154** |
| 24 | **+22.6%** | **−9.3%** | **Prism 2.060 vs REPS 2.511** |
| 32 | **+25.1%** | **−10.7%** | **Prism 2.045 vs REPS 2.545** |
| 48 | **+13.3%** | **−5.2%** | **Prism 2.404 vs REPS 2.656** |

### PRISM vs STrack deltas (goodput)

| `-failed` | Goodput delta |
|---|---|
| 0 | −2.8% |
| 8 | **+17.1%** |
| 16 | **+23.3%** |
| 24 | **+20.4%** |
| 32 | **+24.1%** |
| 48 | **+14.4%** |

### PRISM vs REPS+Swift deltas (goodput / avg-FCT)

| `-failed` | Goodput delta | Avg-FCT delta | P99 |
|---|---|---|---|
| 0 | +2.5% | −1.6% | Prism 1.170 vs Swift 1.205 |
| 8 | **+25.0%** | **−4.3%** | **Prism 1.769 vs Swift 2.168** |
| 16 | **+24.0%** | **−7.7%** | **Prism 1.810 vs Swift 2.235** |
| 24 | **+15.0%** | **−12.5%** | **Prism 2.060 vs Swift 2.308** |
| 32 | **+15.1%** | **−13.7%** | **Prism 2.045 vs Swift 2.358** |
| 48 | **+6.3%** | **−15.0%** | **Prism 2.404 vs Swift 2.553** |

PRISM beats REPS+Swift on goodput at every failed ≥ 8 point (+6–25%). Avg-FCT is clearly lower for Prism at failed ≥ 8. At f0 (symmetric), both are comparably penalised by under-growth vs REPS+NSCC.

### PRISM vs REPS+MSwift deltas (goodput / avg-FCT)

| `-failed` | Goodput delta | Avg-FCT delta | P99 |
|---|---|---|---|
| 0 | +2.8% | −5.4% | Prism 1.170 vs MSwift 1.212 |
| 8 | **+2.6%** | **−3.0%** | **Prism 1.769 vs MSwift 1.819** |
| 16 | **+5.3%** | **−2.9%** | **Prism 1.810 vs MSwift 1.921** |
| 24 | **+3.3%** | **−3.5%** | **Prism 2.060 vs MSwift 2.092** |
| 32 | **+6.2%** | **−4.1%** | **Prism 2.045 vs MSwift 2.154** |
| 48 | **+5.6%** | **−4.2%** | **Prism 2.404 vs MSwift 2.467** |

REPS+MSwift is the closest delay-driven non-PRISM arm. PRISM still beats it on goodput (+2.6–6.2% at failed ≥ 8) and avg-FCT. The advantage is smaller than vs REPS+Swift because MSwift's median trigger is less aggressive in over-decreasing, but the gap persists at all non-zero asymmetry points.

### PRISM vs REPS+MNSCC deltas (goodput / avg-FCT)

| `-failed` | Goodput delta | Avg-FCT delta |
|---|---|---|
| 0 | −10.3% | +32.2% (known symmetric cost) |
| 8 | **+6.3%** | +9.1% (goodput win but FCT not yet ahead) |
| 16 | **+16.2%** | **−1.6%** |
| 24 | **+20.3%** | **−7.8%** |
| 32 | **+18.1%** | **−8.9%** |
| 48 | **+9.7%** | **−4.2%** |

REPS+MNSCC and REPS+NSCC behave similarly (MNSCC is NSCC with a median delay trigger). PRISM wins on goodput at failed ≥ 8 (+6–20%). The FCT win is smaller than vs REPS+NSCC and only clear at failed ≥ 16 — consistent with the pattern seen at 128 nodes.

### Headline

Under meaningful asymmetry (failed ≥ 8) PRISM beats all six baselines on goodput. The clean two-metric win (goodput + avg-FCT both ahead) firms up at failed ≥ 16 vs REPS+NSCC / STrack / REPS+MNSCC, and is present at failed ≥ 8 vs REPS+Swift / REPS+MSwift. P99-FCT is clearly lowest for PRISM at failed ≥ 8 across all arms.

At **f0** (symmetric): PRISM carries its known under-growth penalty vs the NSCC-family arms (−9.6% goodput vs REPS+NSCC, −10.3% vs REPS+MNSCC). Both Swift-family arms (REPS+Swift, REPS+MSwift) have similar f0 goodput to PRISM — they also under-grow relative to NSCC under symmetric load.

At **f8**: PRISM goodput leads REPS+NSCC by +14.0% and REPS+MNSCC by +6.3%, but avg-FCT is mixed at this transition point. PRISM already leads avg-FCT over REPS+Swift (+4.3%) and REPS+MSwift (+3.0%) at f8.

**STrack does not beat REPS+NSCC** throughout the sweep (e.g. f8: 1910.0 vs 1961.6 Gbps; f48: 1465.6 vs 1479.2). The Swift-family arms (REPS+Swift, REPS+MSwift) are weaker than REPS+NSCC at low-moderate asymmetry (f8: Swift 1789.4 vs NSCC 1961.6) but slightly exceed REPS+NSCC at high asymmetry (f32: Swift 1693.2 vs NSCC 1558.7; MSwift 1834.4 vs NSCC 1558.7). Despite this, both Swift-family arms lose to PRISM at every failed ≥ 8 point — the PRISM floor decomposition benefits equally from the Swift-type delay signal under asymmetry.

**The win is NOT diluted at scale.** Peak goodput delta +25.1% at f32 vs REPS+NSCC is comparable to (and slightly above) the 128-node result of +19–22%. More spare paths at 1024 nodes did not dilute the advantage — the floor decomposition identifies the degraded paths regardless of fabric size.

---

## 5. D2 results — 4:1 oversub (fat_tree_1024_4os_100g)

**All cells cr = 1.00 except OPS+NSCC at f3 (0.95) and f4 (0.74). All other arms cr = 1.00 throughout. Goodput in Gbps; avg-FCT in µs.**

See `figs/figD2_4os_main`.

### Goodput / avg-FCT / cr

| Arm | f0 | f1 | f2 | f3 | f4 |
|---|---|---|---|---|---|
| OPS+NSCC | 1228.1 / 2530 / cr 1.00 | 711.6 / 2897 / cr 1.00 | 603.5 / 3465 / cr 1.00 | 489.2 / 4540 / **cr 0.95** | 377.4 / 5156 / **cr 0.74** |
| REPS+NSCC | 1332.5 / 2454 / cr 1.00 | 919.0 / 2587 / cr 1.00 | 798.3 / 2851 / cr 1.00 | 676.8 / 3498 / cr 1.00 | 592.0 / 4343 / cr 1.00 |
| REPS+Swift | 1350.7 / 2775 / cr 1.00 | 709.2 / 3147 / cr 1.00 | 673.9 / 3489 / cr 1.00 | 656.1 / 4018 / cr 1.00 | 620.5 / 4649 / cr 1.00 |
| REPS+MSwift | 1328.0 / 2772 / cr 1.00 | 844.7 / 2821 / cr 1.00 | 785.5 / 2970 / cr 1.00 | 730.7 / 3323 / cr 1.00 | 682.8 / 3786 / cr 1.00 |
| REPS+MNSCC | 1338.9 / 2443 / cr 1.00 | 974.9 / 2567 / cr 1.00 | 860.5 / 2801 / cr 1.00 | 718.3 / 3326 / cr 1.00 | 616.2 / 4148 / cr 1.00 |
| STrack | 1336.2 / 2357 / cr 1.00 | 875.3 / 2577 / cr 1.00 | 776.0 / 2870 / cr 1.00 | 673.8 / 3507 / cr 1.00 | 583.8 / 4413 / cr 1.00 |
| Prism | 1287.7 / 2737 / cr 1.00 | 952.7 / 2662 / cr 1.00 | 875.7 / 2790 / cr 1.00 | 835.9 / 3073 / cr 1.00 | 774.6 / 3430 / cr 1.00 |

### PRISM vs REPS+NSCC deltas

| `-failed` | Goodput delta | Avg-FCT delta |
|---|---|---|
| 0 | −3.4% | +11.5% (known symmetric cost) |
| 1 | **+3.7%** | +2.9% |
| 2 | **+9.8%** | −2.1% |
| 3 | **+23.5%** | **−12.2%** |
| 4 | **+30.8%** | **−21.0%** |

### PRISM vs REPS+Swift deltas (4:1)

| `-failed` | Goodput delta | Avg-FCT delta |
|---|---|---|
| 0 | −4.7% | −1.4% |
| 1 | **+34.4%** | **−15.4%** |
| 2 | **+30.0%** | **−20.1%** |
| 3 | **+27.4%** | **−23.5%** |
| 4 | **+24.8%** | **−26.2%** |

PRISM beats REPS+Swift on goodput at every failed ≥ 1 point (+24–34%). REPS+Swift goodput is lower than REPS+NSCC at f1 (709.2 vs 919.0) — Swift's under-growth hurts it more in the oversubscribed regime.

### PRISM vs REPS+MSwift deltas (4:1)

| `-failed` | Goodput delta | Avg-FCT delta |
|---|---|---|
| 0 | −3.0% | −1.3% |
| 1 | **+12.8%** | **−5.6%** |
| 2 | **+11.5%** | **−6.1%** |
| 3 | **+14.4%** | **−7.5%** |
| 4 | **+13.4%** | **−9.4%** |

PRISM beats REPS+MSwift at every failed ≥ 1 point (+11–15%). MSwift's median trigger reduces its over-decrease compared to Swift, making it closer to PRISM than Swift is, but the floor decomposition advantage persists.

### PRISM vs REPS+MNSCC deltas (4:1)

| `-failed` | Goodput delta | Avg-FCT delta |
|---|---|---|
| 0 | −3.8% | +12.1% (symmetric cost) |
| 1 | −2.3% | +3.7% (slight goodput loss at f1) |
| 2 | **+1.8%** | −0.4% |
| 3 | **+16.4%** | **−7.6%** |
| 4 | **+25.7%** | **−17.3%** |

REPS+MNSCC is the strongest NSCC-family baseline at 4:1 (f1: 974.9 vs REPS+NSCC 919.0 Gbps). PRISM loses goodput to REPS+MNSCC at f1 (−2.3%) and is within noise at f2 (+1.8%). The win emerges cleanly at f3 (+16.4%) and f4 (+25.7%), consistent with the expA pattern.

**expA's 4:1 asymmetric pattern reproduced at 1024 nodes on a 4:1/100G oversubscribed core.**
PRISM beats all six baselines on goodput at failed ≥ 3 (cr = 1.00 throughout). The PRISM vs REPS+NSCC win (+30.8% at f4) matches (and slightly exceeds) the 128-node expB-asym 4:1 win of +14–32% goodput.

**OPS+NSCC drops to cr 0.95 at f3 and cr 0.74 at f4** — the oblivious spray cannot maintain
completion rate under combined oversubscription and asymmetry. All other arms hold cr = 1.00
across the full sweep. Avg-FCT comparisons are clean (cr = 1.00) for all six non-OPS arms.

**STrack does not beat REPS+NSCC** (e.g. f3: 673.8 vs 676.8 Gbps; f4: 583.8 vs 592.0). REPS+MNSCC outperforms both REPS+NSCC and STrack at low failed (f1: 974.9 vs 919.0 vs 875.3) — but at high asymmetry (f3, f4) PRISM leads the whole field.

---

## 6. D2 results — 8:1 oversub (fat_tree_1024_8os)

**EXP_END = 12 ms. Goodput in Gbps; avg-FCT in µs. At f4 every arm has cr < 1.00 — avg-FCT is confounded at f4; compare only goodput + cr there.**

See `figs/figD2_8os_main`.

### Goodput / avg-FCT / cr

| Arm | f0 | f1 | f2 | f4 (cr < 1 — FCT confounded) |
|---|---|---|---|---|
| OPS+NSCC | 690.8 / 4590 / cr 1.00 | 398.8 / 5283 / cr 1.00 | 303.2 / 6423 / **cr 0.88** | 45.4 / — / **cr 0.13** |
| REPS+NSCC | 729.1 / 4360 / cr 1.00 | 511.1 / 4601 / cr 1.00 | 408.1 / 5524 / cr 1.00 | 122.8 / — / **cr 0.36** |
| REPS+Swift | 733.1 / 5053 / cr 1.00 | 425.3 / 5472 / cr 1.00 | 389.5 / 6440 / cr 1.00 | 180.8 / — / **cr 0.53** |
| REPS+MSwift | 724.5 / 5020 / cr 1.00 | 465.5 / 4956 / cr 1.00 | 418.5 / 5541 / cr 1.00 | 226.5 / — / **cr 0.66** |
| REPS+MNSCC | 725.4 / 4334 / cr 1.00 | 524.9 / 4613 / cr 1.00 | 428.9 / 5387 / cr 1.00 | 125.6 / — / **cr 0.37** |
| STrack | 729.9 / 4233 / cr 1.00 | 492.1 / 4558 / cr 1.00 | 399.4 / 5598 / cr 1.00 | 123.2 / — / **cr 0.36** |
| Prism | 727.8 / 4792 / cr 1.00 | 539.9 / 4600 / cr 1.00 | 466.0 / 5130 / cr 1.00 | 286.8 / — / **cr 0.84** |

### PRISM vs REPS+NSCC deltas (clean cr = 1.00 cells only)

| `-failed` | Goodput delta | Avg-FCT delta | Note |
|---|---|---|---|
| 0 | −0.2% | +9.9% | symmetric — all arms tie on goodput |
| 1 | **+5.6%** | −0.02% | cr = 1.00 all main arms |
| 2 | **+14.2%** | −7.1% | cr = 1.00 all main arms |
| 4 | **+133% goodput, 2.3× completion** | (confounded — do not cite) | Prism cr 0.84 vs REPS cr 0.36 |

### PRISM vs new arms deltas (8:1, cr = 1.00 cells only; f4 goodput+cr only)

| Arm | f0 goodput | f1 goodput | f2 goodput | f4 cr / goodput |
|---|---|---|---|---|
| REPS+Swift | +733.1 vs Prism 727.8 → Prism −0.7% | Prism **+26.9%** (539.9 vs 425.3) | Prism **+19.6%** (466.0 vs 389.5) | Prism 0.84 vs Swift **cr 0.53** (286.8 vs 180.8 Gbps, **+58.6%**) |
| REPS+MSwift | Prism −0.4% (727.8 vs 724.5) | Prism **+16.0%** (539.9 vs 465.5) | Prism **+11.3%** (466.0 vs 418.5) | Prism 0.84 vs MSwift **cr 0.66** (286.8 vs 226.5 Gbps, **+26.6%**) |
| REPS+MNSCC | Prism +0.3% (727.8 vs 725.4) | Prism **+2.9%** (539.9 vs 524.9) | Prism **+8.6%** (466.0 vs 428.9) | Prism 0.84 vs MNSCC **cr 0.37** (286.8 vs 125.6 Gbps, **+128%**) |

At 8:1 the Swift-family arms (REPS+Swift, REPS+MSwift) gracefully degrade better than the NSCC-family arms — at f4, Swift reaches cr 0.53 and MSwift cr 0.66 vs NSCC/MNSCC cr 0.36–0.37. This is because Swift/MSwift's delay-driven under-growth reduces queue buildup on the oversubscribed fabric. However, Prism still achieves the best cr (0.84) and highest goodput at f4 across all seven arms. At f0 all arms tie on goodput (within 1%). At f1–f2 (cr = 1.00 across all), Prism leads every arm.

### The graceful-degradation finding (scale-dependent)

This result is **qualitatively different from `expB_oversub_asym`**, where the 128-node 8:1 fabric
hard-saturated every arm at any failure (failed ≥ 2 → cr ≈ 0 for all arms). At 1024 nodes with
8:1 oversubscription the picture changes:

- **f0:** All arms tie on goodput (~727–730 Gbps, cr = 1.00). Prism carries the expected symmetric
  avg-FCT penalty (+9.9% vs REPS+NSCC; −0.2% goodput gap is noise).
- **f1, f2:** All four arms complete (cr = 1.00 for REPS+NSCC, STrack, Prism; OPS drops to cr 0.88
  at f2). PRISM leads goodput clearly: f1 +5.6%, f2 +14.2% vs REPS+NSCC — at full completion.
- **f4:** The averaging arms (REPS+NSCC and STrack) drop to cr = 0.36 (122–123 Gbps). OPS drops to
  cr = 0.13 (45 Gbps). Prism completes cr = 0.84 (286.8 Gbps) — a **+133% goodput / 2.3×
  completion advantage**.

So at 8× scale the 8:1 topology becomes a **PRISM graceful-degradation win region** rather than a
universal saturation boundary. The larger fabric retains more reroutable headroom; PRISM's floor
decomposition exploits it while the averaging arms over-decrease and stall.

**Honest framing — what is and is not clean:**

- f0, f1, f2 cells for REPS+NSCC / STrack / Prism are all cr = 1.00 and FCT comparisons are
  unconfounded.
- At **f4, cr < 1.00 for every arm** (Prism 0.84, REPS 0.36, STrack 0.36). Avg-FCT at f4 is
  therefore **confounded** — flows that completed early are selected; do not compare avg-FCT
  across arms at this point. The goodput and cr numbers are the valid comparison at f4.
- This is a **scale-dependent strengthening** of the result, not just a replication. It must be
  stated as such: the 128-node hard-saturation boundary becomes, at 1024 nodes, a regime where
  PRISM gracefully degrades while averaging arms stall. Whether this generalises further (e.g.
  to even higher failure fractions or 12:1 oversub) is not tested here.

---

## 7. Mechanism

All mechanism runs: seed 13, 4 MB message size (so every arm's makespan spans the window).

### D1 — failed=32 (50% pod0 core ingress)

See `figs/figD1_mech_signal`, `figs/figD1_mech_cwnd`.

| Arm | Per-ACK cwnd-decrease events |
|---|---|
| REPS+NSCC | 18331 |
| STrack | 19873 |
| Prism | **4073** |

**Floor-MD fraction (Prism):** floor-driven epoch-MDs / total cwnd-decreases = 1370 / 4073 = **0.336**.

Prism makes **4.5× fewer cwnd decreases** than REPS+NSCC at this scale. The floor-MD fraction
0.336 sits between the 128-node trimming baseline (~0.05) and the expA 4 MB delay-driven mechanism
run (0.374) — consistent with delay-driven operation at comparable asymmetry fraction.

**STrack distinctness (PASSED).** Per-ACK cwnd-decrease events: STrack = 19873 vs REPS+NSCC =
18331 — measurably different. STrack is not a clone of NSCC at this scale.

### D2 — 4:1, failed=4 (cr = 1.00 win point)

See `figs/figD2_mech`.

| Arm | Per-ACK cwnd-decrease events |
|---|---|
| REPS+NSCC | 11959 |
| STrack | 13422 |
| PRISM | **4585** |

**Floor-MD fraction (PRISM):** 493 / 4585 = **0.108**.

PRISM makes **2.6× fewer cwnd decreases** than REPS+NSCC. The floor-MD fraction 0.108 is low —
consistent with the 4:1 pattern from `expB_oversub_asym` (0.131 at the analogous point): the win
here comes primarily from *not over-cutting* (the averaging arms see elevated mean delay from the
degraded links and over-decrease) rather than from many floor-triggered cuts. The decomposition
lever is the same; the balance between floor-cut and hold shifts with the density of the asymmetry.

**STrack distinctness (PASSED).** STrack = 13422 vs REPS+NSCC = 11959 — measurably different.

---

## 8. Fairness

**Jain fairness index** (`figs/figD1_fairness`), D1 (1:1), per arm:

| Arm | f0 | f8 | f16 | f24 | f32 | f48 |
|---|---|---|---|---|---|---|
| OPS+NSCC   | 0.927 | 0.738 | 0.728 | 0.812 | 0.845 | 0.919 |
| REPS+NSCC  | 0.932 | 0.803 | 0.820 | 0.870 | 0.910 | 0.902 |
| REPS+Swift | 0.932 | 0.863 | 0.903 | 0.925 | 0.956 | 0.969 |
| REPS+MSwift| 0.949 | 0.914 | 0.941 | 0.962 | 0.969 | 0.958 |
| REPS+MNSCC | 0.932 | 0.811 | 0.831 | 0.869 | 0.909 | 0.898 |
| STrack     | 0.915 | 0.788 | 0.811 | 0.877 | 0.913 | 0.905 |
| Prism      | 0.898 | 0.838 | 0.901 | 0.923 | 0.941 | 0.944 |

Prism is the **most fair among the NSCC-family arms** at failed ≥ 8 (e.g. f32: 0.941 vs REPS+NSCC 0.910 / STrack 0.913 / REPS+MNSCC 0.909). The Swift-family arms (REPS+Swift, REPS+MSwift) achieve higher fairness indices than Prism at high asymmetry — e.g. f32: MSwift 0.969, Swift 0.956, Prism 0.941. This is consistent with their rate-reduction behaviour under asymmetry (more conservative sends → more uniform across flows), but does not translate to better goodput or FCT. At f0 Prism (0.898) is slightly less fair than REPS+NSCC (0.932), same under-growth cost as for goodput.

**Jain fairness index** (`figs/figD2_4os_fairness`), D2 4:1 oversub, per arm:

| Arm | f0 | f1 | f2 | f3 | f4 |
|---|---|---|---|---|---|
| OPS+NSCC   | 0.949 | 0.869 | 0.785 | 0.686 | 0.658 |
| REPS+NSCC  | 0.960 | 0.914 | 0.869 | 0.802 | 0.754 |
| REPS+Swift | 0.996 | 0.910 | 0.840 | 0.757 | 0.787 |
| REPS+MSwift| 0.995 | 0.945 | 0.901 | 0.844 | 0.821 |
| REPS+MNSCC | 0.950 | 0.912 | 0.870 | 0.832 | 0.798 |
| STrack     | 0.950 | 0.906 | 0.863 | 0.802 | 0.762 |
| Prism      | 0.983 | 0.930 | 0.881 | 0.847 | 0.843 |

Prism is the **most fair arm** at f1–f4 among the NSCC-family and STrack. REPS+MSwift (0.995 at f0) and REPS+Swift (0.996 at f0) exceed Prism's 0.983 at f0, but Prism leads at f3–f4 (0.847/0.843 vs Swift 0.757/0.787 and REPS+NSCC 0.802/0.754). The fairness advantage for Prism grows with asymmetry in the NSCC-family comparison. REPS+MNSCC fairness (0.832/0.798 at f3/f4) is better than REPS+NSCC (0.802/0.754) but both trail Prism.

---

## 9. Verdict

Both PRISM headline wins survive at 8× scale across all seven arms:

**D1 (1:1, delay-driven asymmetry):** PRISM beats all six baselines on goodput at failed ≥ 8.
The peak delta vs REPS+NSCC is +25.1% at f32 (comparable to 128-node result of +19–22%). PRISM
also leads REPS+MSwift (+6.2% at f32) and REPS+Swift (+15.1% at f32), the closest delay-driven
baselines. The clean two-metric win (goodput + avg-FCT) vs REPS+NSCC/STrack/REPS+MNSCC firms up
at failed ≥ 16; vs REPS+Swift/REPS+MSwift, avg-FCT is lower for Prism at every failed ≥ 8 point.
The STrack distinctness check passes; the "decomposition, not coupling" conclusion transfers.

**D2 (4:1 oversubscribed):** PRISM wins on goodput at failed ≥ 3 vs all six arms (cr = 1.00
throughout for all non-OPS arms). REPS+MNSCC is the strongest baseline at f1 (974.9 Gbps,
narrowly ahead of Prism's 952.7 — a −2.3% Prism loss at this single point); the Prism win widens
at f3 (+16.4%) and f4 (+25.7%). REPS+Swift is the weakest non-OPS baseline at f1 (709.2 Gbps).

**D2 (8:1 oversubscribed):** The result is **stronger than at 128 nodes**, not just equal. At
1024 nodes, PRISM gracefully degrades better than every arm: f1 and f2 are clean wins at
cr = 1.00 (+5.6% / +14.2% goodput vs REPS+NSCC); at f4 PRISM holds cr = 0.84 vs REPS+NSCC
cr = 0.36 (+133% goodput). The Swift-family arms also degrade more gracefully than the NSCC-family
at f4 (Swift cr 0.53, MSwift cr 0.66 vs NSCC cr 0.36), but both still trail Prism (cr 0.84) on
cr and goodput at f4. This is a scale-dependent finding and must be framed as such.

**Honest caveats:**

- **Symmetric penalty (f0) persists** in D1 vs NSCC-family arms (goodput −9.6% vs REPS+NSCC;
  Swift-family arms have similar f0 goodput to Prism). The cost of holding spray under symmetric
  load is unchanged at scale.
- **D1 f8 FCT is not yet a win vs REPS+NSCC** (+5.8%): goodput leads but avg-FCT slightly higher,
  as at expA's f2 transition point. Clean two-metric win firms up at failed ≥ 16 for NSCC-family.
- **D2 4:1 f1: PRISM loses goodput to REPS+MNSCC** (−2.3%): this is the one cell where the new
  arms reveal a Prism weakness. The win is not clean across every single point at 4:1; it emerges
  consistently at f3–f4.
- **D2 8:1 f4 avg-FCT is confounded** (cr < 1.00 for every arm). Do not cite avg-FCT at f4; use
  goodput + cr only.
- **8:1 graceful degradation is scale-dependent**: not a replication of the 128-node result.
  Whether it generalises further is not tested.
- 1024-node development-scale topology; delay-driven regime only (`-disable_trim`). STrack's
  adaptive ECN-bitmap spray (Approach B) is not ported — deliberately, to hold spray fixed and
  isolate the CC signal decomposition.

---

## 10. Reproduce

```
bash prism_eval/expD_scale1024/repro.sh   # from sim/datacenter
```

---

## 11. Honest scope

- **Development scale:** 1024-node fat-tree. Production-scale evaluation (8192+ nodes) deferred.
- **Delay-driven only:** `-disable_trim` throughout. Trimming-regime oversub-asym behaviour at
  1024 nodes is deferred.
- **STrack Approach B deferred:** STrack's adaptive ECN-bitmap spray is not ported (spec §3,
  Approach B). The STrack arm here is STrack's CC core on the shared REPS spray — deliberately
  held fixed to isolate the CC signal.
- **Permutation / AI-collectives traffic deferred:** many2many incast workload only.
- **8:1 graceful-degradation is an observation, not a proof:** the finding that 1024-node 8:1
  becomes a Prism win region (vs 128-node hard-saturation) is reported as a scale-dependent
  effect, not a general claim about all oversub ratios at all scales.

Cross-links: `../expA_delaydriven/` (1:1 win, 128 nodes) | `../expB_oversub_asym/` (4:1 and 8:1
win/saturation, 128 nodes) | `../NARRATIVE.md` | `../TARGET_REGIME.md`.
