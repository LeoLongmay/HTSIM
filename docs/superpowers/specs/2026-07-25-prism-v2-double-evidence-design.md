# Prism v2 double-evidence evaluation design

## Goal

Make the existing 1024-node Prism v2 result easier to interpret without changing its
statistical population, then test the same four algorithms over a predeclared,
reproducible path-asymmetry sweep.

## Scope

The work has two linked deliverables.

1. **ACK-delay explanation figure, no new simulation.** Reuse the already completed
   `failed=16`, five-seed ACK traces.  Render three panels: a full-range ACK-delay ECDF,
   a 0--25 us low-delay zoom, and an ECDF difference panel relative to REPS+NSCC.
2. **1024-node failure sweep.** Run all four arms at the fixed failure levels
   `{0, 8, 16, 24, 32}` and seeds `{13, 14, 15, 16, 17}`.  This is exactly 100 runs.
   Produce goodput, mean FCT, and p99 FCT versus failed-link count, plus an FCT ECDF at
   the predeclared high-asymmetry level `failed=32` and Prism v2 engagement fraction
   versus failed-link count.

No failure level, seed, algorithm, or metric may be selected after inspecting its result.
Raw data remains ignored; scripts, tests, summaries, and final PDF/PNG figures are committed.

## Experimental contract

| item | fixed value |
|---|---|
| topology | `fat_tree_1024.topo` |
| workload | 256 senders to 64 receivers, `pairs`, 2,000,000-byte flows |
| controller mode | `-disable_trim`, `PATHS=8`, `NODES=1024`, `END_MS=8` |
| failure levels | `0, 8, 16, 24, 32` |
| seeds | `13, 14, 15, 16, 17` |
| algorithms | OPS+NSCC, REPS+NSCC, REPS+STrack, REPS+Prism v2-full |
| Prism v2-full flags | `-prism_smooth_beta 0.3 -prism_hysteresis 0.25 -prism_engage_spread 28 -prism_disengage_spread 20` |

`-failed=N` is a deterministic, concentrated fat-tree degradation configuration: the
enumerated core-to-aggregation links are reduced to 25% capacity.  It is therefore a
reproducible path-asymmetry stressor, not a post-hoc random failure placement.

## Data and statistics

### ACK-delay figure

Each ACK sample is a genuine, non-probe, normal-send sample with
`q = max(raw_rtt - base_rtt, 0)`.  For every arm, calculate an ECDF separately for each
seed and average those five ECDFs; a seed never receives more weight because it emitted
more ACKs.

The delta panel is `F_arm(q) - F_REPS+NSCC(q)` in percentage points.  Draw the five-seed
mean and a 95% bootstrap confidence band obtained by resampling the five seeds with
replacement.  The full CDF remains the headline population view; the 0--25 us panel and
delta panel are explanatory views, not replacements.

### Failure sweep

For every completed `.flow.txt`, use the existing metrics parser to obtain completion
rate, goodput, mean FCT, and p99 FCT.  Plot the mean across five seeds and standard-error
bars.  A cell with completion rate below 0.999 is retained and visibly annotated; it is
never silently dropped.  Prism engagement fraction is read from its epoch trace and
averaged equally across seeds.

The `failed=32` FCT ECDF pools no seeds: it follows the same equal-seed ECDF convention
as the ACK figure.  Its purpose is to show application-facing latency under the
predeclared strongest asymmetry point, while the sweep prevents that one plot from being
used as a selectively chosen headline.

## Outputs

All new artefacts live under `htsim/sim/datacenter/prism_eval/expI_prism_v2/`:

- `repro_1024_double_evidence.sh`: complete, idempotent 100-run reproduction script;
- `make_1024_double_evidence_figs.py`: ACK enhancement and sweep renderers;
- `figs/figI_1024_ack_qdelay_evidence.{png,pdf}`;
- `figs/figI_1024_failure_sweep.{png,pdf}`;
- `figs/figI_1024_f32_fct_cdf.{png,pdf}`;
- `figs/figI_1024_v2_engagement_sweep.{png,pdf}`.

## Verification

- Unit tests cover malformed ACK/epoch input rejection, equal seed weighting, delta-sign
  convention, bootstrap determinism, and figure generation on synthetic traces.
- A shell dry-run test verifies all 100 run commands, every declared failure level, all
  four arms, and the exact v2 flags.
- Before rendering, the reproduction script verifies every expected flow and trace file,
  schema-validates ACK rows, and enforces the documented completion-rate rule.

