# LAPS baseline design

## Scope

Integrate LAPS (Latency Aware Packet Spraying) into the existing UEC-based
datacenter simulator.  LAPS is a joint sender congestion-control and multipath
selection baseline; it must use the same topology, connection matrix, UEC NIC,
reliability machinery, and workload runners as Prism, REPS, STrack, and MSwift.

The baseline is selected only through the existing two-axis interface:

```text
-sender_cc_algo laps -load_balancing_algo laps
```

There is no new `main`, topology, experiment pipeline, source-routing layer, or
replacement reliability implementation.  This design intentionally does not
reproduce the FPGA/SmartNIC implementation, source-route headers, PFC behavior,
or all paper experiments.

## Existing integration boundary

`main_uec.cpp` parses the sender CC and load-balancing tokens and constructs one
`UecSrc`, `UecSink`, and `UecMultipath` object per flow.  `UecSrc` owns the
send records, ACK/SACK/NACK handling, RTO, retransmission queue, and sender CC
dispatch.  A `UecMultipath` supplies an entropy to every new or retransmitted
packet.  Fat-tree ECMP uses that entropy as part of the forwarding hash.

LAPS therefore represents each candidate entropy as its candidate path.  This
matches the simulator's existing packet-spraying abstraction; it does not claim
that distinct entropy values always resolve to distinct physical paths.

## Components and interfaces

### `UecMpLaps`

Add `UecMpLaps : UecMultipath` in `uec_mp.h/.cpp`.  It is responsible only for
path state, feedback ingestion, packet spraying, and probe selection.

Each candidate entropy has the following state:

```text
entropy, valid, sampled, base_latency, real_latency,
last_update, last_probe
```

- `base_latency` is the minimum one-way latency observed for that entropy.
- `real_latency` is the most recent one-way latency sample.
- `sampled` distinguishes a learned baseline from bootstrap state.
- `valid` allows a future link/path failure signal to exclude a candidate; all
  configured entropies initially remain valid.

The base `UecMultipath` interface gains default no-op LAPS feedback hooks so
existing implementations are behaviorally unchanged:

- record a valid data-ACK latency sample;
- record probe transmission and process a probe ACK;
- select an entropy for a probe; and
- expose a read-only LAPS latency summary to the sender controller.

The LAPS summary includes the number of valid/sampled paths, the global
threshold `T`, whether every valid sampled path exceeds `T`, and the latest
maximum latency.  It does not expose mutable path internals to `UecSrc`.

### Latency-aware spraying

Before every entropy choice, `UecMpLaps` checks stale entries.  A sampled path
is stale when:

```text
now - last_update > 2 * real_latency
```

Unsampled paths are selected round-robin during bootstrap so every candidate
can gain an initial sample.  After bootstrap, valid, fresh paths use a
numerically stable Softmax distribution:

```text
w_i = exp(-beta * (real_latency_i - min_latency) / max(T, 1))
P_i = w_i / sum(w_j)
```

Subtracting the minimum latency is the stable form of the paper's Softmax and
does not alter relative probabilities.  `beta=0` is uniform spraying.  A stale
path is temporarily penalized by doubling its current latency estimate when a
probe is issued, preventing immediate repeated selection/probing.  If no fresh
sample is usable, selection falls back to round-robin valid entropies.

The default `beta` and path freshness behavior are configurable LAPS-specific
parameters.  Their values are kept independent of Prism settings.

### UEC packet and ACK metadata

LAPS needs one-way latency, not ACK round-trip time.  `UecDataPacket` gains
optional LAPS send-time metadata.  When LAPS sends a data packet or probe it
sets this timestamp.  `UecSink` calculates the one-way delay upon reception and
places it, together with the existing path ID, in optional `UecAckPacket` LAPS
metadata.  The probe type already exists in UEC and is preserved in the ACK.

`UecSrc::processAck` consumes the metadata only for LAPS and only if the data
ACK maps to a valid current send attempt.  Probe ACKs update the matching path
state through the LAPS hook.  This protects state from delayed acknowledgments
of superseded retransmissions.

All legacy packet creation and ACK handling leave the optional metadata unused.

### Active probing

`UecSrc` adds a LAPS-only probe timer while an unfinished LAPS flow is active.
On a tick it asks `UecMpLaps` for one stale candidate and sends the existing
`DATA_PROBE` packet through that entropy.  `UecSink` returns the existing probe
ACK augmented with its one-way latency sample.  One probe is sent per tick; a
successful probe restores the path's current latency and freshness.

