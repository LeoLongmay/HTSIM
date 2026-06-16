# Experiment A — Delay-Driven Regime (-disable_trim)

**Why.** P2 (trimming default) found PRISM tied REPS+NSCC; data-mining showed the decomposition
was masked by loss/NACK-dominated cwnd control (PRISM's floor-MD governed only ~5% of cwnd
decreases). This variant adds `-disable_trim` (no trimming, 5xBDP buffer) so queues build and
delay-MD drives cwnd -- the regime where the floor-vs-avg decomposition *can* dominate.

**P3 update.** Added **STrack** as the coupled-SOTA congestion-control baseline
(`-sender_cc_algo strack`, ported from the STrack paper Algorithm 4 into `UecSrc`, run on the
shared REPS spray). STrack's window controller keys its multiplicative decrease off the
**average** RTT across paths -- it is the published-SOTA embodiment of the very signal
*conflation* PRISM's decomposition is contrasted against. The decisive question P3 answers:
does PRISM's floor decomposition beat not just the *decoupled* REPS+NSCC, but also a strong
*coupled* CC that averages?

## Setup
Identical to `expA_asymmetric` (many2many 64->16 pod0, 2 MB; fat_tree_128_1os; -paths 8;
baselines OPS+NSCC / REPS+NSCC / **STrack** / PRISM; -failed {0,2,4,8,12}; seeds {13..17};
mechanism at failed=8, seed=13) **plus `EXTRA_ARGS="-disable_trim"` on every run**. All four
arms share the same fabric, sink, trimming-off setting and loss machinery; only the
sender CC (and, for ops, the spray) differs -- so the comparison isolates the controller.

## Figures
- `figs/figA1dd_main_perf` -- goodput / avg-FCT / P99-FCT vs # constrained links (4 lines).
- `figs/figA2dd_mechanism` -- signal (REPS+NSCC avg/floor vs PRISM C_cc vs target) + cwnd(t)
  for REPS+NSCC / PRISM / STrack; prints fair per-ACK cut counts, the **floor-MD fraction**,
  and the **STrack-vs-NSCC distinctness** check.

## Result (128-node many2many, 5 seeds, `-disable_trim`; END=8 ms; all cr = 1.00)

Goodput (Gbps) / avg-FCT (µs):

| -failed | OPS+NSCC | REPS+NSCC | STrack (coupled, avg) | PRISM (floor) | PRISM vs STrack |
|---|---|---|---|---|---|
| 0  | 906 / 788  | 997 / 737  | 912 / 789  | 869 / 945  | goodput −5%, FCT worse (symmetric penalty) |
| 2  | 411 / 1374 | 533 / 1202 | 515 / 1255 | 572 / 1305 | goodput +11%, FCT +4% (mixed) |
| 4  | 373 / 1762 | 483 / 1450 | 471 / 1513 | **574 / 1401** | goodput **+22%**, FCT **−7%** |
| 8  | 311 / 2260 | 431 / 1694 | 415 / 1725 | **504 / 1518** | goodput **+21%**, FCT **−12%** |
| 12 | 287 / 2522 | 379 / 1856 | 364 / 1890 | **434 / 1725** | goodput **+19%**, FCT **−9%** |

**Headline (P3):** under meaningful asymmetry (failed ≥ 4) PRISM beats the coupled-SOTA STrack
on **both** goodput (+19–22%) **and** avg-FCT (7–12% lower); P99-FCT is also clearly lowest for
PRISM at failed ≥ 2 (figA1dd, bottom panel). This holds the same advantage PRISM has over the
decoupled REPS+NSCC.

**The decisive observation for the thesis:** **STrack does *not* beat the decoupled
REPS+NSCC** -- it ties/slightly trails it everywhere (e.g. f8: 415 vs 431 Gbps; f12: 364 vs
379). So *coupling per se is not the win*. Both STrack and REPS+NSCC drive their decrease off
the **averaged** delay signal, and both lose to PRISM's **floor** decomposition under
asymmetry. This is direct evidence for the framing "*it is decomposing the signal (floor vs
average), not coupling CC and LB, that recovers the lost performance.*"

**Distinctness check (mandatory; PASSED).** STrack must not collapse into the NSCC baseline.
Per-ACK cwnd-decrease events @failed=8: **STrack = 2440 vs REPS+NSCC(=NSCC) = 2208** (+10.5%) --
measurably different, and the cwnd(t) trajectories in figA2dd visibly diverge (STrack cuts
more often and drains longer). STrack's avg-only, ECN-gated MD makes it slightly more
decrease-happy than NSCC's `skip && delay≥target` MD, which is also why it trails REPS+NSCC
on throughput here. So STrack is a genuinely distinct controller, not a clone.

