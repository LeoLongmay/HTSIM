# PRISM congestion-decomposition figure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `render_decomposition` renderer that plots PRISM's `C_cc(t)` and `C_spray(t)` as time series (symmetric vs asymmetric × 128/1024), wired into the two folders' `make_figs.py`.

**Architecture:** One new shared function in `common/perf_figs.py` reusing existing helpers (`metrics.parse_prism_epoch`, `_bin_series`, `plot_style`), called once from each folder's `make_figs.py` over its own committed PRISM epoch CSVs. Pure plotting — no controller change, no new simulations.

**Tech Stack:** Python, matplotlib, the project's `common/perf_figs.py` / `common/metrics.py` / `common/plot_style.py`.

## Global Constraints

- **No controller change; no new simulations; no new raw data.** Reuses committed `*.epoch.csv` only. Copied from spec §5.
- **No change to any existing figure.** `render_decomposition` is a NEW function; existing `render_*` calls untouched. After `make_figs.py` re-renders everything, restore churn on all tracked figs and `git add -f` ONLY the two new decomposition figures.
- **Reuse `plot_style.COLORS["ccc"]` (C_cc) and `COLORS["spray"]` (C_spray) and `COLORS["target"]`** — already defined for this purpose.
- **Data cells (seed 13, 2 MB):** 128 → `expA_prism_f0_s13` / `expA_prism_f8_s13`; 1024 → `expD1_prism_f0_s13` / `expD1_prism_f32_s13`.
- **Output figs:** `expA_delaydriven/figs/figA2dd_decomp.{pdf,png}` and `expD_scale1024/figs/figD1_mech_decomp.{pdf,png}`.
- **No git commit unless the user explicitly asks (per-task local commits ARE authorized for this subagent-driven run); never push.**
- **Working dir for render/verify commands:** the respective experiment folder; for git, `/home/leo/htsim`.

---

### Task 1: render_decomposition + wire both make_figs + render + verify

**Files:**
- Modify: `htsim/sim/datacenter/prism_eval/common/perf_figs.py` (add `render_decomposition`)
- Modify: `htsim/sim/datacenter/prism_eval/expA_delaydriven/make_figs.py` (one call)
- Modify: `htsim/sim/datacenter/prism_eval/expD_scale1024/make_figs.py` (one call)
- Output (force-added): the four new figure files above

**Interfaces:**
- Consumes: `metrics.parse_prism_epoch(path) -> [ {time_ns, c_cc_ns, c_spray_ns, base_rtt_ns, ...}, ... ]`; module-level `_bin_series(xs, ys, bin_w) -> (mid_xs, mean_ys)`; `plot_style.COLORS`, `plot_style.save(fig, stem, outdir)`.
- Produces: `render_decomposition(data_dir, figs_dir, tag_prefix, cells, fig_stem, seed=13, bin_w_ms=0.02, xlim_ms=None)` where `cells = [(failed:int, panel_label:str), ...]`.

- [ ] **Step 1: Add `render_decomposition` to `perf_figs.py`**

