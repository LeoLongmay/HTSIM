# Lossless Egress Shared-Overflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `lossless_input` use each egress queue's 150KB dedicated allocation before borrowing its switch's 32MiB shared pool, eliminating hard-capacity diagnostics caused by PFC in-flight overshoot.

**Architecture:** Move pool accounting from ingress virtual queues to their owning lossless output queues. An output queue compares occupancy before/after enqueue or dequeue against `_maxsize`; only the positive excess is reserved/released from its attached non-owning pool. Existing ingress 120/90KB PFC and non-lossless queue behavior remain untouched.

**Tech Stack:** C++17, HTSIM queues/EventList, CMake/CTest.

## Global Constraints

- Apply only to `LOSSLESS_INPUT`; ExpA and other queue modes are unchanged.
- `_maxsize` remains the 150000-byte dedicated egress allocation, not a drop threshold in lossless-input mode.
- Reserve exactly `max(0, new_occupancy - _maxsize) - max(0, old_occupancy - _maxsize)` from the owning 32MiB pool on enqueue; release the inverse delta on dequeue.
- A failed shared-pool reservation throws `std::logic_error("shared-buffer capacity exceeded")` without modifying queue occupancy.
- Do not change LAPS routing, recovery, pacing, congestion control, or 120/90KB ingress PFC thresholds.

---

### Task 1: Egress overflow accounting and unit regression

**Files:**
- Modify: `htsim/sim/queue_lossless_input.h`
- Modify: `htsim/sim/queue_lossless_input.cpp`
- Modify: `htsim/sim/queue_lossless_output.h`
- Modify: `htsim/sim/queue_lossless_output.cpp`
- Modify: `htsim/sim/datacenter/fat_tree_topology.cpp`
- Modify: `htsim/sim/datacenter/add_motivation/common/tests/test_lossless_pfc.cpp`

- [ ] **Step 1: Write failing egress-overflow tests**

Extend `test_lossless_pfc.cpp` with a `LosslessOutputQueue` of dedicated size 100 and a `SharedBufferPool(40, 40, 39)`. Attach the pool to the output queue, enqueue 80 then 30 bytes through real virtual queues, assert `pool.used() == 10`, drain both packets, and assert `pool.used() == 0`. A separate 100+41-byte case must throw `std::logic_error("shared-buffer capacity exceeded")` and preserve both `pool.used()` and output queue occupancy.

- [ ] **Step 2: Confirm RED**

Run `cmake --build htsim/sim/build-lossless --target test_lossless_pfc && htsim/sim/build-lossless/test_lossless_pfc`.

Expected: compilation fails because output-pool attachment/overflow behavior is absent.

- [ ] **Step 3: Implement minimal accounting**

Add `LosslessOutputQueue::setSharedBuffer(SharedBufferPool&)`. Before enqueue, calculate the overflow delta from `_queuesize` and `pkt.size()`, reserve only a positive delta, and throw the exact error on failure. After dequeue, calculate the old/new overflow and release only the positive decrease. Remove pool reserve/release from `LosslessInputQueue`; it keeps only per-ingress PFC occupancy. In `FatTreeTopology`, attach each per-switch pool to all `LOSSLESS_INPUT` output queues on that switch rather than its ingress VQs.

- [ ] **Step 4: Confirm GREEN and commit**

Run `cmake --build htsim/sim/build-lossless --target test_lossless_pfc test_shared_buffer_pool htsim_uec`, execute both tests, run `bash htsim/sim/datacenter/add_motivation/common/tests/test_lossless_cli.sh`, and `git diff --check`. Commit only Task 1 source/test files with `fix: account lossless egress overflow in shared pool`.

### Task 2: Four-arm smoke revalidation

**Files:** generated only under `htsim/sim/datacenter/prism_eval/expL_laps_lossless/data`.

- [ ] **Step 1: Re-run the existing OPS/REPS/LAPS/Prism smoke cells**

Use failure 0, seed 13, `PATHS=8`, `END_MS=8`, and the exact lossless flags. Require four nonempty flow files, each completion fraction 1.00, zero `LOSSLESS not working!`, and zero `shared-buffer capacity exceeded` diagnostics.

- [ ] **Step 2: Gate preview run**

Only after Step 1 passes, permit the existing default 140-run preview and three figures. Never run `--all-baselines` in this plan.

## Plan self-review

- Covers dedicated vs shared occupancy semantics, no mutation on pool failure, topology ownership, regression tests, and the smoke gate.
- Does not change any non-lossless path, PFC thresholds, experiment workload, or congestion controller.
