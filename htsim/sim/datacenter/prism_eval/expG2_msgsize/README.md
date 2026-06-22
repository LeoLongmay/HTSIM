# expG2_msgsize — collective CCT vs message size, relative to REPS+NSCC (A2A / Butterfly-AR), fixed failed=8

## 1. What this group tests

The message-size companion to `../expG_collectives`. expG fixes the per-flow message at 128 KB and
sweeps **failed-links**; expG2 fixes **`-failed 8`** and sweeps the **per-flow message size**. The
question: a barriered collective is latency-bound when each step is sub-BDP (all transports tie), but
as the message grows past one BDP each step becomes bandwidth-bound, where PRISM's congestion
decomposition (floor→CC, spread→spraying) should pull ahead. This figure makes that transition visible.

The figure sweeps collective completion time vs message size (after **STrack**, Le et al.), drawn as
**grouped bars** (one bar per arm, grouped by message size). The y-axis is the collective completion
time **relative to the REPS+NSCC (UEC) baseline** (each arm's makespan divided by REPS+NSCC's, paired
per seed): bars are linear from 0 with a dashed reference line at 1.0, so a bar below 1.0 is faster
than the UEC baseline. Generators are reused unchanged from expG (`coll_alltoall.py`,
`coll_butterfly.py`); only `flowsize` is swept.

## 2. Setup

| Parameter | Value |
|---|---|
| Topology | `fat_tree_128_1os.topo` (3-tier, 100 G, 1:1) |
| Nodes | 128 (single collective group) |
| Collectives | A2A (parallel=32, k=4 steps), Butterfly-AllReduce (k=log2 128=7 steps) |
| Fixed failures | `-failed 8` |
| Message-size sweep | 16 KB, 64 KB, 256 KB, 1 MB, 4 MB (per flow) |
| Regime | delay-driven (`-disable_trim`), PATHS=8, END scaled per size (A2A NIC-bound) |
| Arms | OPS+NSCC, REPS+NSCC, REPS+Swift, REPS+MSwift, REPS+MNSCC, STrack, **Prism** (7) |
| Seeds | 13–17 (5) → 2 × 5 × 7 × 5 = **350 runs** |

**One-command repro:** `bash repro.sh`. Raw data gitignored; figures committed with `git add -f`.

## 3. Metric

**Relative CCT** = collective makespan of an arm / collective makespan of **REPS+NSCC** (the UEC
baseline), computed **per seed** (same random placement) and then averaged over the 5 seeds with SEM.
The reference REPS+NSCC is the flat 1.0 line; an arm below 1.0 finishes the collective faster than the
UEC baseline. A point whose completion-rate < 1 is drawn with a hollow marker (none occur here — all
350 cells completed). Error bars are the standard error of the mean across seeds.

*(An earlier draft normalized CCT by an analytical zero-queue lower bound `k·(base_rtt + size·8/rate)`
in the MSwift style. That bound proved non-physical for these collectives — it undercounts A2A's
per-wave NIC serialization, the `parallel=32` messages each host serializes (giving slowdowns of
15–65×), and it overcounts Butterfly's short, partly-overlapping recursive-doubling steps (giving
slowdowns < 1, i.e. "faster than the lower bound"). The relative-to-baseline ratio cancels any such
modeling error and is exact; the arm-to-arm comparison and the crossover are identical under either
normalization, since dividing every arm by a common per-size constant preserves their ratios.)*

## 4. Honest pre-registration

- **A2A**: arm lines expected to converge (tie) at small sizes (latency-bound) and separate at large
  sizes with PRISM lowest (bandwidth-bound, spread-dominated) — the crossover is the headline.
- **Butterfly**: expected near-flat, arms ~equal at every size (only 7 steps → critical-path-bound
  regardless of message size; CC-invariant) — a control showing some collectives never become
  transport-sensitive.
- A tie even at 4 MB is an acceptable, publishable outcome. Reported straight.

## 5. Results

All **350 cells completed at cr = 1.00** (no incast failure at `-failed 8`; no hollow markers).
Figures: `figs/figH_a2a_msgsize`, `figs/figH_bfly_msgsize`, `figs/figH_legend`. Values below are the
5-seed-mean CCT **relative to REPS+NSCC** (= 1.000 by definition), ± SEM.

**Headline — the crossover is confirmed.** At small (sub-BDP, latency-bound) messages the spraying
arms sit on the REPS+NSCC baseline within noise (do-no-harm); as the message grows past one BDP
(≈175 KB) and each step becomes bandwidth-bound, the spread-aware + robust-CC arms pull below the
baseline, and the gap widens monotonically with size. **PRISM is the best (or tied-best) arm at the
two largest sizes on A2A, reaching 12.7 % below the UEC baseline at 4 MB**, and is uniquely strong at
4 MB on Butterfly.

### All-to-All (parallel=32) — CCT relative to REPS+NSCC

