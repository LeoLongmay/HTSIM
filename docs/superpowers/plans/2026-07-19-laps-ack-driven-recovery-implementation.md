# Strict-LAPS ACK-Driven Loss Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Make strict-LAPS infer and retransmit same-flow, same-physical-path loss from ACK ordering and use a per-flow/path 2 × one-way-delay tail timer, without changing the seven existing baselines or -disable_trim.

**Architecture:** Replace the NIC domain's single physical-path queue with owner-isolated (LapsPathKey, LapsRecoveryOwner*) state. A valid strict-LAPS ACK supplies an attempt and an optional one-way delay: the domain selectively recovers only older attempts in that attempt's owner/path queue, then arms its tail deadline from the delay. The source remains responsible for verifying current attempt identity and turning callbacks into ordinary retransmissions.

**Tech Stack:** C++17, HTSIM EventList, CMake/CTest, Bash ExpA reproducer, Python/Matplotlib figure renderer.

## Global Constraints

- Keep repro_laps.sh invocation settings exactly PATHS=8, END_MS=8, and EXTRA_ARGS=-disable_trim.
- Do not change CompositeQueue, global trimming configuration, or data/control behavior for OPS, REPS, Swift, MSwift, MNSCC, STrack, or Prism.
- Gate every new behavior with UecSrc::isStrictLaps(); legacy LAPS remains unchanged.
- Key recovery by the established plane-qualified LapsPathKey and LapsRecoveryOwner* together.
- Do not infer loss from receiver gaps, UEC SACK, or a different physical path.
- Keep late ACK/NACK/timeout notifications idempotent and attempt-safe.
- Do not commit generated ExpA data, stdout, idmaps, PDFs, PNGs, paper directories, logs, or temporary files.

## File Structure

- htsim/sim/laps_recovery.h — recovery-domain key, API, timeout constants, and state declarations.
- htsim/sim/laps_recovery.cpp — owner/path-local ACK inference, exact NACK/retirement, timer scheduling, and callback-safe expiry.
- htsim/sim/uec.cpp — strict-LAPS data ACK wiring that passes its one-way delay to the recovery domain before generic ACK/SACK retirement.
- htsim/sim/datacenter/add_motivation/common/tests/test_laps_recovery.cpp — deterministic domain tests for owner isolation, physical-path isolation, delay timer, and late feedback.
- htsim/sim/datacenter/add_motivation/common/tests/test_laps_packet_feedback.cpp — packet-level valid one-way-delay feedback regression.
- htsim/sim/datacenter/prism_eval/expA_delaydriven/repro_laps.sh and make_figs.py — unchanged consumers used only for final regeneration.

---

### Task 1: Specify failing owner/path-local recovery tests

**Files:**
- Modify: htsim/sim/datacenter/add_motivation/common/tests/test_laps_recovery.cpp
- Modify: htsim/sim/laps_recovery.h

**Interfaces:**
- Consumes: LapsRecoveryDomain::sent(LapsPathKey, LapsRecoveryOwner&, seq_t, mem_b).
- Produces: tests for acknowledge(LapsAttempt, optional<simtime_picosec>), nack, retire, and kBootstrapRto.
- Produces: header declaration static constexpr simtime_picosec kBootstrapRto = 100ULL * 1000000ULL and the extended acknowledge signature; no implementation in this task.

- [ ] **Step 1: Write the failing same-owner inference test**

Replace the former cross-owner expectation with two attempts for owner_a and one interleaved attempt for owner_b on shared_path. ACK the later owner_a attempt and assert only owner_a's first attempt is recovered:

~~~
const LapsAttempt a_first = domain.sent(shared_path, owner_a, 10, 1000);
const LapsAttempt b_only = domain.sent(shared_path, owner_b, 20, 1100);
const LapsAttempt a_later = domain.sent(shared_path, owner_a, 30, 1200);
owner_a.makeCurrent(a_first);
owner_b.makeCurrent(b_only);

