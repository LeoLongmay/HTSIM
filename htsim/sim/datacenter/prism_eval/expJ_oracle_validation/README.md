# expJ_oracle_validation - Prism O(1) Estimator Validation

This experiment separates three questions that the original boundary-only oracle conflated:

1. Does the ACK-sampled estimator agree with a full-path envelope sampled at the same ACK times?
2. How different is the estimator from the instantaneous network state at the epoch boundary?
3. How much of the difference is associated with entropy/physical-path coverage and feedback lag?

The oracle is read-only and never changes entropy selection, packet forwarding, or congestion control.

## Setup

| Parameter | Value |
|---|---|
| Workload | `many2many.py 64 16 pairs 2000000 128 16` |
| Load balancing | `reps` |
| CC | `prism` |
| Entropy namespace | 8 values |
| Scenarios | `symmetric`: 1:1, failed 0; `asymmetry`: 1:1, failed 8; `mixed`: 4:1, failed 8 |
| Full sweep | `kappa in {0.5,1,2}`, `n_min in {1,3,6}`, seeds `{13,14,15,16,17}` |

All runs are delay-driven (`-disable_trim`). Smoke mode runs one seed at `kappa=1,n_min=3`.

## Oracle Definitions

### Entropy-resolved physical paths

For every flow and configured entropy value, the validation code follows the live ECMP FIB using
the same `freeBSDHash(flow_id, entropy, switch_hash_salt)` lookup as packet forwarding. Entropies
that resolve to the same ordered queue sequence are deduplicated only for physical-path extrema.
The static `get_paths()` ordering is not used.

Two coverage metrics are logged and must both remain in `[0,1]`:

- `entropy_coverage_ratio = sampled entropy values / configured entropy values`;
- `path_coverage_ratio = sampled resolved physical paths / eligible resolved physical paths`.

### ACK-time epoch-envelope oracle (primary fidelity comparison)

At every genuine Prism ACK sample time, the oracle snapshots every resolved physical path. Within
the epoch it maintains the minimum path floor and maximum path ceiling over those snapshots. The
primary oracle components are:

```text
oracle_raw_cc     = min over (ACK time, physical path)
oracle_raw_spray  = max over (ACK time, physical path) - oracle_raw_cc
```

This is the full-path analogue of Prism's epoch extrema at the controller's ACK observation times.
It still differs from `RTT-baseRTT`, which describes queueing experienced by a packet sent roughly
one RTT earlier. The boundary lead/lag analysis quantifies that remaining feedback delay.

The log also records mean instantaneous cross-path floor/spread and the within-epoch temporal range
of the instantaneous floor. These distinguish cross-path spread from temporal queue movement.

### Boundary-snapshot oracle (staleness diagnostic)

At the epoch boundary, the oracle separately snapshots all resolved physical paths once. These
fields use the `boundary_oracle_*` prefix. They are an instantaneous-state diagnostic, not the
ground truth for the epoch's historical ACK extrema.

Both oracle streams use Prism's configured EWMA, hysteresis, thresholds, and decision function.

## Commands

```bash
# Three scenarios, one seed and one parameter point
bash prism_eval/expJ_oracle_validation/repro.sh smoke

# 3 scenarios x 3 kappa x 3 n_min x 5 seeds = 135 runs
bash prism_eval/expJ_oracle_validation/repro.sh full

# Regenerate summaries and figures from current-schema raw CSVs
python3 prism_eval/expJ_oracle_validation/make_figs.py --render

# Redraw only the figure from summary.csv plus a streaming coverage pass
python3 prism_eval/expJ_oracle_validation/make_figs.py --plot-only
```

Each reproduction run removes old raw oracle CSVs first so boundary-only and corrected schemas
cannot be mixed.

## Outputs

| Artifact | Path |
|---|---|
| Raw epoch logs | `data/raw/*.oracle.csv` |
| Fidelity summary | `data/summary.csv` |
| Confusion matrices | `data/confusion.csv` |
| Boundary lead/lag sweep | `data/lead_lag.csv` |
| Figure | `figs/prism_oracle_validation.{png,pdf}` |

Rows are valid only when `row_status=ok`. Initial epochs whose FIB is not fully populated are logged
as `path_resolution_failed` or `partial_path_resolution` and excluded from fidelity statistics.
`epoch_sample_deferred=1` means the epoch duration elapsed before `n_min` samples arrived, so Prism
extended the epoch rather than silently skipping it.

## Interpretation Limits

- The ACK-time oracle uses instantaneous forward queue backlog at ACK arrival. Prism uses historical
  RTT queueing and also observes reverse-path delay. Exact equality is therefore not expected.
- `backlogDrainTime()` is a frozen-state queue-work estimate; it is not a counterfactual packet
  traversal through future downstream queue states.
- State agreement measures signal fidelity, not whether the oracle action would optimize goodput or
  FCT. End-to-end controller performance remains a separate experiment.
- Do not make seed-robust or parameter-stability claims from smoke data. Run `full` first.
