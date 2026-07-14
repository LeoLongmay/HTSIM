# Prism Residual-Spread Motivation Task 2 Design

## 1. Scope

This work implements only the two Task 2 motivation experiments from
`codex_prompt_prism_motivation_steps_1_2.md`:

1. M1: entropy-quality discrimination;
2. M2: effective and ineffective redistribution opportunities.

Task 1 control behavior is explicitly excluded. The simulator may expose read-only ACK, epoch,
Legacy REPS token, physical-path, link, and background-workload observations. Offline Python may
maintain a virtual eight-slot cache and shadow validation rounds. Neither observation nor shadow
state may alter foreground entropy selection, packet forwarding, Legacy REPS state, Prism state,
or the congestion window.

The supported claims are deliberately narrower than a mechanism evaluation:

- M1 may show that residual delay provides an ECN-independent and predictive entropy-quality
  signal.
- M2 may show that a complete validation opportunity can end in either spread progress or
  no-progress.
- Neither experiment may claim that unimplemented recycling caused a performance change or that
  an unimplemented handoff reduced the congestion window.

All experiment code and output live under:

```text
htsim/sim/datacenter/add_motivation/
```

Existing `prism_eval` data, figures, scripts, and paper sources are not overwritten.

## 2. Fixed Semantics and Parameters

### 2.1 Same-epoch residual

For genuine ACK samples in observation epoch `e`:

```text
F(e)   = min_j q_j(e)
S(e)   = max_j q_j(e) - F(e)
R_j(e) = max(q_j(e) - F(e), 0)
```

Per-ACK residual always joins the ACK to the raw floor from the same epoch. The analysis must not
use a previous epoch, smoothed floor, fallback delay, or boundary-snapshot Oracle.

### 2.2 Common defaults

Unless a predeclared sensitivity arm says otherwise, both experiments use:

```text
topology             fat_tree_128_1os.topo
normal link rate     100 Gbps
link latency         1 us
queue                875 KB
ECN                  enabled with repository defaults
foreground paths     8
shadow slots         8
T_cc                 14 us
T_spray              14 us
kappa                1
n_min                3
calibration seeds    101,102,103
formal seeds         13,14,15,16,17
```

The eight-slot shadow structure comes from the proposed mechanism design. It must not be
described as the current Legacy REPS data structure. Current `-load_balancing_algo reps` is an
unbounded, one-use token FIFO.

The old `T_spray=7 us, kappa=2` design is not a primary arm. It may be run only as a labeled
post-formal sensitivity check and may not participate in scenario selection.

### 2.3 Calibration discipline

Calibration and formal runs use separate directories and run-ID prefixes. Calibration selects and
locks `configs/formal.csv` before any formal seed is run. Formal outcomes never modify the locked
configuration. Failed cells and negative outcomes remain in the manifests and summaries; no seed,
flow, epoch, or completed round is removed to improve the result.

## 3. Architecture and Data Flow

The simulator emits primitive facts. Python validates and derives all motivation metrics:

```text
foreground ACKs / Legacy REPS token events / Prism epochs
background workload events / path and link metadata
                         |
                         v
        versioned CSV traces with causal event_seq
                         |
                         v
        schema validation and same-epoch residual join
                         |
              +----------+----------+
              |                     |
              v                     v
        M1 persistence       M2 shadow rounds
              |                     |
              +----------+----------+
                         |
                         v
              aggregate CSV + PDF/PNG
```

The existing read-only trace foundation is reused. Trace-disabled runs must not open files,
resolve paths for this feature, scan queues, invoke callbacks, or consume random numbers.

### 3.1 Primitive files

Each run produces a manifest and the following versioned files when tracing is enabled:

```text
<prefix>.ack.csv
<prefix>.token.csv
<prefix>.epoch.csv
<prefix>.pathmap.csv
<prefix>.linkmap.csv
<prefix>.background.csv      # M2 only
<prefix>.manifest.json
```

ACK, token, epoch, and background event rows share a monotonically increasing `event_seq`.
Pathmap and linkmap are static metadata and do not consume event sequence values. Unknown schema
versions are rejected.

The manifest records at least the Git commit, full command, topology, traffic files, seed,
thresholds, epoch settings, link rates, workload parameters, schema version, start/end time, and
whether the run is calibration, smoke, or formal.

### 3.2 Isolation boundaries

- `UecSrc` owns foreground ACK observations and independent epoch observations.
- `UecMpRepsLegacy` exposes real token enqueue/dequeue and selection metadata.
- Python owns residual joins, virtual slots, admission classification, pending replacements,
  shadow completion bits, and `S_ref`.
- `CircularBufferREPS`, freezing behavior, Prism decomposition, and foreground CC actions are not
  modified.
