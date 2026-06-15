# Experiment A — Delay-Driven Regime (-disable_trim)

**Why.** P2 (trimming default) found PRISM tied REPS+NSCC; data-mining showed the decomposition
was masked by loss/NACK-dominated cwnd control (PRISM's floor-MD governed only ~5% of cwnd
decreases). This variant adds `-disable_trim` (no trimming, 5xBDP buffer) so queues build and
delay-MD drives cwnd -- the regime where the floor-vs-avg decomposition *can* dominate.

## Setup
Identical to `expA_asymmetric` (many2many 64->16 pod0, 2 MB; fat_tree_128_1os; -paths 8; -end 2;
baselines OPS+NSCC / REPS+NSCC / PRISM; -failed {0,2,4,8,12}; seeds {13..17}; mechanism at
failed=8, seed=13) **plus `EXTRA_ARGS="-disable_trim"` on every run**.

## Figures
- `figs/figA1dd_main_perf` -- goodput / avg-FCT / P99-FCT vs # constrained links.
- `figs/figA2dd_mechanism` -- signal (REPS+NSCC avg/floor vs PRISM C_cc vs target) + cwnd(t);
  prints fair per-ACK cut counts and the **floor-MD fraction** (decisive: trimming baseline ~0.05).

## Result (128-node many2many, 5 seeds, `-disable_trim`; END=8 ms)

**POSITIVE pre-registered branch. END=8 ms (the 5×BDP no-trim regime needs time to drain; an
earlier END=2 ms pass, commit 9c841ae, was completion-stressed). At END=8 every cell completes
fully (completion_rate = 1.00 everywhere), so FCT is unconfounded — and PRISM wins on BOTH
goodput and FCT under asymmetry.**

1. **Recipe worked (decisive check).** Floor-MD fraction = PRISM epoch-MDs / PRISM per-ACK
   cwnd-decreases @failed=8 = **316/651 = 0.485**, up from the trimming baseline **~0.05** — the
   floor decomposition now governs ~half of PRISM's rate control (loss/NACK no longer dominates).

2. **PRISM beats REPS+NSCC under asymmetry (all completion = 1.00).** Goodput (Gbps) / avg-FCT (µs):

   | -failed | OPS+NSCC | REPS+NSCC | PRISM | PRISM vs REPS |
   |---|---|---|---|---|
   | 0  | 906 / 788  | **997 / 737** | 869 / 945  | worse (symmetric penalty) |
   | 2  | 411 / 1374 | 533 / 1202   | 572 / 1305 | goodput +7%, FCT +9% (mixed) |
   | 4  | 373 / 1762 | 483 / 1450   | **574 / 1401** | goodput +19%, FCT −3% |
   | 8  | 311 / 2260 | 431 / 1694   | **504 / 1518** | goodput +17%, FCT −10% |
   | 12 | 287 / 2522 | 379 / 1856   | **434 / 1725** | goodput +15%, FCT −7% |

   Under meaningful asymmetry (failed ≥ 4) PRISM wins on **both** goodput (+15–19%) **and** avg-FCT
   (3–10% lower); P99-FCT is also clearly lowest for PRISM at failed ≥ 2 (see figA1dd). Both beat
   OPS+NSCC by a wide margin.

**Honest caveats:**
- **Symmetric penalty:** at failed=0 PRISM is *worse* (goodput 869 vs 997, avg-FCT 945 vs 737 µs)
  — holding when there is no reroutable benefit costs throughput. The advantage is asymmetry-specific.
- **Mild asymmetry (failed=2) is mixed:** PRISM goodput +7% but avg-FCT ~9% higher; the clear
  two-metric win emerges at failed ≥ 4.
- **Mechanism figure is messy** (figA2dd): at failed=8 even PRISM's floor C_cc spikes well above
  target, so the win is not a clean "floor stays below target" — it is PRISM making fewer,
  better-targeted floor-driven cuts (651 vs REPS+NSCC's 2208 per-ACK cwnd decreases) that net
  higher delivered work.

**Thesis (sharpened):** *PRISM's decomposition helps when congestion is reroutable AND
delay-driven (not loss/NACK-driven): under asymmetric fabric (failed ≥ 4) it improves both
goodput (+15–19%) and FCT (3–10%) over decoupled REPS+NSCC, at the cost of slightly worse
throughput/FCT when the fabric is symmetric.* The earlier P2 tie is explained: with trimming,
loss/NACK dominated cwnd control (floor-MD ~5%), masking the decomposition; removing trimming
surfaces it.

## Honest scope
- Pre-registered: floor-MD fraction up + PRISM wins -> "reroutable AND delay-driven" thesis
  (this branch). No tuning to force a win. completion_rate = 1.00 everywhere at END=8 (FCT
  unconfounded); goodput is window-free aggregate.
- 128-node many2many only; default END is 8 ms (override `EXP_END`). Next: scale (1024) and add
  STrack + permutation in this regime.

## Reproduce
```
bash prism_eval/expA_delaydriven/repro.sh   # from sim/datacenter; ~75 sweep + 3 mechanism sims
```
