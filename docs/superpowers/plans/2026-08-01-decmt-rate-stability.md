# DecMT Rate-Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reproducible 60-run DecMT rate-stability experiment that compares delivery-rate convergence and steady-state variation against OPS, REPS, and STrack, and evaluates DecMT EWMA sensitivity.

**Architecture:** Create a self-contained `expL_rate_stability` package.  Its runner generates the locked many-to-many workload, invokes the common simulator runner with sink logging, and writes per-run manifests.  Its analysis module parses sink-rate records into 10 us aggregate-delivery bins, computes per-seed stability metrics, and produces deterministic CSV inputs.  The renderer consumes only those CSV inputs and writes the two vector figures.

**Tech Stack:** Python 3 standard library, Bash, existing `prism_eval/common/run_lib.sh`, Matplotlib, pytest, htsim `htsim_uec` and `parse_output`.

## Global Constraints

- Use the existing 128-node `fat_tree_128_1os.topo`, 8 paths, 2 MB 64-to-16 many-to-many workload, 8 ms end time, and `-disable_trim`.
- Use seeds `13, 14, 15, 16, 17` exactly.
- Primary conditions are `failed=0` and `failed=8`; beta sensitivity uses only `failed=8`.
- Primary labels are exactly `OPS`, `REPS`, `STrack`, and `DecMT`.
- The displayed series use 10 us bins and a centered 50 us moving mean; all summary metrics use un-smoothed bins from the 1--6 ms window.
- DecMT v2 parameters are exactly `-prism_smooth_beta 0.3 -prism_hysteresis 0.25 -prism_engage_spread 28 -prism_disengage_spread 20`.
- Beta sweep values are exactly `1.0, 0.5, 0.3, 0.15`, with all non-beta DecMT v2 parameters unchanged.
- Do not alter controller, routing, or packet behavior; this experiment only requests existing sink logging.
- All generated data must be ignored by Git; scripts, tests, README, and PDF/PNG figures follow the repository's existing experiment conventions.

---

### Task 1: Define the experiment package and locked run contract

**Files:**
- Create: `htsim/sim/datacenter/prism_eval/expL_rate_stability/__init__.py`
- Create: `htsim/sim/datacenter/prism_eval/expL_rate_stability/run.py`
- Create: `htsim/sim/datacenter/prism_eval/expL_rate_stability/repro.sh`
- Create: `htsim/sim/datacenter/prism_eval/expL_rate_stability/README.md`
- Create: `htsim/sim/datacenter/prism_eval/expL_rate_stability/tests/__init__.py`
- Create: `htsim/sim/datacenter/prism_eval/expL_rate_stability/tests/test_runner.py`
- Modify: `htsim/sim/datacenter/prism_eval/.gitignore`

**Interfaces:**
- Consumes: `bash prism_eval/common/run_lib.sh CC LB FAILED TOPO SEED CM sink TAG OUTDIR`.
- Produces: `Case`, `cases_for_phase(phase)`, `case_id(case)`, `ensure_workload(path)`, `fixed_environment(case)`, `run_lib_command(case, workload, output_root)`, and a manifest per completed case.
- Data contract: a primary case is `(condition, arm, seed)` and a beta case is `(beta, seed)`; all raw outputs use `rate_<case-id>.sink.txt` and `<case-id>.manifest.json`.

- [ ] **Step 1: Write failing runner-contract tests**

```python
from prism_eval.expL_rate_stability.run import (
    BETA_VALUES, PRIMARY_ARMS, Case, cases_for_phase, ensure_workload,
    fixed_environment, run_lib_command,
)

def test_formal_matrix_has_exactly_sixty_unique_cases():
    cases = cases_for_phase("formal")
    assert len(cases) == 60
    assert len({case.case_id for case in cases}) == 60
    assert {case.arm for case in cases if case.kind == "primary"} == set(PRIMARY_ARMS)
    assert {case.beta for case in cases if case.kind == "beta"} == set(BETA_VALUES)

def test_primary_arm_commands_and_decmt_v2_flags_are_locked(tmp_path):
    case = Case(kind="primary", condition="asymmetric", arm="decmt", seed=13)
    env = fixed_environment(case)
    command = run_lib_command(case, tmp_path / "m2m.cm", tmp_path)
    assert command[2:7] == ["prism", "reps", "8", "fat_tree_128_1os.topo", "13"]
    assert "-disable_trim" in env["EXTRA_ARGS"]
    assert "-prism_smooth_beta 0.3" in env["EXTRA_ARGS"]
    assert env["LOGTIME_US"] == "10"

def test_workload_is_deterministic_and_rejects_conflicting_content(tmp_path):
    path = tmp_path / "m2m.cm"
    digest = ensure_workload(path)
    assert digest == ensure_workload(path)
    path.write_text("conflict\n", encoding="ascii")
    with pytest.raises(ValueError, match="conflicting"):
        ensure_workload(path)
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest -q htsim/sim/datacenter/prism_eval/expL_rate_stability/tests/test_runner.py`

