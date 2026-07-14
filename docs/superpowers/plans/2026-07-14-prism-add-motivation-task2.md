# Prism Add-Motivation Task 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add behavior-neutral Legacy REPS/Prism tracing and offline M1/M2 analyses under `htsim/sim/datacenter/add_motivation` to validate residual-quality discrimination and redistribution no-progress without implementing recycling or CC handoff.

**Architecture:** The simulator emits versioned primitive ACK, Legacy REPS token, and epoch CSV events with one shared event sequence, plus versioned static path and link metadata CSVs that do not consume that sequence. Python validates those files, computes same-epoch residuals, and projects the real Legacy REPS FIFO into a virtual eight-slot shadow validation cache. The shadow never feeds entropy selection or congestion control.

**Tech Stack:** C++17, HTSIM UEC/REPS, Python 3 standard library, NumPy, Matplotlib, Bash, CMake.

## Global Constraints

- Create `htsim/sim/datacenter/add_motivation` beside `prism_eval`; never overwrite Evaluation data.
- Keep `-load_balancing_algo reps` mapped to `UecMpRepsLegacy`; do not modify `CircularBufferREPS` or the `freezing` arm.
- Do not implement entropy invalidation, replacement policy, recycling control, CC handoff, or any new cwnd action.
- Trace is disabled by default and must not allocate files, scan paths, or call trace callbacks when disabled.
- Trace callbacks must not call `rand()`/`random()`, modify token ordering, or alter controller state.
- M1 uses same-epoch raw floor and genuine ACKs only; never use the previous epoch or a smoothed floor for per-ACK residual.
- M2's `B=8` slots are offline virtual state, never described as Legacy REPS physical slots.
- Calibration uses seeds `101,102,103`; formal runs use seeds `13,14,15,16,17` only after `formal.csv` is locked.
- Formal results retain negative outcomes and right-censored rounds; no seed or flow filtering.
- Use `apply_patch` for manual edits and keep unrelated dirty-worktree files untouched.

---

## File Map

**Production C++**

- Modify `htsim/sim/uec_mp.h`: selection/token trace types and no-op-compatible multipath observer interface.
- Modify `htsim/sim/uec_mp.cpp`: Legacy REPS token IDs, enqueue/dequeue observations, and last-selection metadata.
- Create `htsim/sim/motivation_trace.h`: versioned row types and writer interface.
- Create `htsim/sim/motivation_trace.cpp`: lazy CSV writers, shared event sequence, headers, filtering, and failures.
- Create `htsim/sim/motivation_epoch.h`: pure independent epoch observer used by all sender CC modes.
- Modify `htsim/sim/uec.h`: send-record metadata, motivation configuration, observer state, and path resolver state.
- Modify `htsim/sim/uec.cpp`: ACK/token correlation, observer invocation, ACK/epoch/path/link emission.
- Modify `htsim/sim/queue.h`: read-only queue name/rate accessors only.
- Modify `htsim/sim/datacenter/main_uec.cpp`: four motivation CLI arguments and resolver installation.
- Modify `htsim/sim/CMakeLists.txt`: compile `motivation_trace.cpp` into `htsim`.

**Tests and analysis**

- Create `htsim/sim/datacenter/add_motivation/common/tests/test_legacy_reps_trace.cpp`.
- Create `htsim/sim/datacenter/add_motivation/common/tests/test_motivation_epoch.cpp`.
- Create `htsim/sim/datacenter/add_motivation/common/trace_schema.py`.
- Create `htsim/sim/datacenter/add_motivation/common/shadow_replay.py`.
- Create `htsim/sim/datacenter/add_motivation/common/tests/test_trace_schema.py`.
- Create `htsim/sim/datacenter/add_motivation/common/tests/test_shadow_replay.py`.
- Create the M1/M2 directory trees, configs, runners, analyzers, plotters, READMEs, and `.gitignore` files from the approved design.

---

### Task 1: Legacy REPS Token Identity and Selection Metadata

**Files:**
- Modify: `htsim/sim/uec_mp.h:16-92`
- Modify: `htsim/sim/uec_mp.cpp:213-276`
- Create: `htsim/sim/datacenter/add_motivation/common/tests/test_legacy_reps_trace.cpp`

**Interfaces:**
- Produces: `UecMpSelection`, `UecMpTokenEvent`, `UecMultipath::lastSelection()`, `setTokenObserver()`, and `setFeedbackTraceContext()`.
- Preserves: `UecMultipath::nextEntropy(...) -> uint32_t` and all existing entropy choices.

- [ ] **Step 1: Write a failing Legacy REPS trace test**

Create a test that drives first-window, good feedback, recycled selection, and empty-list random selection:

