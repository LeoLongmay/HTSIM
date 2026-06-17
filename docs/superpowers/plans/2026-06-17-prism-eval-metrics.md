# PRISM eval — richer metrics infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add reusable metric helpers (`jain_fairness`, `fct_slowdown`) to `common/metrics.py`, render the one metric that adds information on today's uniform workloads (Jain fairness) for the two committed headline groups, and elevate the per-ACK rate-reduction count from a console print onto the mechanism cwnd figure.

**Architecture:** `metrics.py` gains two unit-tested functions (zero-cost, from existing `flow.txt`). `perf_figs.py` gains a self-contained `render_fairness()` (does not touch `aggregate()`/`render_main_perf`, so existing figures are byte-unaffected) and a text annotation of the existing cut counts on `render_mechanism`/`render_mechanism_split`. The two headline group wrappers add a `render_fairness` call. No controller change, no new simulations.

**Tech Stack:** Python 3 + matplotlib (`common/`), stdlib-only metrics.

---

## Conventions binding on every task (read first)

- **NO git commits during execution** (user's standing rule). End each task with changes in the working tree; one milestone commit only on explicit user approval (T4). Reviewers review the working-tree diff.
- **No controller change; no new sims.** All metrics from committed `flow.txt` + the mechanism `PRISM_PATHRTT` logs (present in the groups' gitignored `data/`).
- **`render_fairness` is purely additive** — it must NOT modify `aggregate()` or `render_main_perf*`; existing committed goodput/FCT figures stay byte-identical.
- Paths relative to repo root `/home/leo/htsim`. Common dir = `htsim/sim/datacenter/prism_eval/common`.
- Honest framing: fairness = do-no-harm / characterization (may be neutral, all arms share REPS spray); rate-reduction count = the on-thesis advantage.
- Figures `git add -f`; raw data gitignored.

---

## File structure

| File | Responsibility | Task |
|---|---|---|
| `common/metrics.py` | + `jain_fairness`, `fct_slowdown` | 1 |
| `common/tests/test_metrics.py` | + unit tests for both | 1 |
| `common/perf_figs.py` | + `render_fairness`; cut-count annotation on `render_mechanism`/`_split` | 2 |
| `expA_delaydriven/make_figs.py` | + `render_fairness` call → `figA1dd_fairness` | 3 |
| `expB_oversub_asym/make_figs.py` | + `render_fairness` call (4:1) → `figBa_4os_fairness` | 3 |
| both groups' `figs/` | new fairness fig + re-rendered mechanism fig (with annotation) | 3 |
| both groups' `README.md`, memory | brief fairness + #cuts notes | 4 |

---

## Task 1: `metrics.py` — `jain_fairness` + `fct_slowdown` (TDD)

**Files:** Modify `common/metrics.py`, `common/tests/test_metrics.py`.

- [ ] **Step 1: Add the two failing tests to `common/tests/test_metrics.py`**

Before the `if __name__ == "__main__":` block, add:

```python
def test_jain_fairness():
    d = tempfile.mkdtemp()
    # equal throughput: 2 flows, same size + same FCT -> Jain = 1.0
    p = os.path.join(d, "fair.flow.txt")
    with open(p, "w") as fh:
        for fid in (1, 2):
            fh.write(f"0.000000000 Type FLOW_EVENT SrcID {fid} Ev START FlowID {fid} Flowsize 1000\n")
            fh.write(f"0.001000000 Type FLOW_EVENT SrcID {fid} Ev FINISH FlowID {fid} Bytes 1000 Pkts 1\n")
    assert abs(metrics.jain_fairness(p) - 1.0) < 1e-9, metrics.jain_fairness(p)
    # skewed: flow1 tput 1000/1ms, flow2 tput 1000/3ms -> 0.5 < Jain < 1
    p2 = os.path.join(d, "skew.flow.txt")
    with open(p2, "w") as fh:
        fh.write("0.000000000 Type FLOW_EVENT SrcID 1 Ev START FlowID 1 Flowsize 1000\n")
        fh.write("0.001000000 Type FLOW_EVENT SrcID 1 Ev FINISH FlowID 1 Bytes 1000 Pkts 1\n")
        fh.write("0.000000000 Type FLOW_EVENT SrcID 2 Ev START FlowID 2 Flowsize 1000\n")
        fh.write("0.003000000 Type FLOW_EVENT SrcID 2 Ev FINISH FlowID 2 Bytes 1000 Pkts 1\n")
    j = metrics.jain_fairness(p2)
    assert 0.5 < j < 1.0, j
    # <2 completed -> nan
    import math
    p3 = os.path.join(d, "one.flow.txt")
    with open(p3, "w") as fh:
        fh.write("0.000000000 Type FLOW_EVENT SrcID 1 Ev START FlowID 1 Flowsize 1000\n")
        fh.write("0.001000000 Type FLOW_EVENT SrcID 1 Ev FINISH FlowID 1 Bytes 1000 Pkts 1\n")
    assert math.isnan(metrics.jain_fairness(p3)), metrics.jain_fairness(p3)
    print("ok jain_fairness")

def test_fct_slowdown():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "sd.flow.txt")
    # 1,250,000 B = 1e7 bits; at 100 Gbps ideal-transmit = 1e7/1e11 = 100us; base_rtt 0;
    # FCT = 200us -> slowdown = 2.0
    with open(p, "w") as fh:
        fh.write("0.000000000 Type FLOW_EVENT SrcID 1 Ev START FlowID 1 Flowsize 1250000\n")
        fh.write("0.000200000 Type FLOW_EVENT SrcID 1 Ev FINISH FlowID 1 Bytes 1250000 Pkts 1\n")
    sd = metrics.fct_slowdown(p, link_gbps=100.0, base_rtt_s=0.0)
    assert abs(sd["mean"] - 2.0) < 1e-9, sd
    print("ok fct_slowdown")
```

And add their calls into `if __name__ == "__main__":` (before `print("ALL PASS")`):

```python
    test_jain_fairness()
    test_fct_slowdown()
```

- [ ] **Step 2: Run the tests — verify they FAIL**

Run: `cd htsim/sim/datacenter/prism_eval/common/tests && python3 test_metrics.py`
Expected: `AttributeError: module 'metrics' has no attribute 'jain_fairness'`.

- [ ] **Step 3: Add the two functions to `common/metrics.py`**

After the `aggregate_goodput_gbps` function (it ends with `return total_bytes * 8.0 / span / 1e9`), add:

```python
def jain_fairness(flow_path):
    """Jain's fairness index over per-flow throughput (bytes / FCT) of the COMPLETED flows.
    Returns a float in (0, 1] (1.0 = perfectly fair); nan if fewer than 2 completed flows."""
    starts, finishes = parse_flow_events(flow_path)
    tput = [finishes[k][1] / (finishes[k][0] - starts[k])
            for k in finishes if k in starts and finishes[k][0] > starts[k]]
    n = len(tput)
    if n < 2:
        return float("nan")
    s = sum(tput); s2 = sum(t * t for t in tput)
    return (s * s) / (n * s2) if s2 > 0 else float("nan")

def fct_slowdown(flow_path, link_gbps=100.0, base_rtt_s=14e-6):
    """Per-flow slowdown = FCT / (base_rtt_s + bytes*8 / (link_gbps*1e9)); returns {'mean','p99'}.
    Built for varied-size workloads; redundant at uniform flow size (where slowdown is proportional
    to FCT), so not rendered there. nan if no completed flows."""
    starts, finishes = parse_flow_events(flow_path)
    rate = link_gbps * 1e9
    sd = []
    for k in finishes:
        if k not in starts:
            continue
        fct = finishes[k][0] - starts[k]
        ideal = base_rtt_s + finishes[k][1] * 8.0 / rate
        if ideal > 0:
            sd.append(fct / ideal)
    if not sd:
        return {"mean": float("nan"), "p99": float("nan")}
    sd.sort()
    return {"mean": statistics.mean(sd), "p99": _percentile(sd, 99)}
```

(`metrics.py` already imports `statistics` and defines `_percentile` and `parse_flow_events`.)

- [ ] **Step 4: Run the tests — verify they PASS**

Run: `cd htsim/sim/datacenter/prism_eval/common/tests && python3 test_metrics.py`
Expected: `ok jain_fairness`, `ok fct_slowdown`, ... `ALL PASS`.

- [ ] **Step 5: Do NOT commit.**

---

## Task 2: `perf_figs.py` — `render_fairness` + cut-count annotation

**Files:** Modify `common/perf_figs.py`.

- [ ] **Step 1: Add `render_fairness` (self-contained; after `render_main_perf_split`)**

Insert this function immediately after `render_main_perf_split` (before `def render_mechanism_split`):

```python
def render_fairness(data_dir, figs_dir, tag_prefix, baselines, failed, seeds, fig_stem, xlabel):
    """Standalone Jain-fairness figure: fairness vs `failed`, one line per baseline + error bars.
    Self-aggregating (computes metrics.jain_fairness in its own loop) -- does NOT touch aggregate()
    or render_main_perf, so existing figures are unaffected. Skips cells with <2 completed flows."""
    import matplotlib.pyplot as plt
    plot_style.apply_style(13)
    def _fair(lab, f):
        vals = []
        for s in seeds:
            fp = os.path.join(data_dir, f"{tag_prefix}_{lab}_f{f}_s{s}.flow.txt")
            if not os.path.exists(fp):
                continue
            j = metrics.jain_fairness(fp)
            if j == j:   # not nan
                vals.append(j)
        return vals
    fig, ax = plt.subplots(1, 1, figsize=(5.2, 3.4))
    for (lab, disp, ck) in baselines:
        xs, ys, es = [], [], []
        for f in failed:
            vals = _fair(lab, f)
            if vals:
                xs.append(f); ys.append(statistics.mean(vals)); es.append(statistics.pstdev(vals))
        if xs:
            ax.errorbar(xs, ys, yerr=es, marker="o", lw=2.0, ms=6, capsize=3,
                        color=plot_style.COLORS[ck], label=disp)
    ax.set_ylabel("Jain fairness index"); ax.set_xlabel(xlabel)
    ax.set_xticks(failed); ax.grid(alpha=0.3); ax.legend(fontsize=9)
    plt.tight_layout()
    plot_style.save(fig, fig_stem, figs_dir)
    plt.close(fig)
    for (lab, disp, _c) in baselines:
        cells = [(f, statistics.mean(v)) for f in failed for v in [_fair(lab, f)] if v]
        print(f"[{fig_stem}] {disp}: " + " ".join(f"f{f}:{m:.3f}" for f, m in cells))
```

- [ ] **Step 2: Annotate the cut counts on `render_mechanism_split`'s cwnd panel**

In `render_mechanism_split`, the cwnd-panel block currently ends (after the per-arm loop) with the
`axc.set_xlabel(...)` line. Insert the cut-count computation + annotation BEFORE `axc.set_xlabel`:

Find:
```python
        makespans.append((disp, xs[-1]))
    axc.set_xlabel("time (ms)"); axc.set_ylabel("cwnd (KB, mean/flow)")
```
Replace with:
```python
        makespans.append((disp, xs[-1]))
    reps_dec = metrics.count_cwnd_cuts_from_pathrtt(reps_pr)
    prism_dec = metrics.count_cwnd_cuts_from_pathrtt(prism_pr) if os.path.exists(prism_pr) else -1
    strack_dec = metrics.count_cwnd_cuts_from_pathrtt(strack_pr) if os.path.exists(strack_pr) else -1
    axc.text(0.02, 0.97, f"rate reductions (per-ACK cwnd cuts): Prism {prism_dec}, "
             f"REPS+NSCC {reps_dec}, STrack {strack_dec}", transform=axc.transAxes, fontsize=7,
             va="top", bbox=dict(boxstyle="round", fc="white", ec="gray", alpha=0.85))
    axc.set_xlabel("time (ms)"); axc.set_ylabel("cwnd (KB, mean/flow)")
```
Then in the diagnostics block below, REMOVE the now-duplicate recomputation lines so the printed
values reuse the ones above. Find:
```python
    reps_dec = metrics.count_cwnd_cuts_from_pathrtt(reps_pr)
    prism_dec = metrics.count_cwnd_cuts_from_pathrtt(prism_pr) if os.path.exists(prism_pr) else -1
    prism_md = sum(r["cut"] for r in ep)
```
Replace with:
```python
    prism_md = sum(r["cut"] for r in ep)
```
And find:
```python
    if os.path.exists(strack_pr):
        strack_dec = metrics.count_cwnd_cuts_from_pathrtt(strack_pr)
        print(f"[{stem_prefix}] DISTINCTNESS (per-ACK cwnd-decreases @{lbl}): "
              f"STrack={strack_dec}  REPS+NSCC={reps_dec}")
```
Replace with:
```python
    if os.path.exists(strack_pr):
        print(f"[{stem_prefix}] DISTINCTNESS (per-ACK cwnd-decreases @{lbl}): "
              f"STrack={strack_dec}  REPS+NSCC={reps_dec}")
```

- [ ] **Step 3: Annotate the cut counts on `render_mechanism`'s cwnd panel**

In `render_mechanism`, find:
```python
    ax_cw.set_ylabel("cwnd (KB, mean/flow)")
    ax_cw.set_xlabel("time (ms)")
    ax_cw.grid(alpha=0.3); ax_cw.legend(fontsize=9)
    plt.tight_layout()
    plot_style.save(fig, fig_stem, figs_dir)
    plt.close(fig)
    if not ep:
        print(f"[{fig_stem}] WARNING: prism epoch log empty -- floor-MD fraction unreliable")
    reps_dec = metrics.count_cwnd_cuts_from_pathrtt(reps_pr)
    prism_dec = metrics.count_cwnd_cuts_from_pathrtt(prism_pr) if os.path.exists(prism_pr) else -1
    prism_md = sum(r["cut"] for r in ep)
```
Replace with:
```python
    ax_cw.set_ylabel("cwnd (KB, mean/flow)")
    ax_cw.set_xlabel("time (ms)")
    reps_dec = metrics.count_cwnd_cuts_from_pathrtt(reps_pr)
    prism_dec = metrics.count_cwnd_cuts_from_pathrtt(prism_pr) if os.path.exists(prism_pr) else -1
    strack_dec = metrics.count_cwnd_cuts_from_pathrtt(strack_pr) if os.path.exists(strack_pr) else -1
    ax_cw.text(0.02, 0.97, f"rate reductions (per-ACK cwnd cuts): Prism {prism_dec}, "
               f"REPS+NSCC {reps_dec}, STrack {strack_dec}", transform=ax_cw.transAxes, fontsize=7,
               va="top", bbox=dict(boxstyle="round", fc="white", ec="gray", alpha=0.85))
    ax_cw.grid(alpha=0.3); ax_cw.legend(fontsize=9)
    plt.tight_layout()
    plot_style.save(fig, fig_stem, figs_dir)
    plt.close(fig)
    if not ep:
        print(f"[{fig_stem}] WARNING: prism epoch log empty -- floor-MD fraction unreliable")
    prism_md = sum(r["cut"] for r in ep)
```
(`strack_pr` is already defined earlier in `render_mechanism`.) Then REMOVE the now-duplicate
`strack_dec` recomputation in the distinctness print. Find:
```python
    if os.path.exists(strack_pr):
        strack_dec = metrics.count_cwnd_cuts_from_pathrtt(strack_pr)
        print(f"[{fig_stem}] DISTINCTNESS (per-ACK cwnd-decreases @{lbl}): "
```
Replace with:
```python
    if os.path.exists(strack_pr):
        print(f"[{fig_stem}] DISTINCTNESS (per-ACK cwnd-decreases @{lbl}): "
```

- [ ] **Step 4: Selftest passes (aggregation math unchanged)**

Run: `cd htsim/sim/datacenter/prism_eval/common && python3 perf_figs.py`
Expected: `ok perf_figs aggregation selftest`.

- [ ] **Step 5: Do NOT commit.**

---

## Task 3: Wire the two groups, re-render, capture numbers

**Files:** Modify `expA_delaydriven/make_figs.py`, `expB_oversub_asym/make_figs.py`. Produces the new fairness figs + re-rendered mechanism figs.

- [ ] **Step 1: `expA_delaydriven/make_figs.py` — add the fairness call**

In the `else:` render block (after the `render_main_perf_split(...)` line, before `render_mechanism_split(...)`), add:
```python
        perf_figs.render_fairness(DATA, FIGS, "expA", BASELINES, FAILED, SEEDS, "figA1dd_fairness", XLABEL)
```
(`FAILED = [0,2,4,6,8,10,12]`, `XLABEL`, `BASELINES`, `SEEDS` already defined in that file.)

- [ ] **Step 2: `expB_oversub_asym/make_figs.py` — add the fairness call (4:1 only)**

In the `else:` render block, add (after the two `render_main_perf` calls):
```python
        perf_figs.render_fairness(DATA, FIGS, "expBa4os", BASELINES, FAILED_4OS, SEEDS,
                                  "figBa_4os_fairness", "requested -failed (4:1 oversub, delay-driven)")
```
(`FAILED_4OS = [0,4,8,12]`, `BASELINES`, `SEEDS` already defined there.)

- [ ] **Step 3: Re-render both groups (data already present in their gitignored `data/`)**

Run:
```bash
cd htsim/sim/datacenter/prism_eval/expA_delaydriven && python3 make_figs.py 2>&1 | grep -E 'figA1dd_fairness|figA2dd_cwnd|rate reduction|cwnd-decrease'
cd ../expB_oversub_asym && python3 make_figs.py 2>&1 | grep -E 'figBa_4os_fairness|cwnd-decrease'
```
Expected: a `[figA1dd_fairness]` per-arm line and a `[figBa_4os_fairness]` per-arm line print; no errors. (If a group's `data/` was cleaned, run its `repro.sh` first — but normally the committed-session data persists locally.)

- [ ] **Step 4: Capture the fairness numbers**

Record VERBATIM the `[figA1dd_fairness]` and `[figBa_4os_fairness]` per-arm lines (Jain index per failed), and the mechanism cut-count line(s) for both groups. These feed the READMEs.

- [ ] **Step 5: Confirm the new + updated figures exist**

Run:
```bash
ls htsim/sim/datacenter/prism_eval/expA_delaydriven/figs/figA1dd_fairness.* \
   htsim/sim/datacenter/prism_eval/expB_oversub_asym/figs/figBa_4os_fairness.*
```
Expected: `.png` + `.pdf` for each. (The mechanism figs `figA2dd_cwnd` / `figBa_mech` are re-rendered with the cut-count annotation.)

- [ ] **Step 6: Do NOT commit.**

---

## Task 4: README notes + memory + present milestone

**Files:** Modify `expA_delaydriven/README.md`, `expB_oversub_asym/README.md`, `/home/leo/.claude/projects/-home-leo-htsim/memory/prism-eval-roadmap.md`.

- [ ] **Step 1: Add a short "Fairness & rate reductions" note to each group README**

In each group's README (a new short subsection or appended bullet), state, from the Task-3 numbers:
- Jain fairness per arm (reference `figA1dd_fairness` / `figBa_4os_fairness`), framed as **do-no-harm /
  characterization** (all arms share REPS spray; note plainly whether PRISM is on par / better / worse).
- The per-ACK rate-reduction count at the mechanism point (PRISM vs REPS+NSCC vs STrack), framed as the
  **on-thesis advantage** (PRISM achieves its goodput with far fewer rate reductions); reference the
  annotated mechanism cwnd figure.

- [ ] **Step 2: Update the roadmap memory**

Append a short "richer-metrics" block: `metrics.jain_fairness` + `fct_slowdown` (dormant) added to
`common/`; `render_fairness` + mechanism cut-count annotation in `perf_figs`; fairness rendered for
expA_delaydriven + expB_oversub_asym(4:1) with the measured values; framing (fairness = do-no-harm,
#cuts = on-thesis). Note slowdown/tail are built-but-dormant until varied-size workloads. Commit
pending user approval.

- [ ] **Step 3: Final verification**

Run:
```bash
cd htsim/sim/datacenter/prism_eval
( cd common/tests && python3 test_metrics.py | tail -1 )
python3 common/perf_figs.py
git -C /home/leo/htsim status --porcelain | grep -E 'uec\.(cpp|h)|main_uec' && echo "UNEXPECTED controller change" || echo "ok: no controller change"
grep -nE 'TBD|TODO|FIXME|XXX' expA_delaydriven/README.md expB_oversub_asym/README.md || echo "ok: no placeholders"
```
Expected: `ALL PASS`; `ok perf_figs aggregation selftest`; no controller change; no placeholders.

- [ ] **Step 4: Present the milestone for user approval (DO NOT commit)**

Summarize: the new metrics (fairness rendered; slowdown/tail dormant), the #cuts elevation, the
measured fairness numbers + the framing, and the change set (`metrics.py`, `test_metrics.py`,
`perf_figs.py`, both make_figs, new + updated figs, README notes). Milestone commit (figs `git add -f`)
only on explicit approval.

---

## Self-review notes (author)

- **Spec coverage:** §2.1 metrics functions → T1; §2.2 tests → T1; §2.3 render_fairness + cut annotation → T2; §2.4 group wiring → T3; §3 (fairness rendered, slowdown/tail dormant) → T1 builds both, T3 renders only fairness; §4/§5/§6 → conventions + T4.
- **Placeholder scan:** none; the only runtime-determined values are the fairness numbers + cut counts (captured in T3/T4 from the render output).
- **Type/name consistency:** `jain_fairness` / `fct_slowdown` names consistent across metrics.py, tests, and render_fairness; `render_fairness` signature matches the make_figs call sites; tag prefixes `expA` / `expBa4os` match the committed groups' flow-file naming; `reps_dec`/`prism_dec`/`strack_dec` computed once and reused (no double-compute) in both mechanism renderers.
