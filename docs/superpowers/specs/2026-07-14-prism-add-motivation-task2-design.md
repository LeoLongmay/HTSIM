# Prism Residual-Spread Motivation Task 2 Design

## 1. Scope

This work validates the motivation for Residual-Spread Coordination without implementing
entropy recycling or congestion-control handoff. The simulator may emit read-only ACK, REPS
cache, epoch, path, and link observations. An offline Python replay may maintain a shadow cache
and shadow recycling rounds, but shadow state must never affect entropy selection, packet
forwarding, REPS freezing, Prism state, or the congestion window.

The experiments live under a new directory beside `prism_eval`:

```text
htsim/sim/datacenter/add_motivation/
```

Existing Evaluation data, figures, experiment identifiers, and paper sources are out of scope.

## 2. Questions and Claims

### 2.1 M1: Entropy-quality discrimination

M1 tests whether ECN-unmarked ACKs can still carry persistent, entropy-specific high residual
delay. Finding isolated unmarked high-residual samples is insufficient. The experiment must also
test whether a high residual predicts elevated delay on the next use of the same entropy and
whether the result remains after deduplicating entropies that map to the same physical path.

The supported claim is limited to:

```text
ECN-only admission leaves a measurable population of predictably poor entropy observations
that a residual-aware admission rule could distinguish.
```

M1 does not claim that recycling improves goodput or FCT.

### 2.2 M2: Effective and ineffective redistribution

M2 tests whether a complete, observable feedback/cache-turnover round can coincide with either:

1. a material reduction in spread when healthy-path capacity has headroom; or
2. no spread reduction when healthy-path capacity cannot absorb the offered load, while the
   overall fabric is not yet path-wide overloaded.

The supported claim is limited to:

```text
A no-progress state exists after one complete observable correction opportunity, so an
explicit handoff condition is worth evaluating in a later mechanism experiment.
```

Because the shadow replay does not alter actual path selection, it must not attribute observed
spread changes to shadow recycling.

## 3. Directory Structure

```text
htsim/sim/datacenter/add_motivation/
├── README.md
├── .gitignore
├── common/
│   ├── trace_schema.py
│   ├── shadow_replay.py
│   └── tests/
│       ├── test_trace_schema.py
│       └── test_shadow_replay.py
├── expM1_entropy_quality/
│   ├── README.md
│   ├── .gitignore
│   ├── calibrate.sh
│   ├── repro.sh
│   ├── analyze.py
│   ├── make_figs.py
│   ├── configs/
│   │   ├── calibration.csv
│   │   └── formal.csv
│   ├── data/
│   │   ├── raw/
│   │   └── summary.csv
│   └── figs/
└── expM2_redistribution_progress/
    ├── README.md
    ├── .gitignore
    ├── calibrate.sh
    ├── repro.sh
    ├── analyze.py
    ├── make_figs.py
    ├── configs/
    │   ├── calibration.csv
    │   └── formal.csv
    ├── data/
    │   ├── raw/
    │   ├── shadow/
    │   └── summary.csv
    └── figs/
```

The experiments reuse `../prism_eval/common/run_lib.sh`, traffic generators, plotting style, and
metrics. They do not copy those utilities. Raw traces, stdout, generated traffic matrices, and
per-event shadow output are ignored. Configurations, summaries, documentation, and final figures
are versioned.

Calibration and formal runs use separate output directories and run-ID prefixes. Calibration
uses seeds `101,102,103`; formal results use seeds `13,14,15,16,17`.

## 4. Implementation Approach

The simulator emits primitive facts. Python validates and replays those facts. This event-sourced
approach is preferred over an in-simulator shadow controller because it minimizes behavioral risk,
allows the round semantics to be tested independently, and permits analysis changes without
rerunning simulations.

The data flow is:

```text
UEC ACK / REPS cache operation / Prism epoch
                |
                v
       read-only trace callbacks
                |
                v
 ack.csv + cache.csv + epoch.csv
 pathmap.csv + linkmap.csv
                |
                v
 schema validation + ordered replay
                |
        +-------+-------+
        |               |
        v               v
 M1 analysis       M2 shadow rounds
        |               |
        v               v
 summary.csv       shadow/*.csv
        |               |
        +-------+-------+
                |
                v
          final figures
```

## 5. Simulator Observation Interface

### 5.1 CLI

The trace is disabled by default. The proposed CLI is:

```text
-motivation_trace_prefix <path-prefix>
-motivation_trace_flow_id <id>
-motivation_run_id <string>
-motivation_scenario <string>
```