Expected: FAIL during collection because `prism_eval.expL_rate_stability` does not yet exist.

- [ ] **Step 3: Implement the locked runner contract**

Implement the following constants and mappings in `run.py`:

```python
PRIMARY_ARMS = {
    "ops": ("nscc", "oblivious", "OPS", ""),
    "reps": ("nscc", "reps", "REPS", ""),
    "strack": ("strack", "reps", "STrack", ""),
    "decmt": ("prism", "reps", "DecMT",
              "-prism_smooth_beta 0.3 -prism_hysteresis 0.25 "
              "-prism_engage_spread 28 -prism_disengage_spread 20"),
}
BETA_VALUES = (1.0, 0.5, 0.3, 0.15)
SEEDS = (13, 14, 15, 16, 17)
CONDITIONS = {"symmetric": 0, "asymmetric": 8}
```

Generate the same deterministic workload as `many2many.py 64 16 pairs 2000000 128 16`, write a SHA-256 manifest containing the logical command, environment, workload hash, executable hash, and retained sink/stdout/idmap file hashes.  In `fixed_environment`, set `PATHS=8`, `END_MS=8`, `NODES=128`, `MTU=4150`, `LOGTIME_US=10`, and `EXTRA_ARGS=-disable_trim ...`.  Update `run_lib.sh` in Task 2 so `LOGTIME_US` reaches the binary as `-logtime_us`.

Add `repro.sh` with `smoke`, `historical-check`, and `full` phases.  The formal phase executes the 40 primary and 20 beta cases, then invokes the analysis and renderer.  Add README commands and the exact 60-run matrix.  Add `expL_rate_stability/data/` and `expL_rate_stability/data/*.sink.txt` ignore patterns.

- [ ] **Step 4: Run runner tests and static phase checks**

Run: `pytest -q htsim/sim/datacenter/prism_eval/expL_rate_stability/tests/test_runner.py`

Expected: PASS.  Also run:

```bash
python3 htsim/sim/datacenter/prism_eval/expL_rate_stability/run.py --phase smoke --dry-run
python3 htsim/sim/datacenter/prism_eval/expL_rate_stability/run.py --phase formal --dry-run
```

Expected: smoke prints one case; formal prints exactly 60 unique logical commands and writes no data.

- [ ] **Step 5: Commit the runner contract**

```bash
git add htsim/sim/datacenter/prism_eval/.gitignore \
  htsim/sim/datacenter/prism_eval/expL_rate_stability
git commit -m "feat: add DecMT rate stability runner"
```

### Task 2: Add precise sink logging support to the common runner

**Files:**
- Modify: `htsim/sim/datacenter/prism_eval/common/run_lib.sh:18-44`
- Create: `htsim/sim/datacenter/prism_eval/expL_rate_stability/tests/test_run_lib_logtime.py`

**Interfaces:**
- Consumes: optional environment variable `LOGTIME_US` as a decimal-free positive integer string.
- Produces: a `-logtime_us "$LOGTIME_US"` argument only when `LOGTIME_US` is set, without changing the argument vector for existing callers.

- [ ] **Step 1: Write the failing compatibility tests**

```python
SCRIPT = Path("htsim/sim/datacenter/prism_eval/common/run_lib.sh").read_text()

def test_run_lib_supports_opt_in_logtime_without_changing_default_callers():
    assert 'LOGTIME_ARG=""' in SCRIPT
    assert '[ -n "${LOGTIME_US:-}" ]' in SCRIPT
    assert 'LOGTIME_ARG="-logtime_us ${LOGTIME_US}"' in SCRIPT
    assert '${LOGTIME_ARG}' in SCRIPT

def test_rate_stability_runner_sets_ten_microsecond_logtime():
    assert '"LOGTIME_US": "10"' in Path(
        "htsim/sim/datacenter/prism_eval/expL_rate_stability/run.py"
    ).read_text()
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest -q htsim/sim/datacenter/prism_eval/expL_rate_stability/tests/test_run_lib_logtime.py`

Expected: FAIL because `run_lib.sh` has no `LOGTIME_US` handling.

- [ ] **Step 3: Implement the opt-in argument**

Insert directly after `TQD_ARG` in `run_lib.sh`:

```bash
LOGTIME_ARG=""
[ -n "${LOGTIME_US:-}" ] && LOGTIME_ARG="-logtime_us ${LOGTIME_US}"
```

Append `${LOGTIME_ARG}` alongside `${EXTRA_ARGS:-}` in the `htsim_uec` command.  Preserve the current argument order for callers that leave `LOGTIME_US` unset.

