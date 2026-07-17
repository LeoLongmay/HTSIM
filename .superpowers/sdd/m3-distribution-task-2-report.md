# M3 Distribution Task 2 Report

## Scope

Implemented the read-only M3 distribution analyzer in
`analyze_distribution.py` and extended `tests/test_distribution.py`. The
analyzer writes only to the caller-provided output directory. No C++ code or
existing formal analyzer code was modified.

## Behavior

- Each run requires one identical positive `base_rtt_ps` across its ACK rows;
  distribution-bin width is exactly `4 * base_rtt_ps`.
- `distribution_bins.csv` emits post-1 ms bins
  `[warmup + k * width, warmup + (k + 1) * width)` with separate healthy and
  throttled `newly_acked_bytes`, plus `throttled_ratio`.
- Every ACK is required to have a resolved pathmap mapping that agrees with its
  physical path ID before it can contribute attribution.
- `refresh_effects.csv` includes only post-warm-up `prism_recycle`
  round-completion terminals whose existing `_replacement_chain_complete`
  proof succeeds. Its non-overlapping windows are anchored to terminal time
  `t`: preceding `[t - width, t)` and following `[t, t + width)`.
- A refresh ratio is blank when its window is partial with respect to the
  post-warm-up observation range or has zero ACKed bytes; the ratio change is
  blank unless both ratios are available.
- `summary.csv` contains one row per run/seed for figure use, including the
  base RTT, width, traffic totals/ratio, bin count, and refresh-effect means.

## TDD Evidence

Red command, run after adding the focused fixtures and before adding production
code:

```text
$ python3 -m unittest htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.tests.test_distribution
ModuleNotFoundError: No module named 'htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.analyze_distribution'
Ran 1 test
FAILED (errors=1)
```

Green command, run after implementation:

```text
$ python3 -m unittest htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.tests.test_distribution
Ran 7 tests in 0.020s
OK
```

## Verification

```text
$ python3 -m unittest htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.tests.test_distribution htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.tests.test_analyze htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.tests.test_workload
Ran 64 tests in 0.221s
OK

$ python3 -m py_compile htsim/sim/datacenter/add_motivation/expM3_residual_spread_coordination/analyze_distribution.py htsim/sim/datacenter/add_motivation/expM3_residual_spread_coordination/tests/test_distribution.py
exit 0

$ git diff --check
exit 0
```

## Concerns

None. Full-window eligibility uses the post-warm-up lower bound and the latest
post-warm-up ACK timestamp; a trace ending before a following window completes
intentionally produces blank effect ratios rather than an inferred value.
