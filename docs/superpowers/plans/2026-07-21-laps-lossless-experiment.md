# LAPS Lossless/PFC Experiment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an independent eight-arm ExpA-style experiment on a configurable PFC/lossless FatTree with a 150 KiB egress queue and a 32 MiB shared buffer per switch.

**Architecture:** Add a bounded shared-buffer component; make lossless ingress virtual queues reserve it and release the reservation when the corresponding output queue services the packet; then expose the configuration through `htsim_uec`. Add an `expL_laps_lossless` harness that owns all workload, data, and figures while reusing the common metrics and plot utilities.

**Tech Stack:** C++17, HTSIM EventList/queues, CMake/CTest, Bash, Python 3, Matplotlib.

## Global Constraints

- Preserve `expA_delaydriven` source, generated data, and figures byte-for-byte.
- The new matrix is 8 arms × failures `{0,2,4,6,8,10,12}` × seeds `{13,14,15,16,17}` = 280 runs.
- Every invocation uses `-queue_type lossless_input -queue_size_bytes 150000 -pfc_high_bytes 122880 -pfc_low_bytes 92160 -shared_buffer_bytes 33554432`; no invocation contains `-disable_trim`.
- Pools belong to individual FatTree switches. Their use must stay within `[0, capacity]`.
- Do not modify LAPS PID selection, ACK routing, probes, recovery, or congestion control.
- Do not stage unrelated existing worktree changes.

---

### Task 1: Bounded shared-buffer accounting

**Files:**
- Create: `htsim/sim/shared_buffer_pool.h`
- Create: `htsim/sim/shared_buffer_pool.cpp`
- Create: `htsim/sim/datacenter/add_motivation/common/tests/test_shared_buffer_pool.cpp`
- Modify: `htsim/sim/CMakeLists.txt`

**Interfaces:**
- `SharedBufferPool(mem_b capacity, mem_b pause_high, mem_b resume_low)` rejects `capacity == 0`, `pause_high == 0`, `pause_high > capacity`, and `resume_low >= pause_high`.
- `bool reserve(mem_b bytes)` changes no state and returns `false` on capacity exhaustion.
- `void release(mem_b bytes)` throws `std::logic_error` on underflow.
- `used()`, `capacity()`, and `paused()` are const observers.

- [ ] **Step 1: Write a failing unit test**

```cpp
#include "shared_buffer_pool.h"
#include <cassert>
#include <stdexcept>
int main() {
  SharedBufferPool pool(100, 80, 60);
  assert(pool.reserve(79)); assert(!pool.paused());
  assert(pool.reserve(1));  assert(pool.used() == 80 && pool.paused());
  pool.release(21);         assert(pool.used() == 59 && !pool.paused());
  assert(!pool.reserve(42)); assert(pool.used() == 59);
  bool threw = false; try { pool.release(60); } catch (const std::logic_error&) { threw = true; }
  assert(threw);
}
```

- [ ] **Step 2: Confirm RED**

Run `cmake --build htsim/sim/build-laps --target test_shared_buffer_pool`.

Expected: fails because the target/header does not exist.

- [ ] **Step 3: Implement the minimal component and register it**

Implement these state transitions in `shared_buffer_pool.cpp`:

```cpp
bool SharedBufferPool::reserve(mem_b bytes) {
  if (bytes < 0 || bytes > capacity_ - used_) return false;
  used_ += bytes;
  if (used_ >= pause_high_) paused_ = true;
  return true;
}
void SharedBufferPool::release(mem_b bytes) {
  if (bytes < 0 || bytes > used_) throw std::logic_error("shared-buffer underflow");
  used_ -= bytes;
  if (used_ < resume_low_) paused_ = false;
}
```

Add the source to `SOURCE_FILES`; add a `test_shared_buffer_pool` executable linked with `htsim`; add CTest name `shared_buffer_pool` with label `lossless;unit`.

- [ ] **Step 4: Confirm GREEN and commit**

Run `cmake --build htsim/sim/build-laps --target test_shared_buffer_pool && htsim/sim/build-laps/test_shared_buffer_pool && ctest --test-dir htsim/sim/build-laps -R shared_buffer_pool --output-on-failure`.

