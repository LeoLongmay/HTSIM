# HTSIM-localized LAPS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `laps` a path-aware, HTSIM-native baseline whose LAPS PID selection and paired reverse ACK paths use UEC's normal loss recovery and congestion control.

**Architecture:** Split the old `isStrictLaps()` meaning into a LAPS path-semantics predicate and ordinary UEC reliability behavior.  `UecMpLaps` continues to select and probe PIDs; `UecSrc` records PID/catalog metadata only for route pairing, while NACK/RTO/retransmission/cwnd follow the common UEC code path.  The isolated ExpL runner gains a required full-completion gate before plotting.

**Tech Stack:** C++17, HTSIM UEC/FatTree simulator, CMake/CTest, Bash, Python 3, Matplotlib.

## Global Constraints

- `laps` is the public HTSIM-localized baseline; do not expose the old strict controller as an experiment option.
- Preserve PID Softmax, stale-PID zero weight, active probes, stable data PID, and exact reverse ACK routing for LAPS only.
- Use generic UEC/NSCC NACK, RTO, cwnd, and retransmission behavior for LAPS.
- Do not alter OPS, REPS, Prism, the other baselines, ExpA, or ExpL's PFC queue settings.
- ExpL `-failed` means reduced capacity, not a hard failure; do not add topology-oracle PID invalidation.
- No figure may be generated if any selected baseline/failure/seed cell is missing or has completion rate other than `1.0`.
- Generated `.cm`, logs, `data/`, and `figs/` files remain untracked.

---

### Task 1: Separate LAPS path semantics from strict recovery

**Files:**
- Modify: `htsim/sim/uec.h:183-220,345-416,844-851`
- Modify: `htsim/sim/uec.cpp:760-940,1533-1730,3157-3990,4047-4368,4760,5068`
- Modify: `htsim/sim/uec_mp.cpp:142-240`
- Modify: `htsim/sim/datacenter/add_motivation/common/tests/test_laps_source_routing.cpp`
- Modify: `htsim/sim/datacenter/add_motivation/common/tests/test_laps_uec_isolation.cpp`

**Interfaces:**
- Consumes: `UecMpLaps::nextLapsEntropy()`, `UecMpLaps::nextLapsProbeEntropy(now)`, `LapsPathCatalog`, and `UecSrc::createSendRecord(...)`.
- Produces: `bool UecSrc::isLaps() const`; LAPS packets with PID/catalog metadata and paired reverse ACKs; generic UEC retransmission state for LAPS.

- [ ] **Step 1: Replace strict-behavior expectations with failing localized-LAPS tests**

  In `test_laps_source_routing.cpp`, rename the strict fixture/test names to localized LAPS and add these assertions after sending a LAPS data packet and a retransmission:

  ```cpp
  // LAPS data and its ACK remain catalog-paired.
  assert(data->lapsPidValid());
  assert(data->route() == f.catalog(plane).entry(pid).forward);
  UecAckPacket* ack = f.sink.sack(pid, data->epsn(), data->epsn(), false, false, data);
  assert(ack->route() == f.catalog(plane).entry(pid).reverse);

  // Generic recovery has no retained strict replay route.  Force PID 3 to be
  // the current low-delay choice and verify the retry is sent on PID 3, not
  // the original PID 1.
  f.selectOnly(3);
  f.source._rtx_queue.emplace(seqno, 1'500);
  f.source._rtx_backlog = 1'500;
  assert(f.source.sendRtxPacket(f.forwardFib(0)) == 1'500);
  assert(static_cast<const UecDataPacket*>(f.lastForwardPacket(0, 3))->lapsPid() == 3);
  ```

  In `test_laps_uec_isolation.cpp`, replace strict PIT callback tests with a direct LAPS source test that creates an ordinary send record, calls `recalculateRTO()`, and asserts `_rtx_timeout_pending`; retain the non-LAPS isolation assertions.

- [ ] **Step 2: Run the focused tests and verify the old port fails them**

  Run:

  ```bash
  cmake --build htsim/sim/build-lossless --target test_laps_source_routing test_laps_uec_isolation -j2
  htsim/sim/build-lossless/test_laps_source_routing
  htsim/sim/build-lossless/test_laps_uec_isolation
  ```

  Expected: at least the retransmission assertion fails because the old code replays `_laps_rtx_routes`, and the generic-RTO assertion fails because the strict branch suppresses it.

