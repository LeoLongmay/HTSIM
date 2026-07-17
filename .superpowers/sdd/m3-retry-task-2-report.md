# M3 Retry Task 2 Report

## Scope

Implemented Task 2 trace and M3 validation support for the coordinator's
`round_complete_retry` terminal. No C++ coordinator files were changed.

## Changes

- Added `round_complete_retry` to the accepted coordination actions in
  `trace_schema.py`.
- Enforced the retry terminal tuple exactly: `refresh_complete=1`,
  `progress=0`, and `handoff=0`.
- Added schema coverage for valid retry terminals and rejection of each invalid
  flag value through both normal and compact trace loaders.
- Extended the M3 analysis fixture to emit retry terminals while retaining the
  existing replacement-chain construction. The regression verifies retry is
  counted in `completed_rounds` but not in `progress_rounds` or
  `handoff_rounds`, and that replacement-chain validation still succeeds.
- Extended the coordination CLI trace inspection so any emitted
  `round_complete_retry` row is checked for the required terminal tuple.

## TDD Evidence

Before the schema implementation, the required focused command failed with
three errors. Both trace loaders rejected `round_complete_retry` as an unknown
coordination action, and the analyzer retry fixture failed while loading its
trace.

After the schema implementation, the same command passed all 87 tests.

## Verification

- `python3 -m unittest htsim.sim.datacenter.add_motivation.common.tests.test_trace_schema htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.tests.test_analyze`
  - Passed: 87 tests.
- `bash htsim/sim/datacenter/add_motivation/common/tests/test_prism_coordination_cli.sh`
  - Passed.
- `git diff --check`
  - Passed.

## Note

The existing CLI smoke workload completed successfully but did not itself enter
the invalidation-and-refresh path that emits a retry terminal. Its assertion is
therefore per emitted retry row; the deterministic analyzer fixture and the
existing C++ coordinator unit test cover retry construction and its valid
replacement chain.

## Important Task 2 Review Fix

Updated the retry analyzer fixture to model the production terminal: retry is
emitted in `full_prism` with reason `spread_not_reduced`.

Exact verification command and output:

```text
$ python3 -m unittest htsim.sim.datacenter.add_motivation.expM3_residual_spread_coordination.tests.test_analyze
...............................................
----------------------------------------------------------------------
Ran 47 tests in 0.196s

OK
```
