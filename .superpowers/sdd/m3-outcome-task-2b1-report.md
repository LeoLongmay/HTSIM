# M3 Outcome Task 2b1 Report

## Scope

Added a standalone `outcome.csv` trace writer and strict optional loader schema.
The change is limited to `motivation_trace`, the common trace schema, and their
focused tests. No UEC, CLI, runner, Task 1, or output-data files changed.

## Outcome Record

Each row records standard metadata (`schema_version`, `run_id`, `seed`, and
`scenario`), event/time/flow/round identity, `window_ps`, and complete
pre/post1/post2 classified bytes, harmful bytes, and exposure ratios.
The writer exposes only `MotivationOutcomeRecord` and `logOutcome`; it does not
define or emit a partial-outcome record.

`TraceBundle.outcome` is empty when `outcome.csv` is absent. When present, the
strict loaders validate its header, types, finite in-range exposure ratios, byte
bounds, event sequence, global event ordering, and run identity.

## TDD Evidence

Red, after adding the C++ writer expectation before the API existed:

```text
$ cmake --build htsim/sim/build --target test_trace_writer -j2
error: 'class MotivationTraceWriter' has no member named 'logOutcome'
```

Red, after adding the focused Python expectations before loader support:

```text
$ python3 -m unittest ...test_trace_schema.TraceSchemaTests.test_loads_optional_outcome_file_with_explicit_types ...test_outcome_file_is_optional_for_existing_trace_bundles
FAILED (failures=1, errors=2)
```

## Verification

```text
$ python3 -m unittest htsim.sim.datacenter.add_motivation.common.tests.test_trace_schema
Ran 42 tests
OK

$ cmake --build htsim/sim/build --target test_trace_writer -j2
$ ctest --test-dir htsim/sim/build -R '^trace_writer$' --output-on-failure
1/1 Test #7: trace_writer ... Passed

$ git diff --check
exit 0
```

## Concerns

No production emitter calls `logOutcome` yet by design; this task supplies only
the independent writer and schema contract. The outcome file is created by an
enabled trace writer but remains optional to Python bundle loading so existing
trace prefixes without it remain valid.
