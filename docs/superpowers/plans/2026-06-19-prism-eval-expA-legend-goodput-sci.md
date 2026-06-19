# expA_delaydriven — standalone legend image + figA1dd_goodput sci-notation y-axis — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Export the shared 7-arm baseline legend as a standalone single-row image, and render figA1dd_goodput's y-axis in offset scientific notation (×10²) — without changing any other figure.

**Architecture:** Two additive changes to the shared `common/perf_figs.py` (a new `render_legend` function + a default-off `goodput_sci` kwarg on `render_main_perf_split`), wired in by two added lines in `expA_delaydriven/make_figs.py`. The kwarg defaults off so every other caller is byte-identical; only the expA figA1dd render is affected.

**Tech Stack:** Python / matplotlib (`common/perf_figs.py`, `common/plot_style.py`).

## Global Constraints

- Branch `prism-motivation-redesign`, **local only — NEVER push**.
- **Per-task LOCAL commits only if the user authorizes this session** (confirmed at pre-flight); otherwise leave changes in the working tree. End any commit body with `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`. Narrow `git add` only.
- **Only two visible outputs may change:** create `figs/figA1dd_legend.{pdf,png}`; regenerate `figs/figA1dd_goodput.{pdf,png}` with sci-notation. EVERY other figure's content must stay unchanged — discard re-render metadata churn on all other figs (do not commit them).
- **`goodput_sci` defaults OFF** → expD `figD1`, expA `figA3dd_load`, and expB callers are byte-identical to before.
- **Preserve the user's in-progress `make_figs.py` edits** (XLABEL text, BASELINES, etc.); only ADD the two wiring lines.
- No controller / data / generator / topology change. Working dir for commands: `/home/leo/htsim/htsim/sim/datacenter/prism_eval`.
- Legend order/labels/colors must match figA1dd exactly: OPS+NSCC, REPS+NSCC, REPS+Swift, REPS+MSwift, REPS+MNSCC, STrack, Prism.

---

### Task 1: perf_figs.py — `render_legend` + `goodput_sci` kwarg (shared code, additive)

**Files:**
- Modify: `htsim/sim/datacenter/prism_eval/common/perf_figs.py`

**Interfaces:**
- Produces (consumed by Task 2):
  - `render_legend(figs_dir, baselines, fig_stem, ncol=None)` — saves `{fig_stem}.{png,pdf}` (legend only).
  - `render_main_perf_split(..., token="f", goodput_sci=False)` — new trailing kwarg.

- [ ] **Step 1: Add the `goodput_sci=False` kwarg to `render_main_perf_split`**

Change the signature line:
```python
def render_main_perf_split(data_dir, figs_dir, tag_prefix, baselines, failed, seeds, stem_prefix, xlabel, token="f"):
```
to:
```python
def render_main_perf_split(data_dir, figs_dir, tag_prefix, baselines, failed, seeds, stem_prefix, xlabel, token="f", goodput_sci=False):
```

- [ ] **Step 2: Add the guarded sci-notation formatter to the goodput panel**

In `render_main_perf_split`, inside the `for key, ylabel, suffix, scale in panels:` loop, immediately AFTER the line `ax.set_ylabel(ylabel)`, insert:
```python
        if goodput_sci and key == "goodput":
            from matplotlib.ticker import ScalarFormatter
            fmt = ScalarFormatter(useMathText=True)
            fmt.set_powerlimits((0, 0))   # force offset notation -> shared "×10ⁿ" multiplier at top
            ax.yaxis.set_major_formatter(fmt)
```
(When `goodput_sci=False`, this block is skipped → identical to the prior code path for every other caller.)

- [ ] **Step 3: Add the `render_legend` function**