`-motivation_trace_flow_id` is optional; omission records all flows. When the trace prefix is not
set, the simulator must not open trace files, resolve paths for this feature, scan queues, allocate
shadow state, or invoke trace callbacks.

### 5.2 Common ordering and schema

Every trace row contains a fixed `schema_version`, run identity, and a monotonically increasing
`event_seq`. Separate CSV files remain causally joinable through `event_seq`, simulation time, and
flow ID. Unknown schema versions are rejected by the analysis scripts.

### 5.3 ACK trace

`<prefix>.ack.csv` contains:

```text
schema_version,run_id,seed,scenario,event_seq,time_ps,
flow_id,epoch_id,acked_psn,entropy,physical_path_id,
raw_rtt_ps,base_rtt_ps,qdelay_ps,ecn,genuine_sample,retransmitted,freezing,
forward_path_backlog_ps,selection_source,source_slot,source_generation
```

Semantics:

- `qdelay_ps` is the exact `raw_rtt - base_rtt` value presented to the Prism observation path.
- fallback, probe, missing-send-record, and otherwise invalid samples set `genuine_sample=0`.
- `forward_path_backlog_ps` scans only the used entropy's resolved forward path at ACK time.
- `selection_source` is one of `cached`, `frozen`, or `random_explore`.
- `source_slot` and `source_generation` identify the cache token that selected the packet; they
  are invalid sentinels for random exploration.
- The ACK event is ordered before the subsequent REPS `processEv()` event at the same simulation
  time.

### 5.4 Actual REPS cache trace

`<prefix>.cache.csv` contains:

```text
schema_version,run_id,event_seq,time_ps,flow_id,
operation,reason,slot,generation,entropy,
valid_before,valid_after,fresh_before,fresh_after,frozen_before,frozen_after
```

Operations include:

```text
add_good_ack
consume_fresh
consume_frozen
random_explore
reset
freeze_enter
freeze_exit
```

This trace describes the real one-use REPS token FIFO. It must not describe it as a persistent
entropy table. `slot + generation` uniquely identifies slot contents across overwrites.

### 5.5 Independent observation epoch

`<prefix>.epoch.csv` contains:

```text
schema_version,run_id,event_seq,flow_id,epoch_id,start_ps,end_ps,sample_count,
raw_floor_ps,raw_spread_ps,smooth_floor_ps,smooth_spread_ps,
observed_region,actual_region,engaged,entropy_coverage,physical_path_coverage
```

The observer runs for every sender CC and uses the same genuine-sample, `kappa`, and `n_min`
semantics as Prism. It has separate state from the real Prism controller. For Prism runs, a smoke
test reconstructs and compares the observer epochs with real Prism epochs.

### 5.6 Path and link metadata

`<prefix>.pathmap.csv` contains one row per flow and configured entropy:

```text
schema_version,run_id,flow_id,entropy,physical_path_id,resolution_status,
queue_fingerprint,bottleneck_rate_gbps,contains_reduced_link,ordered_queue_ids
```

Physical paths use the expJ live ECMP FIB resolver. Entropies with identical ordered queue
sequences share a `physical_path_id`.

`<prefix>.linkmap.csv` contains:

```text
schema_version,run_id,queue_id,queue_name,rate_gbps,reduced_speed
```

Only read-only queue metadata accessors may be added. Queue service behavior is unchanged.

## 6. Isolation Boundaries

- `UecSrc` owns ACK observations, independent epoch state, and path/link metadata emission.
- `UecMpReps` exposes selection source and forwards real cache operation observations.
- `CircularBufferREPS` exposes read-only slot snapshots and operation callbacks.
- Callbacks may read pre/post state and write logs, but may not call an RNG, choose an entropy,
  alter a cache decision, or mutate controller state.
- Python owns admission classification, virtual invalidation, pending replacement state, recycling
  bitmap, round completion, and `S_ref`.
- `prism_decompose.h` and congestion-control action logic remain unchanged.

## 7. M1 Experiment

### 7.1 Configuration

The primary arm is `REPS+NSCC`, which avoids using Prism CC to create the queue state being used to
motivate Prism's residual classifier. Always-on original Prism is a robustness appendix.

Fixed parameters are:

```text
topology       fat_tree_128_1os.topo
traffic        open-loop Poisson many-to-many, 64 senders to 16 receivers
link mode      -disable_trim
paths          8
T_cc           14 us
T_spray        7 us
kappa          2
n_min          3
```

The calibration matrix is:

```text
failed links   0,2,4,8
offered load   30%,50%,70%
seeds          101,102,103
```

