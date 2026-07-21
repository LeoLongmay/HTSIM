# Strict LAPS Physical-Path Recovery Correction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make paired strict LAPS use a shared, canonical physical-path recovery
domain with attempt-safe ACK/NACK/RTO lifecycle handling, then regenerate only
the ExpA LAPS overlay artifacts.

**Architecture:** Extract the fat-tree's lazy FIB materialisation into one
shared routine so a LAPS-only resolver and packet forwarding select the same
ordered egress queues before the first send.  The recovery domain keys that
canonical queue fingerprint and returns a monotonically unique attempt handle
for each transmission.  UEC stores the handle in its live send record and
atomically retires/replaces it on every ACK, NACK, or timeout path.

**Tech Stack:** C++17 HTSIM event simulator; CMake/CTest; Bash/Python ExpA
reproduction contracts.

## Global Constraints

- Activate every new resolver, domain call, and pacing/recovery exception only
  for `sender=LAPS` paired with `mp=UecMpLaps`.
- Use the exact 8 ms LAPS per-physical-path timeout already defined by
  `LapsRecoveryDomain::kRto`.
- The physical key is an ordered complete queue sequence, never raw entropy,
  destination, or a logical path bucket.
- Do not change non-LAPS or unpaired-LAPS forwarding, ACK/NACK, congestion, or
  generated baseline data/figures.
- Do not run `--replace-laps` until all code and regression preflight steps
  pass.  Generated LAPS data/figures remain uncommitted.

---

### Task 1: Share FIB materialisation and resolve canonical LAPS physical paths

**Files:**
- Modify: `htsim/sim/datacenter/fat_tree_switch.h`
- Modify: `htsim/sim/datacenter/fat_tree_switch.cpp`
- Modify: `htsim/sim/datacenter/fat_tree_topology.h`
- Modify: `htsim/sim/datacenter/fat_tree_topology.cpp`
- Modify: `htsim/sim/datacenter/add_motivation/common/tests/test_laps_recovery.cpp`

**Interfaces:**
- Produces `FatTreeTopology::resolve_or_materialize_ecmp_path(src, dst, flow,
  entropy, queues)`, which returns the exact ordered forward queue sequence or
  `false` without changing a pre-existing FIB route-vector order.
- The switch exposes one shared `materializeRoutes(destination, flow_id)`
  helper; `getNextHop` and resolution both invoke it before the identical ECMP
  hash choice.

- [ ] **Step 1: Write failing route-identity tests**

  Add a test topology with four ECMP alternatives and two flows.  Choose two
  distinct full entropy values that resolve to the same ordered queue-name
  sequence, and two values sharing a logical low path bucket that resolve to
  different sequences.  Assert resolution succeeds before a data packet is
  forwarded, equal sequences serialize identically, and distinct sequences do
  not.

- [ ] **Step 2: Run the new resolver test and verify failure**

  Run:
  `cmake --build htsim/sim/build-laps --target test_laps_recovery && ctest --test-dir htsim/sim/build-laps -R '^laps_recovery$' --output-on-failure`

  Expected: FAIL because the current validation-only resolver returns false
  before a route has populated every FIB entry.

- [ ] **Step 3: Extract the exact shared route-materialisation path**

  Move the current missing-route branch from `FatTreeSwitch::getNextHop` into
  a helper that accepts `(destination, flow_id)` and creates exactly the same
  FIB entries/route ordering as today.  Have `getNextHop` call it when its
  route set is absent.  Add an oracle resolver that calls the same helper at
  each hop, then chooses `freeBSDHash(flow_id, entropy, hash_salt) % routes`
  exactly as forwarding does.  Retain the existing read-only resolver for
  motivation/PRISM callers; strict LAPS uses only the new materialising API.

- [ ] **Step 4: Run resolver and existing topology regressions**

  Run:
  `cmake --build htsim/sim/build-laps --target test_laps_recovery htsim_uec && ctest --test-dir htsim/sim/build-laps -R '^(laps_recovery|prism_coordination|legacy_reps_trace)$' --output-on-failure`

  Expected: PASS.  The new test proves the resolver's fingerprint equals the
  forwarding queue sequence for both flow/entropy examples.

- [ ] **Step 5: Commit**

  ```bash
  git add htsim/sim/datacenter/fat_tree_switch.h htsim/sim/datacenter/fat_tree_switch.cpp \
    htsim/sim/datacenter/fat_tree_topology.h htsim/sim/datacenter/fat_tree_topology.cpp \
    htsim/sim/datacenter/add_motivation/common/tests/test_laps_recovery.cpp
  git commit -m "feat: resolve strict LAPS physical paths"
  ```

### Task 2: Make the LAPS recovery domain attempt-safe

**Files:**
- Modify: `htsim/sim/laps_recovery.h`
- Modify: `htsim/sim/laps_recovery.cpp`
- Modify: `htsim/sim/datacenter/add_motivation/common/tests/test_laps_recovery.cpp`

