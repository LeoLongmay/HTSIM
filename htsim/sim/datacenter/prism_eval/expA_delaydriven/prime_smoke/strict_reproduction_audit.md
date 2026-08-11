# PRIME strict reproduction evidence matrix

This is a paper-to-code audit, not a claim that the fixed ExpA smoke reproduces
the paper's performance results. It distinguishes stated paper behavior from
repository behavior and keeps the two evidence scopes separate.

| topic | paper evidence | repository evidence | test/trace | verdict | scope boundary |
| --- | --- | --- | --- | --- |
| Penalty values and decay | `Prime.md:88-90,100` requires distinct ECN/NACK penalties and decay, and states `P_NACK >> P_ECN`. It provides no numeric values. | `uec_mp.cpp:111-117,128-131,168` decays all tier entries after every selection, writes ECN only when zero, and writes NACK/timeout at the configured NACK penalty. | `prime_controller`; diagnostic `penalty_before`/`penalty_after` | aligned | Numeric values and the exact decay quantum are unspecified by paper, so this audit does not assert them. |
| Feedback identity and semantics — ACK ECN | `Prime.md:88,100` says the receiver copies EV into ACK and ACK+ECN updates that EV. | `uec.cpp:1972-1975` feeds `pkt.ev()` as `PATH_ECN` or good; `uec.cpp:3672-3711` forwards and records the selected tuple. | `run.prime.tsv` feedback rows | aligned | Source-level attribution is to the packet EV/tuple; this is not switch-local congestion localization. |
| Feedback identity and semantics — NACK | `Prime.md:78,88,100` says loss/trim lead to a NACK carrying the EV and applying the severe penalty. | `uec.cpp:3419-3424` maps a non-last-hop NACK to `PATH_NACK`; `uec_mp.cpp:125-132` applies its configured NACK penalty to the tuple parts. | `prime_controller`; `run.prime.tsv` NACK feedback | aligned | This checks the sender-side mapping, not the switch implementation assumed by the paper. |
| Feedback identity and semantics — timeout | The described host procedure names ACK and NACK (`Prime.md:88,100`), not timeout. | `uec.cpp:4492-4496,4683-4686` maps recovery timeout to `PATH_TIMEOUT`; `uec_mp.cpp:130-131` treats it as the configured NACK penalty. | recovery trace / `run.prime.tsv` | unspecified by paper | Timeout is a repository recovery signal, not automatically a paper NACK. |
| ACK coalescing | `Prime.md:88` describes an ACK carrying the packet EV; it does not specify ACK coalescing or delayed-ACK attribution. | `uec.cpp:1972-1975` consumes the EV and ECN bit exposed by each processed ACK. | ACK event trace | unspecified by paper | The audit does not infer one feedback item per original data packet from this path. |
| Congestion-history granularity | `Prime.md:90,100` requires every EV part of an MP-EV to be clear before selection. | `uec_mp.cpp:102-108,125-132` sums and updates penalty per tuple tier/port, not as a single opaque path value. | `prime_controller`; slash-separated tuple-tier diagnostics | aligned | This is host-only whole-path tuple mapping, not per-hop measurement or localization. |
| Candidate fallback | `Prime.md:90` says choose the EV with smallest penalty if all paths are congested. | `uec_mp.cpp:146-166` scans candidates, selects a clear one if available, otherwise retains the lowest-penalty candidate. | `prime_controller` | aligned | Candidate order/tie behavior is not specified by paper. |
| ExpA failure semantics | `Prime.md:77-78` discusses ECN and loss/trim; it does not define this simulator's ExpA fault model. | `repro.sh:50-53` and `validate_paths16.sh:35` run with `-disable_trim`; `uec.cpp:3419-3424` identifies non-last-hop NACK feedback. | ExpA `run.prime.tsv`, `summary.tsv` | unspecified by paper | `-disable_trim` means the ExpA runs must not be represented as a trimmed-packet reproduction. |
| PATHS=16 topology coverage | `Prime.md:88-90` gives no fixed simulator path-count experiment. | `validate_paths16.sh:35,52-54` runs `PATHS=16` and rejects incomplete 4-by-4 tuple coverage. | `validation.txt` | unspecified by paper | It is topology coverage only, separate from the fixed `PATHS=8` smoke matrix and not a paper-performance result. |

## Reproduction containment

All PRIME build products, logs, and generated data must remain below this
`prime_smoke` directory. `/tmp` must not be used for any PRIME build, trace,
or result. The repository-contained CMake tree for this audit is
`build/strict_reproduction`; generated build output is ignored by `.gitignore`.

## Task 2 controller and feedback-fixture evidence

`test_prime_controller` exercises the real `UecMpPrime` catalog controller.
Its assertions prove that ECN sets each previously clear component of the
resolved two-tier tuple to 1, while NACK overwrites those same components to
4. `clear_selection_skips_a_penalized_tuple` proves a tuple with any non-zero
component is not selected when a complete clear tuple remains. When every
candidate has a non-zero component, `all_penalized_selection_uses_the_minimum_penalty_tuple`
checks the hand-derived minimum summed penalty. Finally,
`one_selection_decrements_every_nonzero_penalty_component_once` compares the
full pre-/post-selection matrix and requires exactly one decrement for every
non-zero entry.

