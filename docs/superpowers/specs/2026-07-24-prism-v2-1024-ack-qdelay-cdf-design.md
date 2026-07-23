# Prism v2 1024-node ACK queueing-delay CDF

## Purpose

Produce one exploratory CDF comparing the end-to-end queueing-delay experience of all acknowledged data under a 1024-node asymmetric many-to-many workload with `-failed 16`.

## Experimental arms

Use five seeds (`13` through `17`) and the 1:1 1024-node setup from `prism_eval/expD_scale1024`:

| Label | Congestion control | Load balancing |
|---|---|---|
| OPS+NSCC | NSCC | OPS/oblivious |
| REPS+NSCC | NSCC | REPS |
| REPS+STrack | STrack | REPS |
| REPS+Prism v2-full | Prism with `smooth_beta=0.3`, `hysteresis=0.25`, `engage_spread=28 us`, `disengage_spread=20 us` | REPS |

All runs use `fat_tree_1024.topo`, 1024 nodes, `many2many.py 256 64 pairs 2000000 1024 64`, eight paths, 100-Gbps calibration, and `-disable_trim`.

## Measurement

For each valid, non-probe data ACK, define:

`q_ack = max(raw_rtt - base_rtt, 0)`.

This is an ACK-derived end-to-end queueing-delay estimate. It is not a single switch queue's backlog drain time. The logger must retain per-sample base RTT (or qdelay itself), so the plot does not rely on a hard-coded base RTT.

Within each seed and arm, every eligible ACK contributes one sample. Build each seed's ECDF, evaluate it on a shared x-grid, and average the five ECDF values so each seed has equal weight. Do not pool ACKs across seeds before forming the CDF.

## Figure

Write one PNG and PDF under `htsim/sim/datacenter/prism_eval/expI_prism_v2/figs/`.

- x-axis: `ACK-derived end-to-end queuing delay (us)`
- y-axis: `Empirical CDF`
- one curve for each experimental arm
- main panel range: through the maximum arm-wise P99.9 across seed samples
- inset: full finite range, to expose rare tail samples
- caption/legend state the five-seed equal-weight ECDF aggregation and ACK sample definition.

## Validation

- Verify every arm has five completed runs and nonempty ACK samples.
- Verify the generated workload's completion-rate guard remains at least 0.999 for all runs.
- Reject malformed/non-finite delay samples and report their count.
- Keep the experiment read-only with respect to controller behavior: logging must not alter packet forwarding, CC, or load balancing.

## Scope

This is a smoke-scale comparison and produces one figure only. It does not claim a seed-robust performance result beyond the stated scenario, and it does not replace the existing scale verification experiment.
