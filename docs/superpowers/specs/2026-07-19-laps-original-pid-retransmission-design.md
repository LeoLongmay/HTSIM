# Strict-LAPS Original-PID Retransmission

## Purpose

Make one final, semantics-only correction to the strict-LAPS port: a
selectively retransmitted segment must use the same LAPS path identifier
(`pid`) as its original current attempt.  This is the paper's `ReTx(pid)`
operation.  It is not a congestion-control tuning attempt.

The current port correctly identifies same-owner, same-physical-path loss from
ACK ordering and uses a per-owner/path `2 * one_way_delay` tail deadline.
However, `UecSrc::sendRtxPacket` currently calls `nextEntropy`, which chooses
a fresh multipath candidate.  That changes the segment's `pid` and can place
the new attempt on a different physical path.  The paper's sender ring buffer
and its ordered-ACK loss inference instead require a retransmission to remain
on the path identified by the original `pid`.

## Paper-to-Port Mapping

In the paper, `pid` identifies the source-routed path used to index `rBuf`.
In this HTSIM port, the packet `path_id` / entropy recorded in the current
`sendRecord` is that routable `pid`.  It is the only durable token from which
the source can recreate the original candidate route.  `LapsPathKey` remains
an internal, plane-qualified fingerprint used to key recovery ownership; it
is not sufficient to construct a route by itself.

For strict-LAPS retransmission:

1. When strict recovery detaches the current `sendRecord`, preserve its
   `path_id`, selection metadata, and resolved physical key in a
   LAPS-only pending-retransmission record.  The ordinary retransmission
   queue intentionally stores only sequence number and bytes, so looking up
   `_tx_bitmap` later is not possible.
2. Reuse that preserved `path_id` as the retransmission entropy.  Do not call
   `UecMultipath::nextEntropy`, and do not consume or mutate the multipath
   chooser's selection state.
3. Re-resolve the supplied route with that retained entropy.  It must equal
   the preserved plane-qualified `LapsPathKey` from the original live
   attempt.  A
   mismatch is a strict-port invariant violation, not an opportunity to
   silently respray the retransmission.
4. Create the new send record and recovery attempt with that same `pid` and
   resolved path.  The attempt handle is new, as required for idempotent late
   feedback, but the LAPS path identity is unchanged.

Non-strict traffic retains its existing `nextEntropy` behavior exactly.

## Scope and Non-Goals

- Preserve ExpA invocation: `PATHS=8`, `END_MS=8`, and
  `EXTRA_ARGS=-disable_trim`.
- Preserve topology, offered load, queue configuration, failure matrix,
  figure schema, and every control/recovery path of OPS, REPS, Swift, MSwift,
  MNSCC, STrack, and Prism.
- Do not change LAPS `beta`, its safety window, pacing, probe cadence, or any
  congestion-control parameter.
- Do not enable trim, introduce receiver-gap NACKs, or change the paper
  evaluation workload in an attempt to improve the result.
- Do not retain the earlier adapted-LAPS data or figures.  Only a successful
  strict result may replace the existing untracked LAPS data and `_laps`
  overlay PDFs.

## Verification and Decision Gate

### Source-level regression

Add a deterministic strict-LAPS test seam or focused test that establishes:

1. strict recovery carries the original packet's `path_id`, selection
   metadata, and physical key into its LAPS-only pending-retransmission
   record;
2. a retransmission consumes that retained pid rather than making a new
   entropy selection, and its resolved physical key equals the preserved
   strict-LAPS attempt key;
3. non-strict retransmissions still request a fresh entropy; and
4. a stale/replaced send record cannot be used to route a retransmission.

Existing LAPS recovery, packet-feedback, and non-LAPS transport tests must
remain green.

### Two-point operational gate

Run only the unmodified ExpA LAPS command for `f=0, seed=13` and
`f=12, seed=13` first.  Record the existing per-run counters (`Rtx`, `Drops`,
`NACKs`, flow completion) and compare with the retained seven-baseline files.
The implementation is eligible for the full 35-run LAPS sweep only if both
runs complete all 320 flows and the prior retransmission/drop storm is
materially removed.  "Materially removed" means it is no longer of the same
order as the current strict-LAPS observation at f=12, seed=13 (`37,499` RTX
and `18,720` drops, versus roughly `2,300`--`2,900` RTX and
`1,100`--`1,500` drops for individual non-LAPS baselines).  This is a causal
gate, not a requirement to beat any baseline.

If the gate fails, report the implementation as semantically corrected but
unsuitable for this ExpA baseline comparison; do not run the remaining 33
cases, tune LAPS, or alter the figures.  If it passes, invoke
`repro_laps.sh --replace-laps`, verify the 35-run completion table, and
regenerate only:

- `figA1dd_avg_fct_laps.pdf`
- `figA1dd_goodput_laps.pdf`
- `figA1dd_p99_fct_laps.pdf`

The original three seven-algorithm PDFs remain byte-for-byte untouched.

## Expected Interpretation

This change tests a concrete paper invariant, so a failed gate is useful
evidence: the remaining difference is not explained by resprayed recovery.
It would still not prove LAPS is intrinsically poor, because ExpA is a
synchronized incast/failure stress workload with trimming disabled, whereas
the paper evaluates its own lossless/PFC environment.  It does, however,
provide a sound basis for deciding not to present LAPS as a baseline in this
specific experiment.
