# M2 Redistribution Progress

M2 observes unmodified PRISM runs and asks whether a shadow validation round makes progress when the
measured foreground load is below the healthy-cut capacity (`recoverable`) and whether progress
remains absent when it is above that capacity but below the effective residual capacity
(`persistent`). It does not feed the shadow decision back into the simulator.

## Current Result

The fixed 27-cell coarse grid produced 25 invalid cells, one mixed cell
(`coarse-f16-h2-u25`), one stable persistent cell (`coarse-f16-h6-u25`), and no stable
recoverable cell. Persistent confirmation retained the capacity relation at seeds 101-103, but the
literal no-progress predicate passed only seed 101: `51.10%`, `48.90%`, and `49.65%`, respectively.
Seeds 102 and 103 therefore fail the strict `> 50%` outcome threshold. `configs/formal.csv` remains
header-only, `repro.sh full` is intentionally blocked, and this experiment reports a negative result
without weakening the registered grid, thresholds, or seed requirements.

## Reproduction

Run every command from `/home/leo/htsim`.

```bash
# Build the simulator and binary-log decoder.
cmake --build htsim/sim/build --target htsim_uec parse_output -j2

# Real unloaded preflight, one small M2 run, smoke analysis, and real diagnostic figures.
bash htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/repro.sh smoke

# Re-render diagnostics from existing real smoke aggregates.
python3 htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/make_figs.py \
  --render-smoke

# Unloaded cross-pod base-RTT preflight, then exactly 27 seed-101 coarse cells.
bash htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/calibrate.sh coarse

# Analyze coarse data and atomically select at most three cells per inferred scenario.
python3 htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/analyze.py \
  --coarse --select-confirmation

# Render the fixed 27-cell negative-result diagnostics from coarse aggregates only.
python3 htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/make_figs.py \
  --render-calibration

# Run only the selected rows, with every selected cell at seeds 101, 102, and 103.
bash htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/calibrate.sh confirm

# Analyze confirmation data and atomically lock one cell per scenario for formal seeds 13-17.
python3 htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/analyze.py \
  --confirmation --select-formal

# Render the fixed three-seed persistent confirmation diagnosis, including failures.
python3 htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/make_figs.py \
  --render-confirmation

# Require the exact 10-row locked formal CSV, run all cases, analyze, and render real figures.
bash htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/repro.sh full

# Re-run formal aggregation and plotting without re-running simulations.
python3 htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/analyze.py --formal
python3 htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/make_figs.py --render
```

Both smoke and coarse first measure base RTT from one project-local 128-node-topology, cross-pod,
no-background 256 MB flow; neither uses a hard-coded RTT. Each invocation replaces the shared
`configs/base_rtt_ps.txt` and `data/preflight/preflight.json` with its current validated preflight.
Every non-preflight run generates its own `.cm` and `.background-config.csv`, uses `cc=prism`, zero
degraded links, and writes all raw outputs and traces below its own phase directory. Smoke diagnostic
PNG/PDF files are rendered from the real `data/smoke` aggregates and establish no evidence claim.

Starting `calibrate.sh coarse` removes only its old `summary.csv`, `rounds.csv`, `epochs.csv`, and
`confirmation_selection.csv` before any new simulation, so an old selection cannot survive a coarse
rerun. `calibrate.sh confirm` requires both current coarse summary and selection files and rejects a
selection whose modification time is earlier than the summary.

## Outputs

All paths below are relative to
`htsim/sim/datacenter/add_motivation/expM2_redistribution_progress/` and remain inside that project.