assert(domain.acknowledge(a_later, timeFromUs(uint32_t{7})));
assert((owner_a.recovered ==
        std::vector<std::pair<UecBasePacket::seq_t, mem_b>>{{10, 1000}}));
assert(owner_b.recovered.empty());
assert(domain.retire(b_only));
~~~

- [ ] **Step 2: Write the failing cross-path and 2×delay tail test**

Use a fresh EventList and verify an ACK from path_b cannot recover a path_a record. Then create three same-owner path_a attempts, ACK the middle one with 7 us, and assert the remaining tail attempt expires at 14 us rather than the bootstrap deadline:

~~~
const LapsAttempt first = domain.sent(path_a, owner, 100, 1000);
const LapsAttempt middle = domain.sent(path_a, owner, 110, 1000);
const LapsAttempt tail = domain.sent(path_a, owner, 120, 1000);
owner.makeCurrent(first);
assert(domain.acknowledge(middle, timeFromUs(uint32_t{7})));
owner.makeCurrent(tail);
assert(EventList::doNextEvent());
assert(EventList::now() == timeFromUs(uint32_t{14}));
assert((owner.recovered ==
        std::vector<std::pair<UecBasePacket::seq_t, mem_b>>{{100, 1000}, {120, 1000}}));
assert(owner.callbacks.back().attempt == tail);
~~~

Add a separate no-sample assertion that a lone attempt first expires at LapsRecoveryDomain::kBootstrapRto.

- [ ] **Step 3: Write failing late-feedback assertions**

After ACK-inferred recovery and after timer expiry, invoke acknowledge, nack, and retire with the old handle. Require no extra callback:

~~~
const size_t callbacks_before = owner.callbacks.size();
assert(!domain.acknowledge(first, timeFromUs(uint32_t{7})));
assert(!domain.nack(first));
assert(!domain.retire(first));
assert(owner.callbacks.size() == callbacks_before);
~~~

- [ ] **Step 4: Declare the test API and prove the current behavior fails**

In laps_recovery.h, add optional and declare:

~~~
static constexpr simtime_picosec kBootstrapRto = 100ULL * 1000000ULL;
bool acknowledge(LapsAttempt attempt,
                 std::optional<simtime_picosec> one_way_delay = std::nullopt);
~~~

Run:

~~~
cmake --build htsim/sim/build-laps -j2 --target test_laps_recovery
ctest --test-dir htsim/sim/build-laps -R '^laps_recovery$' --output-on-failure
~~~

Expected: compilation or assertions fail because the current implementation still infers across owners and uses fixed kRto.

- [ ] **Step 5: Commit the test contract**

~~~
git add htsim/sim/laps_recovery.h htsim/sim/datacenter/add_motivation/common/tests/test_laps_recovery.cpp
git commit -m "test: specify LAPS ACK recovery isolation"
~~~

### Task 2: Implement owner/path-local ACK inference and delay timers

**Files:**
- Modify: htsim/sim/laps_recovery.h
- Modify: htsim/sim/laps_recovery.cpp
- Test: htsim/sim/datacenter/add_motivation/common/tests/test_laps_recovery.cpp

**Interfaces:**
- Consumes: Task 1 acknowledge(attempt, optional delay) contract.
- Produces: an attempt-safe domain keyed by (LapsPathKey, owner), with exact-only nack/retire and delay-derived timers.

- [ ] **Step 1: Add the owner/path state key**

Add the functional header to laps_recovery.h, then replace the path-only map key with:

~~~
struct OwnerPathKey {
    LapsPathKey path;
    LapsRecoveryOwner* owner = nullptr;

    bool operator<(const OwnerPathKey& other) const {
        if (path < other.path) return true;
        if (other.path < path) return false;
        return std::less<LapsRecoveryOwner*>{}(owner, other.owner);
    }
};

struct PathState {
    std::list<Record> records;
    std::optional<simtime_picosec> one_way_delay;
    simtime_picosec deadline = 0;
};
~~~

