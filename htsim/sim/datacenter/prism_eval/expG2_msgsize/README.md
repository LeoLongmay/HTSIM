# expG2_msgsize — collective CCT-slowdown vs message size (A2A / Butterfly-AR), fixed failed=8

## 1. What this group tests

The message-size companion to `../expG_collectives`. expG fixes the per-flow message at 128 KB and
sweeps **failed-links**; expG2 fixes **`-failed 8`** and sweeps the **per-flow message size**. The
question: a barriered collective is latency-bound when each step is sub-BDP (all transports tie), but
as the message grows past one BDP each step becomes bandwidth-bound, where PRISM's congestion
decomposition (floor→CC, spread→spraying) should pull ahead. This figure makes that transition visible.

Figure conventions follow **STrack** (Le et al., line chart of completion time vs message size) and
**MSwift/PRISM** (Gerstein et al. 2026, CCT normalized to a zero-queue lower bound). Generators are
reused unchanged from expG (`coll_alltoall.py`, `coll_butterfly.py`); only `flowsize` is swept.

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

CCT slowdown = collective makespan / zero-queue lower bound, where the lower bound for a k-step
barriered collective is `k × (base_rtt + size·8/linkrate)` (base_rtt 14 µs, link 100 G). By
construction the slowdown is ≥ 1. A point whose completion-rate < 1 (collective did not fully finish)
is drawn with a hollow marker and is a lower bound.

## 4. Honest pre-registration

- **A2A**: arm lines expected to converge (tie) at small sizes (latency-bound) and separate at large
  sizes with PRISM lowest (bandwidth-bound, spread-dominated) — the crossover is the headline.
- **Butterfly**: expected near-flat, arms ~equal at every size (only 7 steps → critical-path-bound
  regardless of message size; CC-invariant) — a control showing some collectives never become
  transport-sensitive.
- A tie even at 4 MB is an acceptable, publishable outcome. Reported straight.

## 5. Results

_(Filled after the sweep in Task 4: figures `figs/figH_a2a_msgsize`, `figs/figH_bfly_msgsize`,
`figs/figH_legend`; 5-seed-mean slowdown tables; cr audit; the crossover-or-null verdict.)_