| Path | Meaning |
| --- | --- |
| `configs/calibration.csv` | The fixed 27-cell coarse grid; this is an input, not analysis output. |
| `configs/base_rtt_ps.txt` | Positive integer base RTT measured by the unloaded preflight. |
| `data/preflight/preflight.json` | Provenance for the base-RTT measurement. |
| `data/smoke/{summary,rounds,epochs}.csv` | Aggregate diagnostics from the real smoke run; not formal evidence. |
| `figs/smoke/m2_redistribution_progress_smoke.{png,pdf}` | Real smoke diagnostics rendered only from smoke aggregates. |
| `data/coarse/{summary,rounds,epochs}.csv` | Coarse aggregate evidence only. |
| `data/coarse/calibration_diagnostics.csv` | One row per preregistered coarse cell, derived only from coarse summary and rounds aggregates. |
| `figs/calibration/m2_coarse_diagnostics.{png,pdf}` | Fixed 27-cell capacity/evidence diagnostics; not formal evidence. |
| `data/coarse/confirmation_selection.csv` | Exact seed-101 cells expanded to confirmation seeds 101-103. |
| `data/confirmation/{summary,rounds,epochs}.csv` | Confirmation aggregate evidence only. |
| `data/confirmation/confirmation_diagnostics.csv` | Seeds 101-103 persistent outcome and independent capacity predicates, derived from confirmation summary only. |
| `figs/calibration/m2_confirmation_diagnostics.{png,pdf}` | Three-seed confirmation diagnostic with the fixed outcome and capacity thresholds. |
| `configs/formal.csv` | Locked input: exactly one stable recoverable and persistent cell, each at seeds 13-17. |
| `data/formal/{summary,rounds,epochs}.csv` | Ten-run formal aggregates used for the figure and claims. |
| `data/formal/formal_result.csv` | Fixed formal acceptance predicates and explicit failures by scenario. |
| `figs/m2_redistribution_progress.{png,pdf}` | Real figures rendered only from formal aggregate CSVs. |

## Evidence Boundary

Coarse and confirmation CSVs select workloads; they are not formal evidence and must not be pooled
with formal rows. `configs/formal.csv` is produced only by confirmation analysis. `repro.sh full`
requires exactly recoverable/persistent at every seed in `13,14,15,16,17`; it neither chooses a
point nor substitutes a nearby workload. Raw `.dat`, stdout, manifests, generated workloads, and
per-event traces are provenance inputs, while formal `rounds.csv`, `summary.csv`, `epochs.csv`, and
`formal_result.csv` are the claim-facing aggregates.

`--render-calibration` reads exactly `data/coarse/summary.csv` and `rounds.csv`. It rejects a
duplicate, missing, or extra cell relative to the preregistered 8/16/32 foreground x 2/4/6 hot-group
x 0.25/0.50/0.75 utilization grid. A cell is labeled stable recoverable or stable persistent only
when every completed round has that capacity classification. Any combination of recoverable,
persistent, and invalid completed rounds is retained as `mixed`; a cell with no valid capacity
classification is `invalid`. The diagnostic does not alter selection, create a formal lock, or turn
coarse or smoke observations into formal evidence.

`--render-confirmation` reads the current `data/coarse/confirmation_selection.csv` and only
`data/confirmation/summary.csv` from confirmation results. It requires one identical
`scenario=persistent` cell at exactly seeds 101, 102, and 103, with no missing or duplicate rows.
`outcome_pass` is exactly `literal_no_progress_rate > 0.5` and `low_floor_fraction >= 0.8`;
`capacity_pass` independently records `C_healthy < L_foreground < C_effective_residual`. The figure
shows every seed against these fixed boundaries, including failed seeds, and is diagnostic rather
than formal evidence.

For recoverable rounds, the formal claim requires positive redistribution progress under the fixed
capacity, completeness, coverage, and flow-cluster bootstrap rules. For persistent rounds, it
requires majority literal no-progress and the fixed low-floor/capacity/tolerance checks. A failed
selection, missing seed, censored or invalid round, failed predicate, or non-accepting formal result
is a negative result. Do not relax thresholds, drop seeds, reuse smoke output, or select a different
cell after seeing that result.

M2 is shadow analysis only. Task 1, residual-driven recycling, cache replacement, and congestion-
control handoff remain unimplemented.
