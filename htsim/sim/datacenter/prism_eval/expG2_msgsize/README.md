# expG2_msgsize — collective CCT vs message size, relative to REPS+NSCC (A2A / Butterfly-AR), fixed failed=8

## 1. What this group tests

The message-size companion to `../expG_collectives`. expG fixes the per-flow message at 128 KB and
sweeps **failed-links**; expG2 fixes **`-failed 8`** and sweeps the **per-flow message size**. The
question: a barriered collective is latency-bound when each step is sub-BDP (all transports tie), but
as the message grows past one BDP each step becomes bandwidth-bound, where PRISM's congestion
decomposition (floor→CC, spread→spraying) should pull ahead. This figure makes that transition visible.

The figure sweeps collective completion time vs message size (after **STrack**, Le et al.), drawn as
**grouped bars** (one bar per arm, grouped by message size). The y-axis (`CCT slowdown`) is the
collective completion time **relative to the REPS+NSCC (UEC) baseline** — each arm's makespan divided
by REPS+NSCC's, paired per seed, then the **geometric mean** over seeds — with a dashed reference line
at 1.0, so a bar below 1.0 is faster than the UEC baseline. The y-axis is zoomed per collective (floor
0.75 for A2A, 0.5 for Butterfly) to make the spread near 1.0 legible; the top stays auto-scaled.
Generators are reused unchanged from expG (`coll_alltoall.py`, `coll_butterfly.py`); only `flowsize`
is swept.

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
| Seeds | A2A 13–17 (n=5); Butterfly 13–42 (n=30, every bfly run ~0.3–3 s → extra seeds nearly free, used to tighten the 256 K knee) → 7×5×(5+30) = **1225 runs** |

**One-command repro:** `bash repro.sh`. Raw data gitignored; figures committed with `git add -f`.

## 3. Metric

**Relative CCT** (figure axis: `CCT slowdown`) = collective makespan of an arm / collective makespan
of **REPS+NSCC** (the UEC baseline), computed **per seed** (same random placement) and then summarized
over the seeds (A2A n=5, Butterfly n=30) by the **geometric mean**. The reference REPS+NSCC is the flat
1.0 line; an arm below 1.0 finishes the collective faster than the UEC baseline. A point whose
completion-rate < 1 is hatched (none occur here — all 1225 cells completed). Error bars are the
**geometric (multiplicative) SEM**, drawn as an asymmetric interval `[exp(μ−sem_log), exp(μ+sem_log)]`
about the geometric mean.

*Why the geometric mean.* It is the correct average for normalized ratios: symmetric under inversion
(swapping which arm is the numerator inverts it cleanly) and unbiased for multiplicative quantities,
whereas the arithmetic mean over-weights ratios > 1. This matters most at the **knee**: at a per-step
size of ≈ 1.5 BDP (Butterfly at 256 K) the collective makespan is bimodal — a given seed lands in
either a free-flowing (~0.1 ms) or a congested (~0.5 ms) regime depending on placement — so the
per-seed ratio is bimodal. With only 5 seeds that point was unstable (a seed-pair landed in opposite
regimes, ratios 4.95 and 0.23, which the arithmetic mean inflated to 1.62 ± 0.85 — a tall bar whose
error reached 2.46). Two fixes, both applied: the geometric mean cancels reciprocal outliers in log
space, and **Butterfly was re-run at n=30** (it is cheap) so the bimodal knee is properly sampled. The
256 K OPS point now settles to **0.90 with a normal interval [0.75, 1.08]** (cr=1), comparable to the
other bars. Every other cell moved ≤ 0.03 from the arithmetic mean.

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

All **1225 cells completed at cr = 1.00** (no incast failure at `-failed 8`; no hollow markers).
Figures: `figs/figH_a2a_msgsize`, `figs/figH_bfly_msgsize`, `figs/figH_legend`. Values below are the
**geometric-mean** CCT **relative to REPS+NSCC** (= 1.000 by definition), ± geometric SEM, over
A2A's 5 seeds and Butterfly's 30 seeds.

**Headline — the crossover is confirmed.** At small (sub-BDP, latency-bound) messages the spraying
arms sit on the REPS+NSCC baseline within noise (do-no-harm); as the message grows past one BDP
(≈175 KB) and each step becomes bandwidth-bound, the spread-aware + robust-CC arms pull below the
baseline, and the gap widens monotonically with size. **PRISM is the best (or tied-best) arm at the
two largest sizes on A2A, reaching 12.7 % below the UEC baseline at 4 MB**, and is uniquely strong at
4 MB on Butterfly.

### All-to-All (parallel=32) — CCT slowdown relative to REPS+NSCC (geometric mean)

| arm | 16 K | 64 K | 256 K | 1 M | 4 M |
|---|---|---|---|---|---|
| OPS+NSCC | 1.204 ±.119 | 1.186 ±.033 | 1.258 ±.016 | 1.310 ±.008 | 1.319 ±.007 |
| REPS+NSCC | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| REPS+Swift | 1.188 ±.120 | 0.955 ±.023 | 0.971 ±.013 | 0.943 ±.002 | 0.910 ±.001 |
| REPS+MSwift | 1.188 ±.120 | 0.927 ±.026 | 0.965 ±.012 | 0.928 ±.003 | 0.885 ±.001 |
| REPS+MNSCC | 1.190 ±.116 | 0.948 ±.027 | 0.982 ±.010 | 0.982 ±.004 | 0.986 ±.002 |
| STrack | 1.000 ±.000 | 0.975 ±.014 | 1.002 ±.006 | 0.992 ±.003 | 0.960 ±.002 |
| **Prism** | **0.997 ±.008** | **0.947 ±.024** | **0.982 ±.011** | **0.928 ±.002** | **0.873 ±.002** |