The timer is separate from SLEEK probing and the RTO timer.  It neither changes
the data sequence space nor participates in the retransmission queue.

### LAPS congestion control in UEC

Add `LAPS` to `UecSrc::Sender_CC`, select it from `main_uec.cpp`, and dispatch
to `updateCwndOnAck_LAPS`.  UEC is cwnd-based whereas paper LAPS regulates a
NIC rate limiter, so the following faithful cwnd-domain translation is used:

1. From the multipath summary, compute `T = max(base_latency)` over valid,
   sampled candidates, plus the configured LAPS queueing margin.  This allows
   unequal unloaded path costs without treating a long path as congested.
2. If every valid sampled path has `real_latency > T`, halve the cwnd (bounded
   by UEC's minimum cwnd) at most once per `2 * max(real_latency)`.
3. Otherwise, do not reduce cwnd.  At a `2 * T`-gated increase opportunity,
   additively increase cwnd using UEC's established byte/cwnd arithmetic.
4. Before all candidates have baseline samples, bootstrap safely with additive
   increase but never classify the flow as all-path congested.

Thus, a single slow path changes Softmax weights but does not cause a global
window cut.  ECN and NACK remain reliability/path-health feedback; they are not
LAPS's delay congestion trigger.  Existing UEC trimming, SACK, cumulative ACK,
NACK, timeout, and retransmission logic remains the source of truth.

## Configuration and validation

`main_uec.cpp` accepts `laps` in both existing token parsers and creates
`UecMpLaps` in the normal and LogSim multipath factories.  It rejects either
half-configuration:

```text
-sender_cc_algo laps requires -load_balancing_algo laps
-load_balancing_algo laps requires -sender_cc_algo laps
```

LAPS-specific flags expose the Softmax beta, probe interval, and queueing
margin.  Defaults are documented next to the static UEC settings.  Existing
shared runners only need their CC/LB allow-lists expanded to pass `laps`; no
new shell pipeline or experiment entry point is created.

## Reliability and error handling

- Invalid/stale ACK timestamps do not alter LAPS path state.
- Delayed ACKs for retransmitted data use existing send-attempt validation.
- A path that stops returning probes is progressively penalized and does not
  permanently block the flow; UEC's existing RTO/retransmission remains active.
- Empty or unsampled path state falls back to valid round-robin spraying rather
  than dividing by zero or concentrating traffic on an arbitrary path.
- A zero/overflow Softmax normalization falls back deterministically to
  round-robin selection.

## Verification

Add focused unit coverage for pure LAPS state/control behavior and a CLI smoke
test through `htsim_uec`:

1. no feedback: bootstrap uses all valid candidates;
2. two paths with different samples: low-latency path receives a larger
   long-run share;
3. ACK feedback updates path ID and one-way latency correctly;
4. one slow path changes spraying but holds cwnd;
5. all paths slow triggers one gated multiplicative decrease;
6. a stale path is probed and is selectable again after a low-latency probe ACK;
7. an existing Prism, REPS, STrack, and MSwift smoke invocation still compiles
   and runs without selecting LAPS behavior.

## Expected files

- `htsim/sim/uec_mp.h`, `htsim/sim/uec_mp.cpp`: LAPS multipath class and
  backward-compatible interface hooks.
- `htsim/sim/uecpacket.h`: optional LAPS packet/ACK latency metadata.
- `htsim/sim/uec.h`, `htsim/sim/uec.cpp`: sender CC enum, controls, ACK/probe
  integration, and timer.
- `htsim/sim/datacenter/main_uec.cpp`: CLI registration, factories, and pairing
  validation.
- `htsim/sim/datacenter/add_motivation/common/run_case.py` only if its explicit
  validation list is used for LAPS comparison.
- `htsim/sim/CMakeLists.txt` and a new focused test source, if the test is not
  header-only.

## Deliberate differences from paper and NS-3 source

The simulation uses entropy-selected ECMP routes, ACK/SACK based UEC
reliability, and a cwnd controller.  It does not introduce LAPS source routing,
PST/PIT files, INT/SR headers, the FPGA implementation, per-path loss ring
buffers, or a separate rate limiter.  The official NS-3 source's apparent
set-wide staleness/cooldown shortcut is not copied: the implementation follows
the paper's per-path `2 * real_latency` staleness rule.
