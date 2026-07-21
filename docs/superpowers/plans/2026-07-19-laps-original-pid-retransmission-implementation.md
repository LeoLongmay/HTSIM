# Strict-LAPS Original-PID Retransmission Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the LAPS paper's `ReTx(pid)` semantics by carrying a strict-LAPS segment's original routable pid and physical path identity from loss recovery to retransmission, without changing any experiment or control parameter.

**Architecture:** A strict-LAPS send record retains its resolved `LapsPathKey`. When strict recovery or an exact NACK detaches that record, it places the pid, selection metadata, and path key in a LAPS-only pending-retransmission map keyed by sequence number. `sendRtxPacket` consumes that record, reconstructs the original pid rather than selecting a new one, verifies the route resolves to the saved physical key, and registers a new attempt on that same key. Non-strict retransmission retains its existing entropy-selection path.

**Tech Stack:** C++17, HTSIM `UecSrc`/`UecNIC`, CMake/CTest, Bash ExpA runner, Python/Matplotlib renderer.

## Global Constraints

- Keep ExpA at `PATHS=8`, `END_MS=8`, and `EXTRA_ARGS=-disable_trim`.
- Do not change the topology, workload, queue configuration, failure matrix, figure schema, or control/recovery behavior of OPS, REPS, Swift, MSwift, MNSCC, STrack, or Prism.
- Do not change LAPS `beta`, safety window, pacing, probe cadence, or any congestion-control parameter.
- Do not enable trim or add receiver-gap loss inference.
- Gate all new state and behavior behind `UecSrc::isStrictLaps()`; legacy LAPS remains on its pre-existing UEC path.
- Preserve original seven-algorithm PDFs byte-for-byte. Do not commit generated data, stdout, idmaps, DAT files, temporary files, PDFs, PNGs, logs, or paper directories.
- Run the full 35-case LAPS replacement only after both f0/s13 and f12/s13 diagnostics complete all 320 flows and materially eliminate the prior f12/s13 retransmission/drop storm (`37,499` RTX / `18,720` drops).

## File Structure

- `htsim/sim/uec.h` — strict-LAPS-only pending replay state, saved physical key in live send records, and private replay selector declarations.
- `htsim/sim/uec.cpp` — preserve loss origin data when strict records detach; select saved pid for strict retransmission; re-resolve and assert physical identity.
- `htsim/sim/datacenter/add_motivation/common/tests/test_laps_uec_isolation.cpp` — deterministic strict recovery/replay identity regression.
- `htsim/sim/datacenter/prism_eval/expA_delaydriven/repro_laps.sh` and `make_figs.py` — unchanged consumers, used only after the gate passes.

---

### Task 1: Specify the failing strict-LAPS replay-identity regression

**Files:**
- Modify: `htsim/sim/datacenter/add_motivation/common/tests/test_laps_uec_isolation.cpp`
- Test: `htsim/sim/datacenter/add_motivation/common/tests/test_laps_uec_isolation.cpp`

**Interfaces:**
- Consumes: the existing `#define private public` test access and `installStrictRecord` pattern.
- Produces: an expected, not-yet-implemented `UecSrc::RtxPathSelection selectRtxPath(seq_t)` result and strict pending replay state.

- [ ] **Step 1: Write the failing regression before production code**

Add a function before `unpaired_laps_preserves_legacy_uec_behavior` that creates a strict LAPS source with a source-port route and a resolver mapping entropy 7 to `original_queue` and every other entropy to `other_queue`. Install a strict record for sequence 70 with entropy 7, a non-default `UecMpSelection`, and the key resolved from entropy 7; then recover it through `lapsRecover`.

