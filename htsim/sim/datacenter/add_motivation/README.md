# Motivation Experiments

This directory contains trace-only motivation experiments. M1 measures whether same-entropy ACK
residual delay persists to the next use. M2 measures progress during shadow validation rounds under
fixed-path background load. See `expM1_entropy_quality/README.md` and
`expM2_redistribution_progress/README.md` for exact reproduction commands and evidence boundaries.

Task 1 behavior is not implemented here. Residual-driven token recycling, cache replacement, and
handoff into a new or modified congestion controller are also not implemented. Both experiments
observe the existing Legacy REPS/PRISM execution and analyze it offline; they do not change routing,
recycling, or congestion-control decisions.
