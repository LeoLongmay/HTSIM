# Prism Hold-Episode Analysis

## Question

Does the feedback available when Prism enters Hold distinguish episodes whose
delivery recovers from episodes that remain ineffective? Results are
observational labels only and do not change the controller, REPS, cache, or
path selection.

## Fixed matrix

The experiment runs default Prism with REPS for seeds 13, 14, and 15 in each
fixed scenario:

| Scenario | Workload | Regime |
| --- | --- | --- |
| `f0` | 64-to-16, 2 MB many-to-many | delay-driven, `failed=0` |
| `asymmetric` | 64-to-16, 2 MB many-to-many | delay-driven, `failed=8` |
| `incast` | 64-to-1, 1 MB incast | delay-driven |
| `trimming` | 64-to-16, 2 MB many-to-many | trimming enabled, `failed=8` |

This is the fixed 12-run matrix; it is not a parameter sweep. The target
queue-delay and spray settings are both 14 us, and loss decomposition remains
disabled.

## Episode definition

An episode begins only when a flow transitions from a non-Hold epoch to Hold.
Its windows are one base RTT before entry and two adjacent base-RTT windows
after entry. An episode is incomplete when the trace does not reach the end of
the second post-entry window. ACK progress uses all ACK records; low-delay
support and high-delay tail use valid delay samples only. Incomplete episodes
are reported as coverage but are excluded from outcome grouping.

Complete episodes are descriptively labelled `recovered`, `ineffective`, or
`mixed` from their pre/post ACK progress, low-delay support, and high-delay
tail. These labels do not fit or install a controller policy.

## Outputs

`data/` contains per-run manifests and raw traces. `data/aggregate/` contains
`episode_rows.csv` and `scenario_summary.csv`. The renderer writes
`figs/hold_episode.pdf` and `figs/hold_episode.png`.

The four-panel figure reports outcome coverage, Hold-entry `F` versus `S`,
delay support/tail medians, and normalized ACK-progress medians. Scenarios or
outcomes with no complete Hold episodes are annotated as insufficient coverage
instead of being shown as zero-valued evidence.

## Reproduce

```bash
cd htsim/sim/datacenter
bash prism_eval/expK_hold_episode/repro.sh
```