```cpp
void strict_laps_retransmission_keeps_the_original_pid_and_path(EventList& eventlist) {
    setStrictGlobals();
    Queue original_queue(speedFromGbps(100), 100'000, eventlist, nullptr);
    Queue other_queue(speedFromGbps(100), 100'000, eventlist, nullptr);
    original_queue.forceName("original-path");
    other_queue.forceName("resprayed-path");
    UecNIC nic(7, eventlist, speedFromGbps(100), 1);
    UecSrc source(nullptr, eventlist, std::make_unique<UecMpLaps>(8, false, 1.0), nic, 1);
    Route send_route;
    source.getPort(0)->setRoute(send_route);
    source.lapsSetPathResolver([&](uint32_t, uint32_t entropy, uint32_t,
                                   vector<const BaseQueue*>& queues) {
        queues = {entropy == 7 ? &original_queue : &other_queue};
        return true;
    });
    LapsPathKey original_path;
    assert(source.lapsResolvePath(7, send_route, original_path));
    const UecMpSelection original_selection = {7, UecMpSelection::FIRST_WINDOW, 91, 3, 12};
    source.createSendRecord(7, 70, 1'200, original_selection, true, original_path);
    source._in_flight += 1'200;
    const LapsAttempt attempt = nic.lapsRecovery().sent(original_path, source, 70, 1'200);
    source._tx_bitmap.at(70).laps_attempt = attempt;
    source.lapsRecover(attempt, 70, 1'200);

    assert(source._tx_bitmap.empty());
    assert(source._rtx_queue.count(70) == 1);
    const UecSrc::RtxPathSelection replay = source.selectRtxPath(70);
    assert(replay.entropy == 7);
    assert(replay.selection.entropy == 7);
    assert(replay.selection.source == UecMpSelection::FIRST_WINDOW);
    assert(replay.selection.token_id == 91);
    assert(replay.selection.cache_slot == 3);
    assert(replay.selection.cache_generation == 12);
    assert(replay.strict_laps_path.has_value());
    assert(replay.strict_laps_path->queue_fingerprint == original_path.queue_fingerprint);
    LapsPathKey resolved;
    assert(source.lapsResolvePath(replay.entropy, send_route, resolved));
    assert(resolved.queue_fingerprint == replay.strict_laps_path->queue_fingerprint);
}
```

Call it from `main()` and retain the existing pending-event emptiness assertion after it.

- [ ] **Step 2: Verify the new test fails for the intended reason**

Run:

```bash
cmake --build htsim/sim/build-laps -j2 --target test_laps_uec_isolation
```

Expected: compilation fails because `sendRecord` cannot receive `original_path` and `RtxPathSelection` / `selectRtxPath` do not exist. This proves the test demands behavior absent from the current respraying implementation.

- [ ] **Step 3: Commit the failing contract**

```bash
git add htsim/sim/datacenter/add_motivation/common/tests/test_laps_uec_isolation.cpp
git commit -m "test: specify LAPS original-pid replay"
```

### Task 2: Carry and consume strict-LAPS replay identity

**Files:**
- Modify: `htsim/sim/uec.h:291-356`
- Modify: `htsim/sim/uec.cpp:850-867, 3032-3115, 3689-3744, 3904-3932`
- Modify: `htsim/sim/datacenter/add_motivation/common/tests/test_laps_uec_isolation.cpp`
- Test: `htsim/sim/datacenter/add_motivation/common/tests/test_laps_uec_isolation.cpp`

**Interfaces:**
- Consumes: Task 1's `RtxPathSelection` test contract.
- Produces: `sendRecord::laps_path`, `LapsRtxRoute`, `queueForRtx(seq_t, mem_b, std::optional<LapsRtxRoute>)`, and `selectRtxPath(seq_t)`.

- [ ] **Step 1: Add narrowly-scoped data types in `uec.h`**

Extend `sendRecord` and `createSendRecord` so strict data sends save the physical key resolved at send time:

```cpp
struct sendRecord {
    sendRecord(uint32_t ppath, mem_b psize, simtime_picosec stime,
               UecMpSelection pselection, bool strict_laps_data,
               std::optional<LapsAttempt> laps_attempt = std::nullopt,
               std::optional<LapsPathKey> laps_path = std::nullopt)
        : path_id(ppath), pkt_size(psize), send_time(stime), selection(pselection),
          strict_laps_data(strict_laps_data), laps_attempt(laps_attempt),
          laps_path(std::move(laps_path)) {}
    std::optional<LapsPathKey> laps_path;
};
struct LapsRtxRoute { uint32_t path_id; UecMpSelection selection; LapsPathKey path; };
struct RtxPathSelection {
    uint32_t entropy;
    UecMpSelection selection;
    std::optional<LapsPathKey> strict_laps_path;
};

map<UecDataPacket::seq_t, LapsRtxRoute> _laps_rtx_routes;
RtxPathSelection selectRtxPath(UecDataPacket::seq_t seqno);
void queueForRtx(UecDataPacket::seq_t seqno, mem_b pkt_size,
                 std::optional<LapsRtxRoute> laps_route = std::nullopt);
void createSendRecord(uint32_t path_id, UecDataPacket::seq_t seqno, mem_b pkt_size,
                      UecMpSelection selection, bool strict_laps_data = false,
                      std::optional<LapsPathKey> laps_path = std::nullopt);
```

