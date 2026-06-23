# PRISM Parameter Sensitivity (delay-driven regime)

**Why.** This is the consolidated parameter-sensitivity / robustness section (roadmap P5).
It measures how sensitive PRISM's asymmetric advantage is to the three knobs reachable via
existing flags, with **no controller change** (PRISM remains O(1), zero new state).  The
three knobs are `T_spray` (spread tolerance), `T_cc` (shared NSCC queuing target), and
`kappa` (epoch multiplier).

## Setup

128-node delay-driven (`-disable_trim`), many2many 64→16 pod0 2 MB (byte-identical `m2m.cm`),
seeds {13–17}, END=8, failed {0, 8}.  The default center (T_spray=14 µs / T_cc=14 µs /
kappa=1) is reused read-only from `../expA_delaydriven` — no re-runs.  160 new runs cover the
OFAT bracket below.

| Knob | Flag | Default | Bracket |
|------|------|---------|---------|
| `T_spray` | `-prism_t_spray` | **14 µs** | 7, 10, **14**, 20, 28 µs |
| `T_cc`    | `-target_q_delay` | **14 µs** | 7, 10, **14**, 20, 28 µs |
| `kappa`   | `-prism_kappa`    | **1**      | 0.25, 0.5, **1**, 2, 4  |

Figure: `figs/figK_sensitivity.{pdf,png}` (one panel per knob; PRISM goodput and f8-vs-REPS
advantage normalised to REPS's own performance at each setting).

## Results

### T_spray

PRISM's asymmetric win is **robust** to T_spray over the full 0.5–2× bracket.

| T_spray (µs) | f0 goodput (Gbps) | f8 goodput (Gbps) | f8 vs REPS |
|---|---|---|---|
| 7  | 879 | 525 | +21.8% |
| 10 | 879 | 524 | +21.5% |
| **14 (default)** | **869** | **504** | **+17.0%** |
| 20 | 857 | 495 | +14.9% |
| 28 | 841 | 490 | +13.8% |

The win is preserved across the entire bracket (+13.8 .. +21.8%); f0 goodput is stable (841–879
Gbps, no sustained harm). The monotonic trend (lower T_spray → bigger win) is already documented
in `expA_tspray_tuning` and is topology-specific — not re-argued here.

### T_cc

T_cc is the **shared NSCC queuing target** (`-target_q_delay`), used by both PRISM and the REPS
core; it is not a private PRISM parameter.  PRISM's own goodput is flat across the bracket (f8
504–546 Gbps, f0 854–886 Gbps).  However, the **advantage over REPS shrinks and reverses** at
high T_cc, because a loose shared target lets REPS improve more than PRISM does.

| T_cc (µs) | f0 goodput (Gbps) | f8 goodput (Gbps) | f8 vs REPS |
|---|---|---|---|
| 7  | 854 | 520 | +26.6% |
| 10 | 860 | 525 | +25.8% |
| **14 (default)** | **869** | **504** | **+17.0%** |
| 20 | 875 | 522 | +6.0% |
| 28 | 886 | 546 | −12.2% |

The PRISM-minus-REPS difference (not the PRISM curve alone) is the correct sensitivity
signal — see Honest caveats below.

### kappa (deep-dive)

kappa is **not a flat knob**.  kappa ≤ 1 is approximately flat; kappa > 1 monotonically improves
**both** f0 and f8 goodput and FCT.

| kappa | f0 goodput (Gbps) | f8 goodput (Gbps) | f8 avg-FCT (µs) | f8 vs REPS |
|---|---|---|---|---|
| 0.25 | 880 | 509 | 1536 | +18.1% |
| 0.5  | 884 | 516 | 1520 | +19.7% |
| **1 (default)** | **869** | **504** | **1518** | **+17.0%** |
| 2    | 994 | 548 | 1369 | +27.2% |
| 4    | 1135 | 626 | 1145 | +45.3% |

At kappa=4, f0 goodput (1135 Gbps) exceeds REPS+NSCC f0 (~997 Gbps) — **the symmetric-regime
cost is eliminated and reversed**.  This f0 improvement is consistent across all five seeds
(per-seed k=1→k=4: 887→1141, 876→1036, 864→1173, 845→1191, 871→1134 Gbps).

**Mechanism** (m2m f0 seed 13, `PRISM_EPOCH` log):

