# Strict Official LAPS Semantics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current LAPS-style HTSIM adaptation with an isolated port of the official LAPS rate-control and NACK recovery semantics, then replace only the ExpA LAPS artifacts.

**Architecture:** A pure `LapsRateController` reproduces the official `curRate`/`tgtRate` state transitions.  A NIC-owned `LapsRecoveryDomain` maintains the official shared ordered outstanding list and one 8 ms RTO per `(destination, entropy)` candidate path.  `UecSrc` calls these components only when both LAPS axes are selected; all other transports retain the existing UEC cwnd/RTO behavior.

**Tech Stack:** C++17, HTSIM event scheduler and UEC transport, CMake/CTest, Bash, Python 3/Matplotlib.

## Global Constraints

- The official source of truth is `wany16/Laps-ns3` commit `4a4be642f2866d8b340c9b1bbdd1707a372ae213`, specifically its `CC_LAPS + NACK` path.
- Preserve the public paired interface: `-sender_cc_algo laps -load_balancing_algo laps`.
- `LapsRecoveryDomain` is reachable only from LAPS flow paths; never register or recover other algorithms through it.
- Map the unavailable official path ID to `(sending UecNIC, destination address, entropy)`.
- The strict controller defaults to `beta=1`, starts at NIC rate, uses a 1 Gbps rate floor, an 8 ms path RTO, and no queue-margin control term.
- Do not claim reproduction of LAPS paper experiments; ExpA remains the existing HTSIM workload/topology.
- Existing seven-baseline data and original figures must not be overwritten; generated data/logs are not committed.
- Only `repro_laps.sh --replace-laps` may delete prior LAPS-only artifacts, and it must enumerate the target tags/files before deleting.

---

### Task 1: Add a testable official LAPS rate controller

**Files:**
- Create: `htsim/sim/laps_rate.h`
- Modify: `htsim/sim/datacenter/add_motivation/common/tests/test_laps_cc_decision.cpp`
- Modify: `htsim/sim/CMakeLists.txt:185-189`
- Delete: `htsim/sim/laps_cc.h` only after all callers are migrated

**Interfaces:**
- Consumes: `simtime_picosec` and `linkspeed_bps` from `network.h`.
- Produces: `LapsRateState`, `LapsRateSignal`, and `advanceLapsRate(...)`, consumed by `UecSrc` in Task 3.

- [ ] **Step 1: Replace cwnd-decision assertions with failing official-rate tests**

  Define the public data-only API in the test before adding its header:

  ```cpp
  struct LapsRateState {
      linkspeed_bps cur_rate;
      linkspeed_bps tgt_rate;
      uint32_t inc_stage;
      simtime_picosec next_decrease_at;
      simtime_picosec next_increase_at;
  };
  struct LapsRateSignal {
      bool calibrated;
      bool all_paths_high;
      simtime_picosec target_delay;
      simtime_picosec max_delay;
  };
  LapsRateState advanceLapsRate(LapsRateState state, const LapsRateSignal& signal,
                                simtime_picosec now, linkspeed_bps nic_rate);
  ```

  Add assertions for: uncalibrated hold; all-path-high halves 100 to 50 Gbps;
  decrease is blocked before `now + 2*max_delay`; one safe signal advances
  `50 -> max(51, 75) = 75 Gbps`; stage 6 doubles target; 1 Gbps is never
  crossed; and NIC rate is never exceeded.

- [ ] **Step 2: Run the target test to demonstrate the old API is insufficient**

  Run: `cmake --build htsim/sim/build-laps --target test_laps_cc_decision && ctest --test-dir htsim/sim/build-laps -R '^laps_cc_decision$' --output-on-failure`

  Expected: compilation failure because `laps_rate.h` and `advanceLapsRate` do not exist.

