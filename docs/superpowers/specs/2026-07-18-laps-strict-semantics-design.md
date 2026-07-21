# Strict official LAPS semantics in HTSIM

## Status and purpose

This design supersedes the congestion-control and recovery portions of
`2026-07-18-laps-design.md`.  The earlier implementation is a LAPS-style HTSIM
adaptation and must not be described as a faithful LAPS baseline.

The new goal is to port the **control and loss-recovery semantics implemented
by the official LAPS NS-3 repository** (commit
`4a4be642f2866d8b340c9b1bbdd1707a372ae213`) into HTSIM.  It deliberately does
not reproduce the paper's topology, PFC configuration, traffic patterns, or
reported results.  HTSIM's existing ExpA workload and evaluation framework
remain unchanged.

The selected public interface remains:

```text
-sender_cc_algo laps -load_balancing_algo laps
```

LAPS is the only algorithm affected by this work.  OPS, REPS, Swift, MSwift,
MNSCC, STrack, and Prism retain their existing transport, routing,
retransmission, output, and command-line behavior.

## Official behavior being ported

The reference implementation uses `CC_LAPS` with its `NACK` reliability path.
The relevant source is:

- `rdma-hw.cc`: `UpdateRateForLaps`, `IncreaseRateForLaps`,
  `DecreaseRateForLaps`, and path-level outstanding-data/RTO handling;
- `rdma-queue-pair.h`: the `CcLaps` state;
- `rdma-smartflow-routing.cc`: Softmax weighting over candidate path latency.

For each flow, the official controller owns:

```text
curRate, tgtRate, incStage, tgtDelay, nextRateDecrease, nextRateIncrease
```

It starts at the NIC rate.  When every candidate path has latency strictly
greater than the target delay, it halves `curRate`, sets `tgtRate` to the
pre-decrease rate, clears `incStage`, and delays the next decrease by twice the
current maximum path delay.  Otherwise, after twice the target delay, it
increases rate toward `tgtRate`; after stage 5 it doubles `tgtRate` up to the
NIC rate.  The exact rate update is:

```text
curRate = min(nicRate, max(curRate + 1 Gbps, (curRate + tgtRate) / 2))
```

The official source's recovery domain is **per sending NIC and physical path**,
not per flow.  It keeps a shared, send-ordered outstanding list for each path
and a single 8 ms RTO.  An ACK for a later entry makes all preceding entries on
that path lost; those entries are queued for retransmission by their owning
flows.  A path RTO makes every outstanding entry on that path lost.

## HTSIM mapping and isolation

HTSIM exposes an ECMP entropy rather than the official globally allocated path
identifier.  The equivalent recovery key is therefore:

```text
(sending UecNIC instance, destination address, entropy)
```

The sending NIC scopes the recovery-domain object; destination plus entropy
prevents unrelated destinations from being conflated.  For HTSIM's deterministic
fat-tree ECMP forwarding this identifies the candidate end-to-end path class
selected by a LAPS flow.  The mapping is an adapter-boundary difference, not a
different recovery policy.

`UecNIC` will own an optional `LapsRecoveryDomain`.  The domain contains only
LAPS records:

```text
PathKey -> { ordered { UecSrc*, sequence, packet_size }, RTO event }
```

The domain is never created, registered, queried, or mutated for a non-LAPS
flow.  Its calls are guarded at the `UecSrc` LAPS dispatch boundary.  Existing
generic UEC SACK/NACK/RTO recovery continues to serve every other baseline.

For LAPS, data send appends a record to the domain.  A valid LAPS ACK removes
the acknowledged record and transfers each preceding record on its path to the
owning source's LAPS retransmission queue.  A nonempty list resets its 8 ms RTO;
an empty list cancels it.  On expiry, the domain transfers all remaining
records for that path to their owners.  These transfers bypass
`mark_packet_for_retransmission()`, so the old per-retransmission NSCC window
decrease is not applied to LAPS.

## Rate control, fixed window, and latency feedback

`UecSrc` receives a dedicated LAPS rate controller.  It replaces the current
LAPS-style `cwnd /= 2` and NSCC additive-increase branch; it does not alter
those branches for other algorithms.

