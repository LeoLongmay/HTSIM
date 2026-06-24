# expH\_overhead — PRISM Overhead Analysis

**Claim.** PRISM is O(1) in both signal state and per-ACK compute — as light as the cheapest
single-RTT schemes — while producing a spread-aware, robust congestion signal.  The median-based
schemes (MNSCC, MSwift) pay O(window) state and O(H log H) per-ACK compute for a signal that
is less robust to asymmetric loss patterns.  The headline: *cheap cost for a robust signal*.

This experiment has no FCT or goodput measurements.  It consists of a standalone C++
microbenchmark (timing + sizeof) and a kappa sweep of PRISM_EPOCH logs extracted from reused
simulation runs.

---

## Complexity table

State bytes are measured (`sizeof`) by the microbench.  O-notation is from the source
(congestion-control algorithm definitions; Gerstein et al. 2026 for MNSCC/MSwift).
Wire column: none of these schemes add any extra header fields.

| Arm         | State (B) | State O     | Per-ACK O   | Wire |
|-------------|----------:|-------------|-------------|------|
| Prism       |        56 | O(1)        | O(1) min/max | none |
| NSCC        |         8 | O(1)        | O(1)        | none |
| STrack      |         8 | O(1)        | O(1)        | none |
| Swift       |         8 | O(1)        | O(1)        | none |
| MNSCC       |       264 | O(1) [32-win] | O(H log H) | none |
| MSwift      |       520 | O(1) [64-win] | O(H log H) | none |
| REPS (LB)   |        72 | O(8)        | O(1)        | none |
| BITMAP\*    |    O(#paths) | O(#paths) | O(#paths)  | none |

\* BITMAP is an illustrative per-path design point only, not an eval competitor.
Its state grows linearly with the number of monitored paths; shown in figO1 (right panel).

---

## Figures

### figO1 — State footprint

**Reading.** Prism holds 56 B per flow (two uint32 running-min/max accumulators plus scalars).
NSCC, STrack, and Swift each need 8 B (one or two scalars).  MNSCC carries a 32-sample circular
buffer (264 B) and MSwift a 64-sample buffer (520 B) — 4.7× and 9.3× more than Prism.  REPS
(the load balancer) holds a per-path bitmask, fixed at 72 B for 8 paths.  The right panel
shows that Prism and REPS are flat as #paths grows, while a hypothetical per-path design scales
linearly.

### figO2 — Per-ACK compute

**Reading.** Prism's signal-extraction routine takes **1.25 ns/ACK** (microbench, isolated timing;
machine-specific — see caveat 1).  NSCC is 1.17 ns, STrack 1.64 ns, Swift 9.45 ns — all O(1)
and in the same single-digit-ns range.  MNSCC at its default window of H=32 costs **252 ns/ACK**
and MSwift at H=64 costs **696 ns/ACK** — 203× and 559× more than Prism respectively.  The right
panel shows both median schemes scale super-linearly with window size H (O(H log H) sorting),
while Prism's cost (dashed line) stays flat.

### figO3 — Samples aggregated per control decision (kappa=1)

**Reading.** At kappa=1 (epoch length = 1 × base\_rtt ≈ 14 µs), the median number of ACKs
Prism aggregates per epoch is **8** (across 16 047 epochs, 5 seeds).  This is far below the
MNSCC window (32, marked) and the MSwift window (64, marked): Prism triggers a control decision
after accumulating 8 samples on average, not 32 or 64.  The bounded distribution reflects the
epoch-driven batching — most epochs see exactly one RTT worth of returning ACKs.

### figO4 — Reaction latency vs kappa

**Reading.** Reaction latency (median inter-decision cadence per flow) rises linearly with kappa,
tracking the reference line kappa × base\_rtt (14 µs per RTT):

| kappa | measured cadence (µs) | expected kappa × 14 µs |
|-------|-----------------------:|------------------------:|
| 0.5   |                   10.7 |                     7.0 |
| 1.0   |                   17.4 |                    14.0 |
| 2.0   |                   31.6 |                    28.0 |
| 4.0   |                   59.5 |                    56.1 |

The small positive offset (≈3–4 µs) is the epoch-collection lag: the epoch closes at the
boundary but arriving ACKs complete slightly after.  The tradeoff is explicit: longer kappa
lowers per-ACK work (more aggregation) at the cost of a proportionally slower reaction.
Per-ACK schemes like NSCC react in ~1 RTT (14 µs lower bound, reference line in the figure).

---

## Honest caveats

1. The microbench times signal-extraction routines in isolation, not the shared full ACK
   handler — absolute ns figures are machine-specific.  Report relative comparisons and O(H)
   scaling, not absolute ns.

2. The eval competitors (NSCC, STrack, Swift, MNSCC, MSwift) are NOT O(#paths).  BITMAP is
   an illustrative per-path design point only; it is not an eval competitor.

3. Reaction latency = bounded epoch staleness (~kappa × base\_rtt).  This is PRISM's explicit
   tradeoff for O(1) state and compute; it is not a defect.

4. The benchmark scope is congestion-signal extraction only, not the per-packet datapath
   (header parsing, ACK demux, window update).  That datapath is identical across all arms and
   is not a differentiator.

---

## Out of scope

- FCT and goodput measurements (see expA\_delaydriven, expB\_oversub\_asym, expC).
- Runtime instrumentation of the production simulator path (only isolated bench).
- Heavy step-response or ramp experiments.
- Cross-scale topology comparisons.

---

## Repro

```bash
# From htsim/sim/datacenter/
bash prism_eval/expH_overhead/repro.sh
```

Prerequisites: `htsim_uec` built; `prism_eval/expA_delaydriven/data/m2m.cm` present (run
`expA_delaydriven/repro.sh` first, or copy any compatible `.cm`).

The script: (1) runs `make_figs.py --selftest`; (2) compiles and runs `overhead_bench` to
produce `data/bench_*.csv`; (3) runs 20 PRISM\_EPOCH simulations (kappa ∈ {0.5, 1, 2, 4} ×
5 seeds, failed=8, `-disable_trim`); (4) renders figO1..figO4 via `make_figs.py --render`.

`data/` is gitignored.  Figures are force-added to git.
