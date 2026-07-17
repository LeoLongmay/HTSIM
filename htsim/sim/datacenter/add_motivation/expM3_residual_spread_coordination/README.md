# M3 Residual Spread Coordination

M3 is the fixed 18-trial validation of PRISM residual-spread coordination.
It compares `original_prism`, `prism_recycle`, and `full_prism` for the
recoverable and persistent target-pod scenarios at seeds 13, 14, and 15.

Each scenario/seed pair creates one deterministic, long-lived foreground-only
target-pod traffic matrix. The matrix is shared unchanged by all three modes.
All runs use PRISM, `reps_actual`, and 25 Gbps degraded-link capacity. The
recoverable and persistent scenarios intentionally use two and eight degraded
links respectively. No background traffic, link events, or traffic grids are
used.

The target pod has 800 Gbps healthy ingress. Recoverable traffic uses six
distinct 100 Gbps source NICs (a 600 Gbps source-NIC ceiling), strictly below
that capacity; persistent traffic uses twelve distinct source NICs (a 1200 Gbps
source-NIC ceiling), strictly above it. These are source-NIC ceilings, not
configured application offered rates.

Run the six-trial smoke reproduction:

```bash
bash htsim/sim/datacenter/add_motivation/expM3_residual_spread_coordination/repro.sh smoke
```

Run the locked formal matrix:

```bash
bash htsim/sim/datacenter/add_motivation/expM3_residual_spread_coordination/repro.sh full
```

Both reproduction modes rebuild the `htsim_uec` target before running. Each
generated manifest records the simulator binary's SHA-256 for freshness
verification.

The analyzer consumes only M3 manifests and trace files beneath `data/`. It
writes `data/aggregate/epoch_series.csv`, `rounds.csv`, `per_seed_metrics.csv`,
and `summary.csv`. `make_figs.py` reads only those aggregate files and renders
`figs/m3_recoverable.{pdf,png}` and `figs/m3_persistent.{pdf,png}`.

## Terminal-Evidence Verifier

Each terminal `rounds.csv` row includes `replacement_chain_complete` and
`clean_scan_complete`. Replacement-chain evidence requires every same-flow,
same-round invalidation before the terminal to have a later genuine,
ECN-unmarked ACK admission token that wrote a newer generation to the same
physical cache slot, followed by a later same-round retain for that replacement
generation. A clean scan has no such invalidations and requires the latest
same-flow, same-round pre-terminal action for every physical cache slot 0
through 7 to be `retain`. A terminal satisfying neither predicate is rejected
as invalid trace evidence. Terminal semantics are validated across the entire
trace, but only terminals at or after the fixed 1 ms warm-up boundary become
`rounds.csv` evidence, figure markers, or verifier input; earlier terminals
remain validated startup-control observations.

The aggregate-only verifier reads `data/aggregate/per_seed_metrics.csv` and
`data/aggregate/rounds.csv`, first checking the exact 18-run matrix and run-ID
binding. It reports `supported` only when at least two recoverable
`prism_recycle` seeds have a chain-backed progress terminal, at least two
recoverable `full_prism` seeds have a chain-backed progress/no-handoff terminal,
and at least two persistent `full_prism` seeds have replacement-chain or
clean-scan-backed no-progress, applied-handoff terminals. Clean scans are not
recycling evidence. Persistent `original_prism` and `prism_recycle` records
must never report an applied handoff. Goodput, P99 genuine queue delay, and
traffic ratios remain descriptive aggregate fields, not support gates.

Run the verifier without selecting individual seeds:

```bash
python3 htsim/sim/datacenter/add_motivation/expM3_residual_spread_coordination/analyze.py --verify-only
```

It prints either `supported` or `not_supported: <first predicate>` and exits
zero for either valid verdict.

## Historical Output

The final reproduction command was:

```bash
bash htsim/sim/datacenter/add_motivation/expM3_residual_spread_coordination/repro.sh full
```

It produced the locked 18 manifests, 18 coordination traces, and four aggregate
CSVs before admission-slot provenance and chain reconstruction were introduced.
The retained figures are
`figs/m3_recoverable.pdf` and `figs/m3_persistent.pdf` (with matching PNGs).
Every trial fixes the scenario-specific capacity relation: recoverable trials
use two degraded links and persistent trials use eight, each at 25 Gbps against
the 100 Gbps normal-link capacity.

Those historical traces do not contain the required admission provenance and
must not be used for a chain-backed verdict. Regenerate the fixed matrix before
recording a new result. M3 remains a mechanism-validation experiment, not a
substitute for a full performance evaluation.

Remove generated traces and aggregate data while retaining local figures:

```bash
bash htsim/sim/datacenter/add_motivation/expM3_residual_spread_coordination/clean_outputs.sh
```