- [ ] **Step 3: Implement the pure state machine in `laps_rate.h`**

  Use saturating time addition and this transition order:

  ```cpp
  if (!signal.calibrated) return state;
  if (signal.all_paths_high && now >= state.next_decrease_at) {
      state.tgt_rate = std::max(kLapsMinRate, state.cur_rate);
      state.cur_rate = std::max(kLapsMinRate, state.cur_rate / 2);
      state.inc_stage = 0;
      state.next_decrease_at = saturatingAdd(now, 2 * signal.max_delay);
      return state;
  }
  if (!signal.all_paths_high && now >= state.next_increase_at) {
      if (state.inc_stage > 5) state.tgt_rate = std::min(nic_rate, state.tgt_rate * 2);
      state.cur_rate = std::min(nic_rate,
          std::max(state.cur_rate + speedFromGbps(1), (state.cur_rate + state.tgt_rate) / 2));
      state.tgt_rate = std::max(state.tgt_rate, state.cur_rate);
      ++state.inc_stage;
      state.next_increase_at = saturatingAdd(now, 2 * signal.target_delay);
  }
  return state;
  ```

  Make `kLapsMinRate = speedFromGbps(1)` and the saturating helpers explicit.
  Remove `laps_cc.h` only after `rg 'decideLapsCwnd|LapsCwnd' htsim/sim` has no
  production callers.

- [ ] **Step 4: Run focused and full existing LAPS-controller tests**

  Run: `cmake --build htsim/sim/build-laps --target test_laps_cc_decision && ctest --test-dir htsim/sim/build-laps -R '^laps_cc_decision$' --output-on-failure`

  Expected: PASS; tests state exact rate and time values, not just action names.

- [ ] **Step 5: Commit the rate-controller slice**

  ```bash
  git add htsim/sim/laps_rate.h htsim/sim/laps_cc.h \
    htsim/sim/datacenter/add_motivation/common/tests/test_laps_cc_decision.cpp
  git commit -m "feat: add official LAPS rate controller"
  ```

### Task 2: Add a NIC-scoped shared LAPS recovery domain

**Files:**
- Create: `htsim/sim/laps_recovery.h`
- Create: `htsim/sim/laps_recovery.cpp`
- Create: `htsim/sim/datacenter/add_motivation/common/tests/test_laps_recovery.cpp`
- Modify: `htsim/sim/CMakeLists.txt:SOURCE_FILES` and test registration block

**Interfaces:**
- Consumes: `EventSource`, `EventList`, `UecBasePacket::seq_t`, and `mem_b`.
- Produces: `LapsRecoveryDomain` with `sent`, `acknowledge`, `removeOwner`, and `doNextEvent`; Task 3 wires it to `UecNIC`/`UecSrc`.

- [ ] **Step 1: Write failing recovery-domain tests with fake owners**

  Use a fake owner implementing:

  ```cpp
  class LapsRecoveryOwner {
  public:
      virtual ~LapsRecoveryOwner() = default;
      virtual void lapsRecover(UecBasePacket::seq_t seq, mem_b bytes) = 0;
  };
  ```

  Cover two owners on the same `LapsPathKey{destination=9, entropy=3}`: send
  `A:10`, `B:20`, `A:30`, acknowledge `A:30`, and assert that A receives 10
  and B receives 20 in order while 30 is acknowledged.  Add a distinct
  destination/entropy pair to prove isolation.  Advance the `EventList` to
  exactly 8 ms and assert that only that path's remaining records are
  recovered.  Assert duplicate ACKs and a mismatched owner/size do nothing.

- [ ] **Step 2: Run the recovery test and verify it fails before implementation**

  Run: `cmake --build htsim/sim/build-laps --target test_laps_recovery`

  Expected: target/source does not exist.

- [ ] **Step 3: Implement `LapsRecoveryDomain` as one event source**

  Define:

  ```cpp
  struct LapsPathKey { uint32_t destination; uint32_t entropy; };
  class LapsRecoveryDomain final : public EventSource {
  public:
      // timeFromUs() is runtime-only in this C++17 codebase; 8000 us == 8 ms.
      static constexpr simtime_picosec kRto = 8000ULL * 1000000ULL;
      void sent(LapsPathKey, LapsRecoveryOwner&, UecBasePacket::seq_t, mem_b);
      bool acknowledge(LapsPathKey, LapsRecoveryOwner&, UecBasePacket::seq_t, mem_b);
      void removeOwner(LapsRecoveryOwner&);
      void doNextEvent() override;
  };
  ```

  Store `std::list<Record>` per key in insertion order.  `acknowledge` must
  locate the exact owner/sequence/size record; recover and erase every prior
  record, then erase the matched record.  Maintain one deadline per nonempty
  key and schedule the earliest deadline through the normal `EventList` handle.
  On deadline, recover and erase that path list, then schedule the next one.
  `removeOwner` erases only that owner's records and cancels a now-empty key.

