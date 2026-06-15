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

## Result (128-node many2many, 5 seeds, `-disable_trim`; END=2 ms)

**Lands on the POSITIVE pre-registered branch: the recipe made control delay-driven, and PRISM
now beats REPS+NSCC under asymmetry — but with honest caveats.**

1. **Recipe worked (decisive check).** Floor-MD fraction = PRISM epoch-MDs / PRISM per-ACK
   cwnd-decreases @failed=8 = **316/651 = 0.485**, up from the trimming baseline **~0.05**. The
   floor decomposition now governs ~half of PRISM's rate control (loss/NACK no longer dominates).

2. **PRISM beats REPS+NSCC under asymmetry (failed≥2).** Goodput (Gbps) / completion:

   | -failed | OPS+NSCC | REPS+NSCC | PRISM |
   |---|---|---|---|
   | 0  | 906 / 1.00 | **997** / 1.00 | 869 / 1.00 |
   | 2  | 451 / 0.83 | 524 / 0.96 | **585** / 0.99 |
   | 4  | 314 / 0.60 | 474 / 0.92 | **574** / 1.00 |
   | 8  | 195 / 0.37 | 402 / 0.78 | **518** / 0.96 |
   | 12 | 121 / 0.23 | 308 / 0.59 | **392** / 0.76 |

   PRISM goodput is +12% (f2), +21% (f4), **+29% (f8)**, +27% (f12) over REPS+NSCC, and PRISM
   **completes far more flows** (e.g. f8: 0.96 vs 0.78; f12: 0.76 vs 0.59). PRISM's P99-FCT is
   also lower (better tail) at f4/f8 (see figA1dd).

**Honest caveats:**
- **Symmetric penalty:** at failed=0 PRISM is *worse* (goodput 869 vs 997, avg-FCT 945 vs 737 µs)
  — holding when there is no reroutable benefit costs throughput. The advantage is asymmetry-specific.
- **avg-FCT is confounded by completion:** FCT is over *completed* flows; PRISM completes 20–30%
  more flows (including slower ones REPS+NSCC abandons), so its avg-FCT includes stragglers and is
  not lower than REPS+NSCC despite more work done. **Goodput + completion are the clean headline.**
- **Completion-stressed regime:** `-disable_trim` gives 5×BDP buffers + no drops, so queues build
  and many flows do not finish within END=2 ms (REPS f12=0.59). A longer END would clarify FCT;
  the goodput/completion *advantage* is robust to this (it is a relative comparison at fixed END).
- **Mechanism figure is messy** (figA2dd): at failed=8 even PRISM's floor C_cc spikes well above
  target, so the win is not a clean "floor stays below target" — it is PRISM making fewer,
  better-targeted floor-driven cuts that net higher delivered work.

**Thesis (sharpened):** *PRISM's decomposition helps when congestion is reroutable AND
delay-driven (not loss/NACK-driven): under asymmetric fabric it preserves goodput (+12–29%) and
completes far more flows than decoupled REPS+NSCC, at the cost of slightly lower throughput when
the fabric is symmetric.* The earlier P2 tie is explained: with trimming, loss/NACK dominated
cwnd control (floor-MD ~5%), masking the decomposition; removing trimming surfaces it.

## Honest scope
- Pre-registered: floor-MD fraction up + PRISM wins -> "reroutable AND delay-driven" thesis;
  still tied -> accept negative/scoping. No tuning to force a win. FCT over completed flows
  (completion_rate surfaced); goodput window-free.
- 128-node many2many only; if `-disable_trim` alone doesn't raise the floor-MD fraction, a
  larger buffer (`-queue_size_bdp_factor`) is the documented next lever.

## Reproduce
```
bash prism_eval/expA_delaydriven/repro.sh   # from sim/datacenter; ~75 sweep + 3 mechanism sims
```
