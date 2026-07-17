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

## Task 2 Findings Fix Report

### Changes

- `analyze_distribution` now validates all discovered manifests before loading
  trace data or writing figure inputs. The required keys are exactly
  `original_prism` and `prism_recycle` crossed with `recoverable` and
  `persistent`, for seeds `13`, `14`, and `15`, each exactly once. Missing,
  duplicate, and unexpected scenario/seed keys raise `ValueError`.
- Analysis fixtures now build the complete locked matrix. Focused regressions
  cover missing manifests, duplicate manifest bundles, unexpected scenarios and
  seeds, and independently zero-byte complete pre and post refresh-effect
  windows. Zero-byte windows retain their complete flag but write blank ratio
  and ratio-change fields.

### TDD Evidence

Red command, after adding the malformed-matrix tests and before the manifest
validator:

```text
$ python3 -m unittest htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.tests.test_distribution
...FF.....
======================================================================
FAIL: test_rejects_duplicate_manifest_from_locked_trial_matrix
FAIL: test_rejects_missing_manifest_from_locked_trial_matrix
FAIL: test_rejects_unexpected_manifest_scenario_or_seed (field='scenario')
FAIL: test_rejects_unexpected_manifest_scenario_or_seed (field='seed')

Ran 11 tests in 0.216s

FAILED (failures=4)
```

Green command, after the manifest validator and zero-byte regressions:

```text
$ python3 -m unittest htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.tests.test_distribution
...........
----------------------------------------------------------------------
Ran 11 tests in 0.227s

OK
```

Additional verification:

```text
$ python3 -m py_compile htsim/sim/datacenter/add_motivation/expM3_residual_spread_coordination/analyze_distribution.py htsim/sim/datacenter/add_motivation/expM3_residual_spread_coordination/tests/test_distribution.py
exit 0

$ git diff --check
exit 0
```