```cpp
#include "uec_mp.h"
#include <cassert>
#include <vector>

int main() {
    UecMpRepsLegacy reps(8, false);
    std::vector<UecMpTokenEvent> events;
    reps.setTokenObserver([&](const UecMpTokenEvent& e) { events.push_back(e); });

    (void)reps.nextEntropy(0, 8);
    assert(reps.lastSelection().source == UecMpSelection::FIRST_WINDOW);

    reps.setFeedbackTraceContext(41);
    reps.processEv(3, UecMultipath::PATH_GOOD);
    assert(events.back().operation == UecMpTokenEvent::ENQUEUE_GOOD_ACK);
    assert(events.back().related_ack_event_seq == 41);

    uint32_t entropy = reps.nextEntropy(8, 8);
    assert(entropy == 3);
    assert(reps.lastSelection().source == UecMpSelection::RECYCLED);
    assert(reps.lastSelection().token_id == events.front().token_id);

    (void)reps.nextEntropy(9, 8);
    assert(reps.lastSelection().source == UecMpSelection::RANDOM_EMPTY);
}
```

- [ ] **Step 2: Compile to verify the new interface is absent**

Run from `htsim/sim/datacenter`:

```bash
g++ -std=c++17 -I.. add_motivation/common/tests/test_legacy_reps_trace.cpp \
  ../build/libhtsim.a -o /tmp/test_legacy_reps_trace
```

Expected: compilation fails because `UecMpTokenEvent` and the observer methods do not exist.

- [ ] **Step 3: Add trace-only types without changing `nextEntropy` signatures**

Add to `uec_mp.h`:

```cpp
struct UecMpSelection {
    enum Source : uint8_t { UNKNOWN, RECYCLED, FIRST_WINDOW, RANDOM_EMPTY };
    static constexpr uint64_t NO_TOKEN = UINT64_MAX;
    uint32_t entropy = 0;
    Source source = UNKNOWN;
    uint64_t token_id = NO_TOKEN;
};

struct UecMpTokenEvent {
    enum Operation : uint8_t {
        ENQUEUE_GOOD_ACK,
        DEQUEUE_RECYCLE,
        SELECT_FIRST_WINDOW,
        SELECT_RANDOM_EMPTY
    };
    static constexpr uint64_t NO_EVENT = UINT64_MAX;
    Operation operation;
    uint64_t token_id;
    uint32_t entropy;
    uint32_t queue_depth_before;
    uint32_t queue_depth_after;
    uint64_t related_ack_event_seq = NO_EVENT;
};
```

Add default no-op methods to `UecMultipath` so non-REPS algorithms require no changes:

```cpp
using TokenObserver = std::function<void(const UecMpTokenEvent&)>;
virtual UecMpSelection lastSelection() const { return {}; }
virtual void setTokenObserver(TokenObserver) {}
virtual void setFeedbackTraceContext(uint64_t) {}
```

Change `UecMpRepsLegacy::_next_pathid` from `list<uint32_t>` to:

```cpp
struct Token { uint32_t entropy; uint64_t id; };
list<Token> _next_tokens;
uint64_t _next_token_id = 0;
uint64_t _feedback_event_seq = UecMpTokenEvent::NO_EVENT;
UecMpSelection _last_selection;
TokenObserver _token_observer;
```

Emit observer rows only after the existing entropy/list state transition. Do not add any RNG call.

- [ ] **Step 4: Run the trace test and a deterministic entropy regression**

Compile and run the new test, then run an on/off observer fixture that constructs two instances
with the same `srandom()` seed and compares 100 returned entropies.

Expected: both tests pass and the 100-element entropy vectors are identical.

- [ ] **Step 5: Commit Task 1**

```bash
git add htsim/sim/uec_mp.h htsim/sim/uec_mp.cpp \
  htsim/sim/datacenter/add_motivation/common/tests/test_legacy_reps_trace.cpp
git commit -m "trace: expose Legacy REPS token lifecycle"
```

---

### Task 2: Versioned Motivation Trace Writer and CLI

**Files:**
- Create: `htsim/sim/motivation_trace.h`
- Create: `htsim/sim/motivation_trace.cpp`
- Modify: `htsim/sim/CMakeLists.txt:53-130`
- Modify: `htsim/sim/datacenter/main_uec.cpp:189-249,666-669`
- Create: `htsim/sim/datacenter/add_motivation/common/tests/test_trace_writer.cpp`

**Interfaces:**
- Produces: `MotivationTraceWriter::configure`, `enabledFor`, `nextEventSeq`, `logAck`, `logToken`, `logEpoch`, `logPath`, and `logLink`.
- Consumes: `UecMpTokenEvent` from Task 1.

- [ ] **Step 1: Write a failing writer test**

The test configures `/tmp/motivation_writer_test`, writes one token row, closes the writer, and
asserts the exact header and `schema_version=1` row.