**Interfaces:**
- Replaces `LapsPathKey{destination, entropy}` with an ordered queue-fingerprint
  key.
- `sent(path, owner, seq, bytes)` returns `LapsAttempt`.
- `acknowledge(attempt)`, `nack(attempt)`, and `retire(attempt)` detach the
  matching live attempt; timeout callbacks carry that exact attempt.
- `LapsRecoveryOwner::lapsRecover(attempt, seq, bytes)` acts only on the
  matching current attempt.

- [ ] **Step 1: Write failing lifecycle tests**

  Add tests that register two records on one canonical path and one on another:
  `acknowledge(second)` must detach/recover only preceding same-path records;
  `retire` must suppress all future timeout callbacks; `nack` must remove the
  named attempt before a same-sequence retry receives a new handle; and a
  callback for the old handle cannot affect that retry.

- [ ] **Step 2: Run the lifecycle tests and verify failure**

  Run:
  `cmake --build htsim/sim/build-laps --target test_laps_recovery && ctest --test-dir htsim/sim/build-laps -R '^laps_recovery$' --output-on-failure`

  Expected: FAIL because records are currently matched only by
  `(owner, seq, bytes)` and there is no retirement/NACK API.

- [ ] **Step 3: Implement opaque handles and atomic detach operations**

  Introduce a monotonic `uint64_t` attempt ID stored in every domain record.
  Locate a record by ID, detach it and any inferred preceding same-path loss
  batch before owner callbacks, and reschedule/cancel the single earliest
  timer.  `retire` removes only its named record with no callback.  `nack`
  removes its named record plus returns/recoveries preceding entries but never
  recovers the NACKed attempt itself.  Timeout first detaches full expired
  lists, then calls owners with each handle.

- [ ] **Step 4: Run domain suite**

  Run:
  `cmake --build htsim/sim/build-laps --target test_laps_recovery && ctest --test-dir htsim/sim/build-laps -R '^(laps_recovery|laps_packet_feedback)$' --output-on-failure`

  Expected: PASS, including repeated-timeout/re-registration coverage from the
  earlier strict integration work.

- [ ] **Step 5: Commit**

  ```bash
  git add htsim/sim/laps_recovery.h htsim/sim/laps_recovery.cpp \
    htsim/sim/datacenter/add_motivation/common/tests/test_laps_recovery.cpp
  git commit -m "fix: make strict LAPS recovery attempt-safe"
  ```

### Task 3: Wire paired UEC sends, ACKs, NACKs, and SACKs to the domain

**Files:**
- Modify: `htsim/sim/uec.h`
- Modify: `htsim/sim/uec.cpp`
- Modify: `htsim/sim/datacenter/main_uec.cpp`
- Modify: `htsim/sim/datacenter/add_motivation/common/tests/test_laps_uec_isolation.cpp`
- Modify: `htsim/sim/datacenter/add_motivation/common/tests/test_laps_packet_feedback.cpp`

**Interfaces:**
- `UecSrc::lapsSetPathResolver` stores a paired-LAPS-only resolver returning a
  canonical ordered queue fingerprint.
- Each strict data `sendRecord` stores `optional<LapsAttempt>`; control records
  never do.
- Main installs the resolver after the source has its flow ID and only for
  `isStrictLaps()`.

- [ ] **Step 1: Add failing UEC integration regressions**

  Cover all four state transitions with two strict sources sharing one NIC:

  1. distinct entropies resolving to one full route share one ordered domain;
  2. exact ACK then cumulative ACK/SACK across another path leaves no callback
     after `kRto`;
  3. strict NACK removes the old attempt before RTX, and old-path expiry does
     not remove the new-path attempt;
  4. a non-LAPS source sharing that NIC has identical tx/rtx/backlog/in-flight
     state before and after strict activity.

- [ ] **Step 2: Run integration tests and verify failure**

  Run:
  `cmake --build htsim/sim/build-laps --target test_laps_uec_isolation test_laps_packet_feedback htsim_uec && ctest --test-dir htsim/sim/build-laps -R '^(laps_uec_isolation|laps_packet_feedback)$' --output-on-failure`

  Expected: FAIL because ACK/NACK generic cleanup does not retire the current
  domain attempt and the current key is raw entropy.

- [ ] **Step 3: Install resolver and synchronize every record removal**

  Canonicalize the resolver's queue names with length-prefixing to preserve
  ordering and avoid delimiter ambiguity.  Resolve before strict `sent`; fail
  closed if resolution fails.  Store the returned attempt in the send record.
  Call `acknowledge` for the exact ACK before generic cleanup; immediately call
  `retire` before every strict data erase in cumulative ACK and SACK handling;
  call `nack` before strict NACK state erasure and RTX queueing.  Change
  `lapsRecover` to require handle equality before touching `_tx_bitmap`.
  Keep generic handling for unpaired LAPS and all non-LAPS sources byte-for-
  byte equivalent in behavior.

