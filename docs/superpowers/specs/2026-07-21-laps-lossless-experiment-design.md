# LAPS Lossless/PFC Experiment Design

## Goal

Add an independent, reproducible experiment that compares LAPS with the seven
existing Prism-evaluation baselines in the same PFC/lossless network.  It keeps
Experiment A's topology, workload, failure sweep, and metrics, but does not
reuse, overwrite, or reinterpret Experiment A's delay-driven results.

## Scope and invariants

- The experiment directory is `htsim/sim/datacenter/prism_eval/expL_laps_lossless/`.
- It uses `fat_tree_128_1os`, the existing 64-to-16 pod-0 2 MB many-to-many
  workload, `-failed {0,2,4,6,8,10,12}`, and seeds `{13,14,15,16,17}`.
- Every matrix cell runs OPS, REPS, Swift, MSwift, MNSCC, STrack, Prism, and
  LAPS under the same lossless/PFC command-line configuration.
- The experiment has its own `data/` and `figs/` trees.  It must never write
  to `expA_delaydriven/data` or `expA_delaydriven/figs`.
- The lossless network configuration is: 150 KiB per data egress queue, a
  32 MiB shared pool per FatTree switch, PFC pause at 120 KiB, and PFC resume
  below 90 KiB.  The 150 KiB queue and 32 MiB switch-buffer values are the
  LAPS-paper configuration.  The 80%/60% pause/resume watermarks are explicit
  experiment choices because the paper does not publish them.
- No run uses `-disable_trim`; lossless queues provide backpressure rather
  than trimming or DropTail loss.

## Architecture

### CLI configuration

`main_uec` will expose `lossless_input` as a `-queue_type` value and accept
the following byte-valued options:

- `-pfc_high_bytes 122880`
- `-pfc_low_bytes 92160`
- `-shared_buffer_bytes 33554432`

The program rejects a zero shared buffer, a zero high watermark, and any
configuration where the low watermark is greater than or equal to the high
watermark.  Existing queue types retain their current behavior.

### Lossless queue and shared-buffer behavior

The experiment uses the existing `LOSSLESS_INPUT` topology mode: ingress
virtual queues account for traffic arriving at a switch, while lossless output
queues hold and transmit packets.  Each switch owns one shared-buffer object.
All data egress queues belonging to that switch reserve bytes from this object
when they enqueue a packet and return exactly those bytes when the packet
leaves service.

An ingress virtual queue sends PAUSE when its accounted occupancy exceeds
120 KiB and sends resume when the occupancy falls below 90 KiB.  A shared pool
at capacity keeps affected ingress traffic paused; it must not silently accept
more bytes or convert the packet to a DropTail loss.  A shared-buffer accounting
overflow is a simulator error.  The model leaves existing control-packet
priority handling intact.

### Experiment driver and figures

`expL_laps_lossless/repro.sh` runs the full 8 x 7 x 5 matrix and records all
artifacts under its own `data/` directory.  It follows the existing
`common/run_lib.sh` interface and supplies the lossless/PFC flags on every
invocation.  A dry-run mode prints the exact matrix without running it.

The figure wrapper uses the existing common metric and plotting utilities to
produce independent goodput, average-FCT, and P99-FCT PDF/PNG outputs.  The
legend contains all eight algorithms; Prism remains green and appears last.

## Verification

Before a full matrix run, automated tests must establish all of the following:

1. `main_uec` accepts `lossless_input` and the three PFC/shared-buffer options,
   and rejects invalid watermarks.
2. A lossless queue crossing 120 KiB produces PAUSE; draining below 90 KiB
   produces resume; no data packet is dropped by the queue.
3. Shared-buffer reservations and releases are byte-conserving and capacity is
   never exceeded.
4. A short lossless smoke workload completes for each of the eight algorithms.
5. The experiment driver's dry run emits exactly 280 commands with the same
   lossless flags and no `-disable_trim` flag.
6. The plotting test reads only the new experiment's data tree and preserves
   Prism's green, last-legend presentation.

## Non-goals

- This work does not alter ExpA, its existing figures, or its no-trim results.
- It does not claim to reproduce the LAPS paper's Rail topology or workloads.
- It does not retune LAPS parameters to force a favorable result.
- It does not alter non-LAPS congestion-control logic beyond making all arms
  use the same network-level lossless/PFC mechanism.
