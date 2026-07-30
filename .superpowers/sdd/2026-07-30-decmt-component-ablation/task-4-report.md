# Task 4 report — ExpJ DecMT component ablation

## Scope delivered

- Added `expJ_decmt_ablation/README.md`, documenting the locked `4 x 2 x 10 =
  80` case matrix, `failed=8` main condition, `failed=0` symmetric control,
  every arm's exact controller/target/flag definition, metrics, output paths,
  commands, and the non-outcome-asserting causal interpretation.
- Made `repro.sh` enter its own directory and list the reproducible ordered
  stages literally as `run.py smoke`, `run.py formal`, `analyze.py`, and
  `make_figs.py`.
- Added the entry-point ordering contract to `tests/test_runner.py`.

## Test evidence

The new contract was first run before the entry-point adjustment and failed as
intended with `ValueError: substring not found` for `run.py smoke`; the quoted
script path prevented the required literal contract from matching. After the
entry-point update:

```text
python3 -m pytest -q .../expJ_decmt_ablation/tests/test_runner.py
5 passed in 0.07s
```

The required real smoke run completed all four `failed=8, seed=13` arms.
Direct log validation found `starts=64 finishes=64` for each of
`original_nscc`, `matched_nscc`, `floor_only`, and `decmt`.

```text
python3 -m pytest -q tests ../common/tests/test_metrics.py
23 passed in 2.98s
```

## Formal reproduction and products

`python3 run.py formal` completed the locked 80-case matrix in about 27 seconds
(runner wall time across the terminal polling intervals). `python3 analyze.py`
completed in 9.2 seconds and `python3 make_figs.py` in 1.9 seconds. A final
`bash repro.sh` reran the ordered entry point against the immutable/reused
bundles and regenerated the summaries and figure.

Validation found:

- 80 `data/formal/*.manifest.json` files and 80 formal flow logs;
- `data/aggregate/per_seed.csv`: 81 lines (header plus 80 rows);
- `data/aggregate/summary.csv`: 9 lines (header plus 8 arm/control rows);
- `figs/figJ1_decmt_ablation.pdf`: 20,187 bytes;
- `figs/figJ1_decmt_ablation.png`: 139,335 bytes.

Primary figures:

- `htsim/sim/datacenter/prism_eval/expJ_decmt_ablation/figs/figJ1_decmt_ablation.pdf`
- `htsim/sim/datacenter/prism_eval/expJ_decmt_ablation/figs/figJ1_decmt_ablation.png`

## Runtime notes and concerns

No simulator rebuild was required: the experiment used the configured binary
at `htsim/sim/build/datacenter/htsim_uec`. Matplotlib warned that
`~/.config/matplotlib` was not writable and used a temporary cache under
`/tmp`; rendering still exited successfully and both nonempty figure products
were verified. No other issues were observed.

## Review round 1 corrections

The review identified two scoped reproducibility-package issues. The README
had called P99 “nearest-rank,” while the implemented `metrics.fct_stats`
selects sorted completion time at zero-based `round(0.99 * (n - 1))`. The
README now states that exact rule (and the fixed-64-flow index, 62). A new
contract constructs 64 ordered FCTs, verifies the implementation returns the
63rd order statistic, and requires the README to document the same rule.

The aggregate CSV writer now passes `lineterminator="\n"` to `csv.DictWriter`.
A new aggregation contract rejects CRLF in either generated table. Before the
fixes, the targeted test run produced the expected two failures: the README
did not contain the rounded-index definition, and both generated tables
contained `\r\n`. After the fixes:

```text
python3 -m pytest -q tests/test_runner.py tests/test_analysis.py
12 passed in 1.71s

python3 -m pytest -q tests ../common/tests/test_metrics.py
25 passed in 3.36s
```

`python3 analyze.py` regenerated the two formal aggregate CSVs in 8.9 seconds,
and `python3 make_figs.py` regenerated the primary figure in 1.8 seconds.
Final direct validation confirmed 80 manifests and 80 complete (64 START/64
FINISH) flow logs, 80 per-seed rows, 8 summary rows, LF-only aggregate CSVs,
and nonempty `figJ1_decmt_ablation.{pdf,png}` products (20,187 and 139,335
bytes). Matplotlib repeated the harmless temporary-cache warning noted above.
