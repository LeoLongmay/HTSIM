# expE_permutation — permutation traffic × failed-links

## 1. What this group tests

Whether PRISM's **delay-driven asymmetric-fabric advantage** — shown on the incast-style many2many
workload in `../expA_delaydriven` (128) and `../expD_scale1024` (1024) — **generalizes to a uniform
random permutation**, the standard load-balancer benchmark used by STrack and MSwift. A permutation
has **no incast and no receiver oversubscription**, so any difference is attributable to the fabric
(failed links), not a fan-in hotspot. This adds the comparability point those papers expect and
addresses the "PRISM only wins on a contrived incast" critique.

**Pre-registered expectation:**
- **f0 (symmetric permutation):** the canonical LB benchmark; spraying arms balance evenly. PRISM is
  expected to be **do-no-harm or carry a small f0-style cost** (the transient-spread under-growth of
  `../expA_f0_diagnosis`) — **not a win**.
- **f>0 (asymmetric):** PRISM's spread-aware decomposition should avoid degraded paths → **modest win
  or at least do-no-harm**. A **tie everywhere is an acceptable result** (do-no-harm on the standard
  benchmark).

## 2. Setup

| Parameter | P1 (128) | P2 (1024) |
|---|---|---|
| Topology | `fat_tree_128_1os.topo` (3-tier, 100G, 1:1) | `fat_tree_1024.topo` (3-tier, 100G, 1:1) |
| Failed-link sweep | {0,2,4,6,8,10,12} | {0,8,16,24,32,40,48} |
| Workload | full random permutation, 2 MB/flow, per-seed | full random permutation, 2 MB/flow, per-seed |
| Regime | delay-driven (`-disable_trim`), END=8 ms, PATHS=8 | same (sequential; shared idmap) |
| Arms | OPS+NSCC, REPS+NSCC, REPS+Swift, REPS+MSwift, REPS+MNSCC, STrack, Prism | same |
| Seeds | 13–17 | 13–17 |

**One-command repro:** `bash repro.sh`. Raw data gitignored; figures committed with `git add -f`.

## 3. Caveat (honest)

`permutation.py` produces a **random derangement** (the standard permutation, as in STrack/MSwift),
not a guaranteed cross-pod matching. On 128 nodes (8 pods) ≈ 1/8 of pairs land **intra-pod** and do
not traverse the core, so failed **core** links bite only the ≈ 7/8 cross-pod flows. This is inherent
to a uniform permutation and is noted, not engineered around.

## 4. Results

Rendered figures: `figs/figE_p128_{goodput,avg_fct,p99_fct}` and `figs/figE_p1024_{...}`. The 5-seed
mean tables are added here after `repro.sh` completes (numbers reported straight whichever way they land).