- [ ] **Step 4: Run the tests and a legacy dry-run regression check**

Run:

```bash
pytest -q htsim/sim/datacenter/prism_eval/expL_rate_stability/tests/test_run_lib_logtime.py
PATHS=8 END_MS=8 EXTRA_ARGS=-disable_trim bash htsim/sim/datacenter/prism_eval/common/run_lib.sh \
  nscc reps 0 fat_tree_128_1os.topo 13 /tmp/nonexistent.cm sink dry /tmp --help
```

Expected: test PASS; the second command reaches the existing missing-workload error rather than an argument-parsing error, demonstrating that the added optional variable is inert when unset.

- [ ] **Step 5: Commit the logging compatibility change**

```bash
git add htsim/sim/datacenter/prism_eval/common/run_lib.sh \
  htsim/sim/datacenter/prism_eval/expL_rate_stability/tests/test_run_lib_logtime.py
git commit -m "feat: support sink logtime in shared runner"
```

### Task 3: Implement deterministic rate aggregation and stability metrics

**Files:**
- Create: `htsim/sim/datacenter/prism_eval/expL_rate_stability/analyze.py`
- Create: `htsim/sim/datacenter/prism_eval/expL_rate_stability/tests/test_analysis.py`

**Interfaces:**
- Consumes: one decoded `UEC_SINK RATE` text file per case.
- Produces: `parse_sink_rate(path) -> list[tuple[float, int, float]]`, `aggregate_bins(records, bin_us=10) -> list[RateBin]`, `centered_mean(bins, width_us=50) -> list[RateBin]`, `stability_metrics(bins, steady_us=(1000, 6000)) -> StabilityMetrics`, `median_trajectory(series_by_seed) -> list[RateBin]`, and `write_analysis(data_dir, output_dir)`.
- CSV contract: `data/rate_series.csv` columns `kind,condition,arm,beta,seed,time_us,rate_gbps,display_rate_gbps`; `data/stability_summary.csv` has per-seed rows and five-seed aggregate rows.

- [ ] **Step 1: Write failing analysis tests**

```python
def test_aggregate_bins_sums_all_sinks_at_the_same_time():
    records = [(0.000010, 1, 20e9), (0.000010, 2, 30e9), (0.000020, 1, 40e9)]
    bins = aggregate_bins(records, bin_us=10)
    assert [(b.time_us, b.rate_gbps) for b in bins] == [(10.0, 50.0), (20.0, 40.0)]

def test_centered_mean_never_uses_samples_outside_the_half_width():
    bins = [RateBin(10.0, 0.0), RateBin(20.0, 100.0), RateBin(30.0, 0.0)]
    assert [b.rate_gbps for b in centered_mean(bins, width_us=20)] == [50.0, 100.0, 50.0]

def test_stability_metrics_use_unfiltered_steady_window_and_report_settling():
    bins = [RateBin(float(t), 100.0 if t >= 1000 else 20.0) for t in range(0, 6501, 10)]
    metrics = stability_metrics(bins, steady_us=(1000, 6000))
    assert metrics.coefficient_of_variation == pytest.approx(0.0)
    assert metrics.normalized_p95_p5 == pytest.approx(0.0)
    assert metrics.settling_time_us == pytest.approx(1000.0)

def test_insufficient_nonzero_steady_samples_are_invalid():
    metrics = stability_metrics([RateBin(1000.0, 0.0)], steady_us=(1000, 6000))
    assert metrics.valid is False
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest -q htsim/sim/datacenter/prism_eval/expL_rate_stability/tests/test_analysis.py`

Expected: FAIL during collection because `analyze.py` does not exist.

- [ ] **Step 3: Implement parsers, aggregation, and metrics**

Parse only lines with `Type UEC_SINK` and a `Rate` field.  Convert the trailing rate to Gbps, group all sinks into `floor(time_seconds * 1e6 / 10) * 10` bins, and emit zero-valued bins only between the first and last observed bins of a run.  Define the centered mean as an arithmetic mean of bins whose timestamps are at most 25 us from the target bin.

For stability metrics, retain bins with `1000 <= time_us <= 6000` and `rate_gbps > 0`.  Require at least 100 such bins.  Calculate population standard deviation, nearest-rank P5/P95, and the earliest bin from which the next 200 us of bins remain within 10% of the steady mean.  Use `None` for an unavailable settling time and `valid=False` for inadequate input.  Form each displayed primary and beta trajectory by taking the pointwise median across the five seed-aligned raw series, then apply `centered_mean` only to this plotted median.

- [ ] **Step 4: Run the analysis tests**

Run: `pytest -q htsim/sim/datacenter/prism_eval/expL_rate_stability/tests/test_analysis.py`

Expected: PASS.

- [ ] **Step 5: Commit analysis and tests**