- [ ] **Step 4: Run focused recovery tests**

  Run: `cmake --build htsim/sim/build-laps --target test_laps_recovery && ctest --test-dir htsim/sim/build-laps -R '^laps_recovery$' --output-on-failure`

  Expected: PASS, including the exact 8 ms boundary and cross-flow ordering.

- [ ] **Step 5: Commit the isolated recovery component**

  ```bash
  git add htsim/sim/laps_recovery.h htsim/sim/laps_recovery.cpp \
    htsim/sim/datacenter/add_motivation/common/tests/test_laps_recovery.cpp \
    htsim/sim/CMakeLists.txt
  git commit -m "feat: add shared LAPS path recovery"
  ```

### Task 3: Wire strict LAPS pacing and recovery into UEC only

**Files:**
- Modify: `htsim/sim/uec.h:47-95, 111-460`
- Modify: `htsim/sim/uec.cpp:388-650, 1337-1505, 3323-3906`
- Modify: `htsim/sim/datacenter/add_motivation/common/tests/test_laps_packet_feedback.cpp`
- Create: `htsim/sim/datacenter/add_motivation/common/tests/test_laps_uec_isolation.cpp`
- Modify: `htsim/sim/CMakeLists.txt`

**Interfaces:**
- Consumes: `LapsRecoveryDomain`, `LapsRecoveryOwner`, `LapsRateState`, and `advanceLapsRate` from Tasks 1-2.
- Produces: LAPS-only `UecNIC::lapsRecovery()` and `UecSrc::lapsRecover(...)`; Tasks 4-6 consume the unchanged CLI and runner contract.

- [ ] **Step 1: Add failing UEC isolation/integration tests**

  Add a two-source fixture sharing one `UecNIC`.  The test must send records
  from two LAPS sources, process a later ACK, and assert that only LAPS source
  retransmission queues receive the preceding records.  In the same fixture,
  create an OPS/NSCC source and assert that it neither creates the NIC recovery
  domain nor receives a recovery callback.  Add a pacing assertion that a
  1500-byte packet at 50 Gbps cannot be emitted before its calculated
  `next_laps_send_at`.

- [ ] **Step 2: Run the new UEC tests and verify the strict hooks are absent**

  Run: `cmake --build htsim/sim/build-laps --target test_laps_uec_isolation`

  Expected: compilation failure until `UecNIC::lapsRecovery` and the LAPS
  source methods exist.

- [ ] **Step 3: Add guarded NIC ownership and source recovery hooks**

  In `UecNIC`, add a lazily constructed `std::unique_ptr<LapsRecoveryDomain>`
  and a method available only to LAPS source code:

  ```cpp
  LapsRecoveryDomain& lapsRecovery();
  ```

  Make `UecSrc` implement `LapsRecoveryOwner`.  Add
  `bool isStrictLaps() const`, `LapsPathKey lapsPathKey(uint32_t entropy) const`,
  and `void lapsRecover(seq_t, mem_b)`.  `lapsRecover` must remove the exact
  record from `_tx_bitmap`/`_send_times`, decrement `_in_flight`, enqueue it
  through `queueForRtx`, and never call `mark_packet_for_retransmission`.
  It must be idempotent when the record has already been ACKed or recovered.