Keep a state with a valid delay after its records are empty so a later tail packet gets the latest sample. removeOwner must erase every state for that owner.

- [ ] **Step 2: Add safe timeout and arm helpers**

Use overflow-safe helpers:

~~~
simtime_picosec twiceOrMax(simtime_picosec delay) {
    return delay > std::numeric_limits<simtime_picosec>::max() / 2
        ? std::numeric_limits<simtime_picosec>::max()
        : 2 * delay;
}

void LapsRecoveryDomain::arm(PathState& state) {
    const simtime_picosec interval = state.one_way_delay
        ? twiceOrMax(*state.one_way_delay) : kBootstrapRto;
    state.deadline = EventList::now() > std::numeric_limits<simtime_picosec>::max() - interval
        ? std::numeric_limits<simtime_picosec>::max() : EventList::now() + interval;
}
~~~

Call arm on every sent for that owner/path. A nonzero ACK delay replaces the saved sample, then refreshes the deadline. Timer scans ignore empty states.

- [ ] **Step 3: Implement local ACK inference and exact NACK/retirement**

Find the matched record by attempt; its OwnerPathKey is the only candidate list. Copy and erase records before it plus the matched record, re-arm remaining records, call updateTimer, then issue callbacks:

~~~
bool LapsRecoveryDomain::acknowledge(
    LapsAttempt attempt, std::optional<simtime_picosec> one_way_delay) {
    auto located = findAttempt(attempt);
    if (!located) return false;
    PathState& state = located->state;
    if (one_way_delay && *one_way_delay != 0) state.one_way_delay = *one_way_delay;
    std::vector<Record> inferred(located->record_begin, located->record);
    state.records.erase(located->record_begin, std::next(located->record));
    if (!state.records.empty()) arm(state);
    updateTimer();
    for (const Record& record : inferred)
        record.owner->lapsRecover(record.attempt, record.seq, record.bytes);
    return true;
}
~~~

Implement nack and retire through an exact-record detach helper. Neither may infer a preceding record. Re-arm only the affected state and always schedule before callbacks.

- [ ] **Step 4: Implement local timeout expiry**

In doNextEvent, copy only nonempty owner/path states with deadline <= now, clear their records before callbacks, retain a valid delay sample, call updateTimer, then invoke lapsRecover. This must preserve callback re-registration safety.

- [ ] **Step 5: Verify tests**

Run:

~~~
cmake --build htsim/sim/build-laps -j2 --target test_laps_recovery
ctest --test-dir htsim/sim/build-laps -R '^laps_recovery$' --output-on-failure
ctest --test-dir htsim/sim/build-laps -L laps --output-on-failure
~~~

Expected: all recovery assertions and pre-existing LAPS tests pass.

- [ ] **Step 6: Commit**

~~~
git add htsim/sim/laps_recovery.h htsim/sim/laps_recovery.cpp \
  htsim/sim/datacenter/add_motivation/common/tests/test_laps_recovery.cpp
git commit -m "fix: isolate LAPS ACK-driven recovery"
~~~

### Task 3: Wire strict-LAPS ACK delay into recovery

**Files:**
- Modify: htsim/sim/uec.cpp:1437-1605
- Modify: htsim/sim/datacenter/add_motivation/common/tests/test_laps_packet_feedback.cpp

**Interfaces:**
- Consumes: Task 2 acknowledge(attempt, optional delay).
- Produces: valid strict-LAPS data ACKs cause paper-style immediate recovery before cumulative/SACK retirement; no other transport changes.

- [ ] **Step 1: Add/confirm packet feedback test**

Extend test_laps_packet_feedback.cpp's existing synthetic source/sink route to assert the returned ACK provides its one-way sample:

~~~
assert(ack->lapsDelayValid());
assert(ack->lapsOneWayDelay() == expected_one_way_delay);
~~~

Run:

