# DecMT Ablation Split-Panel Figure Design

## Objective

Provide three standalone paper panels for the existing ExpJ DecMT component
ablation without changing simulations, aggregate data, metrics, or the current
three-panel composite figure.

## Outputs

`make_figs.py` will continue to render `figJ1_decmt_ablation.{pdf,png}` and
will additionally render the following standalone products in the same `figs`
directory:

- `figJ1_goodput.{pdf,png}`
- `figJ1_avg_fct.{pdf,png}`
- `figJ1_p99_fct.{pdf,png}`

Each standalone panel uses the existing failed=8 summary data and the four
locked arm labels.  The `failed=0` textual control summary remains exclusive
to the composite figure because it would otherwise obscure the concise
standalone panels.

## Style

The panels follow the visual parameters used by `figF1_cct_bars`: a 6.4 by 2.8
inch canvas, 16-point shared plotting style, grouped-bar width derived from a
0.66 group width, standard error-bar capsize 2, and the shared algorithm color
palette.  Titles are omitted.  Each panel retains its metric-specific y-axis
label and the four DecMT-ablation arm names on the x-axis.  FCT is displayed in
milliseconds as in the existing composite.

## Verification

Tests will assert all six standalone files are produced and that rendering the
new products preserves the existing composite output.  Regeneration reads the
existing summary CSV only; it does not rerun the 80 formal simulations.