```cpp
MotivationTraceWriter writer;
writer.configure("/tmp/motivation_writer_test", "run", "scenario", 13, -1);
uint64_t seq = writer.nextEventSeq();
writer.logToken(seq, 7, 1000, event);
writer.close();
assert(firstField("/tmp/motivation_writer_test.token.csv", 2) == "1");
```

- [ ] **Step 2: Verify the writer test fails to compile**

Expected: `MotivationTraceWriter` is undefined.

- [ ] **Step 3: Implement lazy, fail-fast CSV output**

Define configuration:

```cpp
struct MotivationTraceConfig {
    std::string prefix;
    std::string run_id;
    std::string scenario;
    uint32_t seed = 0;
    int64_t flow_filter = -1;
};
```

The writer opens `<prefix>.{ack,token,epoch,pathmap,linkmap}.csv` only from `configure()` when
`prefix` is non-empty. Failed opens throw `std::runtime_error`. `enabledFor(flow)` is:

```cpp
return _enabled && (_config.flow_filter < 0 ||
                    static_cast<uint64_t>(_config.flow_filter) == flow_id);
```

Use one `uint64_t _event_seq` shared by ACK, token, and epoch event rows. Pathmap and linkmap are
static metadata, follow the exact Section 5.6 schemas, and do not consume `event_seq`. The token CSV
includes `related_ack_event_seq`; all CSV headers are the exact schemas in the spec.
Do not flush every row; flush/close at process teardown and explicit test close.

Production uses one process-wide writer owned by `UecSrc`; individual sources only query and log
through that writer. This keeps `event_seq` globally monotonic across flows. The writer remains
directly constructible so the unit test can isolate file lifecycle behavior.

- [ ] **Step 4: Add CLI parsing and configuration**

Add local arguments in `main_uec.cpp`:

```cpp
std::string motivation_prefix;
std::string motivation_run_id;
std::string motivation_scenario;
int64_t motivation_flow_id = -1;
```

Parse:

```text
-motivation_trace_prefix
-motivation_trace_flow_id
-motivation_run_id
-motivation_scenario
```

After `seed` is finalized, call one static `UecSrc::configureMotivationTrace(...)`. Validate that
run ID and scenario contain no comma or newline.

- [ ] **Step 5: Build and run the writer test**

Run:

```bash
cmake --build htsim/sim/build --target htsim_uec -j2
```

Expected: `htsim_uec` builds and the writer fixture produces all headers without creating files
when configured with an empty prefix.

- [ ] **Step 6: Commit Task 2**

```bash
git add htsim/sim/motivation_trace.h htsim/sim/motivation_trace.cpp \
  htsim/sim/CMakeLists.txt htsim/sim/datacenter/main_uec.cpp \
  htsim/sim/datacenter/add_motivation/common/tests/test_trace_writer.cpp
git commit -m "trace: add versioned motivation CSV writer"
```

---

### Task 3: Independent Epoch Observer and ACK/Token Correlation

**Files:**
- Create: `htsim/sim/motivation_epoch.h`
- Modify: `htsim/sim/uec.h:153-165,248-260,511-549`
- Modify: `htsim/sim/uec.cpp:542-670,1082-1230,1854-1982,2950-3098`
- Create: `htsim/sim/datacenter/add_motivation/common/tests/test_motivation_epoch.cpp`

**Interfaces:**
- Produces: `MotivationEpochObserver::observe(...) -> optional<MotivationEpochResult>`.
- Extends: `sendRecord` with `selection_source` and `source_token_id`.
- Consumes: writer and Legacy selection metadata from Tasks 1-2.

- [ ] **Step 1: Write failing pure epoch tests**

Use a base RTT of 10 us, `kappa=1`, and `n_min=3`:

```cpp
MotivationEpochObserver obs(1.0, 3, 1.0, 0.0);
assert(!obs.observe(0, 2000, true, 1, 0, 10000));
assert(!obs.observe(5000, 9000, true, 2, 1, 10000));
auto result = obs.observe(10000, 5000, true, 1, 0, 10000);
assert(result);
assert(result->raw_floor_ps == 2000);
assert(result->raw_spread_ps == 7000);
assert(result->sample_count == 3);
```

Also assert that `genuine=false` does not increment samples and that elapsed time with fewer than
`n_min` samples defers closure.

- [ ] **Step 2: Verify tests fail before adding the observer**

Expected: missing `motivation_epoch.h`.

- [ ] **Step 3: Implement the pure observer**

`MotivationEpochResult` contains epoch IDs/times, sample count, raw/smoothed floor/spread, observed
region, and entropy/path coverage counts. The observer:

```cpp
if (!genuine) return std::nullopt;
if (_samples == 0) { _start = now; _min = _max = q; }
else { _min = std::min(_min, q); _max = std::max(_max, q); }
++_samples;
if (now - _start < kappa * base_rtt || _samples < n_min) return std::nullopt;
```