`failed=0` is the symmetric control. `failed>0` is a throttled-link gray degradation: links retain
ACK delivery and ECN remains enabled. Formal runs retain one symmetric control, one stable gray
condition, and only if needed one stronger gray condition.

Calibration selection requires completion rate at least `0.99`, negligible freezing, adequate
entropy/path coverage, and a high-residual unmarked population in every calibration seed. The
formal matrix is locked before seeds `13..17` are run.

### 7.2 Residual calculation

For genuine ACKs in epoch `e`:

```text
F(e) = min_j q_j(e)
R_j(e) = max(q_j(e) - F(e), 0)
```

M1 uses the same epoch's raw floor. It never uses the previous epoch's floor, the smoothed floor,
fallback delay, or the boundary-snapshot Oracle. `T_spray=7 us` is inherited from the existing
Prism evaluation and is not tuned on M1.

### 7.3 Metrics

M1 reports:

1. the residual distribution among ECN-unmarked genuine ACKs;
2. `P(R >= T_spray | ECN=0)`;
3. the fraction of actual REPS cache tokens that shadow admission would reject;
4. next-use persistence for the same flow and entropy;
5. the risk ratio between current-high and current-low residual groups;
6. entropy-grouped and deduplicated-physical-path-grouped persistence;
7. correlation between RTT residual and ACK-time forward-path backlog residual;
8. entropy/path coverage, freezing, next-use matching interval, and unmatched-next-use rate.

The next-use risk ratio is:

```text
     P(high next | high current, ECN=0)
RR = ----------------------------------
     P(high next | low current,  ECN=0)
```

Confidence intervals use flow-cluster bootstrap resampling so packet-heavy flows do not dominate.

### 7.4 Decision rule and figure

M1 supports the motivation only if:

- the gray condition has a stable unmarked high-residual rate above the symmetric control;
- the bootstrap 95% lower confidence bound for `RR` exceeds 1;
- the absolute future-high probability is nontrivial and not concentrated in one seed or flow;
- entropy and physical-path analyses agree in direction; and
- freezing, low coverage, or unmatched next-use observations do not explain the result.

If only the first condition holds, the result is negative: classification disagreement exists, but
residual lacks demonstrated predictive value.

The primary three-panel figure shows:

1. ECDFs of ECN-unmarked residual for symmetric and gray conditions;
2. next-use high-residual probability conditioned on current low/high residual;
3. actual-cache shadow-rejection exposure and the future-high rate of rejected tokens.

Path-level persistence, backlog correlation, coverage, and per-seed results are appendix outputs.

## 8. M2 Experiment

### 8.1 Controller configuration

The main arm is always-on original Prism:

```text
-prism_smooth_beta 1
-prism_hysteresis 0
-prism_engage_spread 0
-prism_engage_mult 0
-target_q_delay 14
-prism_t_spray 7
-prism_kappa 2
-prism_n_min 3
```

Prism v2 is an appendix robustness arm only.

### 8.2 Capacity witness

The analysis deduplicates shared target-pod cut links using `pathmap.csv` and `linkmap.csv`:

```text
C_healthy   = sum(capacity of unique healthy cut links)
C_effective = sum(capacity of all unique cut links)
```

Configured offered load and measured sink throughput are both reported. A scenario is not named
recoverable or persistent from `-failed` alone.

Calibration scans `fat_tree_128_1os`, `failed={2,4,8,12}`, and offered load
`{20%,40%,60%,80%}` with seeds `101..103`. The 4:1 topology may be used only as an explicitly
reported supplementary scan.

The selected formal scenarios satisfy:

```text
recoverable: L_offered < C_healthy
persistent:  C_healthy < L_offered < C_effective
```

Both must repeatedly enter `F < T_cc` and `S >= T_spray`. The persistent point is invalid if it is
primarily a high-floor path-wide-overload point.

### 8.3 Shadow round semantics

Python reconstructs the eight physical cache slots and generations from real cache events.

At entry to an actual Prism HOLD epoch:

1. start a high-spread episode and record `S_ref`;
2. snapshot all eight slots, treating empty slots as pending;
3. associate cached sends and ACKs through `source_slot + source_generation`;
4. complete a slot only when its selected token returns a genuine ACK with `ECN=0` and
   `R < T_spray`;
5. treat marked or high-residual ACKs as shadow-invalid/pending without completing the slot;
6. require a replacement generation to be sent, genuinely ACKed, and admitted before completing
   an invalidated slot;
7. suspend ordinary shadow recycling during freezing and protect an ACK-validated survivor; and
8. declare the round complete only when all eight slots are complete.

