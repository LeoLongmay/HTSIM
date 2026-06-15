# Experiment A — Asymmetric Fabric (PRISM vs OPS+NSCC vs REPS+NSCC)

**Claim.** Under fabric asymmetry, congestion is largely *reroutable* (a clean path still
exists). PRISM should preserve goodput / lower FCT by *holding* (not cutting) the window when
the floor is below target, whereas REPS+NSCC cuts because its average queuing delay is inflated
by the path spread.

## Setup
- Topology `fat_tree_128_1os.topo` (128 hosts, 1:1), `-paths 8`, `-end 2` (ms).
- Workload `many2many` pairs: 64 senders outside pod0 -> 16 pod0 receivers, 2 MB each.
- Baselines: OPS+NSCC (`nscc`,`oblivious`), REPS+NSCC (`nscc`,`reps`), PRISM (`prism`,`reps`).
- Asymmetry `-failed {0,2,4,8,12}`; seeds {13..17}; mechanism trace at failed=8, seed=13.

## Figures
- `figs/figA1_main_perf` — goodput / avg-FCT / P99-FCT vs # constrained links, 3 baselines, error bars (std over seeds).
- `figs/figA2_mechanism` — (a) the signal each controller reacts to (REPS+NSCC avg delay + the floor it ignores vs PRISM floor C_cc, vs target); (b) cwnd(t) PRISM vs REPS+NSCC. Window-cut counts printed by make_figs.

## Result (128-node many2many, 5 seeds; commit at run time; END=2 ms)

**Honest summary: the mechanism works as designed, but the headline performance advantage over
REPS+NSCC does NOT appear in this slice — PRISM ties REPS+NSCC; both clearly beat OPS+NSCC.**

Goodput (Gbps) / avg FCT (µs) / completion vs `-failed` (`figA1_main_perf`):

| -failed | OPS+NSCC | REPS+NSCC | PRISM |
|---|---|---|---|
| 0  | 1117 / 653 / 1.00 | 1282 / 628 / 1.00 | 1263 / 635 / 1.00 |
| 2  | 841 / 739 / 1.00  | 1005 / 675 / 1.00 | 971 / 689 / 1.00 |
| 4  | 664 / 874 / 1.00  | 850 / 744 / 1.00  | 843 / 757 / 1.00 |
| 8  | 471 / 1188 / 0.91 | 709 / 925 / 1.00  | 710 / 955 / 1.00 |
| 12 | 312 / 1365 / 0.60 | 521 / 1288 / 0.99 | 530 / 1290 / 0.99 |

- **PRISM ≈ REPS+NSCC** on goodput and FCT at every asymmetry level (within ~2% / overlapping
  error bars). PRISM is not worse, but shows no goodput/FCT advantage here.
- **Both beat OPS+NSCC** substantially as asymmetry grows (e.g. f8 goodput 710 vs 471). OPS also
  collapses on completion (cr 0.91@f8, 0.60@f12) — its FCT is over only the flows that finished,
  so it understates OPS's true cost; the goodput + completion together show OPS struggling.
- **Mechanism (`figA2_mechanism`, failed=8): PRISM cut its window 141 times vs REPS+NSCC's 3155
  (~22× fewer).** So the decomposition demonstrably suppresses cutting (epoch-granular floor
  decision vs NSCC's per-ACK avg-delay cut). BUT at failed=8 the floor `C_cc` is frequently
  *above* the 6 µs target (congestion is not purely reroutable when 8 of the ingress links are
  degraded), so PRISM does decrease at times, and its cwnd tracks slightly *below* REPS+NSCC.

**Why no win, honestly:** REPS+NSCC's many small per-ACK cuts evidently do not cost it
throughput here — adaptive spraying keeps it well utilized, and the few-vs-many cut distinction
does not translate into goodput/FCT at this scale/load. PRISM's advantage thesis (avoid cuts
when reroutable → preserve utilization) is not demonstrated in this 128-node many2many slice.

**Implication / next:** finding a regime where reduced cutting actually translates to throughput
needs either (a) a more cleanly *reroutable* setting where the floor stays below target (lighter
load / fewer constrained links / more clean-path diversity), or (b) a genuinely cwnd-limited
bottleneck where NSCC's cutting throttles delivery (oversubscribed/incast, P4). This slice is a
faithful de-risk result, not a tuned win.

## Honest scope
- FCT is over *completed* flows; completion_rate is reported per cell (incomplete-flow skew is surfaced, not hidden).
- Goodput is window-free aggregate (total delivered bytes / makespan).
- First de-risk slice at 128 nodes, many2many only. 1024-node scale + permutation workload + STrack baseline are deferred (P2 follow-on / P3).

## Reproduce
```
bash prism_eval/expA_asymmetric/repro.sh    # from sim/datacenter; ~75 sweep + 3 mechanism sims
```
Pinned commit; deterministic `-seed`; raw data under `data/` gitignored; figures committed with `git add -f`.