The controller uses a LAPS-only pacer.  `curRate` determines the earliest time
at which that flow may emit its next packet.  Normal UEC NIC arbitration still
limits physical transmission.  A fixed in-flight safety window is set to:

```text
2 * targetDelay * nicRate / 8
```

matching the official fixed-window initialization.  It is not used as an
additive-increase or multiplicative-decrease variable.

The official simulator obtains candidate-path minimum delays from its static
path table.  HTSIM does not have that table.  Its faithful adapter is a
LAPS-only startup calibration: record the minimum valid one-way ACK/probe
latency for every configured candidate and set `targetDelay` to their maximum.
No all-path congestion decision may occur until that calibration is complete.
This preserves the official controller's unequal-cost-path comparison while
honestly documenting the one unavoidable HTSIM representation difference.

The existing LAPS one-way ACK feedback, packet spraying, and probe transport
remain LAPS-only.  Softmax uses the calibrated `targetDelay` as its denominator
and defaults to `beta = 1`, the official/paper default.  Legacy
`laps_queue_margin` is removed from strict-controller decisions.  Stale-path
probes refresh latency state but cannot invoke generic UEC recovery.

## Error handling and lifecycle

- Delayed, duplicate, or invalid LAPS ACKs must not remove a different
  outstanding entry.  The domain verifies owner, sequence, and packet size.
- Repeated loss signals must not enqueue the same source sequence twice.
- Completing/destroying a LAPS flow unregisters any of its remaining records
  and cancels an empty path RTO.
- A path-domain RTO with no records is a no-op; it never reaches a non-LAPS
  flow.
- The existing single-flow UEC RTO is disabled only for strict LAPS data
  records.  It remains available to every other transport and for unrelated
  control-packet paths.

## Validation

Tests are written before the corresponding production code and must include:

1. exact controller initialization, decrease, cooldown, increase, stage-5
   target doubling, 1 Gbps floor, and NIC-rate ceiling;
2. two LAPS flows sharing a path: a later ACK marks preceding shared entries
   lost and queues them on their correct owners;
3. path RTO at exactly 8 ms requeues all and only that path's records;
4. isolation: a non-LAPS source cannot enter, observe, or be recovered by a
   LAPS domain;
5. packet/ACK identity and duplicate-ACK safety;
6. full CMake/CTest LAPS suite, the LAPS CLI smoke test, and existing baseline
   regression coverage.

Only after these checks pass may ExpA be run.  `repro_laps.sh` continues to
execute only the 35 LAPS configurations.  Its explicit replacement step may
delete only former LAPS artifacts under:

```text
htsim/sim/datacenter/prism_eval/expA_delaydriven/data/expA_laps_*
htsim/sim/datacenter/prism_eval/expA_delaydriven/figs/*_laps.pdf
htsim/sim/datacenter/prism_eval/expA_delaydriven/figs/*_laps.png
```

It then regenerates the LAPS data and three `_laps` figures.  The original
seven-baseline figures must remain byte-identical.  The final figures are
labelled as the official-LAPS control/recovery semantics port in HTSIM, not as
a reproduction of the LAPS paper experiments.

## Expected implementation surface

- `htsim/sim/laps_recovery.{h,cpp}`: LAPS-only NIC-scoped recovery domain;
- `htsim/sim/uec.{h,cpp}`: LAPS registration, ACK/send dispatch, LAPS pacer,
  controller state, and lifecycle cleanup;
- `htsim/sim/uec_mp.{h,cpp}`: calibrated target-delay path state and official
  Softmax defaults;
- `htsim/sim/laps_cc.h`: replace old cwnd decision helper with testable
  official rate-controller helper, or remove it if superseded cleanly;
- `htsim/sim/datacenter/main_uec.cpp`: strict defaults and removal/rejection of
  obsolete controller flags;
- `htsim/sim/CMakeLists.txt` plus focused tests;
- `expA_delaydriven/repro_laps.sh` and plotting tests only as needed to make
  the deliberate LAPS-artifact replacement reproducible.
