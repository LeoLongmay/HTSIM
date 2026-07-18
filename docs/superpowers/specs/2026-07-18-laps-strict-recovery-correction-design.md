# Strict LAPS physical-path recovery correction

## Purpose

Correct the strict-LAPS HTSIM port so that its shared recovery domain has the
same ownership and outstanding-data lifecycle required by the official NS-3
implementation.  This supersedes only the earlier use of
`(sending NIC, destination, entropy)` as a path key; all other strict-LAPS
control, calibration, pacing, and ExpA requirements remain in force.

## Scope and isolation

The correction is active only when `sender=LAPS` and `mp=UecMpLaps` are paired.
It must not install route resolution, recovery state, handlers, pacing
exemptions, or changed ACK/NACK behavior for any other algorithm or an
unpaired LAPS source.

No LAPS-paper topology or workload reproduction is added.  The final ExpA
outputs are labelled as an official-control/recovery-semantics port in HTSIM.

## Canonical physical-path identity

Before a paired strict-LAPS packet is registered as outstanding, the source
resolves the packet's full deterministic ECMP route using the same FIB choice
and hash inputs as data-plane forwarding.  Its recovery key is the immutable,
ordered sequence of physical egress queues (including plane and bundle
identity), scoped by the sending NIC.  It is not a destination address,
logical path bucket, low entropy bits, or raw entropy.

The resolver is LAPS-only and must be ready before the first LAPS data send;
it may prepopulate relevant FIB state without changing vector order after
forwarding starts, or share the forwarding's deterministic choice routine.
Failure to resolve is fail-closed for paired strict LAPS rather than silently
falling back to the former entropy key.

## Outstanding attempt lifecycle

Each `sent(PhysicalPathId, owner, seq, bytes)` operation appends one ordered
domain entry and returns an opaque attempt handle.  The owning `sendRecord`
stores that handle.  A callback may change a live UEC send record only when
the handle still matches; `(owner, seq, bytes)` alone is not enough.

The paired strict-LAPS domain provides these atomic operations:

- `acknowledge(attempt)`: remove the named attempt and detach all preceding
  entries on that exact physical path as inferred loss.
- `nack(attempt)`: remove the named attempt and detach preceding same-path
  entries as inferred loss; the named packet is subsequently retransmitted
  exactly once by the normal strict NACK path.
- `retire(attempt)`: remove an ACKed, cumulatively ACKed, or SACKed attempt
  without loss inference.
- `timeout(PhysicalPathId)`: detach the entire expired list before invoking
  owners; callbacks for stale handles are no-ops.

Ordering is binding:

1. Exact ACK calls `acknowledge` before generic ACK cleanup.
2. Every generic cumulative-ACK and SACK record removal calls `retire` first.
3. Strict NACK calls `nack` before generic state erasure or retransmission can
   register a new attempt.
4. Timeout callbacks validate their attempt handle before modifying
   `_tx_bitmap` or queueing RTX.

This retains the official later-control-packet inference for preceding
entries on one physical path but prevents stale entries from acting on a later
retransmission or an already ACKed packet.

## Runner fail-closed order

`repro_laps.sh --replace-laps` validates and backs up the shared idmap before
deleting any old LAPS-only artifact.  The existing exact 35-tag / eight-overlay
deletion allowlist remains unchanged.

## Required regressions

Tests must demonstrate all of the following before data replacement:

1. Two paired LAPS flows with different entropy prefixes sharing one resolved
   full route enter one ordered recovery list; same logical bucket but a
   different full route enters a different list.
2. Cumulative ACK and SACK retirement leave no strict-domain callback after
   advancing past 8 ms.
3. NACK, immediate retransmission on another path, and expiry of the old path
   do not recover or remove the new attempt.
4. An RTO callback for a stale attempt handle cannot affect a newer attempt.
5. A non-LAPS source sharing the NIC remains unchanged.
6. Invalid shared idmap rejects replacement before deleting LAPS artifacts.

After the full LAPS and baseline regression suites pass, stale LAPS ExpA data
and `_laps` figures are explicitly replaced, the three original figures are
hash-unchanged, and exactly 35 nonempty LAPS flow files and three principal
overlay PDFs are present.
