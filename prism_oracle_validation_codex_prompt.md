# Codex Prompt: Add Oracle Validation for Prism's O(1) Estimator

> **Corrected design note (2026-07-12).** The original requirements below treated one
> instantaneous all-path scan at the epoch boundary as the ground truth for extrema formed from
> ACKs collected throughout the epoch. Those quantities are not time-aligned: an ACK's
> `RTT-baseRTT` describes a packet sent roughly one RTT earlier, while the boundary scan describes
> current forward queue backlog. Implementations must therefore:
>
> 1. resolve every configured entropy through the live `(flow_id, entropy, switch hash salt)` ECMP
>    FIB, rather than truncating the topology's static path enumeration;
> 2. report entropy coverage and deduplicated physical-path coverage separately, both in `[0,1]`;
> 3. use a full-path snapshot at every genuine ACK sample time to build the primary epoch-envelope
>    oracle;
> 4. retain the epoch-boundary snapshot only as a separately named staleness diagnostic;
> 5. report boundary-state agreement over oracle epoch offsets `[-2,+2]` to expose feedback lag;
> 6. log and exclude unresolved or partially resolved epochs instead of silently accepting them;
> 7. stratify coverage results by scenario rather than pooling them into a confounded aggregate.
>
> The ACK-time envelope still uses instantaneous forward queue workload rather than a
> counterfactual packet RTT. It is a closer full-path analogue, not an assertion of perfect ground
> truth. The corrected implementation and field definitions are documented in
> `expJ_oracle_validation/README.md`; that document supersedes conflicting boundary-only language
> in sections 4, 5, 7, 9, and 12 below.

## 1. Task objective

Please inspect the existing Prism/htsim codebase and add a **read-only oracle validation pipeline** for Prism's epoch-based O(1) congestion estimator.

The goal is to answer the following reviewer concern:

> Prism estimates the congestion floor and path spread from the minimum and maximum ACK-derived queueing samples within an epoch. Because these samples may come from different paths and different times, the estimator may conflate cross-path congestion variation with temporal queue variation or incomplete path coverage. Does the O(1) estimator still preserve enough path-resolved information to choose the correct congestion-control action?

The validation must compare Prism's existing estimator against a simulator-side oracle that can inspect the instantaneous queueing state of every eligible forward path. The oracle is used **only for logging and evaluation**. It must never affect packet spraying, congestion-window updates, entropy selection, or any other runtime decision.

The expected outcome is a small, reproducible experiment showing whether Prism's O(1) estimator agrees with an ideal path-aware oracle on the control state:

- `Increase`
- `Hold`
- `Decrease`

Do not redesign Prism's core algorithm unless a small bug prevents the validation from running.

---

## 2. Background

Prism currently estimates, within control epoch \(e\),

\[
C_{cc}^{(e)} = q_{\min}^{(e)},
\qquad
C_{spray}^{(e)} = q_{\max}^{(e)} - q_{\min}^{(e)},
\]

where \(q_{\min}^{(e)}\) and \(q_{\max}^{(e)}\) are the minimum and maximum ACK-derived queueing-delay samples observed in the epoch.

Prism then maps the estimated components to three rate-control states:

\[
\textsc{Decrease}
\quad\text{if}\quad
\hat C_{cc}^{(e)} \ge T_{cc},
\]

\[
\textsc{Hold}
\quad\text{if}\quad
\hat C_{cc}^{(e)} < T_{cc}
\land
\hat C_{spray}^{(e)} \ge T_{spray},
\]

\[
\textsc{Increase}
\quad\text{otherwise}.
\]

The validation should determine whether the estimator and oracle produce the same control state at each epoch boundary.

Use the actual decision logic implemented in the repository as the source of truth. If the implementation contains hysteresis, strict versus non-strict comparisons, minimum-sample checks, EWMA smoothing, or other details not shown above, preserve them exactly in the validation.

---

## 3. Scope and non-goals

### In scope

