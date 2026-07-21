# HTSIM-localized LAPS design

## Purpose

Make `laps` a stable, reproducible HTSIM baseline rather than a claim of a
bit-for-bit reproduction of the LAPS paper.  The baseline keeps LAPS's
latency-aware path selection but uses the simulator's established UEC
reliability mechanisms.  This change is scoped to LAPS; OPS, REPS, Prism, and
the other baselines retain their existing behavior.

The current strict port combines three mechanisms that do not compose well in
the HTSIM model: per-PID PIT recovery, a `2 * realVal` timeout, and replaying a
retransmission on its original PID.  In the `f8/s13` lossless diagnostic this
created 56,045 timeout retransmission records for a 64-flow workload.  The
localized implementation must remove that recovery storm without presenting
incomplete-flow metrics as valid results.

## Algorithm contract

`laps` keeps the following LAPS-specific behavior:

- `UecMpLaps` selects data paths with a numerically stable Softmax over each
  PID's `realVal`.
- A stale PID is excluded from normal spraying while an active probe is
  outstanding.  Its probe ACK refreshes the PID delay state.
- Normal data packets carry a stable PID, and their ACKs use the reverse route
  of that packet's catalogued data path.  The delay sample therefore remains
  associated with a concrete forward/reverse path pair.
- ACK-derived delay samples update the LAPS PID state; degraded paths acquire
  less probability naturally through their larger `realVal`.

`laps` replaces the following strict-port behavior with normal HTSIM/UEC
behavior:

- It does not create, acknowledge, retire, or time out LAPS PIT attempts.
- It does not schedule per-PID `2 * realVal` recovery or ACK-gap batch
  recovery.
- NACKs, RTOs, congestion-window updates, and retransmission bookkeeping use
  the established UEC/NSCC code path.
- A retransmission is not pinned to the old PID.  It invokes the current LAPS
  path selector, which may choose a different healthy PID.
- LAPS uses the standard NSCC ACK/NACK congestion-window updates instead of
  freezing its window.

This is explicitly an HTSIM-localized LAPS baseline, not a strict paper
reproduction.  The experiment documentation and emitted diagnostics will use
that wording.

## Boundaries and invariants

- The `laps` command-line algorithm name directly selects the localized
  implementation.  No separate public strict-LAPS baseline is retained.
- LAPS-specific catalog and reverse-ACK routing remain isolated behind the
  LAPS predicate.  Non-LAPS packets neither carry nor consume LAPS routing
  metadata.
- Existing lossless/PFC queue settings remain unchanged.  This work does not
  change topology failure semantics: ExpL's `-failed` setting denotes reduced
  link capacity, not a hard link failure, so it must not grant LAPS an oracle
  that invalidates these still-usable paths.
- The prior strict recovery machinery may be removed or left unreachable only
  when tests demonstrate that it is not selected by `laps`; the implementation
  must not leave an alternative runtime route to it.

## Validation

1. Unit and route-audit tests prove that LAPS Softmax favors low-delay PIDs,
   stale PIDs are not normally selected, and ACK node/queue sequences are the
   exact reverse of the corresponding data sequence.
2. A targeted NACK and RTO test proves an LAPS retransmission is selected by
   the current LAPS chooser rather than replayed on its original PID.
3. Existing UEC-isolation tests prove OPS, REPS, and Prism do not enter LAPS
   routing or recovery paths.
4. The lossless `f8/s13` diagnostic is run before any broad scan.  It must
   complete all 64 flows, report no lossless/shared-buffer error, and show a
   material reduction from the strict port's 56,045 timeout retransmission
   records.  Completion and error-free execution are hard requirements; the
   timeout-count comparison is diagnostic evidence rather than a tuned target.
5. ExpL's runner and figure builder reject any algorithm/failure/seed cell
   whose completion rate is not exactly `1.0`.  Aggregate FCT and goodput
   figures are generated only after every required cell passes this gate.
6. The runner exposes the simulation end time and defaults it to the value
   established by the diagnostic.  Result metadata records that value.

## Non-goals

- Reproducing the LAPS paper's Rail/Dragonfly topology, traffic traces, or
  strict controller/recovery implementation.
- Re-running other algorithms while first validating the localized LAPS
  diagnostic.
- Altering ExpA's `-disable_trim` environment or overwriting its figures.
- Optimizing LAPS toward a target ranking.  The acceptance criteria measure
  semantic safety and complete, unbiased reporting rather than a desired FCT
  or goodput outcome.