- [ ] **Step 3: Implement the localized source behavior**

  In `uec.h/.cpp`, introduce `isLaps()` with the current algorithm-plus-`UecMpLaps` predicate.  Use it only for LAPS path catalog resolution, packet PID metadata, route audit, paired ACK routing, and probe delay observation.  Delete `isStrictLaps()` from the public interface and replace strict-only error text with `LAPS` text.

  Make these exact behavioral changes:

  ```cpp
  // Constructor: LAPS uses the common NSCC cwnd callbacks.
  case LAPS:
      updateCwndOnAck = &UecSrc::updateCwndOnAck_NSCC;
      updateCwndOnNack = &UecSrc::updateCwndOnNack_NSCC;
      break;

  // Localized recovery never stores a strict replay route.
  UecSrc::RtxPathSelection UecSrc::selectRtxPath(UecDataPacket::seq_t) {
      const uint32_t entropy = _mp->nextEntropy(_highest_sent, (uint64_t)_cwnd / _mss);
      return {entropy, _mp->lastSelection(), std::nullopt, std::nullopt, std::nullopt};
  }
  ```

  Remove all runtime calls to `UecNIC::lapsRecovery()`, `lapsRecover`, `_laps_rtx_routes`, ACK-gap retirement, and the LAPS-specific pacer.  Keep probe scheduling, but make normal data/retransmission admission call the normal UEC cwnd and RTO paths.  For a LAPS retransmission, resolve its newly selected current entropy through the LAPS catalog, set PID/pinned-route metadata, and create an ordinary UEC send record that retains only the metadata needed by ACK delay observation.  In `processNack`, always remove the send record, update base RTT/delay, update cwnd, enqueue the generic retransmission, feed the multipath NACK event, and recompute RTO; do not construct `LapsRtxRoute` or notify a recovery domain.

  Retain the ACK code that calls `observeLapsDelay`/`observeLapsProbe` when a LAPS packet carries a valid one-way sample, but remove the strict attempt acknowledgement.  In `UecSink::sack`, force paired reverse catalog routing whenever `source->isLaps()` and the received data has a valid LAPS PID.  Do not change the non-LAPS ACK branch.

- [ ] **Step 4: Run focused tests and source-level regression checks**

  Run:

  ```bash
  cmake --build htsim/sim/build-lossless --target test_laps_source_routing test_laps_uec_isolation test_laps_multipath test_laps_packet_feedback test_laps_cc_decision -j2
  htsim/sim/build-lossless/test_laps_source_routing
  htsim/sim/build-lossless/test_laps_uec_isolation
  htsim/sim/build-lossless/test_laps_multipath
  htsim/sim/build-lossless/test_laps_packet_feedback
  htsim/sim/build-lossless/test_laps_cc_decision
  rg -n 'lapsRecovery\(|_laps_rtx_routes|lapsRecover\(' htsim/sim/uec.cpp htsim/sim/uec.h
  ```

  Expected: all five tests exit zero; the final search has no source-runtime references (definitions in the standalone legacy recovery component may remain only if independently tested and unreachable).

- [ ] **Step 5: Commit the localized control boundary**

  ```bash
  git add htsim/sim/uec.h htsim/sim/uec.cpp htsim/sim/uec_mp.cpp \
    htsim/sim/datacenter/add_motivation/common/tests/test_laps_source_routing.cpp \
    htsim/sim/datacenter/add_motivation/common/tests/test_laps_uec_isolation.cpp
  git commit -m "feat: localize LAPS recovery to UEC"
  ```

### Task 2: Make ExpL reject incomplete performance data

**Files:**
- Modify: `htsim/sim/datacenter/prism_eval/expL_laps_lossless/repro.sh`
- Modify: `htsim/sim/datacenter/prism_eval/expL_laps_lossless/make_figs.py`
- Modify: `htsim/sim/datacenter/prism_eval/expL_laps_lossless/tests/test_repro.sh`
- Modify: `htsim/sim/datacenter/prism_eval/expL_laps_lossless/tests/test_make_figs.py`
- Modify: `htsim/sim/datacenter/prism_eval/expL_laps_lossless/README.md`

**Interfaces:**
- Consumes: `metrics.fct_stats(flow_path)["completion_rate"]` and the existing `expL_{algorithm}_f{failed}_s{seed}.flow.txt` naming contract.
- Produces: `require_complete_cells(data_dir, tag_prefix, baselines, failed, seeds)` and a runner whose `END_MS` defaults to `80` but may be overridden with `END_MS=<milliseconds>`.