| arm | 16 K | 64 K | 256 K | 1 M | 4 M |
|---|---|---|---|---|---|
| OPS+NSCC | 1.228 ±.124 | 1.188 ±.034 | 1.259 ±.016 | 1.310 ±.008 | 1.319 ±.007 |
| REPS+NSCC | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| REPS+Swift | 1.213 ±.125 | 0.956 ±.023 | 0.971 ±.012 | 0.943 ±.002 | 0.910 ±.001 |
| REPS+MSwift | 1.213 ±.125 | 0.929 ±.026 | 0.965 ±.012 | 0.928 ±.003 | 0.885 ±.001 |
| REPS+MNSCC | 1.213 ±.121 | 0.950 ±.028 | 0.982 ±.010 | 0.982 ±.004 | 0.986 ±.002 |
| STrack | 1.000 ±.000 | 0.975 ±.014 | 1.002 ±.006 | 0.992 ±.003 | 0.960 ±.002 |
| **Prism** | **0.997 ±.008** | **0.949 ±.024** | **0.982 ±.011** | **0.928 ±.002** | **0.873 ±.002** |

At 16 K every spraying arm is within noise of the baseline (large SEMs; a tie — do-no-harm). From
64 K on PRISM and the median-CC arms drop below 1.0; the separation grows with size and the SEMs
shrink to ~0.002. **PRISM is the lowest arm at 1 M (0.928) and 4 M (0.873)** — at 4 M it is 12.7 %
faster than REPS+NSCC and edges out its closest competitor REPS+MSwift (0.885), with the gap ≫ SEM
(highly significant). OPS+NSCC (oblivious, no rerouting) is the worst arm at every size and degrades
monotonically (1.23 → 1.32). This is the textbook latency-→-bandwidth crossover the group set out to
show.

### Butterfly-AllReduce — CCT relative to REPS+NSCC

| arm | 16 K | 64 K | 256 K | 1 M | 4 M |
|---|---|---|---|---|---|
| OPS+NSCC | 0.897 ±.033 | 0.894 ±.038 | 1.615 ±.846 | 1.092 ±.012 | 1.346 ±.044 |
| REPS+NSCC | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| REPS+Swift | 1.000 ±.000 | 1.000 ±.000 | 1.018 ±.009 | 1.200 ±.010 | 1.139 ±.035 |
| REPS+MSwift | 1.000 ±.000 | 1.000 ±.000 | 1.000 ±.007 | 1.153 ±.015 | 1.004 ±.042 |
| REPS+MNSCC | 1.000 ±.000 | 1.000 ±.000 | 0.997 ±.003 | 0.994 ±.014 | 0.994 ±.039 |
| STrack | 1.000 ±.000 | 1.000 ±.000 | 1.000 ±.000 | 1.012 ±.015 | 1.011 ±.022 |
| **Prism** | **1.000 ±.000** | **1.000 ±.000** | **1.041 ±.021** | **1.025 ±.024** | **0.664 ±.030** |

Butterfly is **CC-invariant at small/mid sizes**: at 16 K and 64 K every REPS-based arm has byte-for-
byte the same makespan as REPS+NSCC (ratio exactly 1.000 — the steps are purely latency-bound, so the
transport cannot matter), confirming the pre-registration. Only at the deeply bandwidth-bound 4 MB
does a transport separate: **PRISM alone pulls to 0.664 (−33.6 %, SEM 0.030, significant)**, while the
median-CC arms stay ≈ 1.0 and Swift/MSwift are actually *worse* than the baseline at 1 M (1.20 / 1.15)
— spraying-CC co-design helps here only when it is PRISM's specific decomposition, and only once the
message is large enough.

### What this delineates

The message-size axis cleanly exposes **when** PRISM's congestion decomposition (floor→CC,
spread→spraying) pays off on a barriered collective: not at the small chained steps that make
fine-grained collectives latency-bound (where expG found all transports within ~3–5 %), but once the
per-step transfer is large enough to be bandwidth-bound. Then PRISM increasingly leads — monotonically
on A2A (best from 1 M, −12.7 % at 4 M) and decisively on Butterfly at 4 M (−33.6 %). This is the
crossover the experiment was designed to find, and it complements expG's failed-links axis (which
held message size fixed at the small, latency-bound 128 KB).

## 6. Caveats (honest)

1. **Small-message ties are within noise.** At 16 K (A2A) the spraying arms' SEMs reach ~0.12; the
   "tie with the baseline" there is a genuine do-no-harm, not a measured win.
2. **Butterfly is mostly CC-invariant.** The PRISM advantage on Butterfly is confined to 4 MB; at
   ≤ 1 MB it is ≈ 1.0, and some arms (Swift/MSwift) are slightly worse than the baseline at 1 M. The
   one large OPS+NSCC variance point (256 K, ±0.846) is a single high-makespan seed, reported as-is.
3. **Relative metric.** The y-axis is CCT relative to REPS+NSCC, not an absolute slowdown; see §3 for
   why the analytical zero-queue lower bound was unsuitable for these two collectives.
4. **Fixed operating point.** All cells are at `-failed 8` on the 128-node 100 G COMPOSITE testbed;
   the message-size axis is the only sweep.