1. Add simulator-side path-aware oracle measurements.
2. Log estimator outputs and oracle outputs at each Prism epoch boundary.
3. Compute control-state agreement and estimation error.
4. Record path-sampling coverage statistics.
5. Add scripts to aggregate results and generate a compact validation figure or table.
6. Reuse the existing Prism experiment framework, configuration format, and plotting style where possible.

### Out of scope

1. Do not let the oracle influence Prism's runtime behavior.
2. Do not replace the O(1) estimator with a per-path estimator.
3. Do not add a hardware or DPDK implementation.
4. Do not introduce a new congestion-control law.
5. Do not retune \(T_{cc}\), \(T_{spray}\), or other default Prism parameters to improve agreement.
6. Do not fabricate results or hard-code expected values.
7. Do not silently change existing baselines or workload definitions.

---

## 4. Required oracle definition

### 4.1 Eligible path set

For each Prism flow at an epoch boundary, identify the set of forward paths that the flow can currently use through its entropy-value or path-selection mechanism.

The oracle path set should follow these rules:

1. Use the same entropy/path namespace available to Prism's sender.
2. Exclude paths that are administratively invalid or unavailable.
3. Include degraded or congested paths if Prism is still allowed to select them.
4. Evaluate only the forward data path. Do not include ACK reverse-path delay.
5. Log the number of eligible paths.

If the codebase does not expose a direct list of eligible paths, trace how entropy values are mapped to ECMP paths and implement the smallest reusable helper that resolves:

```text
(flow, entropy_value) -> ordered forward-path queues/links
```

Avoid duplicating topology logic if a path-resolution helper already exists.

### 4.2 Instantaneous path queueing delay

At the epoch boundary, calculate the instantaneous forward queueing delay for every eligible path \(p\):

\[
q_p^{*,(e)}.
\]

Prefer an existing simulator API that reports queue waiting time or queueing delay. If no such API exists, derive the instantaneous queueing delay from queue occupancy and service rate:

\[
q_p^{*,(e)}
=
\sum_{h \in p}
\frac{B_h(t_e)}{R_h},
\]

where:

- \(B_h(t_e)\) is the queued number of bits or bytes at hop \(h\) at epoch boundary \(t_e\);
- \(R_h\) is the service rate of that output link;
- units must be converted consistently to microseconds.

If the queue model exposes a more accurate `next_service_time`, packet serialization backlog, or virtual-finish-time estimate, use that instead and document the choice.

Do not include fixed propagation delay in the oracle queueing value.

### 4.3 Oracle congestion components

For each epoch \(e\), define the raw oracle components as:

\[
C_{cc}^{*,(e)}
=
\min_{p \in \mathcal P^{(e)}} q_p^{*,(e)},
\]

\[
C_{spray}^{*,(e)}
=
\max_{p \in \mathcal P^{(e)}} q_p^{*,(e)}
-
\min_{p \in \mathcal P^{(e)}} q_p^{*,(e)}.
\]

Here, \(\mathcal P^{(e)}\) is the eligible forward-path set.

### 4.4 Match Prism's smoothing and decision logic

The estimator used by Prism may apply EWMA or other smoothing before state selection. The oracle comparison must be apples-to-apples.

Therefore:

1. Log both raw oracle values:
   - \(C_{cc}^{*,(e)}\)
   - \(C_{spray}^{*,(e)}\)

2. Apply the same smoothing rule and coefficient used by Prism to obtain:
   - \(\hat C_{cc}^{*,(e)}\)
   - \(\hat C_{spray}^{*,(e)}\)

3. Derive the oracle state using the exact same thresholds, hysteresis, and comparison operators as Prism.

4. Compare:
   - Prism's actual estimator-driven state;
   - the smoothed oracle-driven state.

Do not compare a smoothed Prism estimate against an unsmoothed oracle.

---

## 5. Instrumentation point

Add the oracle instrumentation at the Prism epoch boundary, immediately before or after the normal estimator-driven state transition, provided that both sides observe the same network timestamp.

The logging sequence should be:

1. The epoch expires.
2. Prism verifies its normal minimum-sample requirement.
3. Prism computes its existing raw and smoothed estimates.
4. The oracle reads all eligible forward-path queue states at the same simulation time.
5. The oracle computes raw and smoothed components.
6. Both Prism and oracle independently derive a control state.
7. Log all values.
8. Prism continues using only its own estimator-driven state.

The instrumentation must be read-only. Add a prominent code comment such as:

```cpp
// Validation only: oracle values must never affect Prism control.
```

---

## 6. Required logging schema

Write one structured row per valid Prism epoch. CSV is preferred unless the project already uses another structured format.

Use at least the following fields:

```text
run_id
seed
scenario
flow_id
epoch_id
epoch_start_ns
epoch_end_ns
kappa
n_min
t_cc_us
t_spray_us
num_ack_samples
num_distinct_sampled_paths
num_eligible_paths
path_coverage_ratio
est_raw_cc_us
est_raw_spray_us
est_smoothed_cc_us
est_smoothed_spray_us
oracle_raw_cc_us
oracle_raw_spray_us
oracle_smoothed_cc_us
oracle_smoothed_spray_us
est_state
oracle_state
state_match
abs_error_cc_us
abs_error_spray_us
```

Definitions:

\[
\text{path coverage ratio}
=
\frac{\text{number of distinct entropy paths sampled by ACKs}}
{\text{number of eligible paths}}.
\]

If tracking distinct sampled paths requires a large per-flow structure in the production controller, keep it strictly inside validation/debug instrumentation or reconstruct it offline from packet traces. It must not be counted as Prism runtime state.

Also record any reason an epoch was skipped, for example:

```text
insufficient_ack_samples
no_eligible_path
oracle_path_resolution_failed
```

Skipped epochs must not silently disappear.

---

## 7. Metrics

The primary metric is **control-state agreement**, because Prism only needs the estimator to select the correct control region rather than reconstruct the full per-path queue vector.

### 7.1 Overall state agreement

\[
\text{Agreement}
=
\frac{
\#\{e : S_{\mathrm{est}}^{(e)} = S_{\mathrm{oracle}}^{(e)}\}
}{
\#\{\text{valid epochs}\}
}.
\]

Report:

- overall agreement;
- agreement per scenario;
- agreement per parameter setting;
- agreement per oracle state.

### 7.2 Three-state confusion matrix

Build a \(3 \times 3\) confusion matrix:

```text
                 Oracle
Estimator     Increase  Hold  Decrease
Increase
Hold
Decrease
```

This is important because different errors have different consequences:

- `Increase -> Hold`: conservative but usually safe;
- `Hold -> Decrease`: unnecessary rate reduction;
- `Decrease -> Hold/Increase`: failure to react to path-wide overload.

Report both counts and row-normalized percentages.

### 7.3 Estimation error

Report absolute errors:

\[
E_{cc}^{(e)}
=
\left|
\hat C_{cc}^{(e)}
-
\hat C_{cc}^{*,(e)}
\right|,
\]

\[
E_{spray}^{(e)}
=
\left|
\hat C_{spray}^{(e)}
-
\hat C_{spray}^{*,(e)}
\right|.
\]

For each component, report:

- median absolute error;
- P90 absolute error;
- P99 absolute error if the number of epochs is sufficient.

Avoid using only relative error because the oracle value may be close to zero. If relative error is included, use a clearly documented stabilizer and treat it as secondary.

### 7.4 Path-coverage analysis

Report the relationship between ACK path coverage and state agreement.

At minimum, bucket epochs into:

```text
coverage <= 25%
25% < coverage <= 50%
50% < coverage <= 75%
coverage > 75%
```

For each bucket, report:

- number of epochs;
- state agreement;
- median/P90 errors.

This directly addresses incomplete path sampling.

### 7.5 Symmetric false-spread rate

For the symmetric scenario, report the fraction of epochs in which the oracle spread is below \(T_{spray}\) but Prism estimates a spread above \(T_{spray}\):

\[
P\left(
\hat C_{spray} \ge T_{spray}
\mid
\hat C_{spray}^{*} < T_{spray}
\right).
\]

This quantifies whether temporal queue variation creates false path imbalance.