- [ ] **Step 1: Add failing completion-gate tests**

  Add this test to `test_make_figs.py` using a temporary data directory with all required file names, then replace one file with a log containing an unfinished flow:

  ```python
  try:
      module.require_complete_cells(tmpdir, "expL", module.PREVIEW_BASELINES, [0], [13])
  except RuntimeError as exc:
      assert "expL_laps_f0_s13" in str(exc)
      assert "completion_rate" in str(exc)
  else:
      raise AssertionError("incomplete ExpL cell was accepted")
  ```

  Extend `test_repro.sh` so it accepts the parameterized command prefix and the new default:

  ```bash
  grep -c '^PATHS=8 END_MS=80 EXTRA_ARGS=' "$output" | grep -qx "$expected"
  END_MS=37 bash "$RUNNER" --dry-run | grep -c '^PATHS=8 END_MS=37 EXTRA_ARGS=' | grep -qx 140
  ```

- [ ] **Step 2: Run the contract tests and verify they fail**

  Run:

  ```bash
  MPLCONFIGDIR=/tmp python3 htsim/sim/datacenter/prism_eval/expL_laps_lossless/tests/test_make_figs.py
  bash htsim/sim/datacenter/prism_eval/expL_laps_lossless/tests/test_repro.sh
  ```

  Expected: the first test fails because no completion checker exists; the second fails because `repro.sh` hard-codes `END_MS=8`.

- [ ] **Step 3: Implement the gate and end-time contract**

  In `make_figs.py`, add and call this function before `render_main_perf_split`:

  ```python
  def require_complete_cells(data_dir, tag_prefix, baselines, failed, seeds):
      failures = []
      for label, _display, _color in baselines:
          for failed_links in failed:
              for seed in seeds:
                  path = os.path.join(data_dir, f"{tag_prefix}_{label}_f{failed_links}_s{seed}.flow.txt")
                  if not os.path.exists(path):
                      failures.append(f"missing {os.path.basename(path)}")
                      continue
                  rate = metrics.fct_stats(path)["completion_rate"]
                  if rate != 1.0:
                      failures.append(f"{os.path.basename(path)} completion_rate={rate:.6f}")
      if failures:
          raise RuntimeError("ExpL refuses incomplete cells: " + "; ".join(failures))
  ```

  In `repro.sh`, set `END_MS="${END_MS:-80}"` once near the other fixed inputs and substitute that variable in both `emit_cell` and the real `run_lib.sh` call.  Add `END_MS=<ms>` to `usage`.  Update the README to identify LAPS as HTSIM-localized, document the completion gate, and state that the 80 ms default came from the pre-scan recovery diagnostic rather than an algorithm-specific tuning parameter.

- [ ] **Step 4: Run the contract tests and a synthetic complete render**

  Run:

  ```bash
  MPLCONFIGDIR=/tmp python3 htsim/sim/datacenter/prism_eval/expL_laps_lossless/tests/test_make_figs.py
  MPLCONFIGDIR=/tmp bash htsim/sim/datacenter/prism_eval/expL_laps_lossless/tests/test_repro.sh
  bash htsim/sim/datacenter/prism_eval/expL_laps_lossless/repro.sh --dry-run | wc -l
  ```

  Expected: both tests print their `ok` contracts; dry-run prints exactly `140` commands, each with `END_MS=80` and the unchanged lossless flags.

- [ ] **Step 5: Commit the unbiased reporting contract**

  ```bash
  git add htsim/sim/datacenter/prism_eval/expL_laps_lossless/repro.sh \
    htsim/sim/datacenter/prism_eval/expL_laps_lossless/make_figs.py \
    htsim/sim/datacenter/prism_eval/expL_laps_lossless/tests/test_repro.sh \
    htsim/sim/datacenter/prism_eval/expL_laps_lossless/tests/test_make_figs.py \
    htsim/sim/datacenter/prism_eval/expL_laps_lossless/README.md
  git commit -m "fix: gate ExpL figures on completed flows"
  ```

### Task 3: Validate the localized LAPS diagnostic before any matrix rerun

