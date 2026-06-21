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

*(filled after `bash repro.sh`; figures `figs/figG_{a2a,ring,bfly}`.)*

## 6. Caveat

The failed links must lie on paths the (shuffled, cross-pod) collective traffic traverses; if a
degraded point shows makespan indistinguishable from f0 across **all** arms, the failures are off-path
and the failure model/location must be revisited (see the smoke check in the plan).