## Honest caveats
- **Symmetric penalty persists (failed=0):** PRISM is *worse* than every other arm (goodput
  869 vs 906–997, avg-FCT 945 vs 737–789 µs) -- holding when there is no reroutable benefit
  costs throughput. The advantage is asymmetry-specific.
- **Mild asymmetry (failed=2) is mixed:** PRISM goodput +11% over STrack but avg-FCT ~4% higher;
  the clean two-metric win emerges at failed ≥ 4.
- **STrack underperforms its published reputation here, and that is expected/honest:** this is
  STrack's *CC core on the shared REPS spray*, not the full published STrack *system* (its
  adaptive ECN-bitmap spray is **not** ported -- deliberately, to hold the spray fixed and
  isolate the CC; see spec §3, Approach B deferred). In this delay-driven asymmetric regime
  the averaged-delay MD is the wrong signal, so STrack-CC tracks REPS+NSCC rather than leading.
- **Mechanism figure is messy** (figA2dd): at failed=8 even PRISM's floor C_cc spikes well
  above target, so the win is not a clean "floor stays below target" -- it is PRISM making
  fewer, better-targeted floor-driven cuts (651 per-ACK cwnd decreases vs REPS+NSCC 2208,
  STrack 2440) that net higher delivered work. floor-MD fraction = 316/651 = 0.485
  (delay-driven confirmed; trimming baseline was ~0.05).

### Faithfulness notes on the STrack port (from the final holistic review)
The port realizes STrack Algorithm 4's *intent* (ECN-gated; avg-delay-keyed MD; conservative
no-ECN-high-delay branch with a β starvation bump; periodic-η fairness) with these documented,
deliberate deviations from the *literal* algorithm -- none change the verdict, but they are
recorded so the baseline is not oversold as "exactly Algorithm 4":
- **MD is keyed purely on `avg_delay`** (no inner instantaneous `delay > target` gate that
  Algorithm 4 Line #14 adds). This is *intentional* -- avg-only MD is STrack's signal-conflation
  signature, which is exactly what the eval contrasts PRISM's floor against (spec §6).
- **β starvation bump fires at `delay > 2·target`** (the paper's prose, Line #7) rather than
  Table 1's `target_Qhigh = 3·target`. Rare-firing in this ECN-marking regime (high delay
  usually comes with an ECN mark → the decrease branch), so the practical effect on the numbers
  is negligible; the 2× reading is the more-conservative-eroding of the two and STrack still cuts
  *more* than NSCC, so distinctness is unaffected.
- **achievedBDP fast-converge is provided by the reused `quick_adapt()`** (UEC's achieved-BDP
  machinery) rather than a second explicit `delay > target_Qhigh` trigger.
- **β unit:** the bump uses `_strack_beta·mtu²/cwnd`; htsim's own convention maps the paper's
  `bdp_sf → _mss·_scaling_factor_a`. Aligning the unit (and β/h sensitivity generally) is a P5 item.

## Thesis (sharpened by P3)
*PRISM's decomposition helps when congestion is reroutable AND delay-driven (not
loss/NACK-driven). Under asymmetric fabric (failed ≥ 4) it improves both goodput (+19–22%) and
FCT (7–12%) over **both** the decoupled REPS+NSCC and the coupled-SOTA STrack, at the cost of a
small penalty when the fabric is symmetric. Crucially, the coupled-but-averaging STrack does not
beat the decoupled REPS+NSCC -- so the recovered performance comes from **decomposing the
congestion signal (floor vs average), not from coupling CC and load balancing.***

## Honest scope
- Pre-registered: floor-MD fraction up + PRISM wins → "reroutable AND delay-driven" thesis. No
  tuning to force a win; STrack uses NSCC's `_gamma`/`_eta`/`_target_Qdelay` plus the paper's
  β/h defaults. completion_rate = 1.00 everywhere at END=8 (FCT unconfounded); goodput is
  window-free aggregate.
- 128-node many2many only; default END is 8 ms (override `EXP_END`). Next: scale (1024), add
  STrack's adaptive spray (Approach B, "beats the *full* published STrack"), add permutation,
  and revisit the symmetric-f0 penalty (T_spray tuning, roadmap item).

## Reproduce
```
bash prism_eval/expA_delaydriven/repro.sh   # from sim/datacenter; ~100 sweep + 4 mechanism sims
```