Expected: all exit 0.

Run `git add htsim/sim/shared_buffer_pool.h htsim/sim/shared_buffer_pool.cpp htsim/sim/datacenter/add_motivation/common/tests/test_shared_buffer_pool.cpp htsim/sim/CMakeLists.txt && git commit -m "feat: add bounded shared buffer accounting"`.

### Task 2: Configurable PFC on lossless ingress queues

**Files:**
- Modify: `htsim/sim/queue_lossless_input.h`
- Modify: `htsim/sim/queue_lossless_input.cpp`
- Modify: `htsim/sim/queue_lossless_output.h`
- Modify: `htsim/sim/queue_lossless_output.cpp`
- Create: `htsim/sim/datacenter/add_motivation/common/tests/test_lossless_pfc.cpp`
- Modify: `htsim/sim/CMakeLists.txt`

**Interfaces:**
- `LosslessInputQueue::configurePfc(mem_b high, mem_b low)` requires `0 < low < high`.
- `LosslessInputQueue::setSharedBuffer(SharedBufferPool&)` attaches a non-owning per-switch pool before traffic starts.
- Data receipt reserves `pkt.size()` exactly once; `completedService` releases that same size exactly once.

- [ ] **Step 1: Write the failing PFC event test**

Use an EventList, a `LosslessInputQueue`, a 100-byte `SharedBufferPool`, and a packet-sink recorder for `ETH_PAUSE`. Configure `(80, 60)`, inject 81 bytes, then drain 22 bytes. Assert:

```cpp
assert(recorder.pause_count == 1);
assert(recorder.resume_count == 1);
assert(pool.used() == 59);
```

- [ ] **Step 2: Confirm RED**

Run `cmake --build htsim/sim/build-laps --target test_lossless_pfc`.

Expected: fails because the PFC/pool APIs are absent.

- [ ] **Step 3: Implement pause-state recomputation**

Add `SharedBufferPool* pool_` and `refreshPauseState()` to `LosslessInputQueue`. Reserve before forwarding a data packet; throw `std::logic_error("shared-buffer capacity exceeded")` if reserve fails. Release in `completedService`. The helper must be equivalent to:

```cpp
const bool should_pause = _queuesize > _high_threshold || (pool_ && pool_->paused());
if (should_pause && _state_recv != PAUSED) { _state_recv = PAUSED; sendPause(1000); }
if (!should_pause && _queuesize < _low_threshold && _state_recv == PAUSED) {
  _state_recv = READY; sendPause(0);
}
```

Keep `LosslessOutputQueue` as the sole caller of `completedService` for the packet's associated ingress virtual queue; do not reserve again in the output queue. Register the new test as `lossless;unit`.

- [ ] **Step 4: Confirm GREEN and commit**

Run `cmake --build htsim/sim/build-laps --target test_lossless_pfc test_laps_uec_isolation && htsim/sim/build-laps/test_lossless_pfc && htsim/sim/build-laps/test_laps_uec_isolation`.

Expected: all exit 0.

Run `git add htsim/sim/queue_lossless_input.h htsim/sim/queue_lossless_input.cpp htsim/sim/queue_lossless_output.h htsim/sim/queue_lossless_output.cpp htsim/sim/datacenter/add_motivation/common/tests/test_lossless_pfc.cpp htsim/sim/CMakeLists.txt && git commit -m "feat: configure PFC lossless queue thresholds"`.

### Task 3: FatTree pool ownership and UEC CLI

**Files:**
- Modify: `htsim/sim/datacenter/fat_tree_topology.h`
- Modify: `htsim/sim/datacenter/fat_tree_topology.cpp`
- Modify: `htsim/sim/datacenter/main_uec.cpp`
- Create: `htsim/sim/datacenter/add_motivation/common/tests/test_lossless_cli.sh`

**Interfaces:**
- `-queue_type lossless_input` selects `LOSSLESS_INPUT`; `-queue_size_bytes` is byte-valued and leaves legacy packet-count `-q` unchanged.
- `-pfc_high_bytes`, `-pfc_low_bytes`, and `-shared_buffer_bytes` parse as byte values.
- The topology allocates one pool for every ToR, aggregation, and core switch only in `LOSSLESS_INPUT` mode, and gives every ingress virtual queue the pool of the receiving switch.

