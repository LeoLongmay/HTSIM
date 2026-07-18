# ExpA Delay-Driven LAPS Overlay — Implementation Plan

> **For Codex:** Follow the implementation tasks in order. Keep experiment outputs untracked; commit only scripts, plotting code, and tests.

**Goal:** Run only the 35 LAPS cells under ExpA delay-driven settings and render new LAPS-overlay performance figures without changing the existing seven-baseline figures or their inputs.

**Scope and invariants**

- Work in `htsim/sim/datacenter/prism_eval/expA_delaydriven/`.
- Reuse `data/m2m.cm` and write only `expA_laps_f<failed>_s<seed>` artifacts in the existing `data/` directory.
- Matrix: failed links `0 2 4 6 8 10 12` × seeds `13 14 15 16 17` = 35 cells.
- LAPS invocation is always `-sender_cc_algo laps -load_balancing_algo laps`, 8 paths, 8 ms, `-disable_trim`.
- Never overwrite an existing LAPS result. Never rerun or modify data for the seven existing baselines.
- Existing `figA1dd_*.pdf/png` files remain byte-identical.
- New figures place LAPS purple immediately before Prism; Prism remains green and final in the legend.

---

### Task 1: Add the fail-closed LAPS-only ExpA runner

**Files:**

- Create: `htsim/sim/datacenter/prism_eval/expA_delaydriven/repro_laps.sh`
- Create: `htsim/sim/datacenter/prism_eval/expA_delaydriven/tests/test_repro_laps.sh`

**Step 1: Write the failing tests**

The shell test must:

1. Run `repro_laps.sh --dry-run` and assert exactly 35 unique LAPS commands/tags.
2. Assert every command has the fixed matrix, `laps laps` CC/LB pair, 8 paths, 8 ms, and `-disable_trim`.
3. Put a sentinel `expA_laps_f0_s13.flow.txt` in a disposable test output directory, invoke real mode with a stub `RUN_LIB`, and assert the runner exits nonzero before the stub can run.

Run: `bash htsim/sim/datacenter/prism_eval/expA_delaydriven/tests/test_repro_laps.sh`<br>
Expected before implementation: failure because runner is absent.

**Step 2: Implement the runner**

Use strict Bash mode. Resolve the experiment, common, data, workload, and run-library paths relative to the script. Support:

- `--dry-run`: print the precise 35 planned runs and make no writes.
- normal mode: require `data/m2m.cm` and the run library; preflight every target `.flow.txt` and `.stdout` so any collision aborts before the first run; invoke the existing `common/run_lib.sh` once per cell with tag `expA_laps_f$failed_s$seed`.

Allow environment overrides limited to test seams (for example `DATA_DIR` and `RUN_LIB`), while defaults must reproduce ExpA in place. Do not delete artifacts or regenerate the workload.

**Step 3: Re-run tests**

Run the shell test again. Expected: pass, with 35 dry-run cells and verified collision refusal.

**Step 4: Commit code**

`git add htsim/sim/datacenter/prism_eval/expA_delaydriven/repro_laps.sh htsim/sim/datacenter/prism_eval/expA_delaydriven/tests/test_repro_laps.sh`<br>
`git commit -m "feat: add ExpA LAPS-only runner"`

---

### Task 2: Add opt-in LAPS overlay plotting

**Files:**

- Modify: `htsim/sim/datacenter/prism_eval/common/plot_style.py`
- Modify: `htsim/sim/datacenter/prism_eval/common/perf_figs.py`
- Modify: `htsim/sim/datacenter/prism_eval/expA_delaydriven/make_figs.py`
- Create: `htsim/sim/datacenter/prism_eval/expA_delaydriven/tests/test_make_figs_laps.py`

**Step 1: Write failing tests**

The Python test must import the ExpA plotting module and verify:

1. Default baseline order stays the existing seven entries.
2. The LAPS-only list is `ops, reps, swift, mswift, mnscc, strack, laps, prism`.
3. `laps` maps to `tab:purple` and `prism` remains `tab:green`.
4. The performance renderer accepts an optional suffix and, when `_laps` is supplied, resolves names such as `figA1dd_goodput_laps`; calls without it retain their existing names.
5. The overlay entry point requests only the three main performance plots and `figA1dd_legend_laps`, never the fairness, mechanism, decomposition, or load figures.

