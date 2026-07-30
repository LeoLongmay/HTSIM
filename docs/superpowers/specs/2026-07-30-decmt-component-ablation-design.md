# DecMT Component Ablation Design

## Objective

Establish whether DecMT's performance in asymmetric many-to-many traffic comes
from a relaxed queueing-delay target, the congestion-floor estimator, or the
residual-spread Hold state.  The experiment is deliberately small and uses a
single controlled fabric rather than sweeping the paper's full scenario set.

## Locked setup

The experiment lives in `htsim/sim/datacenter/prism_eval/expJ_decmt_ablation`.
Its main condition is a 128-node, one-oversubscribed fat tree with the existing
many-to-many workload from 64 senders to 16 receivers, 2 MB flows, eight paths,
REPS packet spraying, eight throttled links, and `-disable_trim`.  Each arm runs
for 8 ms with seeds 13 through 22.  The same four arms also run with zero
throttled links as a symmetric-fabric control.  This produces 80 simulations.

All arms use the same topology, workload, buffer and ECN configuration, link
rates, seed, epoch parameters, EWMA coefficient, minimum sample count, and
NSCC window-update functions.  The Full DecMT target queueing delay is supplied
explicitly and the Matched-Target NSCC arm receives exactly that value.  The
experiment will record the resolved value in its README and manifests rather
than relying on an implicit binary default.

## Arms

| ID | Label | Sender controller | Distinguishing behavior |
| --- | --- | --- | --- |
| `original_nscc` | Original NSCC | NSCC + REPS | Existing NSCC target and aggregate delay feedback. |
| `matched_nscc` | Matched-Target NSCC | NSCC + REPS | Same controller, but with DecMT's explicit target queueing delay. |
| `floor_only` | Floor-Only | Prism + REPS | Same floor estimator and control parameters as DecMT, but an otherwise-Hold epoch becomes Increase. |
| `decmt` | DecMT | Prism + REPS | Full floor, residual-spread, and Hold-state controller. |

The first pair isolates target relaxation.  The second pair isolates the
spread-based gate.  Comparing Matched-Target NSCC with Floor-Only identifies
the contribution of using the epoch-bounded congestion floor instead of the
aggregate NSCC signal.

## Controller interface

A new command-line flag, `-prism_floor_only`, applies only when
`-sender_cc_algo prism` is selected.  At an epoch boundary, DecMT first derives
the normal region from its smoothed floor and smoothed residual spread.  When
the flag is set, only the resulting `HOLD` region is remapped to `INCREASE`.
`DECREASE` remains driven by the same floor-versus-target comparison.  The
estimator continues to collect min/max samples, requires the same `N_min`, and
uses the same EWMA and epoch duration as Full DecMT.  Thus the flag removes the
Hold action without changing parameter values or estimator history.

The runner supplies explicit environment and command arguments for every arm
and writes a per-run manifest.  A run is accepted only if its flow log contains
the expected complete workload.  Existing `run_lib.sh` remains the only binary
runner, so every case uses the standard topology, logging, and decoder path.

## Outputs and figures

`repro.sh` builds or checks prerequisites, creates the workload, runs all 80
cases, validates logs, and invokes `make_figs.py`.  The data directory retains
the flow logs, stdout files, id maps, and manifests so figures can be redrawn
without rerunning simulation.

The primary figure has three panels for Goodput, Average FCT, and P99 FCT at
eight throttled links.  Each panel has four bars, one per arm, with a mean and
standard-deviation error bar across ten seeds.  A companion symmetric-control
table or compact panel reports the same metrics at zero throttled links.  The
README includes paper-ready setup wording and a result-interpretation template,
but makes no performance claims before data are collected.

## Verification

Unit tests cover the new region mapping: a high spread with floor below target
is `HOLD` for Full DecMT and `INCREASE` for Floor-Only, while a floor above the
target remains `DECREASE` in both.  Python tests verify the fixed 80-case
matrix, arm arguments, workload completeness, aggregation over ten seeds, and
figure creation.  A smoke run exercises all four arms at eight throttled links
with seed 13 before the full reproduction is launched.

## Exclusions

Raw-Extrema DecMT is intentionally excluded because the supplied plan marks it
as an optional fifth arm.  State-occupancy and switching-rate plots are also
deferred: their traces may be collected later, but they are not required to
answer the primary attribution questions.