- M2's directed background source is experiment-only. It may use configured fixed paths and rates
  for background traffic, but it must not select a path for any measured foreground flow, share a
  mutable RNG with foreground traffic, or feed information to Prism/REPS.

## 4. Directory and Output Structure

```text
htsim/sim/datacenter/add_motivation/
|-- README.md
|-- common/
|   |-- trace_schema.py
|   |-- residual_join.py
|   |-- shadow_replay.py
|   `-- tests/
|-- expM1_entropy_quality/
|   |-- README.md
|   |-- configs/
|   |   |-- calibration.csv
|   |   `-- formal.csv
|   |-- calibrate.sh
|   |-- repro.sh
|   |-- analyze.py
|   |-- make_figs.py
|   |-- data/
|   |   |-- calibration/
|   |   `-- formal/
|   `-- figs/
`-- expM2_redistribution_progress/
    |-- README.md
    |-- configs/
    |   |-- calibration.csv
    |   `-- formal.csv
    |-- calibrate.sh
    |-- repro.sh
    |-- analyze.py
    |-- make_figs.py
    |-- data/
    |   |-- calibration/
    |   |-- formal/
    |   `-- shadow/
    `-- figs/
```

Formal experiment results are written only under this project-local tree, never `/tmp`. Unit-test
fixtures may use `/tmp` only when they remove their own files on success and failure.

## 5. M1: Entropy-Quality Discrimination

### 5.1 Question

M1 asks whether normal ECN leaves a stable population of unmarked ACKs whose same-epoch residual
is high and whether that state predicts the next use of the same entropy. Isolated high-residual
samples are not sufficient motivation for admission or recycling.

The maximum supported positive claim is:

```text
ECN-only admission leaves a measurable population of predictably poor entropy observations that
a residual-aware admission rule could distinguish.
```

M1 does not claim a goodput or FCT benefit from recycling.

### 5.2 Workload and controller

The primary arm is `REPS + NSCC`; Prism is not allowed to create the queue state used to motivate
its own classifier. A labeled always-on original Prism run may be added after the formal primary
matrix as a robustness appendix.

The foreground workload is open-loop Poisson many-to-many traffic from 64 senders outside the
target pod to 16 receivers inside it. Flows are large enough to provide repeated uses of each
entropy; the initial design uses 8 MB flows and an 8 ms arrival window, with simulation end time
covering the arrival window plus drain time.

ECN remains enabled. Gray asymmetry is created by throttling a configured subset of target-pod
cut links while preserving delivery and ACK return. The user-facing configuration and plots call
these `degraded` or `throttled` links, not failed links.

### 5.3 Calibration matrix

The full calibration grid is:

```text
degraded capacity    75,50,25 Gbps
degraded link count  2,4,8
offered load         30%,50%,70%
seeds                101,102,103
```

A 100 Gbps, zero-degraded-link symmetric control is run at every offered-load level. Calibration
may stop a cell early only for a recorded simulator error; an unsuccessful cell remains listed.

The selected gray cell must satisfy all of the following in every calibration seed:

- completion rate at least 0.99;
- a nonzero ECN-unmarked denominator in all valid observation epochs;
- unmarked high-residual rate above its load-matched symmetric control;
- at least 75% of traced foreground flows observe six of eight entropies and two physical paths;
- no loss/freezing signature explains the high residual population; and
- next-use risk-ratio direction is greater than one.

Among eligible cells, selection maximizes the minimum-over-seeds increase in unmarked
high-residual rate, then uses the lower degraded-link count as a deterministic tie-breaker.

### 5.4 Metrics

For ECN-unmarked genuine ACKs:

```text
phi = P(R >= T_spray | ECN = 0)
```

For each sample, the next-use match is the next genuine ACK for the same flow and entropy. The
next sample uses its own epoch's raw floor. Matches never cross flows. The analysis retains and
reports elapsed time, elapsed epochs, and unmatched-next-use rate rather than silently imposing a
matching window.

M1 reports:

1. ECN-unmarked residual ECDF;
2. `phi` overall and per seed;
3. next-use high-residual probability conditioned on current low/high residual;
4. the corresponding risk ratio;
5. entropy-grouped and deduplicated-physical-path-grouped persistence;
6. fraction of real Legacy REPS tokens that shadow admission would reject;
7. future-high rate for rejected tokens;
8. entropy/path coverage and unmatched-next-use rate;
9. completion rate, goodput, and P99 FCT as auxiliary metrics.

Uncertainty uses 10,000 flow-cluster bootstrap resamples. Packet-heavy flows therefore do not
dominate confidence intervals.

### 5.5 Acceptance and figure

M1 supports the motivation only when:

- gray `phi` is above the symmetric control in all five formal seeds;
- the flow-cluster bootstrap 95% lower confidence bound for next-use risk ratio exceeds one;
- the absolute future-high probability is nontrivial and not concentrated in one seed or flow;
- entropy-level and deduplicated-path-level analyses agree in direction; and
- coverage, unmatched samples, hard loss, or freezing do not explain the result.

The primary figure has three panels:

1. symmetric and gray ECN-unmarked residual ECDFs with the 14 us threshold;
2. next-use high-residual probability conditioned on current low/high residual;
3. shadow rejection exposure and future-high rate for rejected tokens.

Goodput, P99 FCT, per-seed results, coverage, and physical-path checks are appendix tables/plots.

If only `phi > 0` is observed, the result is explicitly negative: ECN and residual disagree, but
residual has not demonstrated predictive entropy-quality value.

## 6. M2: Effective and Ineffective Redistribution Opportunities

### 6.1 Question and controller

M2 asks whether a complete eight-slot shadow validation opportunity can end with either reduced
spread or no reduced spread while Prism remains in the low-floor, high-spread region.

The primary foreground controller is always-on original Prism:

```text
-prism_smooth_beta 1
-prism_hysteresis 0
-prism_engage_spread 0
-prism_engage_mult 0
-target_q_delay 14
-prism_t_spray 14
-prism_kappa 1
-prism_n_min 3
```

The supported claim is limited to the existence of progress and no-progress states after a full
validation opportunity. Because the shadow does not control foreground paths, observed spread
changes are not attributed to shadow recycling.

### 6.2 Workload timeline

Foreground traffic consists of cross-pod long-lived large flows that begin at epoch zero and last
through the observation interval. Each run covers:

```text
0--20E       symmetric warm-up
20E          inject directed background traffic
20E--120E    observe at least 3--5 complete shadow rounds
```

Here `E = kappa * base RTT`. All links remain 100 Gbps, reachable, and ECN-enabled. The background
generator sends at configured constant rates over fixed, pre-resolved path groups. It exists only
to construct the workload and is excluded from foreground residual, round, goodput, and FCT
metrics. Its packet counts and configured paths are logged for capacity verification.

The background generator must be deterministic and behaviorally isolated: disabling it at zero
rate must produce byte-identical foreground results to a build without the injector.

### 6.3 Recoverable and persistent capacity witnesses

Let:

```text
C_healthy            = capacity of unique cut links outside background hot path groups
C_hot_residual       = sum over hot cut links of max(link capacity - background rate, 0)
C_effective_residual = C_healthy + C_hot_residual
L_foreground         = measured foreground injection rate over the evaluated round
```

Path and link metadata deduplicate shared physical queues before summing capacity.

Formal scenarios require:

```text
recoverable: L_foreground < C_healthy
persistent:  C_healthy < L_foreground < C_effective_residual
```

Both scenarios must repeatedly enter `F < T_cc` and `S >= T_spray`. The persistent point is invalid
if high floor dominates, if all paths are overloaded, or if loss/freezing rather than queueing
asymmetry explains the state.

Calibration varies foreground-flow count, hot path-group count, and per-hot-link background
utilization. It uses a two-stage predeclared search:

```text
coarse seed           101
foreground flows      8,16,32
hot path groups       2,4,6
background/link       25%,50%,75% of 100 Gbps

confirmation seeds    101,102,103
candidate pairs       best three recoverable and best three persistent coarse cells
```

The formal pair is selected only from candidates that retain the required capacity relation,
low-floor/high-spread occupancy, and round completion in all three confirmation seeds. A
recoverable candidate must have median `delta_S > 0` in every confirmation seed. A persistent
candidate must have majority literal no-progress among completed rounds in every confirmation
seed. Deterministic ranking first maximizes the minimum outcome margin across confirmation seeds,
then the minimum margin to the relevant capacity boundary, and finally prefers the lower
background rate.

### 6.4 Shadow round semantics

Python reconstructs the real Legacy REPS FIFO from token events and projects it into a virtual
eight-slot validation cache.

At the first actual Prism HOLD epoch after background injection:

1. start a high-spread episode and record raw `S_ref`;
2. seed virtual slots from the next eight real FIFO tokens, leaving missing slots pending;
3. associate recycled sends and ACKs using token identity, never entropy value alone;
4. complete a slot only when its selected token returns a genuine ACK with `ECN=0` and
   `R < T_spray`;
5. classify marked or high-residual ACKs as shadow-invalid and leave the slot pending;
6. assign a later genuine, unmarked, low-residual ACK to a pending slot only when the related
   enqueue event proves replacement validation;
7. never count invalidation, selection, transmission, or enqueue without a genuine admitted ACK as
   completion; and
8. declare completion only when all eight slots are complete.

After completion, replay waits for the next full epoch boundary and records `S_end`. If the flow
ends first, the round is right-censored. If Prism exits HOLD before completion, the episode ends and
the incomplete round is censored rather than classified.