**Files:**
- Modify: `htsim/sim/datacenter/prism_eval/expL_laps_lossless/README.md` only if the emitted diagnostic reveals a reproducibility command omission.
- Generated only: `htsim/sim/datacenter/prism_eval/expL_laps_lossless/data/laps_diagnosis/`

**Interfaces:**
- Consumes: built `htsim/sim/build-lossless/htsim_uec`, `run_lib.sh`, and the unchanged ExpL lossless flags.
- Produces: a `f8/s13` 80 ms LAPS diagnostic flow log/stdout with recovery counters.

- [ ] **Step 1: Build the simulator and diagnostic-capable test targets**

  Run:

  ```bash
  cmake --build htsim/sim/build-lossless --target htsim_uec test_laps_source_routing test_laps_uec_isolation -j2
  ```

  Expected: build completes successfully.

- [ ] **Step 2: Run exactly one localized LAPS diagnostic cell**

  Run from `htsim/sim/datacenter`:

  ```bash
  mkdir -p prism_eval/expL_laps_lossless/data/laps_diagnosis
  PATHS=8 END_MS=80 EXTRA_ARGS='-queue_type lossless_input -queue_size_bytes 150000 -pfc_high_bytes 122880 -pfc_low_bytes 92160 -shared_buffer_bytes 33554432' \
    bash prism_eval/common/run_lib.sh laps laps 8 fat_tree_128_1os.topo 13 \
      prism_eval/expL_laps_lossless/data/m2m.cm flow laps_localized_f8_s13 \
      prism_eval/expL_laps_lossless/data/laps_diagnosis
  ```

- [ ] **Step 3: Check completion, queue health, and recovery evidence**

  Run:

  ```bash
  python3 - <<'PY'
  from pathlib import Path
  import sys
  sys.path.insert(0, 'prism_eval/common')
  import metrics
  path = Path('prism_eval/expL_laps_lossless/data/laps_diagnosis/laps_localized_f8_s13.flow.txt')
  stats = metrics.fct_stats(path)
  print(stats)
  assert stats['completion_rate'] == 1.0
  PY
  ! rg -n 'LOSSLESS not working|shared-buffer capacity exceeded' \
    prism_eval/expL_laps_lossless/data/laps_diagnosis/laps_localized_f8_s13.stdout
  rg -n '^New: .* Rtx: .* NACKs:' \
    prism_eval/expL_laps_lossless/data/laps_diagnosis/laps_localized_f8_s13.stdout
  ! rg -n 'lapsRecovery\\(|lapsRecover\\(|_laps_rtx_routes|LAPS_RECOVERY_SUMMARY' \
    ../../uec.cpp ../../uec.h
  ```

  Expected: 64/64 completion, no lossless/shared-buffer diagnostics, a generic UEC `Rtx`/`NACKs` summary, and no source-level strict-recovery implementation.  The old strict 56,045 count measured PIT timeout *records*, whereas `Rtx` counts packets, so record both as non-comparable evidence rather than an improvement ratio; do not select a performance target.

- [ ] **Step 4: Commit only source/documentation changes if needed**

  ```bash
  git status --short
  ```

  Expected: generated `data/laps_diagnosis/` files remain ignored and unstaged.  If Task 3 required a README command correction, stage only that README and commit `docs: record localized LAPS diagnostic`; otherwise make no commit.

### Task 3a: Block generic recovery sends while every LAPS PID is probing

**Files:**
- Modify: `htsim/sim/uec.cpp:3711-3773,3853-3885`
- Modify: `htsim/sim/datacenter/add_motivation/common/tests/test_laps_source_routing.cpp`

**Interfaces:**
- Consumes: `UecMpLaps::nextLapsEntropy()`, `UecMpLaps::hasSelectablePath()`, and `UecSrc::scheduleLapsProbe()`.
- Produces: a zero-byte LAPS retransmission/RTS deferral when all PIDs are probe-pending; the queued retransmission, credit, and in-flight state remain unchanged until a probe ACK refreshes a PID.

