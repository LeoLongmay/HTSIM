# Experiment A — Loss/NACK Decomposition (trimming regime)

**Why.** P2 (trimming default) tied because loss/NACK-driven control masked PRISM's delay
decomposition (floor-MD ~5%). This group adds PRISM's loss decomposition (`-prism_loss_decomp 1`):
hold the window on reroutable (concentrated) loss, cut on uniform/last-hop loss. Tests whether it
turns the P2 tie into a win in the trimming regime.

## Setup
Trimming-default Exp A (P2 setup: many2many 64->16 pod0 2MB; fat_tree_128_1os; -paths 8; END=2;
NO -disable_trim; -failed {0,2,4,8,12}; seeds {13..17}). 4 arms: OPS+NSCC, REPS+NSCC,
PRISM (delay-only, flag off), PRISM (+loss-decomp, flag on). Mechanism at failed=8, seed=13.

## Figures
- `figs/figL1_main_perf` -- goodput / avg-FCT / P99-FCT vs # constrained links (4 lines).
- `figs/figL2_mechanism` -- signal + cwnd(t); prints the **loss-HOLD fraction** (fabric NACKs held
  / total) -- the loss analog of the delay floor-MD fraction.

## Result (128-node many2many, 5 seeds, trimming default, END=2)

**NEGATIVE on the crux question, reported straight.** The loss decomposition *activates* but does
**not** turn the P2 tie into a win. Goodput (Gbps) / avg-FCT (µs):

| -failed | OPS+NSCC | REPS+NSCC | PRISM (delay-only) | PRISM (+loss-decomp) |
|---|---|---|---|---|
| 0  | 1117 / 653  | 1282 / 628 | 1263 / 635 | 1266 / 637 |
| 2  | 841 / 739   | 1005 / 675 | 971 / 689  | 994 / 686 |
| 4  | 664 / 874   | 850 / 744  | 843 / 757  | 858 / 746 |
| 8  | 471 / 1188 (cr 0.91) | 709 / 925 | 710 / 955 | 705 / 934 |
| 12 | 312 / 1365 (cr 0.60) | 521 / 1288 | 530 / 1290 | 537 / 1270 |

*(only OPS+NSCC collapses on completion at high failure; all REPS/PRISM arms cr = 0.99–1.00.)*

**The decomposition IS active** (mechanism worked): loss-HOLD fraction @failed=8 = **1053/5933 =
0.177** — PRISM holds its window on ~18% of fabric trim-NACKs (classified reroutable), vs the
delay floor-MD fraction still ~0.052 (delay stays masked by trimming, as in P2). So in the
trimming regime PRISM *does* switch from delay-decomposition to loss-decomposition.

**But it does NOT produce a win.** `PRISM (+loss-decomp)` ties **both** `PRISM (delay-only)` and
`REPS+NSCC` at every failure level — goodput within ±2–3% and avg/P99-FCT comparable, all inside
the 5-seed error bars (figL1: the blue/green/red lines overlap; only gray OPS is clearly worse).
The marginal +1–3% at f4/f12 is within noise. completion_rate stays 0.99–1.00 (the time-based
safety valve bounds holding; no unsafe-hold collapse).

**Why (honest mechanism read).** In the trimming regime REPS already reroutes away from a
trimming path on every PATH_NACK, and NSCC's loss response is well-tuned; trimming keeps queues
shallow so there is little cwnd headroom for "hold instead of cut" to convert into delivered work.
Holding the window on the ~18% reroutable NACKs neither helps (REPS already handles the rerouting)
nor hurts (valve-bounded). The asymmetric advantage PRISM shows in the **delay-driven** regime
(deep 5×BDP queues, delay-MD: +25–33% over REPS/STrack) does **not** transfer to the trimming
regime via loss decomposition.

**Crux verdict.** *PRISM's decomposition advantage is regime-specific.* It is strong when
congestion is reroutable AND delay-driven (large-buffer / no-trim fabrics); under the trimming
UEC-default regime, decomposing the loss signal activates but yields no advantage — PRISM ties
REPS+NSCC, just as in P2. This sharpens, rather than removes, the "when does the conflation
matter" boundary: the trim-masking is a genuine regime limit, not an implementation gap. (The
negative result is robust under the sound time-valve implementation — a holistic review found and
fixed an epoch-gated-valve unsoundness before this run; results were materially unchanged.)

**Honest caveats.** CC-only PRISM on the shared REPS spray (the full published-STrack adaptive
spray is not ported — Approach B deferred); 128-node; one loss-decomposition design
(hold-on-concentrated-loss) — a different design might behave differently, but this faithful
loss-analog of the delay rule did not help. β/streak-cap not swept (P5).

## Reproduce
```
bash prism_eval/expA_lossdecomp/repro.sh   # from sim/datacenter; ~100 sweep + 3 mechanism sims
```