Insert this new function after `render_main_perf_split` (before `render_fairness`):
```python
def render_legend(figs_dir, baselines, fig_stem, ncol=None):
    """Standalone single-row legend image of the baseline arms, matching the line style of
    render_main_perf_split (marker 'o', lw 2.0, ms 6, per-arm color). Saves {fig_stem}.{png,pdf}
    (legend only, tight-cropped). ncol defaults to len(baselines) -> one row."""
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    plot_style.apply_style(13)
    handles = [Line2D([], [], marker="o", lw=2.0, ms=6, color=plot_style.COLORS[ck], label=disp)
               for (lab, disp, ck) in baselines]
    fig = plt.figure(figsize=(0.1, 0.1))
    fig.legend(handles=handles, ncol=(ncol or len(baselines)), loc="center", frameon=True, fontsize=11)
    plot_style.save(fig, fig_stem, figs_dir)
    plt.close(fig)
    print(f"[{fig_stem}] standalone legend: {len(handles)} entries, ncol={ncol or len(baselines)}")
```

- [ ] **Step 4: Verify the aggregation selftest still passes**

Run: `cd /home/leo/htsim/htsim/sim/datacenter/prism_eval/common && python3 perf_figs.py`
Expected: `ok perf_figs aggregation selftest`

- [ ] **Step 5: Smoke-test `render_legend` produces both files**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter/prism_eval/common && python3 -c "
import perf_figs, tempfile, os
d=tempfile.mkdtemp()
bl=[('ops','OPS+NSCC','ops'),('reps','REPS+NSCC','reps'),('swift','REPS+Swift','swift'),('mswift','REPS+MSwift','mswift'),('mnscc','REPS+MNSCC','mnscc'),('strack','STrack','strack'),('prism','Prism','prism')]
perf_figs.render_legend(d,bl,'t_legend')
assert os.path.exists(os.path.join(d,'t_legend.pdf')) and os.path.exists(os.path.join(d,'t_legend.png')), 'legend files missing'
print('ok render_legend smoke: both files created')
"
```
Expected: `[t_legend] standalone legend: 7 entries, ncol=7` then `ok render_legend smoke: both files created`

- [ ] **Step 6: Commit** *(only if commits authorized this session — else skip, leave in working tree)*

```bash
cd /home/leo/htsim
git add htsim/sim/datacenter/prism_eval/common/perf_figs.py
git commit -m "perf_figs: add render_legend + goodput_sci kwarg (additive, default-off)" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: expA make_figs.py wiring + render + surgical commit

**Files:**
- Modify: `htsim/sim/datacenter/prism_eval/expA_delaydriven/make_figs.py` (two additive lines)
- Regenerate: `figs/figA1dd_goodput.{pdf,png}`; Create: `figs/figA1dd_legend.{pdf,png}`

**Interfaces:**
- Consumes: Task 1's `render_legend` and the `goodput_sci` kwarg.

- [ ] **Step 1: Pass `goodput_sci=True` to the figA1dd render call**

In `expA_delaydriven/make_figs.py`, find the existing figA1dd call (it renders `"figA1dd"`):
```python
        perf_figs.render_main_perf_split(DATA, FIGS, "expA", BASELINES, FAILED, SEEDS, "figA1dd", XLABEL)
```
and add the kwarg:
```python
        perf_figs.render_main_perf_split(DATA, FIGS, "expA", BASELINES, FAILED, SEEDS, "figA1dd", XLABEL, goodput_sci=True)
```
Do NOT add the kwarg to the `figA3dd_load` call. Leave all other lines (XLABEL, BASELINES, the other render calls) untouched.

- [ ] **Step 2: Add the `render_legend` call**

In the same `else:` render block, add one line (e.g. right after the figA1dd call):
```python
        perf_figs.render_legend(FIGS, BASELINES, "figA1dd_legend")
```

- [ ] **Step 3: Render**

Run: `cd /home/leo/htsim/htsim/sim/datacenter/prism_eval/expA_delaydriven && python3 make_figs.py 2>&1 | tail -25`
Expected: no traceback; a `[figA1dd_legend] standalone legend: 7 entries, ncol=7` line appears.

- [ ] **Step 4: Confirm the two intended outputs exist**