~~~
cmake --build htsim/sim/build-laps -j2 --target test_laps_packet_feedback
ctest --test-dir htsim/sim/build-laps -R '^laps_packet_feedback$' --output-on-failure
~~~

Expected: PASS; this is the only delay source passed to recovery.

- [ ] **Step 2: Pass a valid one-way data delay before generic retirement**

In UecSrc::processAck, immediately before the current strict-LAPS acknowledge call, derive and pass only the packet's valid nonzero delay:

~~~
const std::optional<simtime_picosec> laps_one_way_delay =
    pkt.lapsDelayValid() && pkt.lapsOneWayDelay() != 0
        ? std::optional<simtime_picosec>(pkt.lapsOneWayDelay())
        : std::nullopt;

if (isStrictLaps() && valid_normal_send_attempt && i->second.strict_laps_data) {
    assert(i->second.laps_attempt.has_value());
    _nic.lapsRecovery().acknowledge(*i->second.laps_attempt, laps_one_way_delay);
}
~~~

Keep this block before handleCumulativeAck(cum_ack) and SACK processing. Probe ACKs remain in the existing probe path and never acknowledge a data attempt.

- [ ] **Step 3: Preserve isolation and NACK compatibility**

Keep the isStrictLaps gate. Leave processNack's existing call site in place; Task 2 makes it exact-only. Do not edit queue code, trim flags, or non-LAPS multipath implementations.

- [ ] **Step 4: Verify source-level regressions**

Run:

~~~
cmake --build htsim/sim/build-laps -j2
ctest --test-dir htsim/sim/build-laps -L laps --output-on-failure
ctest --test-dir htsim/sim/build-laps -R '^(reps_slot_cache|prism_coordination|prism_.*|legacy_.*)$' --output-on-failure
~~~

Expected: LAPS and selected non-LAPS tests pass.

- [ ] **Step 5: Commit**

~~~
git add htsim/sim/uec.cpp htsim/sim/datacenter/add_motivation/common/tests/test_laps_packet_feedback.cpp
git commit -m "feat: drive strict LAPS recovery from ACK delay"
~~~

### Task 4: Review and verify before artifact replacement

**Files:**
- Inspect: htsim/sim/laps_recovery.h
- Inspect: htsim/sim/laps_recovery.cpp
- Inspect: htsim/sim/uec.cpp
- Inspect: htsim/sim/datacenter/add_motivation/common/tests/test_laps_recovery.cpp

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: review evidence that the feature is strict-LAPS-only and source verification completes before data replacement.

- [ ] **Step 1: Perform semantic review**

Run:

~~~
git diff HEAD~2..HEAD -- htsim/sim/laps_recovery.h htsim/sim/laps_recovery.cpp htsim/sim/uec.cpp
rg -n "acknowledge\(|nack\(|kBootstrapRto|isStrictLaps" \
  htsim/sim/laps_recovery.h htsim/sim/laps_recovery.cpp htsim/sim/uec.cpp
~~~

Accept only if the key includes owner and physical path; matched ACK alone infers earlier records; interval is exactly twice one-way delay; NACK/retire are exact; ACK wiring is strict-LAPS-gated.

- [ ] **Step 2: Run fresh verification**

Run:

~~~
cmake --build htsim/sim/build-laps -j2
ctest --test-dir htsim/sim/build-laps -L laps --output-on-failure
ctest --test-dir htsim/sim/build-laps -R '^(reps_slot_cache|prism_coordination|prism_.*|legacy_.*)$' --output-on-failure
python3 htsim/sim/datacenter/prism_eval/expA_delaydriven/make_figs.py --selftest
bash htsim/sim/datacenter/prism_eval/expA_delaydriven/repro_laps.sh --replace-laps --dry-run
~~~

Expected: build/tests/selftest pass; dry run prints exactly 35 LAPS commands with EXTRA_ARGS=-disable_trim and no other baseline.

- [ ] **Step 3: Commit only a corrective review fix if needed**