Apply EWMA and `prism::decide_region` only after closure, return the result, then reset raw epoch
state and increment epoch ID.

- [ ] **Step 4: Preserve per-send selection metadata**

Immediately after each `_mp->nextEntropy(...)`, read `_mp->lastSelection()`. Pass it to an expanded
`createSendRecord(...)` and store it in `sendRecord`. Unknown metadata remains the default for
non-Legacy algorithms.

- [ ] **Step 5: Log ACK before calling `processEv` and pass explicit context**

For each ACK, after final `qdelay` and genuine status are known:

```cpp
uint64_t ack_event_seq = motivationLogAck(..., send_record.selection);
_mp->setFeedbackTraceContext(ack_event_seq);
_mp->processEv(pkt.ev(), feedback);
```

Install the Legacy token observer once in `UecSrc` construction. Its callback obtains a fresh
writer event sequence and logs the token event with the current `flowId()`.

- [ ] **Step 6: Run unit tests and build**

Expected: epoch tests pass; `htsim_uec` builds; existing Prism decomposition tests still pass.

- [ ] **Step 7: Commit Task 3**

```bash
git add htsim/sim/motivation_epoch.h htsim/sim/uec.h htsim/sim/uec.cpp \
  htsim/sim/datacenter/add_motivation/common/tests/test_motivation_epoch.cpp
git commit -m "trace: observe ACK epochs without changing control"
```

---

### Task 4: Physical-Path and Link Metadata

**Files:**
- Modify: `htsim/sim/queue.h:25-93`
- Modify: `htsim/sim/uec.h:162-165,528-549`
- Modify: `htsim/sim/uec.cpp:1591-1675`
- Modify: `htsim/sim/datacenter/main_uec.cpp:1040-1050`

**Interfaces:**
- Produces: read-only `BaseQueue::bitrate()` and `queueName()`, motivation path resolver setup,
  path IDs, used-path backlog, pathmap rows, and deduplicated linkmap rows.
- Reuses: `FatTreeTopology::resolve_ecmp_path` already used by expJ.

- [ ] **Step 1: Add a failing accessor/path metadata fixture**

Extend the path-resolution fixture to assert two entropies with identical ordered queue names get
the same physical path ID and one link row per unique queue name.

- [ ] **Step 2: Add read-only queue accessors**

Add only:

```cpp
linkspeed_bps bitrate() const { return _bitrate; }
const std::string& queueName() const { return _nodename; }
```

No queue method or member used for service is changed.

- [ ] **Step 3: Install the resolver when either Oracle or motivation tracing needs it**

Keep Oracle behavior unchanged. Add a separate `motivationSetPathResolver(...)` call guarded by
`MotivationTraceWriter::enabled()`. The lambda remains:

```cpp
return topology->resolve_ecmp_path(src, dest, flow_id, entropy, queues);
```

- [ ] **Step 4: Emit stable path/link metadata**

Use ordered queue names, not pointers, for a stable fingerprint. Serialize ordered queue IDs with
`|`. Set `contains_reduced_link` when `queue.bitrate() < UecSrc::_network_linkspeed`. Set the path
bottleneck to the minimum queue bitrate. Deduplicate link rows globally by queue name.

At ACK time, sum `backlogDrainTime()` across only the used resolved path. Resolution failures emit
`resolution_status` and leave path-specific fields invalid.

- [ ] **Step 5: Build and verify expJ still parses current schema**

Run:

```bash
cmake --build htsim/sim/build --target htsim_uec -j2
python3 htsim/sim/datacenter/prism_eval/expJ_oracle_validation/make_figs.py --selftest
```

Expected: build and expJ self-test pass.

- [ ] **Step 6: Commit Task 4**

```bash
git add htsim/sim/queue.h htsim/sim/uec.h htsim/sim/uec.cpp \
  htsim/sim/datacenter/main_uec.cpp
git commit -m "trace: record motivation path and link metadata"
```

---

### Task 5: Trace Schema Validation and Same-Epoch Residuals

**Files:**
- Create: `htsim/sim/datacenter/add_motivation/common/trace_schema.py`
- Create: `htsim/sim/datacenter/add_motivation/common/tests/test_trace_schema.py`

**Interfaces:**
- Produces: `load_trace(prefix) -> TraceBundle`, `validate_bundle(bundle)`, and
  `attach_same_epoch_residuals(bundle, t_spray_ps) -> list[AckSample]`.
- Consumes: the five schema-version-1 CSV files from Tasks 2-4.

- [ ] **Step 1: Write failing parser tests with temporary CSVs**

Tests cover valid loading, unknown schema rejection, non-monotonic event sequence rejection,
missing token linkage, genuine-only floor computation, and no previous-epoch leakage.

```python
samples = attach_same_epoch_residuals(bundle, 7_000_000)
assert [s.residual_ps for s in samples] == [0, 9_000_000]
```