- [ ] **Step 4: Run integration and isolation tests**

  Run:
  `cmake --build htsim/sim/build-laps --target test_laps_uec_isolation test_laps_packet_feedback htsim_uec && ctest --test-dir htsim/sim/build-laps -R '^(laps_uec_isolation|laps_packet_feedback|laps_multipath|laps_cli|reps_slot_cache|prism_coordination|legacy_reps_trace)$' --output-on-failure`

  Expected: PASS.  No test creates a LAPS recovery domain for an unpaired or
  non-LAPS source.

- [ ] **Step 5: Commit**

  ```bash
  git add htsim/sim/uec.h htsim/sim/uec.cpp htsim/sim/datacenter/main_uec.cpp \
    htsim/sim/datacenter/add_motivation/common/tests/test_laps_uec_isolation.cpp \
    htsim/sim/datacenter/add_motivation/common/tests/test_laps_packet_feedback.cpp
  git commit -m "fix: synchronize strict LAPS outstanding attempts"
  ```

### Task 4: Restore fail-closed replacement ordering

**Files:**
- Modify: `htsim/sim/datacenter/prism_eval/expA_delaydriven/repro_laps.sh`
- Modify: `htsim/sim/datacenter/prism_eval/expA_delaydriven/tests/test_repro_laps.sh`

**Interfaces:**
- `--replace-laps` validates and backs up the shared idmap before deleting a
  single allowed LAPS output; its existing exact 35-tag/8-overlay allowlist is
  unchanged.

- [ ] **Step 1: Write failing invalid-idmap replacement test**

  Extend the fixture to create old LAPS artifacts plus a dangling symlink or
  non-regular shared idmap.  Invoke `--replace-laps`; assert failure occurs,
  every LAPS fixture remains byte-identical, and no stub simulation executes.

- [ ] **Step 2: Run the shell contract and verify failure**

  Run: `bash htsim/sim/datacenter/prism_eval/expA_delaydriven/tests/test_repro_laps.sh`

  Expected: FAIL because old LAPS files are currently deleted before idmap
  validation.

- [ ] **Step 3: Move only the guarded preparation before deletion**

  Run shared-idmap regular-file validation, backup creation, and trap setup
  before replacement deletion.  Retain the exact argument parser, tag loop,
  suffix allowlist, and final restore semantics unchanged.

- [ ] **Step 4: Run runner and plotting contracts**

  Run:
  `bash htsim/sim/datacenter/prism_eval/expA_delaydriven/tests/test_repro_laps.sh && python3 htsim/sim/datacenter/prism_eval/expA_delaydriven/tests/test_make_figs_laps.py`

  Expected: PASS, including pre-delete failure preservation, 35-run replacement,
  and original-figure/OPS preservation.

- [ ] **Step 5: Commit**

  ```bash
  git add htsim/sim/datacenter/prism_eval/expA_delaydriven/repro_laps.sh \
    htsim/sim/datacenter/prism_eval/expA_delaydriven/tests/test_repro_laps.sh
  git commit -m "fix: preflight LAPS artifact replacement"
  ```

### Task 5: Verify and regenerate the strict LAPS ExpA overlay

**Files:**
- Modify at runtime only: `htsim/sim/datacenter/prism_eval/expA_delaydriven/data/expA_laps_*`
- Modify at runtime only: `htsim/sim/datacenter/prism_eval/expA_delaydriven/figs/*_laps.{pdf,png}`

- [ ] **Step 1: Run full preflight before mutation**

  Run:
  ```bash
  cmake -S htsim/sim -B htsim/sim/build-laps -DENABLE_TESTS=ON
  cmake --build htsim/sim/build-laps -j2
  ctest --test-dir htsim/sim/build-laps -L laps --output-on-failure
  ctest --test-dir htsim/sim/build-laps -R '^(reps_slot_cache|prism_coordination|legacy_reps_trace)$' --output-on-failure
  ```

  Expected: all pass.  Record SHA-256 hashes of the three original PDFs under
  `/tmp` only after this preflight passes.

- [ ] **Step 2: Replace only strict LAPS artifacts and draw overlays**

  Run:
  ```bash
  bash htsim/sim/datacenter/prism_eval/expA_delaydriven/repro_laps.sh --replace-laps
  python3 htsim/sim/datacenter/prism_eval/expA_delaydriven/make_figs.py --with-laps
  ```

  Expected: exactly 35 nonempty `expA_laps_f*_s*.flow.txt` files; the three
  `_laps.pdf` figures contain LAPS before final green Prism in the legend.

- [ ] **Step 3: Verify artifact integrity and hygiene**

  Recompute the three original PDF hashes and compare with Step 1; run
  `make_figs.py --selftest`, `git diff --check`, `git diff --cached --check`,
  and `git status --short`.  Confirm no generated data/figures is staged.

- [ ] **Step 4: Final independent review**

  Generate a review package from `670bd8d` to HEAD.  Require an independent
  reviewer to inspect the corrected physical key, attempt lifecycle, all
  LAPS-only guards, runner preflight, and verification evidence.  Address any
  Critical or Important finding and repeat Steps 1–3 before handoff.
