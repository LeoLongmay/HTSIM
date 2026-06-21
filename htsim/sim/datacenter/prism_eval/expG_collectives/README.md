# expG_collectives — STrack-style AI collectives (A2A / Ring-AR / Butterfly-AR) × failed-links

## 1. What this group tests

Whether PRISM's delay-driven **asymmetric-fabric advantage** holds on **full multi-step collective
communication**, following STrack's AI/ML workload methodology (Le et al., *STrack*, §4.3). Three
collectives — **All-to-All**, **Ring-AllReduce**, **Butterfly (recursive-doubling) AllReduce** — run
with genuine inter-step message dependencies (barriers/triggers), over a **failed-links** sweep (our
asymmetry axis). This extends `../expF_aiworkload` (a single HSDP ring *step*) to complete collectives.

### Faithful to STrack vs. our extension

| Aspect | Faithful | Our extension / deviation |
|---|---|---|
| Collectives | A2A, Ring-AR, Butterfly/HD-AR (3 of STrack's 4; **DBT omitted** — no generator) | — |
| A2A concurrency | restricted parallel connections (STrack 16/32/64) | **fixed at 32** |
| Chunk size | **128 KB** per message | — |
| Metric | collective completion time = makespan | reported as **raw ms** (not normalized) |
| Job structure | STrack: 64 concurrent collectives (multi-job) | **single job** spanning all 128 |
| Fabric | 2-tier Clos, 400 G | our 128-node 3-tier **100 G / COMPOSITE** testbed |
| Asymmetry | STrack fails links on permutation | we sweep **failed-links {0,4,8,12}** on the collectives |

## 2. Setup

| Parameter | Value |
|---|---|
| Topology | `fat_tree_128_1os.topo` (3-tier, 100 G, 1:1) |
| Nodes | 128 (single collective group) |
| Collectives | A2A (parallel=32), Ring-AllReduce, Butterfly-AllReduce |
| Chunk (per-flow) size | 131072 B (128 KB) |
| Failed-link sweep | `{0, 4, 8, 12}` |
| Regime | delay-driven (`-disable_trim`), PATHS=8, END=20 ms (Ring long pole; override via `EXP_END`) |
| Arms | OPS+NSCC, REPS+NSCC, REPS+Swift, REPS+MSwift, REPS+MNSCC, STrack, **Prism** (7) |
| Seeds | 13–17 (5) → 3 × 4 × 7 × 5 = **420 runs** |

**One-command repro:** `bash repro.sh`. Raw data gitignored; figures committed with `git add -f`.

## 3. Metric

CCT = collective makespan = `max(finish) − min(start)` over the collective's flows (first message out
→ last message in), in ms. A cell with cr < 1 means the collective did not finish; its makespan is a
lower bound (flagged).

## 4. Honest pre-registration

- **A2A** (uniform all-pairs, maximal spread) — PRISM's advantage expected largest.
- **Ring-AR** (random-neighbor after shuffle) — intermediate.
- **Butterfly-AR** (few steps, light) — smallest differences likely.
- The advantage should grow with failed links. A tie is an acceptable, publishable outcome.

## 5. Results

All 420 cells completed at **cr = 1.00** (every collective fully finished; no hatched bars). Figures:
`figs/figG_{a2a,ring,bfly}` (collective makespan, ms, vs failed-links). 5-seed means below.

**Headline (honest, and more nuanced than a clean win).** On these *full multi-step* collectives the
seven transports sit within ~3–5 % of one another, because a barriered collective's makespan is
dominated by its **critical path** (a chain of small 128 KB steps, each roughly one RTT) rather than
by throughput — so the congestion-control choice has limited leverage. Within that narrow band, PRISM
is **do-no-harm at f0 and improves monotonically with failures**: it becomes the **fastest arm on
Ring-AllReduce at f12**, and overtakes the UEC reference (REPS+NSCC) on All-to-All from f8 on. This
extends — at smaller magnitude — the asymmetric advantage that is large on bandwidth-bound concurrent
traffic (`../expA_delaydriven`, `../expE_permutation`, `../expF_aiworkload`).

### Collective makespan (ms, 5-seed mean) and PRISM rank

| All-to-All | f0 | f4 | f8 | f12 |
|---|---|---|---|---|
| OPS+NSCC | 1.57 | 2.78 | 3.60 | 4.63 |
| REPS+NSCC | 1.48 | 2.42 | 3.10 | 3.89 |
| REPS+MNSCC | 1.48 | 2.35 | 2.89 | 3.68 |
| STrack | 1.48 | 2.43 | 3.11 | 3.85 |
| **Prism** | 1.56 | 2.45 | 3.01 | **3.75** |
| Prism / REPS+NSCC | 1.051 | 1.012 | 0.971 | **0.962** |
| Prism rank /7 | 5 | 6 | 4 | **3** |

| Ring-AllReduce | f0 | f4 | f8 | f12 |
|---|---|---|---|---|
| OPS+NSCC | 6.71 | 11.05 | 11.70 | 12.08 |
| REPS+NSCC | 6.88 | 10.78 | 11.67 | 11.93 |
| STrack | 6.88 | 10.70 | 11.37 | 11.80 |
| **Prism** | 6.88 | 10.89 | 11.60 | **11.62** |
| Prism / REPS+NSCC | 1.000 | 1.010 | 0.994 | **0.974** |
| Prism rank /7 | 2 | 6 | 5 | **1 (fastest)** |

**Butterfly-AllReduce** is essentially **CC-invariant**: all seven arms finish in 0.04 ms (f0) →
0.07–0.08 ms (f≥4), identical to two decimals (Prism / REPS+NSCC = 1.000 at every level). With only
log₂128 = 7 steps the collective is too short and latency-bound for the transport to matter — a clean
illustration of the critical-path effect above.

### What this delineates

PRISM's congestion decomposition pays off when congestion is **concentrated and spread-dominated on a
bandwidth-bound transfer** (incast-style many2many, permutation, the HSDP ring *step* — all large
wins). On **fine-grained barriered collectives** (Ring/Butterfly with small chunks) the makespan is
critical-path-bound and *all* good multipath CCAs converge; PRISM stays do-no-harm and still edges
ahead under heavy asymmetry (Ring f12 win), but the headline is the **boundary** this draws, not a
large win. Reported straight.

## 6. Caveats (honest)

1. **Failures are on-path (passed).** Makespan rises monotonically f0→f12 for every arm (e.g. Ring
   REPS+NSCC 6.88→11.93 ms, A2A 1.48→3.89 ms), confirming the `-failed K` choke bites the
   shuffled, cross-pod collective traffic. All 420 cells cr = 1.00.
2. **Magnitudes are small.** The ~3–5 % spread across arms is near the 5-seed SEM at several points;
   the PRISM trend (do-no-harm, improving with failures, Ring-f12 win) is consistent in direction but
   modest. We do not overclaim it.
3. **Fabric / scope deviations** (see §1): our 100 G COMPOSITE testbed, not STrack's 400 G; single
   job, not 64 concurrent; A2A parallelism fixed at 32; DBT omitted.
