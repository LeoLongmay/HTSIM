# M3 Task 1 Review-Finding Fix Report

Base reviewed: `c931285`.

## Red Evidence

After adding the analyzer regressions and before changing production code:

```text
python3 -m unittest htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.tests.test_analyze
Ran 46 tests
FAILED (failures=4)
```

The four subtests changed `config.degraded_links` and `analysis_config.degraded_links` independently for recoverable (8 instead of 2) and persistent (2 instead of 8). Each failed because the analyzer accepted the manifest without raising `ValueError`.

The new recoverable/full_prism pre-warmup malformed-terminal test was already green on the base: terminal evidence validation runs before the warm-up exclusion. It remains as an ordering regression guard. The existing causally valid pre-warmup recoverable handoff test continues to assert that no round evidence is emitted.

## Green Evidence

```text
python3 -m unittest htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.tests.test_analyze
Ran 46 tests
OK

python3 -m unittest htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.tests.test_workload htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.tests.test_analyze
Ran 52 tests
OK
```

## Changes

- `_load_manifest()` now requires both `config.degraded_links` and `analysis_config.degraded_links` to equal 2 for recoverable manifests and 8 for persistent manifests.
- The shared fixture records the scenario-locked count in both manifest sections.
- Tests cover each manifest section for both scenarios and keep a pre-warmup recoverable/full_prism malformed-terminal rejection regression.

## Concerns

None. The analyzer accepts numeric JSON values equal to the locked integer counts; nonnumeric or mismatched values are rejected.
