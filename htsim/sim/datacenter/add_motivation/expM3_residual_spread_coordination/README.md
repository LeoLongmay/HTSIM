# M3 Residual Spread Coordination

M3 is the fixed 18-trial validation of PRISM residual-spread coordination.
It compares `original_prism`, `prism_recycle`, and `full_prism` for the
recoverable and persistent target-pod scenarios at seeds 13, 14, and 15.

Each scenario/seed pair creates one deterministic, long-lived foreground-only
target-pod traffic matrix. The matrix is shared unchanged by all three modes.
All runs use PRISM, `reps_actual`, eight degraded links, and 25 Gbps degraded
capacity. No background traffic, link events, or traffic grids are used.

Run the six-trial smoke reproduction:

```bash
bash htsim/sim/datacenter/add_motivation/expM3_residual_spread_coordination/repro.sh smoke
```

Run the locked formal matrix:

```bash
bash htsim/sim/datacenter/add_motivation/expM3_residual_spread_coordination/repro.sh full
```

The analyzer consumes only M3 manifests and trace files beneath `data/`. It
writes `data/aggregate/epoch_series.csv`, `rounds.csv`, `per_seed_metrics.csv`,
and `summary.csv`. `make_figs.py` reads only those aggregate files and renders
`figs/m3_recoverable.{pdf,png}` and `figs/m3_persistent.{pdf,png}`.

## Fixed-Matrix Result

The final reproduction command was:

```bash
bash htsim/sim/datacenter/add_motivation/expM3_residual_spread_coordination/repro.sh full
```

It produced the locked 18 manifests, 18 coordination traces, and four aggregate
CSVs. The retained figures are
`figs/m3_recoverable.pdf` and `figs/m3_persistent.pdf` (with matching PNGs).
Every trial fixes the same capacity relation: eight degraded links at 25 Gbps,
against the 100 Gbps normal-link capacity.

The aggregate-only causal verifier was run without selecting individual seeds:

```bash
python3 htsim/sim/datacenter/add_motivation/expM3_residual_spread_coordination/analyze.py --verify-only
```

It emitted:

```text
not_supported: every recoverable/full_prism seed has a completed progress round
```

The fixed 18-run matrix is complete, but `rounds.csv` is header-only, so the
required all-seed recoverable progress evidence is absent. This result means the
current small setup did not demonstrate the coordination mechanism; it is not a
claim about full PRISM performance evaluation. M3 remains a mechanism-validation
experiment, not a substitute for a full performance evaluation.

Remove generated traces and aggregate data while retaining local figures:

```bash
bash htsim/sim/datacenter/add_motivation/expM3_residual_spread_coordination/clean_outputs.sh
```
