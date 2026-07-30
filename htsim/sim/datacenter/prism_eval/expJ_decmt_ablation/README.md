# ExpJ — DecMT component ablation

ExpJ is a locked four-arm component ablation in the 128-node fat-tree
many-to-many workload. It distinguishes target matching, the epoch floor
estimator, and DecMT's residual-spread Hold behavior without changing the
workload, spraying algorithm, topology, seeds, or delay-driven execution.

## Locked matrix

The formal reproduction runs `4 arms x 2 controls x 10 seeds = 80` cases:
`failed=8` is the asymmetric main condition and `failed=0` is the symmetric
control. Seeds are 13 through 22. Every case uses REPS, 8 paths, 8 ms end
time, MTU 4150, and the fixed 64-flow workload (`2,000,000` bytes per flow).
All cases use `-disable_trim`.

| Arm | CC / LB | Target queue delay | Additional flag | Definition |
|---|---|---:|---|---|
| Original NSCC | `nscc` / `reps` | default | none | Original REPS+NSCC baseline; no target override. |
| Matched-Target NSCC | `nscc` / `reps` | 14 us | none | The same NSCC algorithm with DecMT's 14 us target. |
| Floor-Only | `prism` / `reps` | 14 us | `-prism_floor_only` | DecMT's floor estimator but no residual-spread Hold action. |
| DecMT | `prism` / `reps` | 14 us | none | Full floor-and-residual-spread controller. |

`-prism_floor_only` preserves Prism's estimator and controller configuration,
but overrides a residual-spread-induced Hold to Increase. Therefore the
floor determines Decrease versus non-Decrease while residual spread does not
pause window growth.

## Metrics and outputs

For each completed flow, FCT is `FINISH time - START time`. The per-case
average FCT and P99 FCT use those 64 FCTs; P99 selects the sorted completion
time at zero-based index `round(0.99 * (n - 1))` (index 62 for 64 flows).
Finite-workload aggregate goodput is completed bytes times eight divided by
the elapsed span from the first START to the last FINISH, in Gbps. Formal
summaries report the mean and sample standard deviation over the ten seeds.

| Artifact | Location |
|---|---|
| Smoke logs and manifests | `data/smoke/` |
| Formal logs and 80 manifests | `data/formal/` |
| Per-seed and aggregate CSVs | `data/aggregate/per_seed.csv`, `data/aggregate/summary.csv` |
| Primary three-panel figure | `figs/figJ1_decmt_ablation.pdf`, `figs/figJ1_decmt_ablation.png` |

## Reproduction

```bash
cd htsim/sim/datacenter/prism_eval/expJ_decmt_ablation
bash repro.sh
python3 make_figs.py
```

`repro.sh` runs the smoke matrix, formal matrix, strict aggregation, and
figure rendering in that order. The runner reuses only an exact immutable
output bundle; a conflicting or incomplete prior bundle is rejected.

## Intended causal interpretation

This experiment is designed to test, not presume, outcomes. Matched-target
NSCC tests threshold fairness. Floor-Only tests the epoch floor estimator.
DecMT versus Floor-Only tests residual-spread Hold. The `failed=0` control
checks the same four arms when the asymmetric throttling condition is absent.
