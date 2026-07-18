# LAPS Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Add LAPS as one integrated UEC transport baseline, selected only by the paired flags `-sender_cc_algo laps -load_balancing_algo laps`, with delay-aware probabilistic path spraying, ACK delay feedback, selective all-path congestion reduction, and stale-path recovery probes.

**Architecture:** Extend the existing UEC split rather than adding a simulator or transport stack: `UecMpLaps` owns per-path delay state and entropy selection; UEC data/ACK packets carry the optional measurement; `UecSink` stamps the measurement; `UecSrc` applies the LAPS rate decision and schedules probes. Existing UEC SACK/NACK/RTO/retransmission ownership remains unchanged. The only accepted configuration is the paired CC/LB mode, so Prism, STrack, MSwift, REPS, ECMP, and Oblivious keep their current behavior.

**Tech Stack:** Existing C++ UEC simulator, CMake/CTest, Bash integration test, existing Python `unittest` runner validation.

**Source constraints:** Implement the paper semantics from the approved design, but do not copy NS-3/GPL source. Keep the current two-axis CLI; do not create a new `--transport` flag, a separate executable, a source-route layer, or a new experiment pipeline. Preserve the dirty worktree and stage only files created for this task.

## Public interfaces and invariants

Add the following narrow, LAPS-only extension points in `uec_mp.h`; their base-class implementations are no-ops so existing algorithms do not change.

```cpp
struct UecMpLapsSignal {
    bool ready = false;             // every physical path has a current sample
    bool all_paths_high = false;    // every sampled real latency is above threshold
    uint16_t sampled_paths = 0;
    simtime_picosec threshold = 0;
    simtime_picosec max_real_latency = 0;
};

virtual void observeLapsDelay(uint32_t path_id, simtime_picosec delay,
                              simtime_picosec now) {}
virtual void observeLapsProbe(uint32_t path_id, simtime_picosec delay,
                              simtime_picosec now) {}
virtual optional<uint32_t> nextLapsProbeEntropy(simtime_picosec now) {
    return {};
}
virtual UecMpLapsSignal lapsSignal(simtime_picosec now,
                                   simtime_picosec queue_margin) const {
    return {};
}
```

`UecMpLaps` implements both existing pure virtual methods and these hooks. It keeps one `LapsPathState` per physical path: `valid`, `base_latency`, `real_latency`, `last_update`, and `last_probe`. Entropy identity is always mapped with `path_id & (_no_of_paths - 1)`; emitted entropies use the same fixed-upper-bit convention as `UecMpOblivious`, so the FatTree ECMP hash retains its existing behavior.

For valid samples, use the stable softmax form below. `beta == 0` must be exactly uniform. A path with no sample receives a bootstrap probability, rather than being permanently excluded.

```text
T = max(base_latency of valid paths) + queue_margin
weight_i = exp(-beta * (real_latency_i - min_real_latency) / max(T, 1))
P(i) = weight_i / sum(weight)
```

Samples older than `2 * real_latency` are stale. A stale candidate is selected before ordinary softmax traffic by `nextLapsProbeEntropy`; its temporary `real_latency` doubles only for the stale interval, then the probe ACK replaces it. An ACK or probe ACK observation updates `real_latency = delay`, keeps `base_latency = min(base_latency, delay)`, and refreshes `last_update`.

`UecSrc` rate action is a single LAPS decision: only when `lapsSignal.ready && lapsSignal.all_paths_high` is true may it halve `_cwnd`, gated by `2 * max_real_latency`. Otherwise it retains the normal UEC ACK/window-growth path, with additive growth gated by `2 * T`. No incomplete/bootstrap sample set may trigger an all-path decrease.

## Test matrix