- [ ] **Step 2: Run tests to verify imports fail**

```bash
python3 -m unittest add_motivation.common.tests.test_trace_schema -v
```

Expected: module not found.

- [ ] **Step 3: Implement typed rows and strict validation**

Use frozen dataclasses for ACK, token, epoch, path, and link rows. Require `schema_version == 1`.
Validate monotonic `event_seq` for the ACK, token, and epoch event files; path and link files are
static metadata and have no `event_seq`. Validate unique token IDs per flow, enqueue before dequeue,
and `source_token_id` referencing the matching flow's dequeued token.

For residual assignment, group genuine ACKs by `(flow_id, epoch_id)`, compute the minimum `qdelay_ps`
from that exact group, and attach `max(q-floor, 0)`. Preserve ECN ACKs in the group because Prism's
floor/spread observes genuine delay samples regardless of mark; filter ECN only in M1 metrics.

- [ ] **Step 4: Run parser tests**

Expected: all schema tests pass.

- [ ] **Step 5: Commit Task 5**

```bash
git add htsim/sim/datacenter/add_motivation/common/trace_schema.py \
  htsim/sim/datacenter/add_motivation/common/tests/test_trace_schema.py
git commit -m "analysis: validate motivation trace schemas"
```

---

### Task 6: Virtual Eight-Slot Shadow Replay

**Files:**
- Create: `htsim/sim/datacenter/add_motivation/common/shadow_replay.py`
- Create: `htsim/sim/datacenter/add_motivation/common/tests/test_shadow_replay.py`

**Interfaces:**
- Produces: `replay_shadow(bundle, t_cc_ps, t_spray_ps, slots=8) -> ReplayResult`.
- Consumes: validated `TraceBundle` and same-epoch ACK residuals from Task 5.

- [ ] **Step 1: Write failing hand-authored replay tests**

Create event fixtures for:

1. eight seeded tokens all returning low residual and completing one round;
2. high residual invalidation that does not complete its slot;
3. later low-residual enqueue completing one pending slot;
4. ECN and fallback ACKs not completing pending slots;
5. duplicate entropy values with distinct token IDs;
6. flow end before completion producing `right_censored=1`; and
7. `delta_s` classifications for epsilon `0,1,2,4 us`.

Assert explicitly:

```python
assert invalidation_event.slot_complete is False
assert replacement_event.slot_complete is True
assert round_result.delta_s_ps == s_end_ps - s_ref_ps
```

- [ ] **Step 2: Run tests to verify replay is absent**

Expected: import failure.

- [ ] **Step 3: Implement real FIFO reconstruction**

Maintain per-flow `deque[token_id]`. Apply `enqueue_good_ack` and `dequeue_recycle` in shared
`event_seq` order and reject mismatches. At HOLD entry, copy the first eight queued token IDs into
virtual slots and mark remaining slots pending.

- [ ] **Step 4: Implement strict virtual completion semantics**

For seeded slots, match ACKs by `source_token_id`. A genuine, unmarked ACK with residual below
`T_spray` completes the slot. Marked/high/fallback ACKs leave it pending. A later genuine,
unmarked, low-residual ACK not already used to complete another seeded slot fills exactly one
pending slot in deterministic slot-index order. Invalidation alone never completes a slot.

When all slots complete, wait for the next epoch row before setting `S_end`. If no such epoch exists,
right-censor the round.

- [ ] **Step 5: Run replay tests**

Expected: all replay fixtures pass, including duplicate entropy/token isolation.

- [ ] **Step 6: Commit Task 6**

```bash
git add htsim/sim/datacenter/add_motivation/common/shadow_replay.py \
  htsim/sim/datacenter/add_motivation/common/tests/test_shadow_replay.py
git commit -m "analysis: replay virtual Prism validation rounds"
```

---

### Task 7: Experiment Scaffolding and Reproduction Library

**Files:**
- Create: `htsim/sim/datacenter/add_motivation/.gitignore`
- Create: `htsim/sim/datacenter/add_motivation/README.md`
- Create: `htsim/sim/datacenter/add_motivation/common/run_motivation.sh`
- Create: both experiment directories and their `.gitignore`, `README.md`, `configs/calibration.csv`,
  `calibrate.sh`, and `repro.sh` files.

**Interfaces:**
- Produces: one-run wrapper that delegates to `prism_eval/common/run_lib.sh` and emits a trace prefix.
- Consumes: CLI and trace files from Tasks 2-4.

- [ ] **Step 1: Create ignored-data rules and directory READMEs**

Ignore:

```text
data/raw/
data/calibration/
data/shadow/
data/*.cm
data/*.stdout
data/*.flow.txt
data/*.idmap
data/mplconfig/
__pycache__/
```

Do not ignore `configs/*.csv`, `data/summary.csv`, or `figs/`.

