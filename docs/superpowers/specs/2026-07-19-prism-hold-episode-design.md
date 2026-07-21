# Prism Hold-Episode Analysis Design

## Goal

Determine, with read-only observations, whether feedback available at a Prism
Hold entry can distinguish a Hold period that improves delivery from one that
does not. The analysis must not change Prism, REPS, cache admission, path
selection, or congestion-window behavior.

## Scope

Create `htsim/sim/datacenter/prism_eval/expK_hold_episode/` with a reproducible
12-run Prism-only matrix: scenarios `f0`, `asymmetric`, `incast`, and
`trimming`, each with seeds 13, 14, and 15.

The cases are fixed as follows:

| Scenario | Workload and regime | Prism configuration |
| --- | --- | --- |
| `f0` | 64-to-16 2 MB many-to-many, delay-driven, `failed=0` | default Prism + REPS |
| `asymmetric` | same many-to-many workload, delay-driven, `failed=8` | default Prism + REPS |
| `incast` | 64-to-1, 1 MB incast, delay-driven, `failed=0` | default Prism + REPS |
| `trimming` | 64-to-16 2 MB many-to-many, trimming enabled, `failed=8` | default Prism + REPS, loss decomposition disabled |

## Read-Only Trace

Add an opt-in `PRISM_HOLD_TRACE` trace in `uec.cpp`. It logs an ACK event with
the following fields:

`time_ns,flow_id,valid_delay_sample,qdelay_ns,base_rtt_ns,ecn,newly_acked_bytes,cwnd_bytes`

The trace observes values that already exist in ACK handling. It must not feed
back into any controller state or load-balancer state. Existing trace formats
remain unchanged.

`PRISM_EPOCH` remains the source of the controller's actual epoch-level
`F=C_cc`, `S=C_spray`, and region decision.

## Episode and Windows

An episode is flow-local. It begins at an epoch whose region is `HOLD` and
whose immediately preceding epoch for that flow is not `HOLD`.

For each complete episode, define three adjacent windows of the Hold-entry
epoch's base RTT duration:

1. `pre`: immediately before the Hold decision.
2. `post1`: immediately after the Hold decision.
3. `post2`: immediately after `post1`.

An episode is incomplete if the trace does not cover the full `post2` window.
Incomplete episodes are counted but excluded from outcome grouping.

For every window, compute:

- ACK progress: `sum(newly_acked_bytes) / window_duration` over all ACK events.
- Low-delay support: fraction of valid delay samples with `qdelay <= T_cc`.
- High-delay tail: fraction of valid delay samples with
  `qdelay >= F_entry + T_spray`.

The entry record supplies `F_entry`, `S_entry`, `T_cc`, and `T_spray` use the
same fixed target value as the run configuration.

## Outcome Groups

The analysis reports continuous changes for every episode. It also assigns a
conservative descriptive group without fitting a classifier:

- `recovered`: both post windows have nondecreasing ACK progress and lower
  high-delay tail than `pre`, and `post2` has nondecreasing low-delay support.
- `ineffective`: `post2` has no lower high-delay tail than `pre` and no higher
  ACK progress than `pre`.
- `mixed`: any other complete episode.

These groups are observational labels for the analysis only. They do not imply
that a future controller must use the same exact predicates.

## Outputs

The analysis writes gitignored raw traces and derived CSV files under the
experiment `data/` directory, and produces:

- `episode_rows.csv`: one complete or incomplete Hold episode per row.
- `scenario_summary.csv`: counts and seed-level outcomes per scenario.
- `figs/hold_episode.pdf`: scenario outcome coverage, entry-signal comparison,
  and pre/post changes in delay support, delay tail, and ACK progress.

The figure must visibly report insufficient episode coverage rather than infer
a conclusion from a scenario with too few complete Hold episodes.

## Decision Rule

The experiment supports a next-stage Outcome-Validated Hold design only if
entry signals show a directionally consistent recovered-versus-ineffective
difference across the three seeds in the delay-driven `f0` and `asymmetric`
cases. Incast and trimming are boundary checks; an absence of complete Hold
episodes there is reported as coverage, not treated as evidence of separation.
