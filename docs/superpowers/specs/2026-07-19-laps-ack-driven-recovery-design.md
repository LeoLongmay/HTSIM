# Strict-LAPS ACK-Driven Loss Recovery

## Purpose

Make strict-LAPS loss recovery follow the LAPS paper while preserving the
ExpA experiment configuration.  In particular, `-disable_trim` remains in
effect and the seven existing baselines retain their current packet, queue,
trim, and recovery behavior.

The previous strict-LAPS results are not a valid LAPS baseline.  They use a
fixed 8 ms recovery deadline and depend on trim-derived UEC NACKs that do not
exist when trimming is disabled.

## Paper Semantics Adopted

LAPS distinguishes loss from ordinary multipath reordering at the sender.
Packets sent by one flow on the same physical path are ordered unless one is
lost.  Therefore, when an ACK for a current attempt arrives, every earlier,
still-unacknowledged attempt from the *same flow* on the *same physical path*
is inferred lost and is selectively retransmitted immediately.

Tail loss has no later ACK to expose it.  For each flow/path pair, a timer is
therefore armed and refreshed from the latest valid one-way latency sample.
Its deadline is two times that sample.  Expiry selectively retransmits all
outstanding attempts for that pair.

Normal delivery across different paths is allowed to reorder.  An ACK on one
path must never infer loss of data from another path.

## Scope and Isolation

Only `UecSrc::isStrictLaps()` traffic participates.  Existing `UECNACK`
handling continues to work for compatibility but strict-LAPS correctness must
not require an arriving NACK.  `CompositeQueue`, trimming policy, and the
control paths of OPS, REPS, Swift, MSwift, MNSCC, STrack, and Prism are not
changed.

The state remains owned by the source NIC's LAPS recovery facility, but its
logical key is:

```
(physical LapsPathKey, UecSrc owner)
```

The physical key is the already-established, plane-qualified forwarding queue
fingerprint.  Owner isolation is essential: different flows sharing a
physical path must neither acknowledge nor declare loss for each other.

## Components and Data Flow

1. Sending a strict-LAPS data attempt registers its immutable attempt handle,
   sequence number, bytes, owner, and physical path in the recovery domain.
   It belongs to that owner/path's ordered outstanding list.
2. A valid data ACK locates the acknowledged attempt before ordinary ACK/SACK
   retirement.  It supplies the latest one-way LAPS delay when available.
3. The recovery domain retires the acknowledged attempt.  Only earlier
   outstanding attempts in the same owner/path list are detached and reported
   through the existing `LapsRecoveryOwner::lapsRecover` callback.
4. The source validates that each callback still refers to its current
   attempt before removing the send record and queueing the retransmission.
   A retransmission is a new attempt and re-registers under its newly selected
   physical path.
5. The valid ACK delay refreshes the owner/path tail timer to
   `now + 2 * one_way_delay`.  Expiry removes only that owner/path's live
   records, then calls recovery for each detached record.

The startup period may not yet have a valid one-way sample.  It uses a named,
bounded conservative fallback deadline solely until a valid ACK or probe
sample exists for that owner/path.  The implementation will document the
chosen value and test that the first valid sample replaces it.  It must not
silently retain the old fixed 8 ms policy as normal operation.

## Ordering and Late Feedback Rules

- ACK inference uses the sender's current-attempt record, not the ACK packet's
  entropy field, because the attempt owns the canonical physical path.
- An ACK/timeout/NACK that refers to a detached or superseded attempt is a
  harmless no-op.
- Cumulative ACK and SACK retirement remove only their matching live attempt;
  they do not infer loss.
- A legacy UEC NACK may retire its exact current strict-LAPS attempt and queue
  recovery, but it must not infer loss across owner or path boundaries.
- Domain state is updated and timers re-armed before recovery callbacks run,
  preventing callbacks from observing stale records or cancelling newly
  registered attempts.

## Verification

Focused C++ tests must demonstrate:

1. an ACK for a later same-owner/same-path attempt recovers each earlier
   outstanding attempt immediately;
2. the same ACK never recovers another owner's record on the shared path;
3. an ACK for a different physical path never recovers a record on this path;
4. a valid delay sample produces a `2 * delay` tail deadline and the expiry
   recovers only that owner/path;
5. late ACK, NACK, and timeout events are idempotent;
6. non-strict-LAPS transport tests remain unchanged.

End-to-end validation must use `repro_laps.sh --replace-laps` unchanged with
`PATHS=8`, `END_MS=8`, and `EXTRA_ARGS=-disable_trim`, then regenerate only
the three `_laps` overlays.  The run must provide completion-rate evidence in
addition to FCT, P99 FCT, and goodput; a low conditional FCT alone is not an
acceptable result.

## Non-Goals

- Enabling trim globally or changing the seven baseline runs.
- Reproducing the paper's topology/workload suite.
- Adding a receiver-gap NACK rule; it treats ordinary multipath reordering as
  loss and contradicts the selected LAPS recovery semantics.
- Preserving the current adaptation-version LAPS artifacts or treating them as
  experimental results.
