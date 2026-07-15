# M1 Entropy-Quality Persistence

M1 tests whether same-epoch residual delay on a genuine ECN-unmarked ACK predicts a high residual
on the next genuine ACK for the same flow and entropy. The simulator remains Legacy REPS with NSCC;
analysis does not feed a classification back into path selection or congestion control.

## Reproduction

Run all commands from `/home/leo/htsim`.

```bash
# Build the simulator and binary-log decoder.
cmake --build htsim/sim/build --target htsim_uec parse_output -j2

# Two-run harness smoke test (one symmetric and one gray-capacity run, seed 13).
bash htsim/sim/datacenter/add_motivation/expM1_entropy_quality/repro.sh smoke

# Calibration seeds 101, 102, and 103 over all configured cells.
bash htsim/sim/datacenter/add_motivation/expM1_entropy_quality/calibrate.sh

# Analyze calibration only and atomically lock the qualifying formal pair.
python3 htsim/sim/datacenter/add_motivation/expM1_entropy_quality/analyze.py \
  --calibration --select-formal

# Run exactly the selected symmetric/gray pair at seeds 13 through 17.
bash htsim/sim/datacenter/add_motivation/expM1_entropy_quality/repro.sh full

# Analyze formal data only. This command never modifies configs/formal.csv.
python3 htsim/sim/datacenter/add_motivation/expM1_entropy_quality/analyze.py --formal

# Render only from formal aggregate CSVs, never from traces or manifests.
python3 htsim/sim/datacenter/add_motivation/expM1_entropy_quality/make_figs.py --render
```

The evidence policy is fixed in code and has no CLI overrides:

- residual-high means `residual_ps >= 14,000,000` (`14 us`);
- completion rate is at least `0.99` for every gray row and load-matched symmetric control;
- at least `0.75` of flows each cover at least `6` entropies and `2` resolved physical paths;
- unmatched next-use rate is at most `0.25` for every gray row and control;
- the future-high probability given current-high is at least `0.10` in every formal seed and has at
  least `2` contributing `(run_id, flow_id)` clusters;
- the flow-cluster bootstrap uses seed `20260714`, `10,000` samples, and the `2.5/97.5` percentiles
  for a `0.95` confidence interval; its risk-ratio lower bound must be strictly greater than `1.0`;
- formal seeds are exactly `13,14,15,16,17`; and
- loss/freezing clearance requires valid auxiliary completion at least `0.99` and zero retransmitted
  genuine ECN-unmarked high-residual ACKs.

## Outputs

Raw Task 7 run outputs and aggregate tables stay below the requested phase directory:

| Output | Definition |
| --- | --- |
| `data/calibration/summary.csv` | One row per calibration run, including phi, persistence, coverage, token, completion, goodput, and P99 FCT values. |
| `data/calibration/calibration_selection.csv` | Eligibility and failed predicates for every gray cell; identifies the selected cell or records `no_qualifying_cell`. |
| `configs/formal.csv` | Atomic calibration-only selection output: one symmetric and one gray row for each seed `13,14,15,16,17`. |
| `data/formal/summary.csv` | One row per formal run with the same metric schema. |
| `data/formal/ecdf.csv` | One genuine ECN-unmarked ACK residual per row for panel 1. |
| `data/formal/next_use.csv` | Current/next ACK identity, residual, interval ps/epochs, match status, and explicit unmatched reason. |
| `data/formal/conditioning.csv` | Flow-balanced current-low/current-high future-high probabilities and 10,000-sample flow-cluster percentile intervals for panel 2. |
| `data/formal/token_detail.csv` | Exact admission ACK, token ID, later dequeue, selected ACK, and unmatched reason for each Legacy token. |
| `data/formal/tokens.csv` | Shadow exposure and rejected-token future-high aggregate denominators/rates for panel 3. |
| `data/formal/coverage.csv` | Per-flow distinct entropy and resolved physical-path coverage. |
| `data/formal/group_direction.csv` | Entropy-group and deduplicated physical-path-group persistence checks. |
| `data/formal/formal_result.csv` | `accepted`, every fixed evidence constant/rule, bootstrap risk-ratio bounds, arm-specific predicates, and explicit `failed_predicates`. |
| `figs/m1_entropy_quality.{png,pdf}` | Three-panel formal figure rendered from aggregate CSVs only. |

`phi` is `P(residual >= 14 us | genuine ACK, ECN=0)`. A next-use match is the next genuine ACK with
the same `(flow_id, entropy)`, with no elapsed-time cap; its residual uses its own attached epoch
floor. Conditioning probabilities are means of per-flow rates so packet-heavy flows do not dominate.
Risk ratio is `P(next high | current high) / P(next high | current low)`. Empty or undefined
denominators remain blank with an invalid reason where applicable; unavailable simulator auxiliary
data is never replaced by zero.

Formal acceptance requires gray phi above its load-matched symmetric control in every seed and a
10,000-resample flow-cluster risk-ratio lower bound strictly above one. Every gray row and every
load-matched symmetric control must independently pass completion, nonzero unmarked denominator,
flow entropy/path coverage, unmatched matching, and loss/freezing gates. Gray persistence must also
pass the fixed future-high, entropy-direction, and deduplicated-path-direction rules. Any failed
condition produces `accepted=0`; control failures use `control_`-prefixed predicate names.

## Selection And Negative Results

A calibration cell qualifies only if every seed has completion at least `0.99`, a nonzero unmarked
denominator, at least 75% of flows covering six entropies and two resolved physical paths, gray phi
above the load-matched control, risk-ratio direction above one, and no loss/freezing signature.
Ranking maximizes the minimum seed-level phi increase, then prefers fewer degraded links, higher
capacity, and lexicographically lower scenario ID as the only deterministic final tie-break.

If no cell qualifies, `calibration_selection.csv` records `no_qualifying_cell` and the explicit
reasons. The command exits nonzero and leaves `configs/formal.csv` unchanged. Criteria are not
relaxed. Likewise, observing only `phi > 0` is a negative persistence result, not evidence that
residual-aware selection would help performance.

## Scope

ACK residuals, ECN bits, Legacy token lifecycle events, path IDs, and simulator flow events are
observed facts. "Shadow rejected" is an offline classification: an actual Legacy token whose linked
admission ACK was genuine, unmarked, and high residual. It does not mean the simulator rejected,
recycled, invalidated, or rerouted that token.

Task 1 behavior, residual-driven recycling, cache replacement, controller handoff, and any new
congestion-control action are explicitly excluded from M1.
