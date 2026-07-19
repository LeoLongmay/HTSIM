# Prism Hold-Episode Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible, read-only 12-run analysis that tests whether the feedback at Prism Hold entry separates recovering from ineffective Hold episodes.

**Architecture:** `uec.cpp` gains an opt-in ACK trace that only serializes already-computed values. A new `prism_eval/expK_hold_episode` experiment owns the fixed case matrix, trace parsing, episode aggregation, figure, and reproduction entrypoint. The offline analyzer consumes only `PRISM_EPOCH` and `PRISM_HOLD_TRACE`; it has no simulator or controller dependency.

**Tech Stack:** C++17 simulator, Python 3 standard library, matplotlib, Bash, pytest.

## Global Constraints

- The trace must not mutate congestion-control, REPS cache, load-balancing, or path-selection state.
- Existing `PRISM_PATHRTT` and `PRISM_EPOCH` formats must remain byte-compatible.
- Run exactly `f0`, `asymmetric`, `incast`, and `trimming`, with seeds 13, 14, and 15; do not add sweeps.
- Use default Prism plus REPS in every run; trimming disables `-disable_trim`, and loss decomposition remains disabled.
- An episode starts only on a per-flow transition from non-HOLD to HOLD.
- Use one base-RTT pre-window and two base-RTT post windows; never infer a result from an incomplete episode.
- Raw data and rendered figures are gitignored; code, tests, the run entrypoint, and README are tracked.

---

## File Structure

| Path | Responsibility |
| --- | --- |
| `htsim/sim/uec.cpp` | Emit `PRISM_HOLD_TRACE` ACK records when explicitly enabled. |
| `htsim/sim/datacenter/prism_eval/expK_hold_episode/run.py` | Lock and execute the 12-case matrix, then write a per-run manifest. |
| `htsim/sim/datacenter/prism_eval/expK_hold_episode/analyze.py` | Parse raw logs, extract episodes, classify descriptive outcomes, and write CSV summaries. |
| `htsim/sim/datacenter/prism_eval/expK_hold_episode/make_figs.py` | Render the single Hold-episode figure from derived CSVs. |
| `htsim/sim/datacenter/prism_eval/expK_hold_episode/repro.sh` | One-command build guard, run, analysis, and rendering entrypoint. |
| `htsim/sim/datacenter/prism_eval/expK_hold_episode/tests/` | Unit coverage for trace parsing, episode windows, classifications, and locked matrix. |
| `htsim/sim/datacenter/prism_eval/expK_hold_episode/.gitignore` | Ignore generated raw traces, CSVs, temporary workloads, and figures. |
| `htsim/sim/datacenter/prism_eval/expK_hold_episode/README.md` | Record the exact cases, definitions, output paths, and reproduction command. |

### Task 1: Opt-In Hold ACK Trace

**Files:**
- Modify: `htsim/sim/uec.cpp:1480-1560`
- Create: `htsim/sim/datacenter/prism_eval/expK_hold_episode/tests/test_hold_trace_cli.sh`

**Interfaces:**
- Consumes: environment variable `PRISM_HOLD_TRACE`.
- Produces: headerless CSV rows with exactly eight fields:
  `time_ns,flow_id,valid_delay_sample,qdelay_ns,base_rtt_ns,ecn,newly_acked_bytes,cwnd_bytes`.
- Compatibility: when `PRISM_HOLD_TRACE` is unset, the simulator creates no trace and follows the existing ACK path exactly.

- [ ] **Step 1: Write the failing CLI trace-contract test**

Create `tests/test_hold_trace_cli.sh`. It must create a temporary two-flow `.cm`, run `htsim_uec` once from `sim/datacenter` with `PRISM_HOLD_TRACE="$tmp/hold.csv"`, and require a nonempty trace. Validate every row with:

```bash
awk -F, '
  NF != 8 { exit 1 }
  $1 !~ /^[0-9]+$/ || $2 !~ /^[0-9]+$/ || $3 !~ /^[01]$/ { exit 1 }
  $4 !~ /^[0-9]+$/ || $5 !~ /^[0-9]+$/ || $6 !~ /^[01]$/ { exit 1 }
  $7 !~ /^[0-9]+$/ || $8 !~ /^[0-9]+$/ { exit 1 }
  $7 > 0 { seen_progress = 1 }
  END { exit !(NR > 0 && seen_progress) }
' "$tmp/hold.csv"
```

The test is expected to fail before the trace exists because `hold.csv` is absent.

- [ ] **Step 2: Run the test to verify the expected failure**

Run:

```bash
bash htsim/sim/datacenter/prism_eval/expK_hold_episode/tests/test_hold_trace_cli.sh
```

Expected: nonzero exit because `PRISM_HOLD_TRACE` is not implemented.

- [ ] **Step 3: Emit the trace without affecting ACK behavior**

In `UecSrc::processAck`, after `delay` and `_prism_genuine_sample` have been established and before any code consumes the values for diagnostics, add a function-local static `std::ofstream*` initialized from `getenv("PRISM_HOLD_TRACE")`. For every ACK, write:

```cpp
timeAsNs(eventlist().now()) << ',' << flowId() << ','
<< (_prism_genuine_sample ? 1 : 0) << ','
<< timeAsNs(_prism_genuine_sample ? delay : 0) << ','
<< timeAsNs(_base_rtt) << ',' << (pkt.ecn_echo() ? 1 : 0) << ','
<< newly_recvd_bytes << ',' << _cwnd << '\n';
```

Flush the opt-in stream after each record, matching existing read-only trace behavior. Do not add members, update counters, or change control flow. Do not edit `PRISM_PATHRTT` or `PRISM_EPOCH`.

- [ ] **Step 4: Build and run the trace-contract test**

Run:

```bash
cmake -S htsim/sim -B htsim/sim/build
cmake --build htsim/sim/build -j2 --target htsim_uec
bash htsim/sim/datacenter/prism_eval/expK_hold_episode/tests/test_hold_trace_cli.sh
```

Expected: build succeeds and the test exits 0.

- [ ] **Step 5: Commit Task 1**

```bash
git add htsim/sim/uec.cpp htsim/sim/datacenter/prism_eval/expK_hold_episode/tests/test_hold_trace_cli.sh
git commit -m "feat: add read-only Prism Hold trace"
```

### Task 2: Episode Parser and Outcome Aggregation

**Files:**
- Create: `htsim/sim/datacenter/prism_eval/expK_hold_episode/analyze.py`
- Create: `htsim/sim/datacenter/prism_eval/expK_hold_episode/tests/test_analyze.py`

**Interfaces:**
- Consumes: one manifest JSON and its `.epoch.csv` and `.hold.csv` paths.
- Produces: `extract_episodes(manifest: dict, epochs: list[Epoch], acks: list[Ack]) -> list[dict]`.
- Produces per-episode keys: `scenario`, `seed`, `flow_id`, `entry_time_ns`, `f_entry_ns`, `s_entry_ns`, `status`, `outcome`, and all `pre_`, `post1_`, `post2_` window metrics.

- [ ] **Step 1: Write failing unit tests for window metrics and transition handling**

Create fixtures with base RTT 100 ns and target values 14 ns. Test these behaviors:

```python
def test_extracts_only_nonhold_to_hold_transition(tmp_path):
    # Regions INCREASE, HOLD, HOLD produce exactly one episode at the first HOLD.
    assert [row["entry_time_ns"] for row in rows] == [200]

def test_uses_adjacent_base_rtt_windows_and_ack_bytes(tmp_path):
    # pre=(100,200], post1=(200,300], post2=(300,400].
    assert row["pre_ack_rate_bps"] == 80_000_000
    assert row["post1_low_support"] == 1.0
    assert row["post2_high_tail"] == 0.0

def test_marks_missing_second_post_window_incomplete(tmp_path):
    assert row["status"] == "incomplete"
    assert row["outcome"] == "incomplete"

def test_assigns_recovered_ineffective_and_mixed_without_threshold_fit(tmp_path):
    assert outcomes == ["recovered", "ineffective", "mixed"]
```

The fixture trace must include invalid-delay ACKs with positive acknowledged bytes, proving that ACK progress uses all ACKs while support/tail use only valid samples.

- [ ] **Step 2: Run the tests to verify the expected failure**

Run:

```bash
pytest -q htsim/sim/datacenter/prism_eval/expK_hold_episode/tests/test_analyze.py
```

Expected: collection failure because `analyze.py` does not exist.

- [ ] **Step 3: Implement strict parsing and episode extraction**

Implement immutable `Epoch` and `Ack` dataclasses and these public functions:

```python
def load_epochs(path: Path) -> list[Epoch]: ...
def load_hold_acks(path: Path) -> list[Ack]: ...
def extract_episodes(manifest: dict, epochs: list[Epoch], acks: list[Ack]) -> list[dict]: ...
def write_aggregate(rows: list[dict], output_dir: Path) -> None: ...
```

`load_epochs` accepts the existing first nine `PRISM_EPOCH` columns and ignores optional later columns. `load_hold_acks` rejects rows not containing exactly eight numeric/binary fields. Sort both streams by `(flow_id, time_ns)`.

