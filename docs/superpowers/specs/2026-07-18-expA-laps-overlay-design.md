# Experiment A Delay-Driven LAPS Overlay Design

## Goal

Extend the existing Experiment A delay-driven performance comparison with a LAPS baseline, using the same A1dd experiment matrix as the existing seven baselines. Preserve every existing data file and figure. Produce three additional figures that include LAPS:

- `figA1dd_goodput_laps.pdf` / `.png`
- `figA1dd_avg_fct_laps.pdf` / `.png`
- `figA1dd_p99_fct_laps.pdf` / `.png`

Also produce an independent `figA1dd_legend_laps.pdf` / `.png` for those figures.

## Scope

Use the existing `htsim/sim/datacenter/prism_eval/expA_delaydriven/` directory. Do not create a separate output tree, overwrite the original `figA1dd_*` figures, or rerun the seven existing baselines.

LAPS runs use the existing A1dd settings:

- topology: `fat_tree_128_1os.topo`
- workload: existing 64-to-16, 2 MB many-to-many matrix in `data/m2m.cm`
- paths: 8
- delay-driven mode: `-disable_trim`
- end time: 8 ms
- failed links: `0, 2, 4, 6, 8, 10, 12`
- seeds: `13, 14, 15, 16, 17`

Only 35 LAPS simulations run: one for every failed-link and seed pair. Each invocation uses the paired LAPS selection:

```text
-sender_cc_algo laps -load_balancing_algo laps
```

## Data and execution

Add a dedicated LAPS-only reproduction script under `expA_delaydriven/`. It must:

1. Preflight the built `htsim_uec` binary and require the existing A1dd workload matrix.
2. Invoke the existing `common/run_lib.sh` with the exact settings above.
3. Write only new tags in the existing `data/` directory:

   ```text
   expA_laps_f{failed}_s{seed}.{flow.txt,idmap,stdout}
   ```

4. Fail rather than delete, replace, or silently regenerate any existing baseline result.
5. Support a dry-run/command-preview mode suitable for checking the 35-run matrix without simulation.

Existing data remains the source for OPS, REPS, Swift, MSwift, MNSCC, STrack, and Prism. This overlay is a same-settings comparison, not a claim that all eight curves were regenerated from one binary revision.

## Plotting behavior

Modify the existing `make_figs.py` only by adding an opt-in `--with-laps` mode. With no option, its current output and filenames remain byte-for-byte behaviorally unchanged.

With `--with-laps`, it loads the seven current tags plus `laps` and writes only the new `_laps` filenames specified above. Use the shared metric aggregation (means and existing error-bar treatment) so the new series has the same statistics as the old series.

Legend and series ordering are fixed:

1. OPS+NSCC
2. REPS+NSCC
3. REPS+Swift
4. REPS+MSwift
5. REPS+MNSCC
6. STrack
7. LAPS
8. Prism

LAPS is purple. Prism stays `tab:green` and is always last in the series and legend. The original legend is not overwritten.

## Validation

- A focused dry-run test proves exactly 35 unique LAPS commands, each with the paired CC/LB flags, existing workload path, A1dd no-trim/end/path settings, and non-overwriting tags.
- Plot self-test covers the eight-series LAPS mode, output suffixes, LAPS purple, and green-last Prism ordering.
- Run all 35 LAPS simulations, verify every expected flow result is present and non-empty, then render the six `_laps` files (three PDF, three PNG) plus the legend pair.
- Run the existing `make_figs.py --selftest` and no-argument rendering path; verify none of the original figure files are modified.
- Do not add generated data or figures to the commit.
