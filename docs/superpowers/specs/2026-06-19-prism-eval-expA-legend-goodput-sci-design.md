# Spec: expA_delaydriven — standalone legend image + figA1dd_goodput scientific-notation y-axis

**Date:** 2026-06-19
**Status:** design approved (user), spec under review
**Branch:** prism-motivation-redesign (local only; never push)

## 1. Goal

Two small, additive figure changes for the `expA_delaydriven` group, both for paper layout:

- **A. Standalone legend image** — export the shared 7-arm baseline legend (used by the main perf + fairness + load figures) as ONE standalone single-row image `figs/figA1dd_legend.{pdf,png}`.
- **B. figA1dd_goodput y-axis in scientific notation** — compact the goodput y-axis using an offset multiplier (`×10²` shown once at the top), so tick labels become small numbers (e.g. 5, 10 = 500, 1000 Gbps).

## 2. Invariants (non-negotiable)

- **Only two visible outputs change:** (1) the NEW `figA1dd_legend.{pdf,png}` is created; (2) `figA1dd_goodput.{pdf,png}` is regenerated with the sci-notation y-axis. **Every other figure's content is unchanged** — in particular expB / expD goodput figures, `figA3dd_load_goodput`, `figA1dd_{avg_fct,p99_fct,fairness}`, and `figA2dd_{signal,cwnd}` must NOT change in appearance (re-rendering them to identical content during a normal `make_figs.py` run is fine; their visual content must not differ).
- **Preserve the user's in-progress `make_figs.py` edits.** Only ADD the two wiring lines described in §5; do not revert or restructure anything else in that file (e.g. the user's `XLABEL = "Number of failed links"`, BASELINES order, etc. stay as-is).
- **`goodput_sci` defaults OFF** so every other caller of `render_main_perf_split` (expD D1 `figD1`, expA `figA3dd_load`) is byte-identical to before.
- No controller, data, generator, or topology change. No git commit unless the user explicitly asks; never push.

## 3. Scope

In: `common/perf_figs.py` (one new function + one new kwarg) and `expA_delaydriven/make_figs.py` (two additive lines). Out: any other folder, the mechanism figures' legends, removing inline legends from existing figures (the existing figures keep their inline legends — "其他都不用动").

## 4. Implementation

### 4.1 Task A — `render_legend` (perf_figs.py, new pure-additive function)
```
def render_legend(figs_dir, baselines, fig_stem, ncol=None):
    """Standalone single-row legend image of the baseline arms, matching the line style
    used in render_main_perf_split (marker 'o', lw 2.0, ms 6, per-arm color). Saves
    {fig_stem}.{png,pdf} (legend only, tight-cropped). ncol defaults to len(baselines)."""
```
- Build one `matplotlib.lines.Line2D([], [], marker="o", lw=2.0, ms=6, color=plot_style.COLORS[ck], label=disp)` proxy per `(lab, disp, ck)` in `baselines` order.
- Create a small figure with no visible axes; place a single `fig.legend(handles, labels, ncol=ncol or len(baselines), loc="center", frameon=True)`.
- Save via `plot_style.save(fig, fig_stem, figs_dir)` (it tight-crops to the legend with `bbox_inches="tight"`).
- The legend order/labels/colors therefore match figA1dd exactly: OPS+NSCC, REPS+NSCC, REPS+Swift, REPS+MSwift, REPS+MNSCC, STrack, Prism.

### 4.2 Task B — `goodput_sci` kwarg on `render_main_perf_split` (perf_figs.py)
- Add `goodput_sci=False` as the last kwarg (after `token="f"`), so positional callers are unaffected.
- In the per-panel loop, AFTER `ax.set_ylabel(ylabel)`, add a guarded block that runs ONLY for the goodput panel when the flag is set:
  ```
  if goodput_sci and key == "goodput":
      from matplotlib.ticker import ScalarFormatter
      fmt = ScalarFormatter(useMathText=True)
      fmt.set_powerlimits((0, 0))          # force offset notation -> "×10ⁿ" at top
      ax.yaxis.set_major_formatter(fmt)
  ```
- When `goodput_sci=False` (every other caller), the code path is unchanged → byte-identical output preserved.
- Matplotlib will choose the offset exponent from the data magnitude (goodput ~360–1000 → `×10²`) and render compact tick labels. If the auto-locator produces intermediate ticks (e.g. 4/6/8) rather than exactly 5/10, that is acceptable per the user; a follow-up `ax.yaxis.set_major_locator(MultipleLocator(500))` can force exactly {5,10} only if the user asks.

### 4.3 Wiring (make_figs.py — two additive lines, user-approved)
- Change the existing `figA1dd` render call to pass the new kwarg:
  `render_main_perf_split(DATA, FIGS, "expA", BASELINES, FAILED, SEEDS, "figA1dd", XLABEL, goodput_sci=True)`
- Add one call to emit the legend (near the other render calls):
  `perf_figs.render_legend(FIGS, BASELINES, "figA1dd_legend")`
- The `figA3dd_load` render call is left WITHOUT `goodput_sci` (stays default off).

## 5. Files changed
- `common/perf_figs.py`: + `render_legend(...)`; + `goodput_sci=False` kwarg + guarded formatter block in `render_main_perf_split`. (Optionally a one-line selftest touch — not required; selftest is data-aggregation only and need not exercise rendering.)
- `expA_delaydriven/make_figs.py`: figA1dd call gains `goodput_sci=True`; one `render_legend` line added. Nothing else touched.

## 6. Reproducibility
`cd expA_delaydriven && python3 make_figs.py` regenerates all figures: `figA1dd_goodput` now sci-notation, `figA1dd_legend.{pdf,png}` newly created; all other figures re-render with identical content. `python3 make_figs.py --selftest` still passes.

## 7. Acceptance criteria
1. `figs/figA1dd_legend.{pdf,png}` exists: a single row of 7 entries in the order OPS+NSCC, REPS+NSCC, REPS+Swift, REPS+MSwift, REPS+MNSCC, STrack, Prism, colors matching the main figures, legend only (no axes/data).
2. `figs/figA1dd_goodput.pdf` y-axis uses an offset multiplier (`×10²` at the top) with compact tick labels; the plotted data is unchanged.
3. `make_figs.py --selftest` passes; a full render produces no traceback.
4. Other goodput figures are unchanged in content: re-rendering expB (`figB*`/`figBa*`), expD (`figD1_goodput`, `figD2_*`), and expA `figA3dd_load_goodput` shows the same axes (no sci notation) as before — `goodput_sci` default-off path is byte-for-byte the prior code path.
5. The user's existing `make_figs.py` edits (XLABEL text, BASELINES, etc.) are preserved; only the two wiring additions are made.