For an entry epoch at time `t` with `base_rtt_ns=b`, use exact half-open intervals `pre=(t-b,t]`, `post1=(t,t+b]`, and `post2=(t+b,t+2b]`. Mark `incomplete` when no ACK trace record reaches `t+2b`. For each window, sum all `newly_acked_bytes`; only valid samples contribute to delay fractions. A fraction with no valid samples is empty (`None` in memory and blank in CSV), not zero.

Set `low_support` from `qdelay_ns <= t_cc_ns` and `high_tail` from `qdelay_ns >= f_entry_ns + t_spray_ns`. A complete row is:

```python
recovered = (
    post1_ack_rate >= pre_ack_rate and post2_ack_rate >= pre_ack_rate
    and post1_high_tail < pre_high_tail and post2_high_tail < pre_high_tail
    and post2_low_support >= pre_low_support
)
ineffective = (
    post2_high_tail >= pre_high_tail and post2_ack_rate <= pre_ack_rate
)
```

Use `mixed` when neither predicate holds. If a required valid-sample fraction is empty, use `mixed` and record `missing_delay_support=1` rather than inventing a value.

- [ ] **Step 4: Verify parser and aggregation tests pass**

Run:

```bash
pytest -q htsim/sim/datacenter/prism_eval/expK_hold_episode/tests/test_analyze.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 2**

```bash
git add htsim/sim/datacenter/prism_eval/expK_hold_episode/analyze.py htsim/sim/datacenter/prism_eval/expK_hold_episode/tests/test_analyze.py
git commit -m "feat: analyze Prism Hold episodes"
```

### Task 3: Locked Matrix Runner and Reproduction Entry Point

**Files:**
- Create: `htsim/sim/datacenter/prism_eval/expK_hold_episode/run.py`
- Create: `htsim/sim/datacenter/prism_eval/expK_hold_episode/repro.sh`
- Create: `htsim/sim/datacenter/prism_eval/expK_hold_episode/.gitignore`
- Create: `htsim/sim/datacenter/prism_eval/expK_hold_episode/tests/test_run.py`

**Interfaces:**
- `locked_cases() -> tuple[Case, ...]` returns exactly 12 cases.
- `run.py --output PATH` creates `{tag}.epoch.csv`, `{tag}.hold.csv`, `{tag}.flow.txt`, and `{tag}.manifest.json` per case.
- `repro.sh` runs the full matrix, invokes `analyze.py`, then invokes `make_figs.py`.

- [ ] **Step 1: Write the failing locked-matrix test**

Create `test_run.py`:

```python
def test_locked_cases_are_exactly_the_four_approved_scenarios():
    cases = run.locked_cases()
    assert len(cases) == 12
    assert {(c.scenario, c.seed) for c in cases} == {
        (scenario, seed)
        for scenario in ("f0", "asymmetric", "incast", "trimming")
        for seed in (13, 14, 15)
    }
    assert next(c for c in cases if c.scenario == "f0").failed == 0
    assert next(c for c in cases if c.scenario == "asymmetric").failed == 8
    assert next(c for c in cases if c.scenario == "incast").fanin == 64
    assert next(c for c in cases if c.scenario == "trimming").disable_trim is False