| Test | Purpose | Required assertion |
| --- | --- | --- |
| `laps_multipath` | Selection/state unit test | low-delay path is sampled more often; beta 0 is uniform; partial congestion does not signal all-high; stale probe selection refreshes state |
| `laps_packet_feedback` | Packet/sink unit test | data timestamp is copied into ACK one-way delay, packet-pool reuse clears optional LAPS metadata |
| `laps_cc_decision` | Rate-decision unit test | incomplete state and one good path hold; all high yields exactly one gated multiplicative decrease; safe state permits gated additive growth |
| `laps_cli` | CLI integration | valid paired flags run a one-flow simulation; either unpaired configuration is rejected with an actionable error |
| `test_run_case.py` | Runner validation | `laps` is accepted in both existing allow-lists and emitted command uses paired values |
| existing CTest suite | Non-regression | existing REPS/Prism unit and CLI tests still pass |

## Task 1: Introduce an isolated, testable LAPS path-state implementation

**Files:**
- Modify: `htsim/sim/uec_mp.h`
- Modify: `htsim/sim/uec_mp.cpp`
- Create: `htsim/sim/datacenter/add_motivation/common/tests/test_laps_multipath.cpp`
- Modify: `htsim/sim/CMakeLists.txt`

- [ ] **Step 1: Write the failing LAPS multipath test.**

  Construct `UecMpLaps(4, false, beta)` directly. Feed four synthetic delay samples at a fixed simulated time using `observeLapsDelay`. Make one path low delay and the other three high delay; call `nextEntropy()` repeatedly with a deterministic `srandom()` seed and count `entropy & 3`. Assert the low delay path is selected more often. Add separate checks that `beta=0` visits all paths within a tolerance, `lapsSignal()` is not ready until all four have samples, and a stale path is returned by `nextLapsProbeEntropy()`.

  ```cpp
  UecMpLaps laps(4, false, 8.0);
  for (uint32_t p = 0; p != 4; ++p)
      laps.observeLapsDelay(p, p == 0 ? 10 : 100, 1'000);
  unsigned low = 0, high = 0;
  for (uint64_t seq = 0; seq != 4'000; ++seq)
      ((laps.nextEntropy(seq, 16) & 3) == 0 ? low : high)++;
  assert(low > high / 3);
  ```

- [ ] **Step 2: Register the failing test in CMake and prove it fails for the missing type.**

  Add `test_laps_multipath`, link it privately to `htsim`, register `add_test(NAME laps_multipath ...)`, and label it `laps;unit`. Configure a fresh task-local build directory and run the single CTest target. The compile failure is the red-state evidence; do not alter unrelated CMake test definitions.

  ```bash
  cmake -S htsim/sim -B htsim/sim/build-laps
  cmake --build htsim/sim/build-laps --target test_laps_multipath -j2
  ```

- [ ] **Step 3: Add the base no-op hooks and `UecMpLaps`.**

  Add `UecMpLapsSignal` and the four virtual hooks specified above to `UecMultipath`. Define `UecMpLaps` beside the existing path algorithms. Its constructor rejects non-power-of-two path counts in the same style as peer algorithms. Implement candidate indexing, measurement observation, per-path base/real updates, stable softmax selection, and stale probe selection in `uec_mp.cpp`. Use only simulator time arguments supplied by callers; do not read wall-clock time.

  Selection edge cases to implement explicitly:

  - No valid states: round-robin/random bootstrap across all paths.
  - `beta == 0`: uniform selection without evaluating `exp`.
  - No stale state: return empty optional from `nextLapsProbeEntropy`.
  - More than one stale state: rotate fairly rather than repeatedly probing path zero.
  - A stale state is temporarily penalized before it can re-enter ordinary selection.

- [ ] **Step 4: Run the unit test and focused legacy regression.**

  ```bash
  cmake --build htsim/sim/build-laps --target test_laps_multipath test_reps_slot_cache -j2
  ctest --test-dir htsim/sim/build-laps --output-on-failure -R '^(laps_multipath|reps_slot_cache)$'
  ```

  Expected: LAPS state tests pass and REPS cache behavior remains unchanged.

## Task 2: Carry optional one-way delay through the UEC packet/ACK path