Insert this function (place it just after `render_mechanism_split`, anywhere at module top level after `_bin_series` is defined):
```python
def render_decomposition(data_dir, figs_dir, tag_prefix, cells, fig_stem,
                         seed=13, bin_w_ms=0.02, xlim_ms=None):
    """PRISM's two decomposed signals as time series, one panel per cell.
    `cells` = [(failed, panel_label), ...]. Reads {tag_prefix}_prism_f{failed}_s{seed}.epoch.csv
    and plots, per panel: faint raw + bold 20us-binned C_cc (floor->CC) and C_spray (spread->spray),
    a target line at ~1 RTT (base_rtt), and a 1st->2nd-half C_spray-mean annotation (persistence)."""
    n = len(cells)
    fig, axes = plt.subplots(1, n, figsize=(5.5 * n, 4.0), sharey=True)
    if n == 1:
        axes = [axes]
    for ax, (failed, label) in zip(axes, cells):
        path = os.path.join(data_dir, f"{tag_prefix}_prism_f{failed}_s{seed}.epoch.csv")
        ep = metrics.parse_prism_epoch(path) if os.path.exists(path) else []
        if not ep:
            ax.set_title(f"{label}\n(no data)", fontsize=11); ax.set_xlabel("time (ms)"); continue
        te = [r["time_ns"] / 1e6 for r in ep]        # ms
        cc = [r["c_cc_ns"] / 1000.0 for r in ep]      # us
        sp = [r["c_spray_ns"] / 1000.0 for r in ep]   # us
        base_us = ep[0]["base_rtt_ns"] / 1000.0       # ~14 us
        ax.plot(te, cc, color=plot_style.COLORS["ccc"], lw=0.6, alpha=0.20)
        ax.plot(te, sp, color=plot_style.COLORS["spray"], lw=0.6, alpha=0.20)
        bx, bcc = _bin_series(te, cc, bin_w_ms)
        ax.plot(bx, bcc, color=plot_style.COLORS["ccc"], lw=2.2, label="C_cc (floor -> CC)")
        sx, bsp = _bin_series(te, sp, bin_w_ms)
        ax.plot(sx, bsp, color=plot_style.COLORS["spray"], lw=2.2, label="C_spray (spread -> spray)")
        ax.axhline(base_us, color=plot_style.COLORS["target"], ls="--", lw=1.3,
                   label=f"target (~1 RTT, {base_us:.0f}us)")
        t_mid = (te[0] + te[-1]) / 2.0
        sp1 = [v for t, v in zip(te, sp) if t < t_mid]
        sp2 = [v for t, v in zip(te, sp) if t >= t_mid]
        if sp1 and sp2:
            ax.text(0.97, 0.95,
                    f"C_spray 1st->2nd half:\n{sum(sp1)/len(sp1):.1f} -> {sum(sp2)/len(sp2):.1f} us",
                    transform=ax.transAxes, ha="right", va="top", fontsize=8,
                    bbox=dict(boxstyle="round", fc="white", alpha=0.7))
        ax.set_title(label, fontsize=11); ax.set_xlabel("time (ms)"); ax.grid(alpha=0.3)
        if xlim_ms:
            ax.set_xlim(0, xlim_ms)
    axes[0].set_ylabel("Queuing delay (us)")
    axes[0].legend(fontsize=8, loc="upper left")
    plt.tight_layout(); plot_style.save(fig, fig_stem, figs_dir); plt.close(fig)
```

- [ ] **Step 2: Wire `expA_delaydriven/make_figs.py`**

In `htsim/sim/datacenter/prism_eval/expA_delaydriven/make_figs.py`, after the existing `render_mechanism_split(DATA, FIGS, "expA", "figA2dd", 8, xlim_ms=3.0)` line, add:
```python
        perf_figs.render_decomposition(DATA, FIGS, "expA",
            [(0, "128 nodes, failed=0 (symmetric)"), (8, "128 nodes, failed=8 (asymmetric)")],
            "figA2dd_decomp")
```

- [ ] **Step 3: Wire `expD_scale1024/make_figs.py`**

In `htsim/sim/datacenter/prism_eval/expD_scale1024/make_figs.py`, after the existing `render_mechanism_split(DATA, FIGS, "expD1", "figD1_mech", 32, ...)` line (the D1 block), add:
```python
        perf_figs.render_decomposition(DATA, FIGS, "expD1",
            [(0, "1024 nodes, failed=0 (symmetric)"), (32, "1024 nodes, failed=32 (asymmetric)")],
            "figD1_mech_decomp")
```

- [ ] **Step 4: Render both folders + confirm the 4 panels exist**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter/prism_eval/expA_delaydriven && python3 make_figs.py 2>&1 | tail -2
cd /home/leo/htsim/htsim/sim/datacenter/prism_eval/expD_scale1024 && python3 make_figs.py 2>&1 | tail -2
ls -la /home/leo/htsim/htsim/sim/datacenter/prism_eval/expA_delaydriven/figs/figA2dd_decomp.{pdf,png} \
       /home/leo/htsim/htsim/sim/datacenter/prism_eval/expD_scale1024/figs/figD1_mech_decomp.{pdf,png}
