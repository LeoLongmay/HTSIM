# Final Fix Report — DecMT Ablation Standalone Panel Style Isolation

## Scope

Fixed the final-review finding that standalone FigF1-style rendering leaked its
16-point Matplotlib rcParams into later legacy composite renders in the same
Python process.

## Change

- `render_single_panels()` now wraps `plot_style.apply_style(16)` and all
  standalone panel creation/saving in `matplotlib.rc_context()`.
- The standalone parameters remain unchanged: 16-point shared style, `6.4 x
  2.8` canvas, group width `0.66`, derived bar width, capsize `2`, shared
  palette, and no titles.
- Added a regression test that resets rcParams in an enclosing context, renders
  twice to separate directories, compares composite PNG bytes, and confirms all
  standalone PDF/PNG artifacts exist for both renders.

## Evidence

- Red: the new regression failed before the correction because the composite
  PNG bytes differed after the first standalone render.
- Green: `python3 -m pytest -q
  htsim/sim/datacenter/prism_eval/expJ_decmt_ablation/tests/test_make_figs.py`
  completed with `4 passed`.
- Re-rendered only from the existing aggregate summary with
  `python3 make_figs.py` in the experiment directory; all standalone PDF and
  PNG files were verified nonempty.

## Data and Artifact Scope

No simulations, data, analyzers, manifests, or summary CSVs were changed.
The standalone files were re-rendered for verification; nondeterministic PDF
metadata-only changes were not included in this fix commit.