**Files:**
- Modify: `htsim/sim/uecpacket.h`
- Modify: `htsim/sim/uecpacket.cpp`
- Modify: `htsim/sim/uec.h`
- Modify: `htsim/sim/uec.cpp`
- Create: `htsim/sim/datacenter/add_motivation/common/tests/test_laps_packet_feedback.cpp`
- Modify: `htsim/sim/CMakeLists.txt`

- [ ] **Step 1: Write the failing packet feedback test.**

  Exercise the actual packet constructors/pool, not a duplicate struct. Create a data packet, mark a LAPS send timestamp, construct its ACK through the existing sink `sack()` path (using the existing lightweight sink fixture pattern), and assert: valid data produces `ack.lapsDelayValid()`, `ack.lapsOneWayDelay() == receive_time - send_time`, and a later pooled packet begins with both optional flags cleared.

- [ ] **Step 2: Add reset-safe packet metadata.**

  Add to `UecDataPacket` a private `simtime_picosec _laps_send_time` plus `bool _laps_send_time_valid`; add `setLapsSendTime`, `lapsSendTime`, and `lapsSendTimeValid`. Add corresponding `UecAckPacket` fields/accessors named `_laps_one_way_delay`, `_laps_delay_valid`, `setLapsOneWayDelay`, `lapsOneWayDelay`, and `lapsDelayValid`.

  In every `newpkt()` initialization path, reset the timestamp/delay to zero and validity to false before handing a pooled object out. This reset is mandatory because UEC packet pools reuse objects.

- [ ] **Step 3: Stamp only LAPS traffic at the send/receive boundaries.**

  In the LAPS send branch, set the data timestamp from `eventlist().now()` immediately before packet injection. Extend `UecSink::sack(uint32_t path_id, seq_t seqno, seq_t acked_psn, bool ce, bool rtx_echo)` only through the packet object: if the received data had a valid LAPS timestamp and `now >= timestamp`, attach `now - timestamp` to the ACK. Do not change the SACK bitmap, sequence spaces, NACK, retransmission, or non-LAPS ACK layout/meaning.

- [ ] **Step 4: Run packet and existing packet tests.**

  ```bash
  cmake --build htsim/sim/build-laps --target test_laps_packet_feedback -j2
  ctest --test-dir htsim/sim/build-laps --output-on-failure -R '^(laps_packet_feedback|trace_writer)$'
  ```

## Task 3: Make the paired CLI configuration construct LAPS and reject invalid combinations

**Files:**
- Modify: `htsim/sim/uec.h`
- Modify: `htsim/sim/uec.cpp`
- Modify: `htsim/sim/datacenter/main_uec.cpp`
- Modify: `htsim/sim/datacenter/add_motivation/common/run_case.py`
- Modify: `htsim/sim/datacenter/add_motivation/common/tests/test_run_case.py`
- Create: `htsim/sim/datacenter/add_motivation/common/tests/test_laps_cli.sh`
- Modify: `htsim/sim/CMakeLists.txt`

- [ ] **Step 1: Write parser and runner tests before implementation.**

  Add Python assertions that `VALID_CC` accepts `laps`, `VALID_LOAD_BALANCERS` accepts `laps`, and the generated command preserves both values. Add a Bash CTest equivalent to the existing one-flow Prism CLI fixture. It must accept:

  ```bash
  -sender_cc_algo laps -load_balancing_algo laps -paths 8
  ```

  It must reject `laps` with `reps_actual` and `prism` with `laps`, with output that includes `requires -sender_cc_algo laps -load_balancing_algo laps` (or the exact inverse requirement for the CC side).

