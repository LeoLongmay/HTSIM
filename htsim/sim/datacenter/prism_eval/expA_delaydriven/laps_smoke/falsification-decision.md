# LAPS falsification ladder decision

## Decision

**Conclusion: insufficient evidence.**

The replacement deterministic gates now cover the previously missing T0–T2
boundaries, and T0–T4 pass. This rules out only the specific gated failures:
probe-policy divergence before the first intentionally different ACK, broken
source/sink ACK-to-PIT wiring, the tested selection/probe/AIMD semantics, and
PIT invariant violations observable in this ExpA matrix. It does not prove the
implementation defect-free or distinguish ExpA workload fit from the paper's
unavailable Dragonfly/lossless regime.

**First failed executable gate:** none. Tier 5 remains a feasibility blocker:
the repository requires a separate Dragonfly LAPS port.

## Replacement evidence

| Gate | Result | Evidence |
| --- | --- | --- |
| T0 | Passed. A deterministic paired event fixture records legacy/paperack probe-send timestamps and their first intentionally different ACK; normalized probe timestamps are identical through that event. Strict LAPS remains on its historical per-deadline behavior. | `laps_falsification_ladder` CTest; `test_laps_falsification_ladder.cpp` |
| T1 | Passed. Repeated fixed-path packets traverse `UecSrc → Pipe → UecSink → Pipe → UecSrc`; ACK PID, carried one-way delay, ACK time, composite before/after snapshots, deadline, probe timing, and eligible-send liveness are asserted. | `laps_falsification_ladder` CTest |
| T2 | Passed. The equivalent eight-path fixture covers every selected PID through the same end-to-end event chain, proves non-selected PIT immutability, probe-ACK isolation, and continuous-traffic selectable-path/send liveness. | `laps_falsification_ladder` CTest |
| T3 | Passed. Seeded 10/20 µs Softmax, pending-path exclusion/restoration, and the existing 100→50/50→75 Gbps rate gates pass. The `2*min_delay` cooldown remains labelled pseudocode fidelity/prose divergence. | `laps_falsification_ladder` and `laps_cc_decision` CTests |
| T4 | Passed. Fixed and 24-cell matrix artifacts include observed FCT samples, explicit censoring, exact sink-delivered bytes/goodput, and diagnostics-derived PIT violations. At `failed=8`, LAPS averages 62.333 completed and 1.667 censored flows, 4773.538 µs mean FCT, 5340.530 µs p95 FCT, and 125.814833 Gbps; all LAPS matrix cells report zero PIT invariant violations. | `/tmp/laps-expa-final-fixed.pLYkIy`; `/tmp/laps-expa-final-matrix.aU4zTH` |
| T5 | Blocked by repository capability. No valid Dragonfly LAPS proxy or reproduction was run. | `laps_paper_proxy/README.md` |

The prior `/tmp/laps-tier0-fix.hS4y64`, `/tmp/laps-expa-fixed.rc29Pm`, and
`/tmp/laps-expa-matrix.taMNCt` artifacts and Task 1/2/4 interpretations are
exploratory historical records. They do not contain the paired Tier 0 trace,
end-to-end Tier 1/2 fixtures, or replacement Tier 4 metrics and must not be
used to claim these gates pass.

## Required next evidence

Implement and validate a separate Dragonfly LAPS port with source-routed PID
paths and the paper's material lossless/control-plane semantics. Only then can
a paper-regime comparison change this decision.