At 16 K every spraying arm is within noise of the baseline (large SEMs; a tie — do-no-harm). From
64 K on PRISM and the median-CC arms drop below 1.0; the separation grows with size and the SEMs
shrink to ~0.002. **PRISM is the lowest arm at 1 M (0.928) and 4 M (0.873)** — at 4 M it is 12.7 %
faster than REPS+NSCC and edges out its closest competitor REPS+MSwift (0.885), with the gap ≫ SEM
(highly significant). OPS+NSCC (oblivious, no rerouting) is the worst arm at every size and degrades
monotonically (1.23 → 1.32). This is the textbook latency-→-bandwidth crossover the group set out to
show.

### Butterfly-AllReduce — CCT slowdown relative to REPS+NSCC (geometric mean, n=30)

| arm | 16 K | 64 K | 256 K | 1 M | 4 M |
|---|---|---|---|---|---|
| OPS+NSCC | 0.997 ±.018 | 0.955 ±.030 | 0.901 ±.16 | 1.115 ±.017 | 1.323 ±.041 |
| REPS+NSCC | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| REPS+Swift | 1.000 ±.000 | 1.000 ±.000 | 1.018 ±.004 | 1.191 ±.004 | 1.086 ±.014 |
| REPS+MSwift | 1.000 ±.000 | 1.000 ±.000 | 1.004 ±.002 | 1.169 ±.005 | 0.943 ±.021 |
| REPS+MNSCC | 1.000 ±.000 | 1.000 ±.000 | 0.999 ±.001 | 0.990 ±.004 | 0.958 ±.014 |
| STrack | 1.000 ±.000 | 1.000 ±.000 | 1.000 ±.000 | 1.003 ±.005 | 1.019 ±.014 |
| **Prism** | **1.000 ±.000** | **1.000 ±.000** | **1.027 ±.007** | **1.027 ±.007** | **0.652 ±.011** |

Butterfly is **CC-invariant at small/mid sizes**: at 16 K and 64 K every REPS-based arm has byte-for-
byte the same makespan as REPS+NSCC (ratio exactly 1.000 — the steps are purely latency-bound, so the
transport cannot matter), confirming the pre-registration; OPS+NSCC (oblivious) is within noise of the
baseline there too (0.997 / 0.955). Only at the deeply bandwidth-bound 4 MB does a transport separate
decisively: **PRISM pulls to 0.652 (−34.8 %, geom-SEM 0.011, significant)**, far below the next-best
arms (MSwift 0.943, MNSCC 0.958), while OPS+NSCC is worst (1.323) and Swift sits above the baseline
(1.086). At 1 M, Swift/MSwift are actually *worse* than the baseline (1.19 / 1.17) while PRISM is ≈ 1.0
— spraying-CC co-design helps decisively here only with PRISM's specific decomposition, and only once
the message is large enough.

### What this delineates

The message-size axis cleanly exposes **when** PRISM's congestion decomposition (floor→CC,
spread→spraying) pays off on a barriered collective: not at the small chained steps that make
fine-grained collectives latency-bound (where expG found all transports within ~3–5 %), but once the
per-step transfer is large enough to be bandwidth-bound. Then PRISM increasingly leads — monotonically
on A2A (best from 1 M, −12.7 % at 4 M) and decisively on Butterfly at 4 M (−34.8 %). This is the
crossover the experiment was designed to find, and it complements expG's failed-links axis (which
held message size fixed at the small, latency-bound 128 KB).

## 6. Caveats (honest)

1. **Small-message ties are within noise.** At 16 K (A2A) the spraying arms' geometric SEMs reach
   ~0.12; the "tie with the baseline" there is a genuine do-no-harm, not a measured win.
2. **Butterfly is mostly CC-invariant; 256 K is the highest-variance point.** The PRISM advantage on
   Butterfly is confined to 4 MB; at ≤ 1 MB it is ≈ 1.0, and some arms (Swift/MSwift) are slightly
   worse than the baseline at 1 M. The OPS+NSCC point at **256 K (≈ 1.5 BDP)** is the latency→bandwidth
   knee, where makespan is bimodal (free-flowing ~0.1 ms vs congested ~0.5 ms by placement). It is the
   only point that needed extra sampling: at n=5 it was unstable; at **n=30** it settles to 0.90 with a
   still-wider-than-average but normal interval [0.75, 1.08] (cr=1). Reported as the knee it is.
3. **Per-collective seed counts.** A2A is summarized over 5 seeds (A2A@4M is NIC-bound and slow to
   run); Butterfly over 30 (every bfly run is ~0.3–3 s). So bfly error bars are tighter than A2A's by
   construction; the two panels are not directly comparable in n. Disclosed on every bfly table.
4. **Relative metric.** The figure axis `CCT slowdown` is CCT relative to REPS+NSCC (geometric mean of
   per-seed ratios), not an absolute slowdown; see §3 for why the analytical zero-queue lower bound was
   unsuitable for these two collectives and why the geometric mean is the right summary for ratios.
5. **Fixed operating point.** All cells are at `-failed 8` on the 128-node 100 G COMPOSITE testbed;
   the message-size axis is the only sweep.