- [ ] **Step 4: Route LAPS sends, ACKs, lifecycle, and RTO through the new domain**

  In `sendNewPacket` and `sendRtxPacket`, after `createSendRecord`, call
  `lapsRecovery().sent(lapsPathKey(ev), *this, seq, size)` for strict LAPS and
  do not call the generic `startRTO`.  In `processAck`, after validating the
  acknowledged send attempt and before generic ACK cleanup, call:

  ```cpp
  _nic.lapsRecovery().acknowledge(lapsPathKey(pkt.ev()), *this,
                                  pkt.acked_psn(), record.pkt_size);
  ```

  Keep generic ACK/SACK cleanup for the acknowledged record itself.  On flow
  completion/destruction call `removeOwner(*this)`.  Ensure `rtxTimerExpired`
  is unreachable for strict LAPS data but unchanged for all other sender CCs.

- [ ] **Step 5: Replace cwnd control with a LAPS pacer**

  Hold the LAPS fixed safety window at `2 * targetDelay * nicRate / 8` after
  calibration.  In `sendIfPermitted`, for LAPS check a stored
  `_laps_next_send_at`; if early, schedule this source at that time and return.
  After each LAPS data/RTX emission, set it by the packet serialization time at
  `LapsRateState::cur_rate`.  On valid LAPS ACK feedback, build a
  `LapsRateSignal` from `UecMpLaps`, call `advanceLapsRate`, and do not invoke
  `applyLapsCwnd`, `fair_increase`, `proportional_increase`, or generic NACK
  cwnd updates for LAPS.  Refactor `sendRtxPacket` to emit and return exactly
  one retransmission, like `sendNewPacket`; remove its internal recursive
  `sendNewPacket/sendRtxPacket` chaining.  The existing outer
  `sendIfPermitted` continuation then re-enters the LAPS time gate before any
  subsequent packet, so retransmissions cannot bypass pacing.

- [ ] **Step 6: Run focused UEC, packet-feedback, and non-LAPS regression tests**

  Run: `cmake --build htsim/sim/build-laps --target test_laps_uec_isolation test_laps_packet_feedback test_reps_slot_cache test_prism_coordination && ctest --test-dir htsim/sim/build-laps -R '^(laps_uec_isolation|laps_packet_feedback|reps_slot_cache|prism_coordination)$' --output-on-failure`

  Expected: PASS.  The non-LAPS tests demonstrate no shared-domain behavior
  leaked into REPS or Prism.

- [ ] **Step 7: Commit the UEC integration slice**

  ```bash
  git add htsim/sim/uec.h htsim/sim/uec.cpp \
    htsim/sim/datacenter/add_motivation/common/tests/test_laps_packet_feedback.cpp \
    htsim/sim/datacenter/add_motivation/common/tests/test_laps_uec_isolation.cpp \
    htsim/sim/CMakeLists.txt
  git commit -m "feat: wire strict LAPS recovery into UEC"
  ```

### Task 4: Align LAPS path state and CLI with the strict semantics

**Files:**
- Modify: `htsim/sim/uec_mp.h:121-156`
- Modify: `htsim/sim/uec_mp.cpp:31-198`
- Modify: `htsim/sim/datacenter/main_uec.cpp:87, 290-300, 888-892, 1316, 1382`
- Modify: `htsim/sim/uec.h:450-452`
- Modify: `htsim/sim/uec.cpp:175-177`
- Modify: `htsim/sim/datacenter/add_motivation/common/tests/test_laps_multipath.cpp`
- Modify: `htsim/sim/datacenter/add_motivation/common/tests/test_laps_cli.sh`

**Interfaces:**
- Consumes: Task 3's LAPS controller requests a calibrated
  `UecMpLapsSignal`.
- Produces: a calibrated target delay and strict Softmax path state; the ExpA
  runner in Task 5 keeps using `laps laps` without special flags.

- [ ] **Step 1: Change path-state tests before implementation**

  Replace old assertions that expect `beta=8`/queue-margin cwnd logic.  Assert
  that all candidate paths must have a baseline sample before the signal is
  calibrated, `targetDelay` is the maximum candidate base latency, and
  `beta=1` gives lower-latency paths a larger but nonzero Softmax share.  Add a
  CLI test that `-laps_queue_margin` is rejected with a clear strict-LAPS
  message and that the paired LAPS flags still pass.