Run: `cd /home/leo/htsim/htsim/sim/datacenter/prism_eval/expA_delaydriven && ls -x figs/figA1dd_legend.pdf figs/figA1dd_legend.png figs/figA1dd_goodput.pdf figs/figA1dd_goodput.png`
Expected: all four paths listed.

- [ ] **Step 5: Discard re-render churn on every figure EXCEPT figA1dd_goodput + figA1dd_legend**

Run:
```bash
cd /home/leo/htsim
for f in $(git status --short htsim/sim/datacenter/prism_eval/expA_delaydriven/figs/ | awk '{print $2}' | grep -vE 'figA1dd_goodput|figA1dd_legend'); do git checkout -- "$f"; done
git status --short htsim/sim/datacenter/prism_eval/expA_delaydriven/figs/
```
Expected: the status now shows ONLY `figA1dd_goodput.{pdf,png}` (modified) and `figA1dd_legend.{pdf,png}` (untracked); no other fig listed.

- [ ] **Step 6: Visual check — legend (single row, 7 entries) + goodput (×10² offset)**

Read `figs/figA1dd_legend.pdf` (page 1): confirm a single row of 7 entries in order OPS+NSCC, REPS+NSCC, REPS+Swift, REPS+MSwift, REPS+MNSCC, STrack, Prism (colors matching the main figures), legend only.
Read `figs/figA1dd_goodput.pdf` (page 1): confirm the y-axis shows an offset multiplier `×10²` at the top with compact tick labels, and the plotted data/curves are unchanged from before.

- [ ] **Step 7: Confirm the user's make_figs.py edits are preserved**

Run: `cd /home/leo/htsim && git diff htsim/sim/datacenter/prism_eval/expA_delaydriven/make_figs.py`
Expected: the diff shows ONLY the two additions (`goodput_sci=True` on the figA1dd call + the new `render_legend` line); XLABEL, BASELINES, and all other lines unchanged.

- [ ] **Step 8: Commit** *(only if commits authorized — else skip)*

```bash
cd /home/leo/htsim
git add htsim/sim/datacenter/prism_eval/expA_delaydriven/make_figs.py
git add -f htsim/sim/datacenter/prism_eval/expA_delaydriven/figs/figA1dd_goodput.pdf htsim/sim/datacenter/prism_eval/expA_delaydriven/figs/figA1dd_goodput.png htsim/sim/datacenter/prism_eval/expA_delaydriven/figs/figA1dd_legend.pdf htsim/sim/datacenter/prism_eval/expA_delaydriven/figs/figA1dd_legend.png
git commit -m "prism_eval: expA standalone 7-arm legend image + figA1dd_goodput sci-notation y-axis" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:** §4.1 render_legend → Task 1 Step 3 + smoke Step 5; §4.2 goodput_sci kwarg + guarded formatter → Task 1 Steps 1–2; §4.3 wiring (2 lines) → Task 2 Steps 1–2; §2 "only two outputs change / discard churn" → Task 2 Step 5; §2 preserve make_figs.py edits → Task 2 Step 7; §6 reproducibility (run make_figs.py) → Task 2 Step 3; §7 acceptance: AC1 legend single-row (T2.6), AC2 goodput offset (T2.6), AC3 selftest (T1.4), AC4 default-off preserves others (Task 1 guarded block + Task 2 Step 5 leaves figA3dd_load_goodput untouched), AC5 make_figs edits preserved (T2.7). All covered.

**Placeholder scan:** No TBD/TODO; every code/command step is complete and concrete.

**Type/name consistency:** `render_legend(figs_dir, baselines, fig_stem, ncol=None)` defined in Task 1 Step 3 is called as `render_legend(FIGS, BASELINES, "figA1dd_legend")` in Task 2 Step 2 (positional args match; ncol defaults to 7). `goodput_sci=False` kwarg defined in Task 1 Step 1 is passed `goodput_sci=True` in Task 2 Step 1. `key == "goodput"` matches the panels tuple key in render_main_perf_split. plot_style.COLORS keys (ops/reps/swift/mswift/mnscc/strack/prism) all exist.
