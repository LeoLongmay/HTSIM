# Fixed PRIME ExpA smoke

This is a fixed 24-cell, 64-to-16, 2 MiB ExpA evaluation: OPS (`nscc/oblivious`),
REPS (`nscc/reps`), DecMT (`prism/reps_actual`), and Prime (`nscc/prime`), crossed
with `failed={0,8}` and `seed={13,14,15}`. Every cell uses `PATHS=8`,
`-disable_trim`, and an 8 ms horizon.

See [`strict_reproduction_audit.md`](strict_reproduction_audit.md) for the
paper-to-code evidence matrix and its terminal conclusion: the paper is
underspecified for a strict-controller change, so this audit proposes none.
All PRIME build products, logs, and generated data must remain under this
`prime_smoke` directory; `/tmp` must not be used.

```bash
bash repro.sh --out runs/prime-expa-fixed
python3 report.py --input runs/prime-expa-fixed --output runs/prime-expa-fixed
```

`summary.tsv` contains each cell plus arm/failed aggregates, explicitly retaining
started-but-unfinished flows as censored. It reports completed-flow mean, p50, p95,
and supplemental p99 FCT. Delivered bytes are derived from the exact
end-of-run per-sink delivery summaries, and the reported goodput is delivered bytes over
the fixed 8 ms horizon. An arm/failure aggregate uses total delivered bytes divided
by the sum of its seed horizons (equivalently, mean per-run goodput), not the sum of
independent seed rates. The two PNGs show completed-flow FCT with completion/
censoring annotations, and Prime's selection shares for every observed tuple tier.

Prime writes `PRIME_DIAG` only when the environment variable names an output path.
It records selection and feedback observations without changing the selector. Feedback
is aggregate at the source: an ACK/ECN/NACK/timeout is attributed to its packet's
selected tuple. Prime is a host-only whole-path mapping, not switch-local or per-hop
forwarding and not congestion localization. Both figure footers repeat this results
boundary; the observations should not be interpreted as evidence of a required
performance win.

## Prime topology-coverage validation (separate from ExpA performance)

The fixed 24-cell comparison above remains `PATHS=8` by design and must not be
silently reinterpreted as full source-uplink coverage. Run the following separate,
Prime-only validation to exercise the complete 4 by 4 tuple domain and every source
ToR uplink in this 128-node topology:

```bash
bash validate_paths16.sh --out runs/prime-paths16-validation
```

It runs one `nscc/prime`, `PATHS=16`, `failed=0`, `seed=13` case and rejects any
trace that does not contain all 16 `(source ToR uplink, core uplink)` tuple pairs.
`validation.txt` labels this as topology coverage only; it is not mixed into
`summary.tsv`, the 24-cell figures, or any performance comparison.

`PRIME_DIAG` uses this ten-column TSV schema, in order:
`event_seq`, `time_ps`, `flow`, `event`, `entropy`, `tuple`, `reason`,
`feedback`, `penalty_before`, `penalty_after`. `event_seq` is assigned by the
observation writer only, so it orders same-timestamp diagnostic events without
becoming controller state. Its `penalty_before` and `penalty_after` fields are
slash-separated per-tuple-tier vectors (for example `0/4`), so diagnostics
retain which tuple component changed rather than only a sum.

## Final diagnostic evidence gate

Run the final gate from the repository root. The output directory must be
absent (or otherwise newly created), so this RED precondition must fail before
the matrix is produced:

```bash
test -s htsim/sim/datacenter/prism_eval/expA_delaydriven/prime_smoke/runs/prime-expa-final/summary.tsv
```

Configure and build the dedicated test tree, then check the focused Prime
tests, the complete CTest suite, and the LAPS no-regression subset:

```bash
cmake -S htsim/sim -B htsim/sim/datacenter/prism_eval/expA_delaydriven/prime_smoke/build/strict_reproduction -DENABLE_TESTS=ON
cmake --build htsim/sim/datacenter/prism_eval/expA_delaydriven/prime_smoke/build/strict_reproduction --parallel
ctest --test-dir htsim/sim/datacenter/prism_eval/expA_delaydriven/prime_smoke/build/strict_reproduction -R 'prime_' --output-on-failure
ctest --test-dir htsim/sim/datacenter/prism_eval/expA_delaydriven/prime_smoke/build/strict_reproduction --output-on-failure
ctest --test-dir htsim/sim/datacenter/prism_eval/expA_delaydriven/prime_smoke/build/strict_reproduction -R 'laps_' --output-on-failure
python3 -m unittest htsim/sim/datacenter/prism_eval/expA_delaydriven/prime_smoke/tests/test_report.py -v
bash htsim/sim/datacenter/prism_eval/expA_delaydriven/prime_smoke/validate_paths16.sh --out htsim/sim/datacenter/prism_eval/expA_delaydriven/prime_smoke/runs/prime-paths16-validation
```

Generate and report the fixed matrix, then require all 24 cell rows and both
figures. The final `awk` prints the aggregate Prime diagnostic totals for each
failure setting, making the recorded route/feedback observations explicit.