This audit began in a shared, already-dirty worktree that contained
pre-existing PRIME controller and transport edits. Task 2 adds no patch to
`uec_mp.cpp`, `uec_mp.h`, `uec.cpp`, or `uec.h` relative to that baseline; it
does **not** establish that the repository as a whole has no controller
changes.

`test_prime_packet_feedback` uses one real `UecSrc -> UecSink -> UecSrc`
delivery for each feedback class. Its forward and reverse pipes retain the
data entropy and the derived feedback object's `ev()`. For both one ECN ACK
and one trimmed NACK it requires `feedback.ev() == data_entropy`, then checks
that only the resolved tuple's tier-port components change (to 1 for ECN and
4 for NACK). This corresponds to the sender calls at `uec.cpp:1973-1975`
(ACK) and `uec.cpp:3419-3424` (NACK); the controller mapping is
`uec_mp.cpp:119-132`.

The fixture also drives two ordinary, different-EV packets through
`UecSink::processData()` with `_bytes_unacked_threshold = 3000`. The first
packet leaves `shouldSack()` false and produces no feedback; the second crosses
the threshold, resets the sink's accepted-byte counter, and produces exactly
one ACK. The returned ACK's `ev()` equals the second, threshold-crossing
packet's EV and differs from the first's. Coalescing verdict: **concrete
observed mapping** — a threshold ACK is attributed to the packet that causes
the threshold crossing; the earlier packet's EV is not represented by that
single ACK. This is the bounded simulator behavior observed by the fixture,
not a generic claim about all delayed-ACK implementations. Timeout remains a
distinct repository recovery input (`PATH_TIMEOUT`), even though the current
controller assigns it the configured NACK penalty; it is not presented as the
paper's trim/loss NACK.

Round-2 fresh direct-build evidence is recorded in the ignored build artifact
`build/strict_reproduction/task2-round2-command-evidence.log`: both focused
test sources compiled and both executables exited 0 with `TMPDIR`, `TMP`, and
`TEMP` explicitly set to `build/strict_reproduction/toolchain-tmp`.

## Task 3 strict ExpA failure/coalescing reproduction

`strict_reproduction/repro.sh --out <below-prime_smoke>` is intentionally a
two-run, observation-only audit rather than a performance sweep. It rejects
an output path outside `prime_smoke` before configuring or running anything.
The runner builds only into `build/strict_reproduction`, directs `TMPDIR`,
`TMP`, and `TEMP` to `build/strict_reproduction/toolchain-tmp`, and leaves raw
runs below the requested output directory. It fixes the exact simulator
inputs to `-paths 16`, `-failed {0,8}`, `-seed 13`, `-end 8`, and
`-disable_trim`, with `UEC_DELIVERY_SUMMARY=1` and a per-run `PRIME_DIAG`.

The companion `strict_reproduction/analyze.py` accepts only diagnostics with
the exact ten-column PRIME schema and `event_seq` contiguous from 1. It counts
emitted `ecn`, `nack`, and `timeout` feedback classes separately and records
the fixed flags from `run_manifest.tsv`. The manifest must contain exactly one
`f0` and one `f8` trace, each at seed 13 and named
`prime_strict_f{failed}_s13/run.prime.tsv`. Its sole generated artifact is
`archive_data/prime_strict_reproduction_audit.tsv`. In particular, a timeout
count is never merged into, or described as, a paper NACK count: timeout is a
distinct repository recovery signal, as established above. The bounded run
can therefore audit this implementation's failure and ACK-coalescing-facing
feedback surface, but does not claim paper-level loss/trim or delayed-ACK
equivalence.

Each strict simulator invocation uses its own contained run directory as the
working directory, with absolute topology and traffic-matrix inputs. This
keeps `Logged::dump_idmap`'s `idmap.txt` local to that run and avoids changing
the source `datacenter/idmap.txt`.

### Fixed-run observation (seed 13)

The strict runner completed its two fixed `PATHS=16` cells and the analyzer
validated every trace row before writing the archive TSV. `failed=0` produced
57052 diagnostic rows: 15851 ECN, 0 NACK, and 7 timeout feedback events.
`failed=8` produced 62580 rows: 14445 ECN, 0 NACK, and 2995 timeout feedback
events.

Both cells ran with `-disable_trim`; accordingly the observed NACK count is
zero. The `failed=8` cell's 2995 timeout records remain timeout records in
the archive, not proxy NACKs. These are implementation observations under the
fixed ExpA model, not a paper loss/trim count or a claim of equivalent ACK
coalescing behavior.

## Terminal decision

**Terminal decision: paper underspecified/no strict-controller change.**

The paper provides no numeric P for the distinct ECN/NACK penalties (or an
exact decay quantum). The fixed `-disable_trim`, `PATHS=16`, `failed=8` ExpA
observation contains **0 NACK** and **2995 timeout** events; the paper defines
NACK/trim feedback, not this repository timeout signal. Timeout therefore
cannot be promoted into a paper NACK to derive a missing controller value.

The audited core behavior is already supported by the bounded controller and
packet-fixture evidence: EV-based tuple feedback, decay, MP-EV clear-first
selection with minimum-penalty fallback, and the observed threshold-ACK
coalescing attribution. This is an implementation-semantics audit only and
does not claim performance reproduction. Accordingly, no strict-controller
change is justified or proposed by this audit.