```
Expected: both `make_figs.py` run without error; all four files exist and are non-empty.

- [ ] **Step 5: Acceptance check — asymmetric C_spray > symmetric, and persistence direction**

Run (from `/home/leo/htsim/htsim/sim/datacenter/prism_eval`):
```bash
python3 - <<'PY'
import os, sys
sys.path.insert(0, "common")
import metrics
def spray_halves(path):
    ep = metrics.parse_prism_epoch(path)
    te = [r["time_ns"]/1e6 for r in ep]; sp = [r["c_spray_ns"]/1000.0 for r in ep]
    mid = (te[0]+te[-1])/2
    a = [v for t,v in zip(te,sp) if t< mid]; b = [v for t,v in zip(te,sp) if t>=mid]
    return sum(a)/len(a), sum(b)/len(b)
for scale, sym, asym in [("128","expA_delaydriven/data/expA_prism_f0_s13.epoch.csv",
                                 "expA_delaydriven/data/expA_prism_f8_s13.epoch.csv"),
                         ("1024","expD_scale1024/data/expD1_prism_f0_s13.epoch.csv",
                                 "expD_scale1024/data/expD1_prism_f32_s13.epoch.csv")]:
    s1,s2 = spray_halves(sym); a1,a2 = spray_halves(asym)
    print(f"{scale}: symmetric C_spray {s1:.1f}->{s2:.1f}us (drain={s1-s2:+.1f}); "
          f"asymmetric {a1:.1f}->{a2:.1f}us (drain={a1-a2:+.1f}); asym 2nd-half {a2:.1f} vs sym 2nd-half {s2:.1f}")
PY
```
Expected (sanity, not a hard gate): on BOTH scales the **symmetric** C_spray drops more from 1st→2nd half (larger positive drain = transient) than the **asymmetric**, and the asymmetric 2nd-half C_spray is **higher** than the symmetric 2nd-half (persistent spread). Report the printed numbers in the task report.

- [ ] **Step 6: Commit the code (renderer + both make_figs)**

```bash
cd /home/leo/htsim
git add htsim/sim/datacenter/prism_eval/common/perf_figs.py \
        htsim/sim/datacenter/prism_eval/expA_delaydriven/make_figs.py \
        htsim/sim/datacenter/prism_eval/expD_scale1024/make_figs.py
git commit -m "$(printf 'prism_eval: render_decomposition -- C_cc(t)+C_spray(t) mechanism figure\n\nNew shared renderer (perf_figs.py) plotting PRISM s two decomposed signals\nas time series; wired into expA (figA2dd_decomp, 128 f0|f8) and expD\n(figD1_mech_decomp, 1024 f0|f32). Pure plotting; reuses committed epoch\nCSVs; no controller change, no new sims.\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

- [ ] **Step 7: Surgically commit ONLY the two new figures (restore churn on all others)**

`make_figs.py` re-rendered every tracked figure; restore those to their committed bytes, then force-add only the two new decomposition figures (figs/ is gitignored — `git checkout` only touches already-tracked figs, and the new ones are untracked so they survive):
```bash
cd /home/leo/htsim
git checkout -- htsim/sim/datacenter/prism_eval/expA_delaydriven/figs/ \
                htsim/sim/datacenter/prism_eval/expD_scale1024/figs/
git add -f htsim/sim/datacenter/prism_eval/expA_delaydriven/figs/figA2dd_decomp.pdf \
           htsim/sim/datacenter/prism_eval/expA_delaydriven/figs/figA2dd_decomp.png \
           htsim/sim/datacenter/prism_eval/expD_scale1024/figs/figD1_mech_decomp.pdf \
           htsim/sim/datacenter/prism_eval/expD_scale1024/figs/figD1_mech_decomp.png
git status --short | grep -E "figA2dd_decomp|figD1_mech_decomp"   # confirm only the 4 new figs staged
git commit -m "$(printf 'prism_eval: figA2dd_decomp + figD1_mech_decomp (C_cc/C_spray time series)\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```
Expected: the `git status` line shows exactly the four new figure paths staged (added); no other figs modified in the commit.

---

## Notes for the reviewer / final review

- This is a plotting-only feature: the "test" is Step 4 (renders cleanly, 4 panels exist) + Step 5 (numeric acceptance: asymmetric C_spray persists, symmetric drains). There is no pytest because the output is a matplotlib figure over real logs; `make_figs.py --selftest` (the shared aggregate-math check) is unaffected and still passes.
- Verify the Step 7 surgical commit touched ONLY `figA2dd_decomp.*` and `figD1_mech_decomp.*` — no churn on other committed figures.