```bash
bash htsim/sim/datacenter/prism_eval/expA_delaydriven/prime_smoke/repro.sh --out htsim/sim/datacenter/prism_eval/expA_delaydriven/prime_smoke/runs/prime-expa-final
python3 htsim/sim/datacenter/prism_eval/expA_delaydriven/prime_smoke/report.py --input htsim/sim/datacenter/prism_eval/expA_delaydriven/prime_smoke/runs/prime-expa-final --output htsim/sim/datacenter/prism_eval/expA_delaydriven/prime_smoke/runs/prime-expa-final
test "$(awk 'NR>1 {n++} END {print n+0}' htsim/sim/datacenter/prism_eval/expA_delaydriven/prime_smoke/runs/prime-expa-final/summary.tsv)" -ge 24
test -s htsim/sim/datacenter/prism_eval/expA_delaydriven/prime_smoke/runs/prime-expa-final/fig_prime_fct.png
test -s htsim/sim/datacenter/prism_eval/expA_delaydriven/prime_smoke/runs/prime-expa-final/fig_prime_tier_share.png
awk -F '\t' 'NR==1 {for (i=1; i<=NF; i++) h[$i]=i; next} $1=="aggregate" && $2=="Prime" {print "failed=" $3 " selections=" $(h["selection_count"]) " feedback=" $(h["feedback_count"])}' htsim/sim/datacenter/prism_eval/expA_delaydriven/prime_smoke/runs/prime-expa-final/summary.tsv
```

This gate establishes implementation route/feedback correctness and the
reproducibility of this fixed smoke matrix. It does not establish a Prime
performance ordering or reproduce the paper's performance results.

### Committed Task 1/2 diagnostic evidence

The fixed `PATHS=8` smoke matrix, the equal-domain `PATHS=16` comparison, and
the offline lifecycle analysis are separate evidence sets. The latter two are
each 24 cells: OPS, REPS, DecMT, and Prime crossed with `failed={0,8}` and
`seed={13,14,15}`. The `PATHS=16` report also requires all four source-ToR
uplinks (`0,1,2,3`) in each of its six Prime cells.

Keep raw run trees ignored. Generate Task 1/2 outputs in a staging directory
and copy only the summaries and figures into the committed paths:

```bash
stage=htsim/sim/datacenter/prism_eval/expA_delaydriven/prime_smoke/build/prime-diagnostic-stage
python3 htsim/sim/datacenter/prism_eval/expA_delaydriven/prime_smoke/paths16_compare/report.py --input htsim/sim/datacenter/prism_eval/expA_delaydriven/prime_smoke/runs/paths16_compare --output "$stage/paths16"
python3 htsim/sim/datacenter/prism_eval/expA_delaydriven/prime_smoke/penalty_lifecycle/analyze.py --input htsim/sim/datacenter/prism_eval/expA_delaydriven/prime_smoke/runs/expa_paths8_final --output "$stage/lifecycle"
cp "$stage/paths16/prime_paths16_compare.tsv" htsim/sim/datacenter/prism_eval/expA_delaydriven/prime_smoke/archive_data/
cp "$stage/lifecycle/prime_penalty_lifecycle.tsv" htsim/sim/datacenter/prism_eval/expA_delaydriven/prime_smoke/archive_data/
cp "$stage/paths16/fig_prime_paths16_fct.png" htsim/sim/datacenter/prism_eval/expA_delaydriven/prime_smoke/figs/
cp "$stage/lifecycle/fig_prime_penalty_lifecycle.png" htsim/sim/datacenter/prism_eval/expA_delaydriven/prime_smoke/figs/
```

The archive gate is RED until all four committed artifacts exist:

```bash
test -s htsim/sim/datacenter/prism_eval/expA_delaydriven/prime_smoke/archive_data/prime_paths16_compare.tsv
test -s htsim/sim/datacenter/prism_eval/expA_delaydriven/prime_smoke/archive_data/prime_penalty_lifecycle.tsv
test -s htsim/sim/datacenter/prism_eval/expA_delaydriven/prime_smoke/figs/fig_prime_paths16_fct.png
test -s htsim/sim/datacenter/prism_eval/expA_delaydriven/prime_smoke/figs/fig_prime_penalty_lifecycle.png
```

Run the full focused diagnostic set explicitly; the plan-level `unittest
discover` command remains useful but finds zero tests from this root because the
nested test directories are not Python packages:

```bash
ctest --test-dir htsim/sim/datacenter/prism_eval/expA_delaydriven/prime_smoke/build/strict_reproduction -R 'prime_' --output-on-failure
python3 -m unittest discover -s htsim/sim/datacenter/prism_eval/expA_delaydriven/prime_smoke -p 'test_*.py' -v
python3 -m unittest htsim/sim/datacenter/prism_eval/expA_delaydriven/prime_smoke/tests/test_report.py -v
python3 -m unittest htsim/sim/datacenter/prism_eval/expA_delaydriven/prime_smoke/paths16_compare/tests/test_report.py -v
python3 -m unittest htsim/sim/datacenter/prism_eval/expA_delaydriven/prime_smoke/penalty_lifecycle/tests/test_analyze.py -v
```

Two interpretation rules bound this evidence: never pool or reinterpret the
`PATHS=8` and `PATHS=16` conditions, and never treat lifecycle observations
(including resolved-only percentiles with censored episodes retained) as an
algorithmic repair, a Prime performance ordering, or reproduction of the paper.