- [ ] **Step 2: Implement the one-run wrapper**

`run_motivation.sh` accepts:

```text
CC LB FAILED TOPO SEED CM TAG OUTDIR SCENARIO
```

It sets:

```bash
TRACE_PREFIX="$OUTDIR/raw/$TAG"
EXTRA_ARGS="${EXTRA_ARGS:-} -motivation_trace_prefix $TRACE_PREFIX \
  -motivation_run_id $TAG -motivation_scenario $SCENARIO"
bash "$PRISM_COMMON/run_lib.sh" "$CC" "$LB" "$FAILED" "$TOPO" \
  "$SEED" "$CM" flow "$TAG" "$OUTDIR"
```

Require `LB=reps`; abort on `freezing` so the experiment cannot silently change substrate.

- [ ] **Step 3: Add exact calibration matrices**

M1 `calibration.csv` has all products of `failed={0,2,4,8}`, `load={30,50,70}`, and
`seed={101,102,103}`. M2 has `failed={2,4,8,12}`, `load={20,40,60,80}`, and the same seeds.

- [ ] **Step 4: Add smoke/full runner modes**

`repro.sh smoke` runs one declared config with seed 13. `repro.sh full` refuses to run unless
`configs/formal.csv` has at least one data row and all seeds are exactly `13..17`.

- [ ] **Step 5: Syntax-check all shell scripts**

```bash
bash -n add_motivation/common/run_motivation.sh
bash -n add_motivation/expM1_entropy_quality/calibrate.sh
bash -n add_motivation/expM1_entropy_quality/repro.sh
bash -n add_motivation/expM2_redistribution_progress/calibrate.sh
bash -n add_motivation/expM2_redistribution_progress/repro.sh
```

Expected: no output and exit code 0.

- [ ] **Step 6: Commit Task 7**

```bash
git add htsim/sim/datacenter/add_motivation
git commit -m "experiment: scaffold Prism add-motivation runs"
```

---

### Task 8: M1 Metrics and Statistical Tests

**Files:**
- Create: `htsim/sim/datacenter/add_motivation/expM1_entropy_quality/analyze.py`
- Create: `htsim/sim/datacenter/add_motivation/expM1_entropy_quality/tests/test_analyze.py`

**Interfaces:**
- Produces: per-run and aggregate M1 summary rows, deterministic flow-cluster bootstrap, and formal
  selection from calibration-only summaries.
- Consumes: `trace_schema.load_trace` and attached residuals.

- [ ] **Step 1: Write failing synthetic M1 tests**

Construct two flows where high-current samples have future-high probability `0.75` and low-current
samples have `0.25`; assert `RR=3`. Include entropy collisions and unmatched last samples.

- [ ] **Step 2: Implement next-use matching and metrics**

Sort by `(flow_id, entropy, time_ps, event_seq)` and pair each sample with the next sample in that
group. Compute unmarked high-residual rate, rejected-token exposure through
`related_ack_event_seq`, next-use probabilities, unmatched rate, and entropy/path variants.

- [ ] **Step 3: Implement deterministic cluster bootstrap**

Resample flow IDs with replacement using `numpy.random.default_rng(20260714)`, 2000 replicates.
Compute percentile 95% intervals for high/low future risks and RR. A zero denominator produces an
invalid-reason field, not infinity.

- [ ] **Step 4: Implement calibration-only formal selection**

Reject cells with completion `<0.99`, path coverage below the configured minimum, or missing
high/low next-use groups. Select the gray cell with the largest minimum-over-calibration-seeds
unmarked-high rate among cells whose RR direction is above 1 in all calibration seeds. Pair it with
the `failed=0` control at the same load. Write only those fixed scenario parameters to
`configs/formal.csv`.

- [ ] **Step 5: Run M1 tests**

Expected: synthetic RR, collision, zero-denominator, and calibration selection tests pass.

- [ ] **Step 6: Commit Task 8**

```bash
git add htsim/sim/datacenter/add_motivation/expM1_entropy_quality/analyze.py \
  htsim/sim/datacenter/add_motivation/expM1_entropy_quality/tests/test_analyze.py
git commit -m "analysis: add M1 entropy-quality metrics"
```

---

### Task 9: M1 Figures and Calibration Lock

**Files:**
- Create: `htsim/sim/datacenter/add_motivation/expM1_entropy_quality/make_figs.py`
- Modify: `htsim/sim/datacenter/add_motivation/expM1_entropy_quality/README.md`
- Generate: `configs/formal.csv`, `data/summary.csv`, and `figs/m1_entropy_quality.{png,pdf}`

**Interfaces:**
- Produces: approved three-panel M1 figure and a locked formal matrix.

- [ ] **Step 1: Add a plotting self-test**

Use an in-memory synthetic summary and assert the renderer creates three axes with titles containing
`Residual`, `Next-use risk`, and `Token exposure`.