```

Also assert every case sets `t_cc_us == 14`, `t_spray_us == 14`, and `loss_decomp is False`.

- [ ] **Step 2: Run the test to verify the expected failure**

Run:

```bash
pytest -q htsim/sim/datacenter/prism_eval/expK_hold_episode/tests/test_run.py
```

Expected: collection failure because `run.py` does not exist.

- [ ] **Step 3: Implement the runner and manifests**

Define a frozen `Case` dataclass and `locked_cases()` with these fixed values:

```python
SEEDS = (13, 14, 15)
T_CC_US = 14
T_SPRAY_US = 14
```

For `f0` and `asymmetric`, generate `m2m.cm` with `many2many.py 64 16 pairs 2000000 128 16`, set `END_MS=8`, add `-disable_trim`, and set `failed` to 0 or 8. For `incast`, generate `incast_64.cm` with `incast.py 64 0 1000000 128 16`, set `END_MS=8`, and add `-disable_trim`. For `trimming`, reuse `m2m.cm`, set `END_MS=2`, omit `-disable_trim`, and set `failed=8`.

Call `prism_eval/common/run_lib.sh` with `cc=prism`, `lb=reps`, `PATHS=8`, `PRISM_EPOCH=<tag>.epoch.csv`, and `PRISM_HOLD_TRACE=<tag>.hold.csv`. Pass `-target_q_delay 14` through `EXTRA_ARGS`; do not pass any coordination, recycling, or loss-decomposition flag. Write a manifest beside each case containing the `Case` fields, output names, and `schema_version=1`.

`repro.sh` must run the Python unit tests first, check `htsim_uec` and `parse_output`, then call:

```bash
python3 "$HERE/run.py" --output "$HERE/data"
python3 "$HERE/analyze.py" --input "$HERE/data" --output "$HERE/data/aggregate"
python3 "$HERE/make_figs.py" --input "$HERE/data/aggregate" --output "$HERE/figs/hold_episode.pdf"
```

Ignore `data/`, `figs/*.pdf`, `figs/*.png`, and Python bytecode.

- [ ] **Step 4: Verify matrix locking tests pass**

Run:

```bash
pytest -q htsim/sim/datacenter/prism_eval/expK_hold_episode/tests/test_run.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 3**

```bash
git add htsim/sim/datacenter/prism_eval/expK_hold_episode/run.py htsim/sim/datacenter/prism_eval/expK_hold_episode/repro.sh htsim/sim/datacenter/prism_eval/expK_hold_episode/.gitignore htsim/sim/datacenter/prism_eval/expK_hold_episode/tests/test_run.py
git commit -m "feat: add Hold episode experiment matrix"
```

### Task 4: Summary Figure, Documentation, and Full Verification

**Files:**
- Create: `htsim/sim/datacenter/prism_eval/expK_hold_episode/make_figs.py`
- Create: `htsim/sim/datacenter/prism_eval/expK_hold_episode/tests/test_make_figs.py`
- Create: `htsim/sim/datacenter/prism_eval/expK_hold_episode/README.md`

**Interfaces:**
- Consumes: `episode_rows.csv` and `scenario_summary.csv` produced by `write_aggregate`.
- Produces: `figs/hold_episode.pdf` and `.png`.
- The figure uses only complete episodes and annotates each scenario with complete/incomplete coverage.

- [ ] **Step 1: Write the failing figure-input test**

Create a two-scenario synthetic `episode_rows.csv` and `scenario_summary.csv`, then test:

```python
def test_render_creates_pdf_png_and_coverage_annotation(tmp_path):
    out = tmp_path / "hold_episode.pdf"
    make_figs.render(tmp_path, out)
    assert out.exists() and out.stat().st_size > 0
    assert out.with_suffix(".png").exists()
```

The synthetic summary must include an `incast` row with zero complete episodes and assert that the generated figure source includes the exact text `insufficient complete Hold episodes`.

- [ ] **Step 2: Run the test to verify the expected failure**

Run:

```bash
pytest -q htsim/sim/datacenter/prism_eval/expK_hold_episode/tests/test_make_figs.py
```

Expected: collection failure because `make_figs.py` does not exist.

- [ ] **Step 3: Implement a compact four-panel figure and README**

Implement `render(input_dir: Path, output_pdf: Path) -> None` with four panels:

1. Complete/incomplete/recovered/ineffective/mixed episode counts per scenario.
2. Entry `F` versus `S` scatter, colored by descriptive outcome.
3. `pre`, `post1`, `post2` low-support and high-tail medians for recovered and ineffective episodes.
4. Corresponding normalized ACK-progress medians (`window_rate / pre_rate`).

Panel 2 and the outcome panels must omit a category with no complete samples and replace it with `insufficient complete Hold episodes`; do not draw a zero-valued result as evidence.

Write README sections titled `Question`, `Fixed matrix`, `Episode definition`, `Outputs`, and `Reproduce`. State that results are observational and do not change the controller. Include only:

```bash
cd htsim/sim/datacenter
bash prism_eval/expK_hold_episode/repro.sh
```

- [ ] **Step 4: Run focused and full checks**

Run:

```bash
pytest -q htsim/sim/datacenter/prism_eval/expK_hold_episode/tests
cmake --build htsim/sim/build -j2 --target htsim_uec
bash htsim/sim/datacenter/prism_eval/expK_hold_episode/repro.sh
git diff --check
```

Expected: all tests pass, exactly 12 manifests exist, aggregate CSVs exist, and both figure formats are nonempty.

- [ ] **Step 5: Commit Task 4**

```bash
git add htsim/sim/datacenter/prism_eval/expK_hold_episode/make_figs.py htsim/sim/datacenter/prism_eval/expK_hold_episode/tests/test_make_figs.py htsim/sim/datacenter/prism_eval/expK_hold_episode/README.md
git commit -m "feat: render Prism Hold episode analysis"
```
