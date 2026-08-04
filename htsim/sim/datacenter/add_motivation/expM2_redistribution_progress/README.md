# M2 Redistribution Progress

M2 tests whether a shadow REPS round behaves differently when the foreground load is below the
healthy reachable cut capacity (`recoverable`) versus between the healthy and degraded reachable
cut capacities (`persistent`). It observes PRISM traces only; it does not enable recycling or CC
handoff.

The old background-flow construction is not used. Each run contains only deterministic foreground
flows into pod 0. The simulator degrades a fixed number of core-to-pod links, and the analysis reads
the actual `linkmap.csv` rates and `reduced_speed` flags. Foreground offered rate comes from epoch
send counters, not sink delivery. Shadow observation starts after a fixed 1ms warm-up, excluding
the connection start-up transient.

## Current Controlled Result

The six-cell coarse grid is in `configs/calibration.csv`. The two selected confirmation cells are:

| Claim | Cell | Coarse capacity relation |
| --- | --- | --- |
| Recoverable | `f8/d8/c50` | 744Gbps foreground below 800Gbps healthy capacity |
| Persistent | `f12/d8/c50` | 931Gbps foreground between 800Gbps healthy and 1200Gbps effective capacity |

The three-seed confirmation preserves those capacity relations. It does **not** satisfy the strict
outcome lock: recoverable has a negative median spread change at seed 102, and persistent has a
49.2% literal no-progress rate at seed 102. `configs/formal.csv` therefore remains header-only and
no formal run is valid. This is a negative validation result, not evidence for recycling.

## Commands

Run from the repository root after building `htsim_uec`:

```bash
# Fast parser/plot smoke test.
bash htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/repro_controlled.sh smoke

# Full controlled M2: coarse/confirmation, threshold diagnostic, trajectory,
# real REPS cache behavior, and residual-recycling A/B diagnostic.
bash htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/repro_controlled.sh all

# Remove generated traces, logs, traffic matrices, and aggregate CSVs.
# Final figures under figs/ are retained.
bash htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/clean_outputs.sh
```

The supported figures are generated under `figs/controlled/`, including the calibration and
confirmation diagnostics, controlled trajectories, real REPS cache behavior, threshold diagnostic,
and recycling A/B diagnostic. All files below `data/` are generated intermediates and are not kept.