| kappa | mean floor C_cc | mean cwnd | epoch-cuts | INC/HOLD/DEC |
|---|---|---|---|---|
| 1 | 12.9 µs | 105 KB | 446 | 41/37/22% |
| 2 | 10.9 µs | 118 KB | 261 | 36/41/23% |
| 4 | 11.2 µs | 127 KB | 144 | 28/49/23% |

Longer epoch → C_cc=min sampled over a longer window → lower observed floor → fewer and
gentler floor-MD cuts (446→144) → larger sustained window (105→127 KB) → faster completion.
This is the signal-side fix: the longer window averages out the f0 startup-incast transient that
the kappa=1 floor reacted to spuriously.

**Stress probes** (kappa {1, 2, 4} + REPS, seeds 13–17, all cr=1.00): kappa > 1 is
do-no-harm-to-beneficial on delay-driven oversub 4:1 (f8 goodput +31.8% at k=1 → +41.7% at k=4
vs REPS; matches published expB 4:1), trimming-incast fan-in 64→host 0 (~97 Gbps flat, kappa
neutral), and dynamic open-loop Poisson load (rho=0.5/0.9 both improved; avg-FCT much lower than
REPS).

**The cost is fairness** (Jain index over per-flow throughput):

| | kappa=1 | kappa=2 | kappa=4 |
|---|---|---|---|
| f0 (symmetric)  | 0.880 | 0.949 | 0.973 (improves) |
| f8 (asymmetric) | 0.979 | 0.859 | 0.838 (degrades) |

kappa > 1 improves f0 Jain (fixes the under-growth of early flows) but degrades f8 Jain — a
longer epoch's laggier per-flow reaction lets some flows grab disproportionate share in the
asymmetric regime.  **Default kappa=1 is the principled fairness-preserving choice.**

## Robustness verdict

Pre-registered light criterion (spec §4): within each 0.5–2× bracket, (i) cr=1.00 everywhere,
(ii) f8 win keeps its sign and stays the same order of magnitude, (iii) f0 cost does not worsen
by more than 5 percentage points.

- **T_spray**: ROBUST.  Win +13.8..+21.8% across the bracket; f0 stable.  The 0.5–2× criterion
  is met at every point.
- **T_cc**: PRISM's own performance is robust (f8 flat at 504–546 Gbps).  Its *advantage* over
  REPS is T_cc-dependent and reverses at the 2× extreme (q=28: −12.2%), because T_cc is the
  shared NSCC target, not a private PRISM parameter.
- **kappa**: NOT flat — does not satisfy the "same order of magnitude" robustness criterion
  above the default.  kappa > 1 yields a throughput ↔ fairness tradeoff: large throughput and
  FCT gains at the cost of asymmetric-regime fairness.  This is reported as an honest boundary,
  not a robustness claim.

## Honest caveats

1. **T_cc is shared** with the NSCC core, not a private PRISM threshold.  The PRISM-vs-REPS
   difference (not the PRISM curve alone) isolates PRISM-specific sensitivity.  The q=28
   reversal is a REPS improvement, not a PRISM regression.
2. **T_spray below-default pivot** is already known and topology-specific
   (`expA_tspray_tuning`); the 14 µs center is used here without re-arguing the tuning.
3. **Scope**: 128-node, m2m/incast/oversub/Poisson workloads, 5 seeds.  Cross-scale (1024-node)
   and mixed flow sizes are untested.  In particular, the kappa > 1 f0-mitigation and its
   fairness tradeoff should be validated at larger scale and with heterogeneous flow sizes before
   any default change or paper claim.  The "f0 cost is not intrinsic to the O(1) decomposition"
   implication (prior kappa sweeps stopped at kappa ≤ 1.0) is flagged as **future work** and is
   not yet asserted in NARRATIVE.md or TARGET_REGIME.md.

## Reproduce

```bash
# From sim/datacenter — regenerates the 160-run OFAT sweep and figK_sensitivity
bash prism_eval/expA_sensitivity/repro.sh
```

Output figure: `figs/figK_sensitivity.{pdf,png}`.  Raw data is gitignored.

**Note on kappa follow-up probes**: the mechanism table (§ kappa deep-dive), stress probes
(oversub/incast/Poisson), and fairness Jain index were controller-run follow-up investigations
and are **not** regenerated by `repro.sh`.  `repro.sh` covers only the 160-run OFAT sweep and
the sensitivity figure.
