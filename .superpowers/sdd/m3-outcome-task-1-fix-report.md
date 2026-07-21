# M3 Outcome Task 1 Fix Report

## Scope

Applied the minimal Task 1 review fixes on top of `f9e41cb`.

- A later outcome invalidation now clears validation progress and all active/completed post-window state.
- `CircularBufferREPS::resetBuffer()` now clears reserved replacement slots.

## Regression Coverage

- `later_invalidation_restarts_outcome_validation_and_post_windows` validates A, completes a post window, invalidates B, and proves no outcome emits until B validates and two new post windows complete.
- `reset_buffer_clears_reserved_slot_before_path_good_admission` reserves an invalidated slot, drives the existing reset path, and verifies the following `PATH_GOOD` admission uses ordinary head slot 0.

## Verification

Red run before the implementation changes:

```text
prism_coordination: assertion !coordinator.outcomeReplacementsValidated() failed
reps_slot_cache: assertion reps.lastAdmission().cache_slot == 0 failed
```

Green run after the implementation changes:

```text
cmake --build htsim/sim/build --target test_prism_coordination test_reps_slot_cache -j2
ctest --test-dir htsim/sim/build -R '^(prism_coordination|reps_slot_cache)$' --output-on-failure

100% tests passed, 0 tests failed out of 2
```