---

## 8. Experiment matrix

Reuse existing 128-node Prism experiments to minimize implementation and runtime cost.

### Scenario A: symmetric transient traffic

Purpose:

- test whether temporal queue variation produces false path spread;
- verify that Prism does not frequently enter `Hold` when paths are symmetric.

Recommended configuration:

- 128-node 1:1 fat-tree;
- no failed or throttled core links;
- existing many-to-many workload;
- use the default representative network load already used by the paper.

### Scenario B: path asymmetry

Purpose:

- test whether the estimator detects genuine cross-path imbalance.

Recommended configuration:

- 128-node 1:1 fat-tree;
- 8 failed/throttled core links using the paper's existing failure model;
- existing many-to-many workload.

### Scenario C: mixed congestion

Purpose:

- test whether the estimator distinguishes simultaneous high floor and high spread.

Recommended configuration:

- 128-node 4:1 oversubscribed fat-tree;
- 8 failed/throttled core links;
- existing many-to-many workload at a moderate or high load.

Use existing scripts and workload generators rather than creating new traffic patterns unless necessary.

### Parameter sweep

Use:

\[
\kappa \in \{0.5, 1, 2\},
\]

\[
N_{\min} \in \{1, 3, 6\}.
\]

Keep:

- \(T_{cc}\) fixed at the paper's default;
- \(T_{spray}\) fixed at the paper's default;
- all CC and spraying parameters unchanged.

Use five random seeds, matching the paper's evaluation methodology.

The full matrix is:

```text
3 scenarios
x 3 kappa values
x 3 N_min values
x 5 seeds
= 135 runs
```

If runtime is excessive, first run a smoke-test matrix with one seed, then execute the full matrix after validating correctness.

---

## 9. Required result artifacts

Create the following outputs.

### 9.1 Raw epoch log

One CSV file per run or one safely appendable consolidated CSV.

Suggested path:

```text
results/prism_oracle_validation/raw/
```

### 9.2 Aggregated summary

Generate a summary CSV with one row per:

```text
scenario x kappa x N_min
```

Include:

```text
valid_epochs
skipped_epochs
state_agreement
agreement_increase
agreement_hold
agreement_decrease
median_abs_error_cc_us
p90_abs_error_cc_us
median_abs_error_spray_us
p90_abs_error_spray_us
median_path_coverage
false_spread_rate
```

Suggested path:

```text
results/prism_oracle_validation/summary.csv
```

### 9.3 Main paper figure

Generate one compact figure with preferably three panels:

1. **State agreement** across \(\kappa\) and \(N_{\min}\), grouped by scenario.
2. **P90 absolute error** for \(C_{cc}\) and \(C_{spray}\).
3. **Agreement versus path coverage**, or a normalized confusion matrix.

Reuse the repository's existing plotting utilities, fonts, dimensions, and export format.

Suggested outputs:

```text
figs/prism_oracle_validation.pdf
figs/prism_oracle_validation.png
```

### 9.4 Optional appendix table

Generate a LaTeX table containing the main agreement and error values if the project already has table-generation utilities.

Do not hard-code numerical values into LaTeX. Generate them from the summary CSV.

---

## 10. Implementation plan

Follow this order.

### Step 1: Repository inspection

Before editing:

1. Locate the Prism sender/flow state.
2. Locate the epoch-boundary decision code.
3. Locate entropy-to-path resolution.
4. Locate queue occupancy or queue-delay APIs.
5. Locate the existing experiment runner and aggregation scripts.
6. Locate the existing plotting style utilities.

Provide a short implementation plan before making code changes.

### Step 2: Add a disabled-by-default validation flag

Add a command-line or configuration flag, for example:

```text
-enable_prism_oracle_validation
```

Default must be `false`.

When disabled:

- no oracle path traversal;
- no validation logging;
- no change to packet-level behavior;
- negligible runtime overhead.

### Step 3: Add path-resolution helper

Implement or reuse a helper that returns the forward queues/links for each eligible entropy path.

Requirements:

- deterministic;
- topology-aware;
- compatible with current ECMP/entropy behavior;
- does not modify route state;
- avoids duplicate paths when multiple entropy values resolve to the same route, unless Prism semantically treats them as distinct selectable choices.

Document how duplicates are handled.

### Step 4: Add oracle snapshot computation

At the epoch boundary:

1. resolve eligible paths;
2. calculate instantaneous queueing delay for every path;
3. compute oracle min, max, floor, and spread;
4. apply the same smoothing as Prism;
5. derive oracle state.

Add assertions for:

- non-negative delays;
- valid units;
- at least one eligible path;
- finite values.

### Step 5: Add validation logging

Write structured rows with buffered I/O.

Avoid flushing on every epoch if that substantially changes simulation runtime. Flush at safe intervals or at process exit.

Ensure each parallel run writes to a unique file.

### Step 6: Add aggregation and plotting scripts

The scripts must:

1. validate required columns;
2. reject malformed rows with a clear error;
3. aggregate across flows and seeds;
4. compute confidence intervals or standard error where appropriate;
5. generate the required figure;
6. print a concise textual summary.

### Step 7: Run correctness checks

At minimum:

1. validation disabled versus enabled should produce the same Prism performance metrics within deterministic simulator tolerance;
2. one-flow or one-path test should produce oracle spread approximately zero;
3. identical empty paths should produce floor and spread approximately zero;
4. an artificially congested single path should produce positive oracle spread;
5. congestion added to all paths should increase the oracle floor.

---

## 11. Acceptance criteria

The task is complete only when all of the following hold:

1. The code compiles successfully.
2. Existing Prism experiments still run.
3. Validation is disabled by default.
4. Oracle values never affect Prism decisions.
5. Each valid epoch logs estimator and oracle values.
6. The same smoothing and control thresholds are applied to both.
7. State agreement, confusion matrix, error, and path coverage are computed.
8. The three required scenarios run successfully.
9. Raw and aggregated CSV files are generated.
10. The final figure is generated from the CSV files.
11. Enabling validation does not materially change Prism's original goodput/FCT results.
12. The implementation includes comments explaining the oracle's read-only role.
13. No numerical result is invented or manually inserted.

---

## 12. Paper-facing interpretation

After obtaining results, prepare a concise paragraph using real measured values only.

Use this structure:

```latex
\noindent\textbf{Estimator fidelity.}
Prism summarizes ACK samples rather than maintaining a
per-path queue table, so its extrema may be affected by incomplete
path coverage and temporal queue variation. We therefore compare
its estimates with an oracle that reads the instantaneous queueing
delay of every eligible forward path at each epoch boundary.
Across symmetric, asymmetric, and mixed-congestion settings,
Prism agrees with the oracle control decision in XX--XX\% of
epochs, with P90 floor and spread errors of XX and XX~$\mu$s,
respectively. Agreement remains stable across the evaluated epoch
lengths and minimum sample counts. These results show that Prism
need not reconstruct the complete per-path queue vector; its
constant-state estimator preserves the control information required
for window adaptation.
```

Do not use this paragraph until all `XX` values are replaced with results generated by the validation scripts.

Suggested figure caption:

```latex
\caption{Fidelity of Prism's O(1) estimator against a simulator-side
per-path oracle. Prism preserves the oracle control decision across
symmetric, asymmetric, and mixed-congestion settings despite
incomplete ACK path coverage.}
```

Adjust the claim if the measured agreement is weaker than expected. Report weaknesses honestly, especially if errors concentrate in `Hold` transitions or low-coverage epochs.

---

## 13. Required final Codex report

At the end, provide:

1. A concise summary of the implementation.
2. The exact files modified or added.
3. The oracle queue-delay calculation used.
4. How eligible paths are resolved.
5. How EWMA/hysteresis are matched.
6. Build and run commands.
7. Smoke-test results.
8. Full experiment commands.
9. Paths to raw CSV, summary CSV, and figures.
10. Any unresolved limitations or assumptions.

Do not stop after adding code. Run at least the smoke tests and verify that the generated logs contain plausible values.
