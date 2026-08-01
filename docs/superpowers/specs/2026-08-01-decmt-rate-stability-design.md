# DecMT Rate-Stability Experiment Design

## Goal

Test whether DecMT's Increase, Hold, and Decrease decisions preserve smooth
control under normal operation.  The claim is deliberately limited: DecMT does
not exhibit material rate oscillation while converging to a steady operating
point in representative delay-driven workloads.  The experiment does not
claim that every individual state transition is perturbation-free.

## Measurement

The plotted rate is **aggregate delivery rate**, not a new sender-side trace.
For a time bin of width `Delta`, it is the sum of newly acknowledged payload
bytes across all sinks during that bin, multiplied by `8 / Delta`.  This gives
one controller-neutral observable for OPS, REPS, STrack, and DecMT.

The runner requests sink logging at 10 us intervals.  The analysis sums all
sink-rate records into 10 us bins and applies a centered 50 us moving mean only
for the displayed trajectories.  All stability numbers use the un-smoothed
10 us series so the plotting filter cannot artificially improve a controller.

For each run, the steady window is 1--6 ms.  It excludes the startup ramp and
the final drain.  The summary reports:

- rate coefficient of variation: `std(rate) / mean(rate)`;
- normalized P95--P5 amplitude: `(P95(rate) - P5(rate)) / mean(rate)`;
- settling time: the first time after which the rate remains inside plus/minus
  10% of that run's steady mean for at least 200 us.

Runs with an insufficient nonzero steady window are marked invalid rather than
being interpreted as stable.

## Fixed Network and Workload

All runs use a 128-host, 1:1 fat-tree, REPS-compatible 8-path configuration,
2 MB flows, 64 senders and 16 receivers in the existing `many2many` traffic
generator.  The fabric is delay-driven (`-disable_trim`) and runs for 8 ms.

Two ordinary workload conditions are used:

| Panel | Topology condition | Purpose |
| --- | --- | --- |
| Symmetric | 1:1, `failed=0` | Tests a normal balanced fabric, where no persistent reroutable asymmetry exists. |
| Asymmetric | 1:1, `failed=8` | Tests the ordinary DecMT target regime with persistent path imbalance. |

Each condition uses seeds 13--17.

## Controllers

The primary comparison fixes the load balancer to REPS and uses four congestion
control arms:

- OPS;
- REPS plus NSCC;
- REPS plus STrack;
- REPS plus DecMT v2-full.

DecMT v2-full uses the established configuration: `smooth_beta=0.3`,
`hysteresis=0.25`, `engage_spread=28 us`, and `disengage_spread=20 us`.
The figure labels are OPS, REPS, STrack, and DecMT.

The sensitivity companion holds the asymmetric workload fixed and repeats the
DecMT run for `smooth_beta` in `{1.0, 0.5, 0.3, 0.15}`.  All other DecMT v2
parameters remain unchanged.  Here `beta=1.0` is the no-EWMA reference.

## Outputs

The experiment resides in `prism_eval/expL_rate_stability/` and follows the
existing experiment layout: `repro.sh`, a Python runner/analysis module,
tests, `data/`, and `figs/`.

1. `figL1_rate_timeseries.pdf`: two side-by-side panels for the symmetric and
   asymmetric conditions.  Each panel shows the median aggregate delivery-rate
   trajectory across five seeds for OPS, REPS, STrack, and DecMT.  The plot
   also shows the interquartile band for DecMT only; this exposes seed
   variation without obscuring the four central trajectories.
2. `figL2_beta_timeseries.pdf`: aggregate delivery-rate trajectories for the
   four DecMT beta values in the asymmetric condition.
3. `data/stability_summary.csv`: one row per arm, condition, and seed, plus
   aggregated mean and standard deviation columns for the three stability
   metrics.

The main paper evidence is FigL1.  FigL2 supports the statement that the
chosen smoothing value is not concealing a rate oscillation.

## Run Matrix and Reproducibility

The primary matrix has 2 conditions x 4 arms x 5 seeds = 40 simulations.  The
beta sensitivity has 4 beta values x 5 seeds = 20 simulations.  Total: 60
deterministic runs.  Each run passes an explicit seed and records its command,
traffic-matrix hash, simulator executable hash, raw sink trace, and manifest.

Before the full matrix, one representative historical/current run will be
compared using the raw sink trace.  If it matches, the full matrix is an
exact reproduction under the current implementation.  If it does not match,
the experiment reports the mismatch and does not describe the result as an
exact historical reproduction.

## Interpretation Rule

DecMT is supported as control-stable only if, in each condition, its
five-seed mean coefficient of variation and normalized P95--P5 amplitude are
each no more than 1.25 times the lowest corresponding baseline mean.  FigL1
must also show no persistent periodic swing whose peak-to-trough amplitude
exceeds 25% of DecMT's steady mean for three or more consecutive cycles.  The
report must explicitly retain a contrary finding if DecMT exceeds either
threshold or has a visibly longer settling time than every baseline.

## Validation

Unit tests cover sink-log parsing, bin aggregation, moving-mean boundaries,
quantile metrics, settling-time detection, invalid-window handling, and
deterministic figure input ordering.  The reproduction script verifies that
all 60 manifests and raw traces exist before rendering.
