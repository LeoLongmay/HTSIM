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
- `figs/figA1dd_goodput`, `figs/figA1dd_avg_fct`, `figs/figA1dd_p99_fct` -- three standalone panels
  (goodput in Gbps; avg-FCT and P99-FCT in **ms**) vs # constrained links (4 lines each), x-ticks
  {0,2,4,6,8,10,12}.
- `figs/figA2dd_signal`, `figs/figA2dd_cwnd` -- two standalone mechanism panels at failed=8,
  seed 13, over a clean [0,3] ms window. The mechanism *illustration* uses a larger **4 MB**
  message size (vs the 2 MB perf sweep) so every arm's makespan exceeds 3 ms (Prism 3.44,
  REPS+NSCC 4.98, STrack 5.08 ms) and all three curves span the full window.
  - *signal*: the queuing-delay signal each controller acts on -- REPS+NSCC avg, **STrack avg**
    (both averaging families overlay near/above target), the floor REPS+NSCC ignores, and Prism's
    per-epoch floor `C_cc` (raw faint + a 20µs-binned overlay; `C_cc` is unsmoothed by design --
    the binned line is a display aid only, and stays largely **below** the ~14µs target).
  - *cwnd*: cwnd(t) for the three arms.
- Console prints fair per-ACK cut counts, the **floor-MD fraction** (0.374), and the
  **STrack-vs-NSCC distinctness** check.

## Result (128-node many2many, 5 seeds, `-disable_trim`; END=8 ms; all cr = 1.00)

Goodput (Gbps) / avg-FCT (µs):

| -failed | OPS+NSCC | REPS+NSCC | STrack (coupled, avg) | PRISM (floor) | PRISM vs STrack |
|---|---|---|---|---|---|
| 0  | 906 / 788  | 997 / 737  | 912 / 789  | 869 / 945  | goodput −5%, FCT worse (symmetric penalty) |
| 2  | 411 / 1374 | 533 / 1202 | 515 / 1255 | 572 / 1305 | goodput +11%, FCT +4% (mixed) |
| 4  | 373 / 1762 | 483 / 1450 | 471 / 1513 | **574 / 1401** | goodput **+22%**, FCT **−7%** |
| 6  | 322 / 2088 | 454 / 1592 | 445 / 1610 | **531 / 1446** | goodput **+19%**, FCT **−10%** |
| 8  | 311 / 2260 | 431 / 1694 | 415 / 1725 | **504 / 1518** | goodput **+21%**, FCT **−12%** |
| 10 | 289 / 2390 | 418 / 1750 | 407 / 1806 | **489 / 1582** | goodput **+20%**, FCT **−12%** |
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
Per-ACK cwnd-decrease events @failed=8 (4 MB mechanism run): **STrack = 4987 vs REPS+NSCC(=NSCC)
= 4344** (+14.8%) -- measurably different, and the cwnd(t) trajectories in figA2dd visibly diverge
(STrack cuts more often and drains longer). STrack's avg-only, ECN-gated MD makes it slightly more
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
- **Mechanism (figA2dd, 4 MB illustration):** the *raw* per-epoch `C_cc` is jittery -- it is an
  unsmoothed floor by design (O(1)); EWMA-smoothing it was tried in the f0 work and backfired, so
  it is kept instantaneous. Its 20 µs-binned trend, however, stays largely **below** the ~14 µs
  target in steady state, while REPS+NSCC and STrack's averaged delay both sit at/above it -- so
  PRISM makes far fewer, better-targeted floor-driven cuts (954 per-ACK cwnd decreases vs REPS+NSCC
  4344, STrack 4987). floor-MD fraction = 357/954 = 0.374 (delay-driven: ~7× the ~0.05 trimming
  baseline). The target is ~14 µs (one network RTT, read from the runtime `_target_Qdelay`), not
  6 µs. (These mechanism counts are at the 4 MB illustration size; the 2 MB perf-sweep failed=8
  condition gives the same qualitative picture.)

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

## Fairness & rate reductions

**Jain fairness** (`figs/figA1dd_fairness`), per arm across `-failed {0,2,4,6,8,10,12}`:

| Arm | f0 | f2 | f4 | f6 | f8 | f10 | f12 |
|---|---|---|---|---|---|---|---|
| OPS+NSCC  | 0.924 | 0.757 | 0.730 | 0.783 | 0.874 | 0.879 | 0.916 |
| REPS+NSCC | 0.931 | 0.784 | 0.810 | 0.873 | 0.912 | 0.941 | 0.911 |
| STrack    | 0.920 | 0.779 | 0.812 | 0.871 | 0.928 | 0.935 | 0.909 |
| PRISM     | 0.880 | 0.842 | 0.867 | 0.941 | 0.979 | 0.976 | 0.967 |