- [ ] **Step 2: Implement the renderer**

Use `prism_eval/common/plot_style.py`. Panel A is an unmarked residual ECDF; Panel B is low/high
next-use future-high probability with flow-cluster CIs; Panel C is actual-token rejection exposure
and future-high risk. Put per-seed/path correlation outputs in appendix files, not the main panel.

- [ ] **Step 3: Run M1 calibration**

```bash
cd htsim/sim/datacenter
bash add_motivation/expM1_entropy_quality/calibrate.sh
python3 add_motivation/expM1_entropy_quality/analyze.py --calibration --select-formal
```

Expected: all 36 calibration runs are present or explicitly failed; `formal.csv` contains one
symmetric and one gray row selected without reading formal seeds.

- [ ] **Step 4: Review and commit the locked M1 matrix**

Record selected capacity/load, completion, coverage, high-residual rate, and RR direction in the
README. Commit calibration summaries only if small; keep raw calibration traces ignored.

- [ ] **Step 5: Run the always-on original Prism robustness arm**

For the locked symmetric and gray scenarios, run the same five formal seeds with `CC=prism` and:

```text
-prism_smooth_beta 1 -prism_hysteresis 0
-prism_engage_spread 0 -prism_engage_mult 0
-target_q_delay 14 -prism_t_spray 7 -prism_kappa 2 -prism_n_min 3
```

Store these rows under `arm=original_prism_appendix`. They must not replace the `REPS+NSCC` main
result or participate in calibration selection.

- [ ] **Step 6: Commit Task 9**

```bash
git add htsim/sim/datacenter/add_motivation/expM1_entropy_quality
git commit -m "experiment: calibrate M1 entropy-quality scenarios"
```

---

### Task 10: M2 Capacity Witness and Round Metrics

**Files:**
- Create: `htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/analyze.py`
- Create: `htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/tests/test_analyze.py`

**Interfaces:**
- Produces: deduplicated cut capacity, run/seed round summaries, epsilon sensitivity, and
  calibration-only recoverable/persistent selection.
- Consumes: `shadow_replay.replay_shadow`, pathmap/linkmap, sink/flow metrics.

- [ ] **Step 1: Write failing capacity and classification tests**

Use two paths sharing one healthy cut link and one reduced link. Assert shared healthy capacity is
counted once. Test:

```python
assert classify_capacity(600, 800, 950) == "recoverable"
assert classify_capacity(850, 800, 950) == "persistent"
assert classify_capacity(1000, 800, 950) == "overload"
```

- [ ] **Step 2: Implement stable cut-link deduplication**

Identify the destination-pod ingress cut from ordered queue names and deduplicate by `queue_id`.
Compute healthy capacity from links with `reduced_speed=0` and effective capacity from all cut
links. If a path cannot identify the cut, mark capacity invalid rather than summing path bottlenecks.

- [ ] **Step 3: Aggregate replay metrics**

Output episode count/fraction, completion/right-censor rates, completion latency, Hold duration,
`S_ref`, `S_end`, `delta_s`, literal no-progress, epsilon rates, FIFO depth, replacements, coverage,
cwnd, offered load, measured sink rate, and both capacities. Bootstrap by flow as in M1.

- [ ] **Step 4: Implement calibration-only pair selection**

Recoverable candidates require `L_offered < C_healthy`, predominantly low floor, completed rounds
in every calibration seed, and negative median `delta_s` in every calibration seed. Persistent
candidates require `C_healthy < L_offered < C_effective`, predominantly low floor, completed rounds,
and majority literal no-progress in every calibration seed. Choose the pair with the largest minimum
round count. If no pair exists, write `selection_status=blocked` and do not invent a formal matrix.

- [ ] **Step 5: Run M2 tests**

Expected: shared-link capacity, overload exclusion, right-censor exclusion, epsilon sensitivity,
and deterministic pair selection tests pass.

- [ ] **Step 6: Commit Task 10**

```bash
git add htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/analyze.py \
  htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/tests/test_analyze.py
git commit -m "analysis: add M2 redistribution progress metrics"
```

---

### Task 11: M2 Figures and Calibration Lock

**Files:**
- Create: `htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/make_figs.py`
- Modify: `htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/README.md`
- Generate: `configs/formal.csv`, `data/summary.csv`, and
  `figs/m2_redistribution_progress.{png,pdf}`

**Interfaces:**
- Produces: recoverable/persistent event-aligned figure and locked formal scenarios.

- [ ] **Step 1: Add a plotting self-test**

Synthetic data must render two scenario columns, `F/S/S_ref` top panels, cwnd/state lower panels,
and round start/complete markers without overlapping labels.

- [ ] **Step 2: Implement event-aligned aggregation and rendering**