Require `laps_route` only for strict LAPS. The extra map is never populated or consulted by non-strict flows.

- [ ] **Step 2: Preserve strict origin information before each detach**

In `lapsRecover`, construct `LapsRtxRoute` from the matching live record before erasing it, require `strict_laps_data` and `laps_path`, then pass it to `queueForRtx` after `delFromSendTimes`:

```cpp
const LapsRtxRoute route = {record->second.path_id, record->second.selection,
                            *record->second.laps_path};
const simtime_picosec send_time = record->second.send_time;
_tx_bitmap.erase(record);
delFromSendTimes(send_time, seqno);
_in_flight -= bytes;
queueForRtx(seqno, bytes, route);
```

Apply the same capture-and-queue operation in the strict branch of `processNack` before its erase. All non-strict `queueForRtx` callers retain the two-argument form. Pass `laps_path` to `createSendRecord` in strict `sendNewPacket` and strict retransmission before calling `LapsRecoveryDomain::sent`. A strict record without `laps_path` is an invariant violation.

- [ ] **Step 3: Implement selection and physical-key verification**

Implement `selectRtxPath` adjacent to `sendRtxPacket`:

```cpp
UecSrc::RtxPathSelection UecSrc::selectRtxPath(UecDataPacket::seq_t seqno) {
    if (!isStrictLaps()) {
        const uint32_t entropy = _mp->nextEntropy(_highest_sent, (uint64_t)_cwnd / _mss);
        return {entropy, _mp->lastSelection(), std::nullopt};
    }
    const auto replay = _laps_rtx_routes.find(seqno);
    assert(replay != _laps_rtx_routes.end());
    return {replay->second.path_id, replay->second.selection, replay->second.path};
}
```

Replace the unconditional `nextEntropy` block in `sendRtxPacket` with this helper. Resolve the chosen entropy as before; for strict LAPS require:

```cpp
assert(selection.strict_laps_path.has_value());
assert(laps_path.queue_fingerprint == selection.strict_laps_path->queue_fingerprint);
assert(_laps_rtx_routes.erase(seq_no) == 1);
```

Erase only after successful route resolution. Use `selection.selection` in the new send record. No call to `nextEntropy` occurs on the strict branch.

- [ ] **Step 4: Run the regression red-to-green and focused suite**

Run:

```bash
cmake --build htsim/sim/build-laps -j2 --target test_laps_uec_isolation test_laps_recovery test_laps_packet_feedback htsim_uec
ctest --test-dir htsim/sim/build-laps -R '^(laps_uec_isolation|laps_recovery|laps_packet_feedback)$' --output-on-failure
ctest --test-dir htsim/sim/build-laps -L laps --output-on-failure
```

Expected: the new replay test passes; all focused and labeled LAPS tests pass. The build target updates the `htsim/sim/datacenter/htsim_uec` executable consumed by ExpA.

- [ ] **Step 5: Commit the semantic correction**

```bash
git add htsim/sim/uec.h htsim/sim/uec.cpp htsim/sim/datacenter/add_motivation/common/tests/test_laps_uec_isolation.cpp
git commit -m "fix: preserve strict LAPS retransmission pid"
```

### Task 3: Apply the two-point causal gate and conditionally regenerate overlays

**Files:**
- Read: `htsim/sim/datacenter/prism_eval/expA_delaydriven/data/expA_{ops,reps,swift,mswift,mnscc,strack,prism}_f12_s13.stdout`
- Write only on gate pass: untracked `htsim/sim/datacenter/prism_eval/expA_delaydriven/data/expA_laps_f*_s*.*` and `htsim/sim/datacenter/prism_eval/expA_delaydriven/figs/figA1dd_*_laps.*`
- Test: existing ExpA runner and renderer; no source edits.