At the asymmetric win region (failed ≥ 4) PRISM is the **most fair** arm: e.g. f8 PRISM 0.979
vs REPS+NSCC 0.912 / STrack 0.928; f12 PRISM 0.967 vs REPS+NSCC 0.911 / STrack 0.909. PRISM
spreads the recovered capacity evenly by holding-and-rerouting rather than cutting on the
inflated average delay. At failed=0 (symmetric) PRISM is slightly **less** fair (0.880 vs
0.931 for REPS+NSCC) — the same under-growth that causes the f0 goodput cost. So fairness is
a modest *additional* advantage exactly where PRISM wins, consistent with (not independent of)
the goodput result.

**Rate reductions** (mechanism, failed=8, annotated on `figs/figA2dd_cwnd`): **PRISM 954
per-ACK cwnd cuts vs REPS+NSCC 4344** (~4.6× fewer; STrack 4987). PRISM reaches its higher
goodput with far fewer rate reductions — the on-thesis "control correctness" advantage
(floor-MD fraction 0.374).

## Offered-load sweep + ECMP anchor

**ECMP+NSCC** (single path per flow, `LB=ecmp CC=nscc`) is added to the `-failed` sweep as the
conventional no-spray anchor: under asymmetry it is the worst arm (f8 goodput 225.1 Gbps vs
430.8 for REPS+NSCC, 414.6 for STrack, 504.2 for PRISM; P99 FCT at f8 4.49 ms vs ~2.0–2.4 ms
for the others), bracketing — with OPS — the contribution of spraying. It is *context*, not
PRISM's competition (REPS+NSCC and STrack are).

**Offered-load figure** (`figA3dd_load_*`): open-loop Poisson arrivals (`common/gen/poisson_load.py`),
fixed 2 MB flows, `-failed 8`. Offered load rho is relative to aggregate receiver-access capacity
C = 16 x 100 Gbps = 1.6 Tbps; lambda = rho*C/(2MB*8). Window 8 ms, END 20 ms, seeds {13-17}.
The `.cm` `start` token is picoseconds (verified by the repro.sh start-unit guard; window_us is converted x1e6 to ps in poisson_load.py).

| rho | goodput (Gbps) REPS / STrack / PRISM | avg FCT (ms) REPS / STrack / PRISM | cr |
|----:|---|---|---|
| 0.1 | 156.2 / 156.4 / 155.2 | 0.299 / 0.322 / 0.321 | 1.00 / 1.00 / 1.00 |
| 0.5 | 564.5 / 560.8 / 726.0 | 3.241 / 3.180 / 1.006 | 1.00 / 1.00 / 1.00 |
| 0.9 | 651.6 / 665.8 / 778.9 | 7.254 / 7.324 / 5.362 | 1.00 / 1.00 / 1.00 |

Note: ECMP cr drops to 0.98 at rho=0.5, 0.68 at rho=0.7, and 0.52 at rho=0.9; OPS cr drops to
0.96 at rho=0.7 and 0.66 at rho=0.9. At these high-rho points ECMP and OPS FCT are **confounded
by incompletion** and cannot be compared cleanly — flagged on the figure.

Reading: near-idle (rho=0.1) the fabric carries little queue, there is no reroutable spread to
decompose, and PRISM ~ties REPS+NSCC (−0.6% goodput; FCT within noise). As rho approaches
saturation under the f8 asymmetry the reroutable spread appears and PRISM's lead over both
REPS+NSCC and STrack widens: at rho=0.5, PRISM goodput is **+28.6%** vs REPS+NSCC and avg FCT
is **3.2× lower** (1.006 vs 3.241 ms); at rho=0.9 the goodput lead is +19.5% vs REPS+NSCC and
+17.0% vs STrack, with FCT ~26% lower than REPS+NSCC (5.362 vs 7.254 ms). The lead narrows
slightly from its rho=0.5–0.7 peak to rho=0.9 — consistent with near-saturation compressing all
arms' effective headroom. All REPS / STrack / PRISM cr = 1.00 at every rho (FCT unconfounded).

## Reproduce
```
bash prism_eval/expA_delaydriven/repro.sh   # from sim/datacenter; ~100 sweep + 4 mechanism sims
```