Use round-start time as zero. Plot per-seed light traces plus flow-cluster median/CI. Shade Hold,
draw `T_cc`/`T_spray`, and add insets for `delta_s`, completion, and no-progress. Capacity and
censoring remain in a companion CSV/table, not crowded into the time-series panels.

- [ ] **Step 3: Run M2 calibration and deterministic selection**

```bash
cd htsim/sim/datacenter
bash add_motivation/expM2_redistribution_progress/calibrate.sh
python3 add_motivation/expM2_redistribution_progress/analyze.py \
  --calibration --select-formal
```

Expected: either a locked recoverable/persistent pair with all selection evidence, or an explicit
blocked/negative calibration result. Do not proceed to formal runs if blocked.

- [ ] **Step 4: Run the Prism v2 appendix smoke on selected scenarios**

Use the same scenarios with:

```text
-prism_smooth_beta 0.3 -prism_hysteresis 0.25
-prism_engage_mult 2 -prism_disengage_ratio 0.7
```

This appendix is observational and cannot replace the always-on main result.

- [ ] **Step 5: Commit Task 11**

```bash
git add htsim/sim/datacenter/add_motivation/expM2_redistribution_progress
git commit -m "experiment: calibrate M2 redistribution scenarios"
```

---

### Task 12: Behavior-Invariance Smoke and Full Formal Runs

**Files:**
- Modify: both experiment READMEs with verified commands/results.
- Generate: final summaries and figures for M1 and M2.

**Interfaces:**
- Verifies all prior tasks and produces final committed Motivation artifacts.

- [ ] **Step 1: Run the complete local test suite**

```bash
cmake --build htsim/sim/build --target htsim_uec -j2
python3 -m unittest discover \
  htsim/sim/datacenter/add_motivation/common/tests -p 'test_*.py' -v
python3 -m unittest discover \
  htsim/sim/datacenter/add_motivation/expM1_entropy_quality/tests -p 'test_*.py' -v
python3 -m unittest discover \
  htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/tests -p 'test_*.py' -v
```

Expected: build succeeds and every test passes.

- [ ] **Step 2: Run behavior-invariance simulations**

Run one small symmetric seed twice with identical arguments, once without trace and once with
`-motivation_trace_prefix`. Hash flow output and `PRISM_EPOCH` output:

```bash
sha256sum data/off.flow.txt data/on.flow.txt
sha256sum data/off.epoch.csv data/on.epoch.csv
```

Expected: each pair has identical SHA256. Also require no trace files in the off run.

- [ ] **Step 3: Run M1/M2 smoke modes and validate schema/replay**

```bash
cd htsim/sim/datacenter
bash add_motivation/expM1_entropy_quality/repro.sh smoke
bash add_motivation/expM2_redistribution_progress/repro.sh smoke
```

Expected: all five trace files exist per run; schema validation and shadow replay exit 0.

- [ ] **Step 4: Run M1 formal matrix and render**

```bash
bash add_motivation/expM1_entropy_quality/repro.sh full
python3 add_motivation/expM1_entropy_quality/analyze.py --formal
python3 add_motivation/expM1_entropy_quality/make_figs.py --render
```

Run both `reps_nscc_main` and the predeclared `original_prism_appendix` rows. Record whether all M1
decision conditions hold. Preserve an honest negative result if RR or path-level consistency
fails.

- [ ] **Step 5: Run M2 formal matrix and render if calibration selected a pair**

```bash
bash add_motivation/expM2_redistribution_progress/repro.sh full
python3 add_motivation/expM2_redistribution_progress/analyze.py --formal
python3 add_motivation/expM2_redistribution_progress/make_figs.py --render
```

If calibration was blocked, skip these commands and document the blocking evidence instead.

- [ ] **Step 6: Run final integrity checks**

```bash
git diff --check
bash -n htsim/sim/datacenter/add_motivation/common/run_motivation.sh
python3 htsim/sim/datacenter/add_motivation/expM1_entropy_quality/make_figs.py --selftest
python3 htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/make_figs.py --selftest
```

Expected: no whitespace errors, shell syntax errors, or plotting self-test failures.

- [ ] **Step 7: Commit verified artifacts and documentation**

```bash
git add htsim/sim/datacenter/add_motivation \
  htsim/sim/motivation_trace.h htsim/sim/motivation_trace.cpp \
  htsim/sim/motivation_epoch.h htsim/sim/uec.h htsim/sim/uec.cpp \
  htsim/sim/uec_mp.h htsim/sim/uec_mp.cpp htsim/sim/queue.h \
  htsim/sim/datacenter/main_uec.cpp htsim/sim/CMakeLists.txt
git commit -m "prism: add residual-spread motivation traces and experiments"
```

The final report must state build/test evidence, on/off hashes, selected calibration cells, formal
seed coverage, M1/M2 decision outcomes, right-censoring, and all unsupported claims.