- [ ] **Step 2: Run the path and CLI tests to verify they fail**

  Run: `cmake --build htsim/sim/build-laps --target test_laps_multipath htsim_uec && ctest --test-dir htsim/sim/build-laps -R '^(laps_multipath|laps_cli)$' --output-on-failure`

  Expected: FAIL until target-delay calibration/default parsing are updated.

- [ ] **Step 3: Implement calibration and strict defaults**

  Keep LAPS feedback/probes LAPS-only.  Make `UecMpLaps::lapsSignal` return
  `calibrated=false` until every candidate has a valid baseline.  Set
  `target_delay = max(base_latency)` and classify congestion only with strict
  `real_latency > target_delay`.  Use that target for Softmax normalization and
  set `_laps_beta = 1.0`.  Remove `_laps_queue_margin` from the LAPS signal and
  parser; reject it rather than silently accepting a behavior-changing legacy
  knob.  Preserve the paired-axis configuration errors.

- [ ] **Step 4: Run strict multipath/CLI tests**

  Run: `cmake --build htsim/sim/build-laps --target test_laps_multipath htsim_uec && ctest --test-dir htsim/sim/build-laps -R '^(laps_multipath|laps_cli)$' --output-on-failure`

  Expected: PASS.

- [ ] **Step 5: Commit path-state and CLI alignment**

  ```bash
  git add htsim/sim/uec_mp.h htsim/sim/uec_mp.cpp htsim/sim/uec.h htsim/sim/uec.cpp \
    htsim/sim/datacenter/main_uec.cpp \
    htsim/sim/datacenter/add_motivation/common/tests/test_laps_multipath.cpp \
    htsim/sim/datacenter/add_motivation/common/tests/test_laps_cli.sh
  git commit -m "fix: align LAPS path state with official semantics"
  ```

### Task 5: Make LAPS artifact replacement explicit and fail-closed

**Files:**
- Modify: `htsim/sim/datacenter/prism_eval/expA_delaydriven/repro_laps.sh`
- Modify: `htsim/sim/datacenter/prism_eval/expA_delaydriven/tests/test_repro_laps.sh`
- Modify: `htsim/sim/datacenter/prism_eval/expA_delaydriven/README.md`
- Modify: `htsim/sim/datacenter/prism_eval/expA_delaydriven/tests/test_make_figs_laps.py` only if plot command/legend contract changes

**Interfaces:**
- Consumes: unchanged `run_lib.sh` matrix and data tags.
- Produces: `repro_laps.sh --replace-laps`, the only mutation path for old
  LAPS ExpA data and `_laps` figures.

- [ ] **Step 1: Extend the shell contract test with replacement cases**

  Keep the existing no-argument collision refusal test.  Add a fixture with all
  35 `expA_laps_f*_s*` output families and fixed LAPS figure filenames.  Assert
  `--replace-laps --dry-run` lists the same 35 matrix without deletion; assert
  `--replace-laps` deletes exactly the LAPS fixture files before the stubbed 35
  runs; assert an OPS fixture and `figA1dd_goodput.pdf` survive byte-identical.

- [ ] **Step 2: Run the shell contract test and observe failure**

  Run: `bash htsim/sim/datacenter/prism_eval/expA_delaydriven/tests/test_repro_laps.sh`

  Expected: FAIL because `--replace-laps` is not accepted.

- [ ] **Step 3: Add an explicit replacement mode**

  Accept only `--dry-run`, `--replace-laps`, and `--replace-laps --dry-run`.
  Without replacement, retain current collision refusal.  Under replacement,
  construct each of the 35 tags from the fixed seed/failure arrays and remove
  only its `.flow.txt`, `.stdout`, `.idmap`, `.dat`, and `.ascii.tmp` files.
  Remove only the known LAPS overlay filenames:

  ```text
  figA1dd_goodput_laps.{pdf,png}
  figA1dd_avg_fct_laps.{pdf,png}
  figA1dd_p99_fct_laps.{pdf,png}
  figA1dd_legend_laps.{pdf,png}
  ```

  Retain the shared-idmap backup/restore trap.  Update the README with the
  exact required command sequence: build/tests, `repro_laps.sh --replace-laps`,
  then `python3 make_figs.py --with-laps`.