```bash
git add htsim/sim/datacenter/prism_eval/expL_rate_stability/analyze.py \
  htsim/sim/datacenter/prism_eval/expL_rate_stability/tests/test_analysis.py
git commit -m "feat: analyze DecMT delivery-rate stability"
```

### Task 4: Render publication figures and verify the complete experiment

**Files:**
- Create: `htsim/sim/datacenter/prism_eval/expL_rate_stability/make_figs.py`
- Create: `htsim/sim/datacenter/prism_eval/expL_rate_stability/tests/test_make_figs.py`
- Modify: `htsim/sim/datacenter/prism_eval/expL_rate_stability/README.md`

**Interfaces:**
- Consumes: `data/rate_series.csv` and `data/stability_summary.csv` produced by `write_analysis`.
- Produces: `figs/figL1_rate_timeseries.{png,pdf}` and `figs/figL2_beta_timeseries.{png,pdf}`.
- Plot constants: `LABELS={"ops":"OPS","reps":"REPS","strack":"STrack","decmt":"DecMT"}` and the established paper colors `tab:gray`, `tab:blue`, `tab:orange`, `tab:green` respectively.

- [ ] **Step 1: Write failing figure tests**

```python
def test_renderer_uses_required_labels_and_type42_embedding():
    source = MAKE_FIGS.read_text()
    for label in ("OPS", "REPS", "STrack", "DecMT"):
        assert label in source
    assert 'mpl.rcParams["pdf.fonttype"] = 42' in source
    assert 'mpl.rcParams["ps.fonttype"] = 42' in source

def test_renderer_writes_both_figures_from_minimal_csv_fixture(tmp_path):
    write_fixture_csvs(tmp_path / "data")
    render(tmp_path / "data", tmp_path / "figs")
    assert (tmp_path / "figs" / "figL1_rate_timeseries.pdf").is_file()
    assert (tmp_path / "figs" / "figL2_beta_timeseries.pdf").is_file()
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `pytest -q htsim/sim/datacenter/prism_eval/expL_rate_stability/tests/test_make_figs.py`

Expected: FAIL during collection because `make_figs.py` does not exist.

- [ ] **Step 3: Implement the renderer**

Set both `mpl.rcParams["pdf.fonttype"]` and `mpl.rcParams["ps.fonttype"]` to 42 before importing `pyplot`.  Render FigL1 as a two-panel, shared-y plot ordered `symmetric`, `asymmetric`, with time in ms on the x-axis and `Aggregate delivery rate (Gbps)` on the y-axis.  Draw the five-seed median trajectory for each primary arm and add only the DecMT 25th--75th-percentile band.  Render FigL2 as one asymmetric panel, with one curve per beta and legend labels `β=1.0`, `β=0.5`, `β=0.3`, `β=0.15`.  Do not put titles inside either plot; use captions/README for scenario context.  Save deterministic PNG and PDF output names from the interface block.

Update README with the exact plotting commands, metric definitions, interpretation thresholds, and an explicit statement that aggregate delivery rate is not a direct packet-departure trace.

- [ ] **Step 4: Run figure and full package tests**

Run:

```bash
pytest -q htsim/sim/datacenter/prism_eval/expL_rate_stability/tests
python3 htsim/sim/datacenter/prism_eval/expL_rate_stability/make_figs.py --selftest
```

Expected: PASS; self-test writes its temporary fixtures only under a temporary directory.

- [ ] **Step 5: Run historical gate, formal matrix, and artifact verification**

Run:

```bash
cd htsim/sim/datacenter
bash prism_eval/expL_rate_stability/repro.sh historical-check
bash prism_eval/expL_rate_stability/repro.sh full
test "$(find prism_eval/expL_rate_stability/data/raw -name '*.sink.txt' | wc -l)" -eq 60
pdffonts prism_eval/expL_rate_stability/figs/figL1_rate_timeseries.pdf
pdffonts prism_eval/expL_rate_stability/figs/figL2_beta_timeseries.pdf
```

Expected: the historical gate reports an exact raw sink-trace hash match before formal runs; all 60 sink traces and manifests exist; both PDFs report embedded `CID TrueType` fonts.

- [ ] **Step 6: Commit figures, docs, and implementation**

```bash
git add htsim/sim/datacenter/prism_eval/expL_rate_stability
git commit -m "feat: add DecMT rate stability evaluation"
```

## Plan Self-Review

- Spec coverage: Tasks 1--2 lock the 60-run simulation contract and existing sink logging; Task 3 implements the exact rate, smoothing, and three stability metrics; Task 4 renders the two specified figures and verifies Type 42 PDF output.
- Placeholder scan: no TBD/TODO markers or unspecified interfaces remain.
- Type consistency: Task 1 produces sink files and manifests; Task 3 consumes those files to produce the two CSVs; Task 4 consumes exactly those CSVs.