Run: `python3 htsim/sim/datacenter/prism_eval/expA_delaydriven/tests/test_make_figs_laps.py`<br>
Expected before implementation: failure on missing list/API/entry point.

**Step 2: Implement the plotting changes**

- Add `"laps": "tab:purple"` to shared plot colours, without altering Prism's colour.
- Extend `render_main_perf_split` with a default-empty output suffix parameter. Apply it only when saving the three output stems, preserving all existing callers and names.
- Define a separate LAPS-inclusive baseline list in `make_figs.py`, leaving `BASELINES` untouched.
- Add `--with-laps` mode that renders the three performance plots using stem `figA1dd` plus suffix `_laps`, and a separate `figA1dd_legend_laps` with balanced `[4, 4]` rows. Default invocation retains all current rendering behavior.

**Step 3: Re-run tests**

Run the Python test and the existing plot self-test:

`python3 htsim/sim/datacenter/prism_eval/expA_delaydriven/tests/test_make_figs_laps.py`<br>
`python3 htsim/sim/datacenter/prism_eval/expA_delaydriven/make_figs.py --selftest`

Expected: both pass.

**Step 4: Commit code**

`git add htsim/sim/datacenter/prism_eval/common/plot_style.py htsim/sim/datacenter/prism_eval/common/perf_figs.py htsim/sim/datacenter/prism_eval/expA_delaydriven/make_figs.py htsim/sim/datacenter/prism_eval/expA_delaydriven/tests/test_make_figs_laps.py`<br>
`git commit -m "feat: add ExpA LAPS overlay plots"`

---

### Task 3: Execute the LAPS matrix and produce the overlay deliverables

**Files (generated and intentionally uncommitted):**

- `htsim/sim/datacenter/prism_eval/expA_delaydriven/data/expA_laps_f*_s*.flow.txt` and matching logs/metadata
- `htsim/sim/datacenter/prism_eval/expA_delaydriven/figs/figA1dd_{goodput,avg_fct,p99_fct}_laps.{pdf,png}`
- `htsim/sim/datacenter/prism_eval/expA_delaydriven/figs/figA1dd_legend_laps.{pdf,png}`

**Step 1: Guard original figures**

Hash the six pre-existing source images (`goodput`, `avg_fct`, `p99_fct` × PDF/PNG) and save the hashes under `/tmp` for this run. Confirm `repro_laps.sh --dry-run` lists 35 cells before spending compute.

**Step 2: Run only LAPS**

Run `bash htsim/sim/datacenter/prism_eval/expA_delaydriven/repro_laps.sh`. Monitor completion and fail fast on a missing/nonzero command. Do not invoke `repro.sh`.

**Step 3: Validate raw output**

Assert that exactly 35 `expA_laps_f*_s*.flow.txt` files exist, one for every failed/seed pair, and that each is nonempty and parses through the normal plotting aggregation path.

**Step 4: Render**

Run `python3 htsim/sim/datacenter/prism_eval/expA_delaydriven/make_figs.py --with-laps`. Verify that all eight new requested PDF/PNG artifacts (three figures plus legend) exist and are nonempty.

**Step 5: Prove non-overwrite and repository hygiene**

Rehash the original six figures and compare against the saved values. Confirm no original source image changed. Use `git status --short` and `git diff --cached --check` to ensure experiment data, logs, and figures are not staged. Keep only source/test commits from Tasks 1–2.

---

### Final verification and handoff

Run:

`bash htsim/sim/datacenter/prism_eval/expA_delaydriven/tests/test_repro_laps.sh`<br>
`python3 htsim/sim/datacenter/prism_eval/expA_delaydriven/tests/test_make_figs_laps.py`<br>
`python3 htsim/sim/datacenter/prism_eval/expA_delaydriven/make_figs.py --selftest`<br>
`python3 htsim/sim/datacenter/prism_eval/expA_delaydriven/make_figs.py --with-laps`

Report:

- the two source commits;
- all 35 LAPS cells completed;
- paths to the new three figures and legend;
- the original-figure hash comparison result;
- confirmation that generated data/logs/figures were left uncommitted.