**Interfaces:**
- Consumes: Task 2's rebuilt `htsim_uec` and source-test evidence.
- Produces on gate pass: replacement strict-LAPS ExpA data and three `_laps` overlay PDFs. Produces on gate failure: a diagnostic report only, with existing figures untouched.

- [ ] **Step 1: Preserve checksums of original baseline PDFs**

```bash
sha256sum htsim/sim/datacenter/prism_eval/expA_delaydriven/figs/figA1dd_avg_fct.pdf htsim/sim/datacenter/prism_eval/expA_delaydriven/figs/figA1dd_goodput.pdf htsim/sim/datacenter/prism_eval/expA_delaydriven/figs/figA1dd_p99_fct.pdf > /tmp/laps-original-pid-baseline-pdfs.sha256
```

- [ ] **Step 2: Run f0/s13 and f12/s13 in an isolated temporary directory**

```bash
rm -rf /tmp/laps-original-pid-gate
mkdir -p /tmp/laps-original-pid-gate
PATHS=8 END_MS=8 EXTRA_ARGS=-disable_trim bash htsim/sim/datacenter/prism_eval/common/run_lib.sh laps laps 0 fat_tree_128_1os.topo 13 /home/leo/htsim/htsim/sim/datacenter/prism_eval/expA_delaydriven/data/m2m.cm flow laps_pid_f0_s13 /tmp/laps-original-pid-gate
PATHS=8 END_MS=8 EXTRA_ARGS=-disable_trim bash htsim/sim/datacenter/prism_eval/common/run_lib.sh laps laps 12 fat_tree_128_1os.topo 13 /home/leo/htsim/htsim/sim/datacenter/prism_eval/expA_delaydriven/data/m2m.cm flow laps_pid_f12_s13 /tmp/laps-original-pid-gate
```

- [ ] **Step 3: Extract completion and storm counters before deciding**

```bash
for f in /tmp/laps-original-pid-gate/*.stdout; do echo "=== $f ==="; rg -n 'New:|Rtx:|ACKs:|NACKs:|Drops:|finished|FLOW_EVENT' "$f" || true; done
wc -l /tmp/laps-original-pid-gate/*.flow.txt
for f in htsim/sim/datacenter/prism_eval/expA_delaydriven/data/expA_{ops,reps,swift,mswift,mnscc,strack,prism}_f12_s13.stdout; do printf '%s: ' "$(basename "$f")"; rg -o 'Rtx: [0-9]+|Drops: [0-9]+' "$f" | tr '\n' ' '; echo; done
```

Pass only if each LAPS flow file has 320 completed flow events and f12/s13 RTX/Drops are no longer comparable to the old `37,499`/`18,720` storm, instead approaching the established few-thousand / low-thousand scale. If either run is incomplete or the storm remains, do not delete or replace ExpA LAPS artifacts, do not invoke `repro_laps.sh`, and do not render figures.

- [ ] **Step 4: On a passed gate, replace the complete sweep and render only overlays**

```bash
bash htsim/sim/datacenter/prism_eval/expA_delaydriven/repro_laps.sh --replace-laps
python3 htsim/sim/datacenter/prism_eval/expA_delaydriven/make_figs.py --with-laps
for f in htsim/sim/datacenter/prism_eval/expA_delaydriven/data/expA_laps_f{0,2,4,6,8,10,12}_s{13,14,15,16,17}.flow.txt; do test "$(wc -l < "$f")" -eq 320 || { echo "incomplete: $f"; exit 1; }; done
sha256sum -c /tmp/laps-original-pid-baseline-pdfs.sha256
test -s htsim/sim/datacenter/prism_eval/expA_delaydriven/figs/figA1dd_avg_fct_laps.pdf
test -s htsim/sim/datacenter/prism_eval/expA_delaydriven/figs/figA1dd_goodput_laps.pdf
test -s htsim/sim/datacenter/prism_eval/expA_delaydriven/figs/figA1dd_p99_fct_laps.pdf
```

- [ ] **Step 5: Record outcome without committing generated artifacts**

```bash
git status --short
```

Expected: code and tests are committed; ExpA data and figures remain untracked and intentionally excluded.