- [ ] **Step 2: Extend configuration vocabulary and enforce the pair.**

  Add `LAPS` to `UecSrc::Sender_CC`; add `LAPS` to `LoadBalancing_Algo`. Parse `laps` on both axes. Add static defaults/configuration storage in `UecSrc` for `laps_beta`, `laps_probe_interval`, and `laps_queue_margin`, parsed as opt-in CLI values with defaults specified in `main_uec.cpp` help text.

  At the existing coupling-validation site, reject either unpaired combination before topology creation. Preserve all current validation errors and do not silently map a single `laps` flag to another baseline.

- [ ] **Step 3: Wire source factories.**

  In both the normal and ATLAHS source construction paths, instantiate `UecMpLaps` only for the accepted LB value and set `UecSrc::_sender_cc_algo` to `LAPS` only for the accepted CC value. Pass the configured beta to the multipath object. No other factory branch should be edited semantically.

- [ ] **Step 4: Execute configuration tests.**

  ```bash
  cmake --build htsim/sim/build-laps --target htsim_uec -j2
  ctest --test-dir htsim/sim/build-laps --output-on-failure -R '^laps_cli$'
  python3 -m unittest htsim.sim.datacenter.add_motivation.common.tests.test_run_case
  ```

## Task 4: Apply ACK feedback, selective LAPS CWND control, and independent probes

**Files:**
- Create: `htsim/sim/laps_cc.h`
- Modify: `htsim/sim/uec.h`
- Modify: `htsim/sim/uec.cpp`
- Modify: `htsim/sim/uec_mp.h`
- Modify: `htsim/sim/uec_mp.cpp`
- Create: `htsim/sim/datacenter/add_motivation/common/tests/test_laps_cc_decision.cpp`
- Modify: `htsim/sim/CMakeLists.txt`

- [ ] **Step 1: Write a pure failing rate-decision test.**

  Keep the decision itself independent of simulator objects in `laps_cc.h`:

  ```cpp
  enum class LapsCwndAction { Hold, AdditiveIncrease, MultiplicativeDecrease };
  struct LapsCwndDecision {
      LapsCwndAction action;
      simtime_picosec next_allowed_at;
  };
  ```

  Test four fixed cases: incomplete samples -> `Hold`; one path at/below threshold -> no decrease; all valid paths strictly above threshold -> `MultiplicativeDecrease`; a repeated all-high observation before its `2 * max_real_latency` gate -> `Hold`. Also test a safe repeated observation permits additive growth only after its `2 * threshold` gate.

- [ ] **Step 2: Implement and verify the pure decision helper.**

  `decideLapsCwnd(signal, now, next_increase_at, next_decrease_at)` returns the action and the revised gate timestamp. It must not mutate cwnd, call random functions, or inspect global state. It uses strict `>` for “high” and leaves policy constants (half cwnd, existing UEC additive increment) in `UecSrc`.

- [ ] **Step 3: Consume ACK measurements exactly once.**

  In `UecSrc::processAck`, after existing ACK validity/RTT attribution establishes that the ACK is usable, if sender CC is `LAPS` and `ack.lapsDelayValid()`, call `_mp->observeLapsProbe(...)` for a probe ACK and `_mp->observeLapsDelay(...)` otherwise. Thus each measurement is consumed exactly once. Preserve the existing `processEv` feedback call so loss/ECN behavior remains coherent. Do not manufacture LAPS latency from retransmitted/stale ACKs.

- [ ] **Step 4: Integrate the decision without bypassing UEC reliability.**

  Add LAPS-only source fields for next allowable increase/decrease and a small method that consumes `lapsSignal(now, _laps_queue_margin)`. On `MultiplicativeDecrease`, set `_cwnd` to `max(_mss, _cwnd / 2)` and update the decrease gate. On `AdditiveIncrease`, use the same existing ACK growth increment that UEC uses for its sender CC path, then update the increase gate. On `Hold`, leave `_cwnd` untouched. Do not alter `_tx_bitmap`, `_rtx_queue`, RTO, SACK, NACK, or packet sequence accounting.