- [ ] **Step 1: Write the failing CLI contract**

Create a two-flow `.cm` fixture and make a valid command with all five lossless values. Require success and startup output containing those values. Require each invalid command below to exit nonzero:

```text
-pfc_high_bytes 0
-pfc_high_bytes 90 -pfc_low_bytes 90
-shared_buffer_bytes 0
-queue_size_bytes 0
```

- [ ] **Step 2: Confirm RED**

Run `bash htsim/sim/datacenter/add_motivation/common/tests/test_lossless_cli.sh`.

Expected: fails with `Unknown queue type lossless_input`.

- [ ] **Step 3: Implement parsing and pool wiring**

Map `lossless_input` to `LOSSLESS_INPUT`. Add a byte-valued `-queue_size_bytes` parsed with `strtoull`, mutually exclusive with `-q`; reject `high == 0`, `low >= high`, `high > queue_size_bytes`, a zero queue/shared capacity, and `-queue_size_bytes` together with `-q`. Use the byte value directly when constructing and updating `FatTreeTopologyCfg`; retain `-q`'s legacy packet-count conversion unchanged. Call `LosslessInputQueue::configurePfc(high, low)` before creating the topology.

Add vectors of `std::unique_ptr<SharedBufferPool>` to `FatTreeTopology`, one vector per tier. In `LOSSLESS_INPUT` mode create pools as `SharedBufferPool(shared_buffer_bytes, shared_buffer_bytes, shared_buffer_bytes - 1)`. Extend the virtual-queue creation sites in the host↔ToR, ToR↔aggregation, and aggregation↔core loops to call `setSharedBuffer` with the receiving switch's pool. Do not create pools for other queue types. Print queue size, PFC high/low, and shared-buffer size at startup.

- [ ] **Step 4: Confirm GREEN and commit**

Run `cmake --build htsim/sim/build-laps --target htsim_uec && bash htsim/sim/datacenter/add_motivation/common/tests/test_lossless_cli.sh`.

Expected: valid case succeeds; all invalid cases fail.

Run `git add htsim/sim/datacenter/fat_tree_topology.h htsim/sim/datacenter/fat_tree_topology.cpp htsim/sim/datacenter/main_uec.cpp htsim/sim/datacenter/add_motivation/common/tests/test_lossless_cli.sh && git commit -m "feat: configure lossless PFC FatTree queues"`.

### Task 4: Independent eight-arm experiment and figures

**Files:**
- Create: `htsim/sim/datacenter/prism_eval/expL_laps_lossless/repro.sh`
- Create: `htsim/sim/datacenter/prism_eval/expL_laps_lossless/make_figs.py`
- Create: `htsim/sim/datacenter/prism_eval/expL_laps_lossless/README.md`
- Create: `htsim/sim/datacenter/prism_eval/expL_laps_lossless/tests/test_repro.sh`
- Create: `htsim/sim/datacenter/prism_eval/expL_laps_lossless/tests/test_make_figs.py`

**Interfaces:**
- `repro.sh --dry-run` emits exactly 280 commands and creates no file.
- Outputs use `expL_<label>_f<failed>_s<seed>` under the new directory only.
- `make_figs.py` emits three independent panels and a legend; Prism is last and uses color key `prism`.

- [ ] **Step 1: Write the failing runner contract**

Require exactly 280 dry-run commands, each containing the literal `EXTRA_ARGS=-queue_type lossless_input -queue_size_bytes 150000 -pfc_high_bytes 122880 -pfc_low_bytes 92160 -shared_buffer_bytes 33554432`. Reject output containing `-disable_trim` or `expA_delaydriven`.

- [ ] **Step 2: Confirm RED**

Run `bash htsim/sim/datacenter/prism_eval/expL_laps_lossless/tests/test_repro.sh`.

Expected: fails because `repro.sh` is missing.

- [ ] **Step 3: Implement the runner and README**

Generate the existing 64→16, 2 MB many-to-many workload in the new `data/` directory. Use `PATHS=8`, `END_MS=8`, and these labels/mappings:

```text
ops=nscc/oblivious  reps=nscc/reps  swift=swift/reps  mswift=mswift/reps
mnscc=mnscc/reps    strack=strack/reps  laps=laps/laps  prism=prism/reps
```

README documents paper-derived 150 KiB/32 MiB values, explicit 80/60 watermarks, matrix scope, and non-overlap with ExpA.

- [ ] **Step 4: Write and implement the plot-isolation contract**

The Python test must assert:

```python
assert module.DATA.endswith("expL_laps_lossless/data")
assert module.FIGS.endswith("expL_laps_lossless/figs")
assert [x[0] for x in module.BASELINES] == ["ops", "reps", "swift", "mswift", "mnscc", "strack", "laps", "prism"]
assert module.BASELINES[-1] == ("prism", "Prism", "prism")
```

Implement the wrapper using `perf_figs.render_main_perf_split(DATA, FIGS, "expL", BASELINES, FAILED, SEEDS, "figL1", "Number of failed links", goodput_tbps=True)` and `render_legend(FIGS, BASELINES, "figL1_legend", row_counts=[4,4])`.

- [ ] **Step 5: Confirm GREEN and commit**

Run `bash htsim/sim/datacenter/prism_eval/expL_laps_lossless/tests/test_repro.sh && python3 htsim/sim/datacenter/prism_eval/expL_laps_lossless/tests/test_make_figs.py`.

Expected: both exit 0.

Run `git add htsim/sim/datacenter/prism_eval/expL_laps_lossless && git commit -m "feat: add lossless LAPS baseline experiment"`.

### Task 5: Verify, smoke-run, and execute the full matrix

**Files:**
- Generated only: `htsim/sim/datacenter/prism_eval/expL_laps_lossless/data/*`
- Generated only: `htsim/sim/datacenter/prism_eval/expL_laps_lossless/figs/*`

- [ ] **Step 1: Run all automated checks**

Run `cmake --build htsim/sim/build-laps --target htsim_uec test_shared_buffer_pool test_lossless_pfc test_laps_recovery test_laps_uec_isolation test_laps_multipath && ctest --test-dir htsim/sim/build-laps -L lossless --output-on-failure && htsim/sim/build-laps/test_laps_recovery && htsim/sim/build-laps/test_laps_uec_isolation && htsim/sim/build-laps/test_laps_multipath && bash htsim/sim/datacenter/prism_eval/expL_laps_lossless/tests/test_repro.sh && python3 htsim/sim/datacenter/prism_eval/expL_laps_lossless/tests/test_make_figs.py`.

Expected: all exit 0.

- [ ] **Step 2: Run one smoke cell for all eight arms**

Use `failed=0`, seed `13`, the exact lossless flags, and `END_MS=8`. Require a nonempty `.flow.txt` per arm and reject stdout containing `LOSSLESS not working!` or `shared-buffer capacity exceeded`.

- [ ] **Step 3: Gate the full run on completion**

Use `metrics.fct_stats` to report every smoke completion rate. Do not compare FCT if any arm is below 1.00; diagnose first.

- [ ] **Step 4: Run and render**

Run `bash htsim/sim/datacenter/prism_eval/expL_laps_lossless/repro.sh && python3 htsim/sim/datacenter/prism_eval/expL_laps_lossless/make_figs.py`.

Expected: 280 flow files, and `figL1_goodput`, `figL1_avg_fct`, `figL1_p99_fct`, and `figL1_legend` in both PDF and PNG.

- [ ] **Step 5: Final artifact check**

Run `find htsim/sim/datacenter/prism_eval/expL_laps_lossless/data -name 'expL_*_f*_s*.flow.txt' | wc -l` and `git status --short`.

Expected: 280 flow files. Do not commit generated data, logs, or figures.

## Plan self-review

- Tasks 1–3 cover shared capacity, PFC thresholds, queue selection, topology ownership, and CLI validation.
- Task 4 covers independent reproducibility, all eight arms, and required figure semantics.
- Task 5 gates the expensive matrix on tests and an eight-arm smoke run.
- No placeholders or ambiguous parameter values remain.