- [ ] **Step 4: Run runner and figure contracts**

  Run: `bash htsim/sim/datacenter/prism_eval/expA_delaydriven/tests/test_repro_laps.sh && python3 htsim/sim/datacenter/prism_eval/expA_delaydriven/tests/test_make_figs_laps.py`

  Expected: PASS; no non-LAPS fixture is removed.

- [ ] **Step 5: Commit the reproducible replacement workflow**

  ```bash
  git add htsim/sim/datacenter/prism_eval/expA_delaydriven/repro_laps.sh \
    htsim/sim/datacenter/prism_eval/expA_delaydriven/tests/test_repro_laps.sh \
    htsim/sim/datacenter/prism_eval/expA_delaydriven/README.md \
    htsim/sim/datacenter/prism_eval/expA_delaydriven/tests/test_make_figs_laps.py
  git commit -m "feat: replace ExpA LAPS artifacts explicitly"
  ```

### Task 6: Verify, regenerate strict LAPS ExpA artifacts, and review

**Files:**
- Modify at runtime only: `htsim/sim/datacenter/prism_eval/expA_delaydriven/data/expA_laps_*`
- Modify at runtime only: `htsim/sim/datacenter/prism_eval/expA_delaydriven/figs/*_laps.{pdf,png}`

**Interfaces:**
- Consumes: complete strict LAPS implementation and Task 5 replacement mode.
- Produces: uncommitted strict LAPS input traces and three overlay figures.

- [ ] **Step 1: Build and run all LAPS plus baseline regression tests**

  Run:

  ```bash
  cmake -S htsim/sim -B htsim/sim/build-laps -DENABLE_TESTS=ON
  cmake --build htsim/sim/build-laps -j2
  ctest --test-dir htsim/sim/build-laps -L laps --output-on-failure
  ctest --test-dir htsim/sim/build-laps -R '^(reps_slot_cache|prism_coordination|legacy_reps_trace)$' --output-on-failure
  ```

  Expected: all commands PASS before any existing LAPS results are replaced.

- [ ] **Step 2: Record hashes of original seven-baseline figures**

  Run `sha256sum` on `figA1dd_goodput.pdf`, `figA1dd_avg_fct.pdf`, and
  `figA1dd_p99_fct.pdf`, saving the values under `/tmp` for post-run comparison.

- [ ] **Step 3: Regenerate only strict LAPS ExpA data**

  Run: `bash htsim/sim/datacenter/prism_eval/expA_delaydriven/repro_laps.sh --replace-laps`

  Expected: exactly 35 nonempty `expA_laps_f*_s*.flow.txt` artifacts and no
  execution of the seven pre-existing baseline algorithms.

- [ ] **Step 4: Render strict LAPS overlays**

  Run: `python3 htsim/sim/datacenter/prism_eval/expA_delaydriven/make_figs.py --with-laps`

  Expected: exactly these three principal files exist and contain a purple
  `LAPS` curve before green final-legend `Prism`:

  ```text
  figs/figA1dd_goodput_laps.pdf
  figs/figA1dd_avg_fct_laps.pdf
  figs/figA1dd_p99_fct_laps.pdf
  ```

- [ ] **Step 5: Check artifact integrity and repository hygiene**

  Recompute the three original-figure hashes and compare them to Step 2.
  Verify 35 flow files, run the plotting self-test, and inspect:

  ```bash
  python3 htsim/sim/datacenter/prism_eval/expA_delaydriven/make_figs.py --selftest
  git diff --check
  git status --short
  ```

  Expected: original figures unchanged, strict LAPS data/figures untracked or
  ignored as intended, and no generated artifact staged for commit.

- [ ] **Step 6: Request final code review before claiming completion**

  Review the diff against `2026-07-18-laps-strict-semantics-design.md`, with
  special attention to LAPS-only guards, exact official rate transitions,
  shared-path RTO ownership, and preserved non-LAPS behavior.  Fix any issue,
  re-run Steps 1 and 5, then report the new LAPS results as HTSIM-port results
  rather than paper-reproduction results.
