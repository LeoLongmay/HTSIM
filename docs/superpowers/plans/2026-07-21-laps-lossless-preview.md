# Four-Arm LAPS Lossless Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce reproducible OPS/REPS/LAPS/Prism lossless-PFC preview data and three isolated comparison figures before any eight-arm expansion.

**Architecture:** Add one `expL_laps_lossless` harness with a four-arm default and an explicit `--all-baselines` future expansion. Reuse the established Prism metric renderer, but pass only the selected baseline list to preserve a four-entry legend with Prism green and last.

**Tech Stack:** Bash, Python 3, Matplotlib, HTSIM `common/run_lib.sh`.

## Global Constraints

- Preserve `expA_delaydriven` source, data, and figures byte-for-byte.
- Default preview matrix: `ops,reps,laps,prism` × failures `{0,2,4,6,8,10,12}` × seeds `{13,14,15,16,17}` = 140 runs.
- Every invocation uses `-queue_type lossless_input -queue_size_bytes 150000 -pfc_high_bytes 122880 -pfc_low_bytes 92160 -shared_buffer_bytes 33554432`, never `-disable_trim`.
- Preview output stays under `expL_laps_lossless/data` and `expL_laps_lossless/figs`; generated artifacts are not committed.
- Prism is green and last in every preview legend. Do not change LAPS control/recovery or any non-LAPS algorithm implementation.

---

### Task 1: Four-arm experiment harness and plot contract

**Files:**
- Create: `htsim/sim/datacenter/prism_eval/expL_laps_lossless/repro.sh`
- Create: `htsim/sim/datacenter/prism_eval/expL_laps_lossless/make_figs.py`
- Create: `htsim/sim/datacenter/prism_eval/expL_laps_lossless/README.md`
- Create: `htsim/sim/datacenter/prism_eval/expL_laps_lossless/tests/test_repro.sh`
- Create: `htsim/sim/datacenter/prism_eval/expL_laps_lossless/tests/test_make_figs.py`

- [ ] **Step 1: Write failing contracts**

`test_repro.sh` must run `repro.sh --dry-run`, assert exactly 140 command lines, and assert every line contains the literal lossless flags above, no `-disable_trim`, and no `expA_delaydriven`. It must run `repro.sh --all-baselines --dry-run` and assert exactly 280 lines. `test_make_figs.py` must import the module and assert:

```python
assert module.DATA.endswith("expL_laps_lossless/data")
assert module.FIGS.endswith("expL_laps_lossless/figs")
assert [x[0] for x in module.PREVIEW_BASELINES] == ["ops", "reps", "laps", "prism"]
assert module.PREVIEW_BASELINES[-1] == ("prism", "Prism", "prism")
```

- [ ] **Step 2: Confirm RED**

Run `bash htsim/sim/datacenter/prism_eval/expL_laps_lossless/tests/test_repro.sh` and `python3 htsim/sim/datacenter/prism_eval/expL_laps_lossless/tests/test_make_figs.py`. Both must fail because the harness and module are absent.

- [ ] **Step 3: Implement the harness and renderer**

Implement `repro.sh` with `PREVIEW=(ops reps laps prism)`, `ALL=(ops reps swift mswift mnscc strack laps prism)`, and the existing mappings `ops=nscc/oblivious`, `reps=nscc/reps`, `laps=laps/laps`, `prism=prism/reps` (plus the four documented full-mode mappings). Default to preview; only `--all-baselines` selects ALL. Generate the 64-to-16, 2 MB many-to-many matrix into the new data directory and call `common/run_lib.sh` with `PATHS=8`, `END_MS=8`, and an `EXTRA_ARGS` string containing the exact lossless flags.

Implement `make_figs.py` with `PREVIEW_BASELINES = [("ops", "OPS", "ops"), ("reps", "REPS", "reps"), ("laps", "LAPS", "laps"), ("prism", "Prism", "prism")]`; invoke `perf_figs.render_main_perf_split` for average FCT, goodput, and P99 FCT and `render_legend(..., row_counts=[4])`. README must document the 140-run preview, its full-mode expansion, fixed topology/workload/failure scan, values, non-overlap with ExpA, and no generated-artifact commits.

- [ ] **Step 4: Confirm GREEN and commit**

Run the two contract tests. Commit only the five source/test/document files with `feat: add four-arm lossless LAPS preview`.

### Task 2: Preview validation and execution

**Files:** generated only under `htsim/sim/datacenter/prism_eval/expL_laps_lossless/{data,figs}`.

- [ ] **Step 1: Build and smoke**

Build `htsim_uec`; run one cell (`failed=0`, seed `13`) for ops/reps/laps/prism using the exact lossless flags. Require each nonempty `.flow.txt` and reject output containing `LOSSLESS not working!` or `shared-buffer capacity exceeded`.

- [ ] **Step 2: Completion gate**

Use `metrics.fct_stats` on the four smoke files. Report completion fractions and do not run the remaining 136 cells if any fraction is below 1.00.

- [ ] **Step 3: Run and render the preview**

Run `bash htsim/sim/datacenter/prism_eval/expL_laps_lossless/repro.sh` then `python3 htsim/sim/datacenter/prism_eval/expL_laps_lossless/make_figs.py`. Require exactly 140 `expL_{ops,reps,laps,prism}_f*_s*.flow.txt` files and PDF/PNG outputs for `figL1_avg_fct`, `figL1_goodput`, `figL1_p99_fct`, and `figL1_legend`.

- [ ] **Step 4: Artifact handoff**

Inspect the three PDFs and report their absolute paths, run count, completion-gate result, and whether an eight-arm expansion is ready. Do not commit generated data, logs, or figures.

## Plan self-review

- The plan covers default four-arm execution, explicit eight-arm expansion, dry-run contracts, lossless-only commands, isolated outputs, smoke/completion gates, and all three requested metrics.
- No task changes ExpA or congestion-control implementations.