- [ ] **Step 5: Add a LAPS-only probe event.**

  Add a distinct source timer/event path rather than changing `_enable_sleek` behavior. While an active LAPS flow has a stale candidate, request `nextLapsProbeEntropy(now)`, emit the existing `DATA_PROBE` packet with a LAPS timestamp and that entropy, and record the probe send through the multipath hook. At the sink, the existing `DATA_PROBE` ACK path marks the ACK as probe ACK; its valid measurement follows the probe-only `observeLapsProbe` branch above. Schedule the next LAPS probe at `_laps_probe_interval`, cancel/avoid rescheduling after the flow finishes, and never use probe sequence numbers in the data reliability bitmap.

- [ ] **Step 6: Run LAPS controller tests and focused regression.**

  ```bash
  cmake --build htsim/sim/build-laps --target test_laps_cc_decision test_laps_multipath htsim_uec -j2
  ctest --test-dir htsim/sim/build-laps --output-on-failure -R '^(laps_cc_decision|laps_multipath|laps_packet_feedback|prism_coordination)$'
  ```

## Task 5: Final integration evidence and comparison-ready invocation

**Files:**
- Modify only if needed after tests: `htsim/sim/datacenter/add_motivation/common/run_case.py`
- Modify only if needed after tests: `htsim/sim/datacenter/add_motivation/common/tests/test_run_case.py`
- No new experiment pipeline or generated data committed.

- [ ] **Step 1: Validate the public command shape.**

  Confirm the simulator accepts a one-flow command using both axes and explicitly prints/records `laps` settings where current configuration reporting permits. The canonical invocation is:

  ```bash
  htsim/sim/build-laps/htsim_uec \
    -topo htsim/sim/datacenter/topologies/fat_tree_128_1os.topo \
    -tm htsim/sim/datacenter/add_motivation/common/tests/one_flow.cm \
    -nodes 128 -paths 8 -sender_cc_algo laps -load_balancing_algo laps \
    -laps_beta 8 -laps_probe_interval 50 -laps_queue_margin 0 -end 2 -o /tmp/laps-one-flow.dat
  ```

  Adjust only file locations/units to the repository’s existing CLI conventions while preserving the two LAPS flags.

- [ ] **Step 2: Run the complete relevant regression set.**

  ```bash
  cmake --build htsim/sim/build-laps -j2
  ctest --test-dir htsim/sim/build-laps --output-on-failure -L laps
  ctest --test-dir htsim/sim/build-laps --output-on-failure \
    -R '^(reps_slot_cache|prism_coordination|prism_coordination_cli|trace_writer|laps_.*)$'
  python3 -m unittest htsim.sim.datacenter.add_motivation.common.tests.test_run_case
  git diff --check
  git status --short
  ```

- [ ] **Step 3: Manually inspect behavioral boundaries.**

  With deterministic small matrices/topologies already in the tree, collect only temporary outputs to establish these checks: (a) beta 0 sprays across all available paths; (b) an artificial high-delay path loses share while a low-delay path retains traffic; (c) one high path does not halve cwnd; (d) all paths high halves cwnd at most once per gate; (e) a stale path receives a probe and re-enters after ACK feedback. Compare using the same topology/traffic against `prism + reps_actual`, `strack + reps_actual`, and `mswift + reps_actual`; this is a baseline smoke comparison, not a claim to reproduce LAPS paper figures.

- [ ] **Step 4: Review scope before handoff.**

  Verify that changed tracked files are limited to the UEC implementation, existing runner validation, CMake tests, and LAPS tests; that no NS-3 source/code or generated outputs were added; and that no behavior changes occur when neither axis is `laps`.

## Completion criteria

- LAPS is constructible only through the paired CLI flags in both source factory paths.
- ACKs deliver valid per-path one-way delay samples without packet-pool leakage.
- Softmax selection, stale refresh, and all-path-only multiplicative decrease have direct automated coverage.
- LAPS probes are independent of SLEEK and the normal UEC reliability lifecycle.
- Focused legacy CTests and runner tests pass, with recorded commands and `git diff --check` clean.