If and only if review identifies a source/test fault, add a focused test and minimal correction, re-run Step 2, then commit:

~~~
git add htsim/sim/laps_recovery.h htsim/sim/laps_recovery.cpp htsim/sim/uec.cpp \\
  htsim/sim/datacenter/add_motivation/common/tests/test_laps_recovery.cpp \\
  htsim/sim/datacenter/add_motivation/common/tests/test_laps_packet_feedback.cpp
git commit -m "fix: correct strict LAPS ACK recovery"
~~~

Otherwise create no empty review commit.

### Task 5: Replace LAPS-only ExpA artifacts and validate the 35-run result

**Files:**
- Generated, uncommitted: htsim/sim/datacenter/prism_eval/expA_delaydriven/data/expA_laps_f{0,2,4,6,8,10,12}_s{13,14,15,16,17}.flow.txt
- Generated, uncommitted: htsim/sim/datacenter/prism_eval/expA_delaydriven/figs/figA1dd_{avg_fct,goodput,p99_fct}_laps.pdf
- Generated, uncommitted: htsim/sim/datacenter/prism_eval/expA_delaydriven/figs/figA1dd_legend_laps.pdf

**Interfaces:**
- Consumes: passing Task 4 and existing repro_laps.sh replacement safeguards.
- Produces: 35 replacement LAPS logs and three overlays with LAPS purple and Prism green/last.

- [ ] **Step 1: Record integrity of the three original PDFs**

Run:

~~~
sha256sum \
  htsim/sim/datacenter/prism_eval/expA_delaydriven/figs/figA1dd_avg_fct.pdf \
  htsim/sim/datacenter/prism_eval/expA_delaydriven/figs/figA1dd_goodput.pdf \
  htsim/sim/datacenter/prism_eval/expA_delaydriven/figs/figA1dd_p99_fct.pdf
~~~

Expected: retain three hashes; originals must match afterward.

- [ ] **Step 2: Replace only stale LAPS data and run the 35 LAPS cases**

Run:

~~~
bash htsim/sim/datacenter/prism_eval/expA_delaydriven/repro_laps.sh --replace-laps
~~~

Expected: only expA_laps_f*_s* and _laps targets are removed/recreated; 7 failed-link settings × 5 seeds complete. No other baseline runs.

- [ ] **Step 3: Render only the overlays**

Run:

~~~
python3 htsim/sim/datacenter/prism_eval/expA_delaydriven/make_figs.py --with-laps
~~~

Expected: figA1dd_avg_fct_laps.pdf, figA1dd_goodput_laps.pdf, figA1dd_p99_fct_laps.pdf, and LAPS legend exist; originals are untouched.

- [ ] **Step 4: Validate artifacts and completion-aware metrics**

Report for every failure count: started flows, completed flows, completion rate, goodput, average FCT, and P99 FCT. Run:

~~~
find htsim/sim/datacenter/prism_eval/expA_delaydriven/data \
  -maxdepth 1 -name 'expA_laps_f*_s*.flow.txt' -type f | wc -l
sha256sum \
  htsim/sim/datacenter/prism_eval/expA_delaydriven/figs/figA1dd_avg_fct.pdf \
  htsim/sim/datacenter/prism_eval/expA_delaydriven/figs/figA1dd_goodput.pdf \
  htsim/sim/datacenter/prism_eval/expA_delaydriven/figs/figA1dd_p99_fct.pdf
ls -lh htsim/sim/datacenter/prism_eval/expA_delaydriven/figs/figA1dd_{avg_fct,goodput,p99_fct}_laps.pdf
~~~

Expected: 35 nonempty logs, unchanged original hashes, all three overlays, and completion rates reported alongside survivor-only FCT.

- [ ] **Step 5: Leave artifacts uncommitted**

Run git status --short and confirm only intended source/test commits are tracked. Do not add data, figures, stdout, idmaps, logs, or paper material.