After validation completion, replay waits for the next full epoch boundary and records `S_end`.
Flows that end first are right-censored.

The progress value is:

```text
delta_S = S_end - S_ref
```

Literal no-progress is `delta_S >= 0`. Sensitivity analysis also reports no-progress for
`delta_S >= -epsilon`, with `epsilon` in `{0,1,2,4} us`. These tolerances are analysis diagnostics,
not mechanism parameters.

If the condition remains HOLD after a round, the next round begins at the evaluation epoch. If the
condition exits HOLD, the episode ends.

### 8.4 Metrics

M2 reports:

- high-spread/low-floor episode count and fraction;
- round completion rate, completion latency, and right-censored fraction;
- `F`, `S`, `S_ref`, `S_end`, and `delta_S`;
- literal and tolerance-aware no-progress rates;
- Hold duration, consecutive Hold epochs, and actual cwnd;
- valid-cache count, replacements, and admission pass/fail counts;
- offered load, measured throughput, `C_healthy`, and `C_effective`;
- entropy/path coverage and freezing.

### 8.5 Decision rule and figure

The recoverable result requires at least four of five formal seeds to have median `delta_S < 0`,
with a flow-cluster bootstrap 95% upper confidence bound below zero. Completed rounds must not be
concentrated in a small number of flows.

The persistent result requires:

- the capacity witness `C_healthy < L_offered < C_effective`;
- literal no-progress to be the majority outcome in at least four of five seeds;
- no direction reversal across the tolerance diagnostic; and
- floor to remain predominantly below `T_cc`.

Failure to find a stable point is retained as a negative result; formal seeds are not filtered.

The main figure has recoverable and persistent columns. Each column shows event-aligned `F`, `S`,
and `S_ref` with round markers, plus actual cwnd and Prism state with Hold shading. Insets summarize
`delta_S`, completion, and no-progress. Capacity, censoring, and five-seed detail are reported in
tables and appendix plots.

## 9. Error Handling

- Failure to create an explicitly requested trace file aborts the run.
- Path-resolution failures are logged. They exclude path-level metrics but retain valid
  entropy-level observations.
- Missing ACK/cache generation links or non-monotonic event ordering invalidate that flow; replay
  does not guess a slot.
- Incomplete rounds are right-censored, not classified as no-progress.
- Insufficient coverage emits an invalid reason instead of a numeric aggregate.
- Reproduction scripts clear only their own current-schema raw output before running.
- Calibration and formal data cannot share run IDs or directories.

## 10. Tests and Verification

### 10.1 C++ tests

Tests cover:

- callback order and slot generation for add, consume, reset, freeze, and unfreeze;
- byte-identical buffer return values with callbacks disabled and enabled;
- cached, frozen, and random selection-source metadata;
- independent epoch min/max, `n_min`, and closure semantics; and
- deduplication of duplicate entropy-to-physical-path mappings.

### 10.2 Python tests

Hand-authored traces cover:

- low-residual genuine ACK completion;
- invalidation not completing a slot;
- unacknowledged replacement not completing a slot;
- genuinely ACKed and admitted replacement completing a slot;
- ECN and fallback rejection;
- generation overwrite isolation;
- freezing suspension and survivor protection;
- right-censoring;
- `delta_S` and tolerance classification; and
- next-use matching that cannot cross flows or incorrect epochs.

### 10.3 End-to-end gates

1. Build `htsim_uec`.
2. Run a small symmetric simulation with tracing disabled and enabled at the same seed.
3. Compare flow, sink, cwnd, and real Prism epoch output hashes; they must match.
4. Validate schemas and replay the emitted trace.
5. Run one-seed M1 and M2 smoke tests.
6. Run calibration and lock both `formal.csv` files.
7. Run all five formal seeds without automatic formal-config changes.

## 11. Reproduction Commands

```bash
# M1
bash add_motivation/expM1_entropy_quality/calibrate.sh
bash add_motivation/expM1_entropy_quality/repro.sh smoke
bash add_motivation/expM1_entropy_quality/repro.sh full
python3 add_motivation/expM1_entropy_quality/make_figs.py --render

# M2
bash add_motivation/expM2_redistribution_progress/calibrate.sh
bash add_motivation/expM2_redistribution_progress/repro.sh smoke
bash add_motivation/expM2_redistribution_progress/repro.sh full
python3 add_motivation/expM2_redistribution_progress/make_figs.py --render
```

Each README distinguishes observed facts, offline shadow results, capacity inference, and claims
that remain unsupported until the actual recycling and handoff mechanisms are implemented.