- [ ] **Step 1: Write a failing all-probe-pending retransmission test**

  In `test_laps_source_routing.cpp`, use the existing localized fixture to set every
  `UecMpLaps::_paths` entry's `probe_pending` to true, enqueue one retransmission,
  and assert that sending does not throw or mutate ownership:

  ```cpp
  const mem_b in_flight_before = f.source._in_flight;
  const mem_b backlog_before = f.source._rtx_backlog;
  f.source._rtx_queue.emplace(91, 1'500);
  f.source._rtx_backlog = 1'500;
  for (auto& state : laps->_paths) state.probe_pending = true;
  assert(f.source.sendRtxPacket(f.forwardFib(0)) == 0);
  assert(f.source._rtx_queue.count(91) == 1);
  assert(f.source._rtx_backlog == backlog_before);
  assert(f.source._in_flight == in_flight_before);
  ```

  Add a companion test that calls `sendRTS()` under the same all-pending state
  and asserts it emits no RTS/send record, then run the test target.  The old
  implementation must fail by throwing `LAPS data selection requested while
  every PID is probe-pending`.

- [ ] **Step 2: Make LAPS recovery routing probe-safe**

  In `sendRtxPacket`, resolve `nextLapsEntropy()` before `spendCredit()` when
  `isLaps()`.  If it has no value, call `scheduleLapsProbe()` and return `0`;
  otherwise construct `RtxPathSelection{*entropy, _mp->lastSelection()}`.
  Use the existing generic `selectRtxPath()` only for non-LAPS algorithms.

  In `sendRTS`, use the same `nextLapsEntropy()` branch for LAPS.  With no
  selectable PID, schedule a LAPS probe and return before allocating an RTS or
  mutating sequence/RTO state.  Non-LAPS RTS behavior remains byte-for-byte
  unchanged.

- [ ] **Step 3: Verify the targeted regression and commit**

  Run:

  ```bash
  cmake --build htsim/sim/build-lossless --target test_laps_source_routing test_laps_uec_isolation htsim_uec -j2
  htsim/sim/build-lossless/test_laps_source_routing
  htsim/sim/build-lossless/test_laps_uec_isolation
  rg -n 'nextEntropy\\(' htsim/sim/uec.cpp
  ```

  Expected: all tests pass; the only LAPS call sites that can invoke generic
  `nextEntropy()` are unreachable from data/retransmission/RTS paths while all
  LAPS PIDs are probe-pending.  Commit with `fix: defer LAPS recovery during probes`.

### Task 4: Rebuild the four-arm lossless preview only after the gate passes

**Files:**
- Generated only: `htsim/sim/datacenter/prism_eval/expL_laps_lossless/data/`
- Generated only: `htsim/sim/datacenter/prism_eval/expL_laps_lossless/figs/`

**Interfaces:**
- Consumes: Tasks 1-3 and the four fixed preview arms `ops`, `reps`, `laps`, `prism`.
- Produces: `figL1_avg_fct.{pdf,png}`, `figL1_goodput.{pdf,png}`, `figL1_p99_fct.{pdf,png}`, and the ordered legend. Prism remains green and last.

- [ ] **Step 1: Confirm all source tests before launching the matrix**

  Run:

  ```bash
  ctest --test-dir htsim/sim/build-lossless --output-on-failure -L laps
  MPLCONFIGDIR=/tmp bash htsim/sim/datacenter/prism_eval/expL_laps_lossless/tests/test_repro.sh
  MPLCONFIGDIR=/tmp python3 htsim/sim/datacenter/prism_eval/expL_laps_lossless/tests/test_make_figs.py
  ```

  Expected: all commands exit zero.

- [ ] **Step 2: Rerun the four-arm matrix under unchanged PFC settings**

  Run:

  ```bash
  cd htsim/sim/datacenter/prism_eval/expL_laps_lossless
  bash repro.sh
  ```

  Expected: 140 flow logs; no `-disable_trim`; no ExpA files touched.

- [ ] **Step 3: Generate figures through the hard completion gate**

  Run:

  ```bash
  cd htsim/sim/datacenter/prism_eval/expL_laps_lossless
  MPLCONFIGDIR=/tmp python3 make_figs.py
  test -f figs/figL1_avg_fct.pdf
  test -f figs/figL1_goodput.pdf
  test -f figs/figL1_p99_fct.pdf
  ```

  Expected: render succeeds only if all 140 cells completed; LAPS is displayed with OPS, REPS, and Prism, and Prism is green/last in the legend.

- [ ] **Step 4: Verify repository hygiene and request final code review**

  Run:

  ```bash
  git -c core.whitespace=cr-at-eol diff --check 7750322..HEAD
  git status --short
  ```

  Expected: no whitespace errors; only ignored generated artifacts remain.  Request a focused review of the localized LAPS boundary and ExpL completion gate before any merge discussion.