For round `k`:

```text
delta_S_k = (S_ref_k - S_end_k) / S_ref_k
```

`delta_S > 0` is progress; `delta_S <= 0` is literal no-progress. Diagnostic tolerances of 1, 2,
and 4 us may be reported separately but never become mechanism parameters or alter the primary
classification.

### 6.5 Metrics

M2 reports:

- low-floor/high-spread episode count and occupancy;
- round completion rate, duration, and right-censored fraction;
- `F`, `S`, `S_ref`, `S_end`, and `delta_S`;
- literal and tolerance-diagnostic no-progress rates;
- HOLD duration, consecutive HOLD epochs, actual cwnd, and actual Prism state;
- real Legacy FIFO depth, virtual replacements, and admission pass/fail counts;
- configured background rate, measured background delivery, and path concentration;
- `L_foreground`, `C_healthy`, and `C_effective_residual`;
- foreground entropy/path coverage, goodput, and queueing delay.

### 6.6 Acceptance and figure

Recoverable acceptance requires at least four of five formal seeds to have median
`delta_S > 0`, with the flow-cluster bootstrap 95% lower confidence bound above zero.

Persistent acceptance requires:

- the capacity witness `C_healthy < L_foreground < C_effective_residual`;
- majority literal no-progress among completed rounds in at least four of five seeds;
- at least 80% of valid round epochs keep `F < T_cc`;
- no direction reversal in the tolerance diagnostic; and
- completed rounds are not concentrated in a small number of flows.

The main figure has recoverable and persistent columns. Each column shows event-aligned raw `F`,
`S`, and `S_ref` with the 14 us threshold and round markers, followed by actual cwnd and Prism state
with HOLD shading. A compact inset summarizes five-seed `delta_S`, completion, and censoring.

If no stable pair satisfies the criteria, the experiment reports a negative result and the
calibration diagnostics. It does not weaken round completion, remove formal seeds, or redefine
no-progress.

## 7. Error Handling and Data Validity

- Failure to create an explicitly requested project-local trace aborts the run.
- Non-monotonic event ordering or an ACK/token causal mismatch invalidates that flow; replay never
  guesses a token.
- An ACK that cannot join exactly one valid epoch is excluded with a recorded reason.
- Path-resolution failure excludes path-level metrics only; valid entropy-level samples remain.
- Insufficient denominators or coverage produce an invalid reason, not a numeric zero.
- Incomplete M2 rounds are right-censored and never counted as no-progress.
- Background path/rate mismatch invalidates the M2 capacity witness.
- Reproduction scripts clear only their own current-schema output and never touch `prism_eval`.
- Calibration and formal run IDs and directories cannot overlap.

## 8. Tests and Verification Gates

### 8.1 Unit tests

C++ tests cover:

- Legacy REPS token identity and event ordering;
- identical entropy choices with tracing disabled/enabled;
- independent raw epoch extrema, `n_min`, and closure semantics;
- duplicate entropy-to-physical-path mapping;
- background generator fixed path/rate accounting and zero-rate isolation.

Python tests cover:

- schema/version rejection and common `event_seq` validation;
- exact same-epoch residual joins;
- next-use matching that cannot cross flows;
- token identity isolation when entropy values repeat;
- invalidation and unacknowledged replacement not completing a slot;
- admitted genuine replacement completing a slot;
- ECN/fallback rejection, right-censoring, and `delta_S` direction;
- capacity deduplication and calibration-only deterministic selection.

### 8.2 End-to-end gates

1. Build `htsim_uec` and analysis tests.
2. Compare trace-disabled and trace-enabled runs at the same seed; foreground entropy sequence,
   flow output, sink output, cwnd, and actual Prism epochs must match.
3. Validate and replay one project-local smoke trace for each experiment.
4. Run M1 calibration and lock its formal configuration.
5. Run M2 coarse/confirmation calibration and lock the formal pair.
6. Run all five formal seeds without automatic configuration changes.
7. Regenerate aggregate CSV, PDF, and PNG exclusively from raw project-local outputs.

## 9. Required Final Artifacts

```text
expM1_entropy_quality/data/formal/summary.csv
expM1_entropy_quality/figs/m1_entropy_quality.pdf
expM1_entropy_quality/figs/m1_entropy_quality.png

expM2_redistribution_progress/data/formal/rounds.csv
expM2_redistribution_progress/data/formal/summary.csv
expM2_redistribution_progress/figs/m2_redistribution_progress.pdf
expM2_redistribution_progress/figs/m2_redistribution_progress.png
```

Each experiment README gives build, calibration, smoke, formal, analysis, and plotting commands,
plus field definitions and an explicit distinction between observed facts, offline shadow results,
capacity inference, and claims that require the later mechanism implementation.
