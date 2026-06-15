# PRISM Eval — Experiment A Delay-Driven Variant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-run Experiment A in a delay-driven regime (`-disable_trim`) to test whether PRISM's floor-vs-avg decomposition produces a goodput/FCT advantage over REPS+NSCC when cwnd control is governed by delay-MD rather than loss/NACK — the decisive probe of the P2 diagnosis.

**Architecture:** Add a generic `EXTRA_ARGS` knob to `common/run_lib.sh`; refactor the (generic) Experiment-A figure logic out of `expA_asymmetric/make_figs.py` into `common/perf_figs.py` (parameterized by data dir / figs dir / baselines / tag prefix), leaving both the existing and the new experiment folder as thin wrappers; add a new self-contained `expA_delaydriven/` group whose `repro.sh` sets `EXTRA_ARGS="-disable_trim"`. The mechanism figure reports a **floor-MD fraction** (PRISM epoch-MDs / total cwnd-decreases) as the decisive "is it delay-driven now?" check.

**Tech Stack:** Python 3 (stdlib + matplotlib via plot_style), Bash, prebuilt `htsim_uec`, the P0/P1/P2 harness.

**Spec:** `docs/superpowers/specs/2026-06-15-prism-eval-expA-delaydriven-design.md`.

---

> **COMMIT POLICY (overrides skill default):** Do NOT `git commit`. Each task ends with `git add` to stage + pause; commit only on explicit user approval.

## File structure

```
htsim/sim/datacenter/prism_eval/common/run_lib.sh                  (MOD) + EXTRA_ARGS knob
htsim/sim/datacenter/prism_eval/common/perf_figs.py                (NEW) generic perf+mechanism figures (+selftest)
htsim/sim/datacenter/prism_eval/expA_asymmetric/make_figs.py       (REWRITE) thin wrapper over perf_figs
htsim/sim/datacenter/prism_eval/expA_delaydriven/make_figs.py      (NEW) thin wrapper (delay-driven)
htsim/sim/datacenter/prism_eval/expA_delaydriven/repro.sh          (NEW) Exp A + EXTRA_ARGS="-disable_trim"
htsim/sim/datacenter/prism_eval/expA_delaydriven/README.md         (NEW)
```

---

### Task 1: `EXTRA_ARGS` knob in run_lib.sh

**Files:** Modify `prism_eval/common/run_lib.sh`

- [ ] **Step 1: Add the knob to the binary invocation**

In `run_lib.sh`, find the `htsim_uec` invocation line (it currently contains `$TQD_ARG $LOGARGS -end "$END_MS"`). Insert `${EXTRA_ARGS:-}` right after `$LOGARGS`:
```bash
$BIN -topo "topologies/$TOPO" -tm "$CM" -nodes "$NODES" \
     -sender_cc_algo "$CC" -load_balancing_algo "$LB" -failed "$FAILED" -mtu "$MTU" \
     -paths "$PATHS" -seed "$SEED" $TQD_ARG $LOGARGS ${EXTRA_ARGS:-} -end "$END_MS" \
     -o "$OUTDIR/$TAG.dat" > "$OUTDIR/$TAG.stdout" 2>&1
```
And add `EXTRA_ARGS` to the "Env knobs" comment block near the top (e.g. append to the line listing knobs): `#            EXTRA_ARGS (unset; extra raw flags appended to htsim_uec, e.g. "-disable_trim")`.

- [ ] **Step 2: Syntax check + verify the flag actually reaches htsim_uec**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter
bash -n prism_eval/common/run_lib.sh && echo "syntax ok"
P=prism_eval/common; mkdir -p prism_eval/_ddv
python3 $P/gen/incast.py prism_eval/_ddv/s.cm 1 0 4000000 128 16
EXTRA_ARGS="-disable_trim" END_MS=2 PATHS=8 bash $P/run_lib.sh nscc reps 0 fat_tree_128_1os.topo 13 prism_eval/_ddv/s.cm flow s prism_eval/_ddv
echo "-- stdout should show non-trimming / disable_trim --"
grep -iE "non-trimming|disable|trim|5xBDP|xBDP" prism_eval/_ddv/s.stdout | head
rm -rf prism_eval/_ddv
```
Expected: `syntax ok`; the stdout grep shows a non-trimming / `xBDP` queue-size line (proving `-disable_trim` reached the binary). Confirm a control run WITHOUT `EXTRA_ARGS` is unaffected (the knob defaults empty).

- [ ] **Step 3: Stage & checkpoint** (do NOT commit)
```bash
cd /home/leo/htsim && git add htsim/sim/datacenter/prism_eval/common/run_lib.sh
git commit -m "prism_eval: run_lib EXTRA_ARGS knob (append raw flags to htsim_uec)"
```
(Stage ONLY `run_lib.sh`; the _ddv smoke dir was already removed in Step 2.)

---

### Task 2: `common/perf_figs.py` (generic perf + mechanism figures)

**Files:** Create `prism_eval/common/perf_figs.py`

- [ ] **Step 1: Create the module (verbatim)**

Create `htsim/sim/datacenter/prism_eval/common/perf_figs.py`:
```python
#!/usr/bin/env python3
"""Generic performance + mechanism figures for prism_eval experiment groups (Experiment A and
its variants). Parameterized by data dir, figs dir, baselines, tag prefix, and the failed/seed
sets, so each group's make_figs.py is a thin wrapper. Reads logs via metrics.py; styles via
plot_style.py. Baselines are (label, display, color_key) triples; files are named
{tag_prefix}_{label}_f{failed}_s{seed}.flow.txt and {tag_prefix}_{label}_mech.* ."""
import os, sys, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import metrics          # noqa: E402
import plot_style       # noqa: E402

def aggregate(data_dir, tag_prefix, label, failed, seeds):
    """Per-failed aggregates for one baseline: {f: {metric:(mean,std)}}; omit f with no data."""
    out = {}
    for f in failed:
        g, afct, p99, cr = [], [], [], []
        for s in seeds:
            flow = os.path.join(data_dir, f"{tag_prefix}_{label}_f{f}_s{s}.flow.txt")
            if not os.path.exists(flow):
                continue
            st = metrics.fct_stats(flow)
            g.append(metrics.aggregate_goodput_gbps(flow))
            afct.append(st["avg_s"] * 1e6)
            p99.append(st["p99_s"] * 1e6)
            cr.append(st["completion_rate"])
        if not g:
            continue
        def ms(v):
            return (statistics.mean(v), statistics.pstdev(v))
        out[f] = {"goodput": ms(g), "avg_fct": ms(afct), "p99_fct": ms(p99), "cr": ms(cr)}
    return out

def render_main_perf(data_dir, figs_dir, tag_prefix, baselines, failed, seeds, fig_stem, xlabel):
    """3 panels (goodput / avg-FCT us / P99-FCT us) vs `failed`, one line per baseline + error bars."""
    import matplotlib.pyplot as plt
    plot_style.apply_style(13)
    aggs = {lab: aggregate(data_dir, tag_prefix, lab, failed, seeds) for (lab, _d, _c) in baselines}
    fig, axes = plt.subplots(3, 1, figsize=(5.2, 8.0), sharex=True)
    panels = [("goodput", "Goodput (Gbps)"), ("avg_fct", "Avg FCT (us)"), ("p99_fct", "P99 FCT (us)")]
    for ax, (key, ylabel) in zip(axes, panels):
        for (lab, disp, ck) in baselines:
            xs = [f for f in failed if aggs[lab].get(f)]
            ys = [aggs[lab][f][key][0] for f in xs]
            es = [aggs[lab][f][key][1] for f in xs]
            ax.errorbar(xs, ys, yerr=es, marker="o", lw=2.0, ms=6, capsize=3,
                        color=plot_style.COLORS[ck], label=disp)
        ax.set_ylabel(ylabel)
        ax.grid(alpha=0.3)
    axes[0].legend(fontsize=9)
    axes[-1].set_xlabel(xlabel)
    axes[-1].set_xticks(failed)
    incomplete = []
    for (lab, _d, _c) in baselines:
        for f in failed:
            cell = aggs[lab].get(f)
            if cell and cell["cr"][0] < 0.999:
                incomplete.append((lab, f, cell["cr"][0]))
    if incomplete:
        note = "completion<1: " + ", ".join(f"{lab}@f{f}={cr:.2f}" for lab, f, cr in incomplete)
        fig.text(0.5, 0.005, note, ha="center", fontsize=7, color="firebrick")
    plt.tight_layout()
    plot_style.save(fig, fig_stem, figs_dir)
    plt.close(fig)
    for (lab, disp, _c) in baselines:
        print(f"[{fig_stem}] {disp}: " + " ".join(
            f"f{f}:g={aggs[lab][f]['goodput'][0]:.1f},avgfct={aggs[lab][f]['avg_fct'][0]:.0f}us,"
            f"cr={aggs[lab][f]['cr'][0]:.2f}" for f in failed if aggs[lab].get(f)))

def render_mechanism(data_dir, figs_dir, tag_prefix, fig_stem, mech_failed, target_us=6.0, base_ns=13945):
    """Mechanism @ mech_failed: (a) REPS+NSCC avg/floor vs PRISM floor C_cc vs target;
    (b) cwnd(t) PRISM vs REPS+NSCC. Prints fair per-ACK cut counts + the floor-MD fraction
    (PRISM epoch-MDs / PRISM total cwnd-decreases) -- the 'is it delay-driven now?' metric."""
    import matplotlib.pyplot as plt
    plot_style.apply_style(13)
    reps_pr = os.path.join(data_dir, f"{tag_prefix}_reps_mech.pathrtt.csv")
    prism_pr = os.path.join(data_dir, f"{tag_prefix}_prism_mech.pathrtt.csv")
    prism_ep = os.path.join(data_dir, f"{tag_prefix}_prism_mech.epoch.csv")
    if not (os.path.exists(reps_pr) and os.path.exists(prism_ep)):
        print(f"[{fig_stem}] mechanism logs missing; skipping")
        return
    fig, (ax_sig, ax_cw) = plt.subplots(2, 1, figsize=(5.2, 6.0), sharex=True)
    bins = metrics.qdelay_bins(reps_pr, base_ns=base_ns, bin_us=20)
    if bins:
        t = [b[0] for b in bins]; mn = [b[1] for b in bins]; av = [b[2] for b in bins]
        ax_sig.plot(t, av, color=plot_style.COLORS["reps"], lw=2.0, label="REPS+NSCC avg delay")
        ax_sig.plot(t, mn, color=plot_style.COLORS["reps"], lw=1.3, ls=":", label="REPS+NSCC floor (ignored)")
    ep = metrics.parse_prism_epoch(prism_ep)
    if ep:
        te = [r["time_ns"] / 1000.0 for r in ep]; cc = [r["c_cc_ns"] / 1000.0 for r in ep]
        ax_sig.plot(te, cc, color=plot_style.COLORS["prism"], lw=2.0, label="PRISM floor C_cc")
    ax_sig.axhline(target_us, color=plot_style.COLORS["target"], ls="--", lw=1.3, label="target")
    ax_sig.set_ylabel("Queuing delay (us)")
    ax_sig.set_title(f"Mechanism @ -failed={mech_failed}", fontsize=11)
    ax_sig.grid(alpha=0.3); ax_sig.legend(fontsize=8)
    def cwnd_series(path):
        import collections as _c
        acc = _c.defaultdict(list)
        with open(path) as fh:
            for ln in fh:
                p = ln.strip().split(",")
                if len(p) < 6:
                    continue
                acc[int(p[0]) // 20000].append(int(p[5]))
        xs = sorted(acc)
        return [b * 20000 / 1000.0 for b in xs], [sum(acc[b]) / len(acc[b]) / 1024.0 for b in xs]
    tr, cr = cwnd_series(reps_pr)
    ax_cw.plot(tr, cr, color=plot_style.COLORS["reps"], lw=2.0, label="REPS+NSCC")
    if os.path.exists(prism_pr):
        tp, cp = cwnd_series(prism_pr)
        ax_cw.plot(tp, cp, color=plot_style.COLORS["prism"], lw=2.0, label="PRISM")
    ax_cw.set_ylabel("cwnd (KB, mean/flow)")
    ax_cw.set_xlabel("time (us)")
    ax_cw.grid(alpha=0.3); ax_cw.legend(fontsize=9)
    plt.tight_layout()
    plot_style.save(fig, fig_stem, figs_dir)
    plt.close(fig)
    if not ep:
        print(f"[{fig_stem}] WARNING: prism epoch log empty -- floor-MD fraction unreliable")
    reps_dec = metrics.count_cwnd_cuts_from_pathrtt(reps_pr)
    prism_dec = metrics.count_cwnd_cuts_from_pathrtt(prism_pr) if os.path.exists(prism_pr) else -1
    prism_md = sum(r["cut"] for r in ep)
    frac = (prism_md / prism_dec) if prism_dec > 0 else float("nan")
    print(f"[{fig_stem}] cwnd-decrease events @failed={mech_failed} (FAIR, per-ACK): "
          f"PRISM={prism_dec}  REPS+NSCC={reps_dec}")
    print(f"[{fig_stem}] floor-MD fraction = PRISM epoch-MDs / PRISM cwnd-decreases = "
          f"{prism_md}/{prism_dec} = {frac:.3f}  (trimming baseline was ~0.05)")

def selftest():
    import tempfile, shutil
    d = tempfile.mkdtemp()
    failed = [0, 2, 4, 8, 12]; seeds = [13, 14, 15, 16, 17]
    for lab in ("ops", "reps", "prism"):
        for f in failed:
            for s in seeds:
                with open(os.path.join(d, f"expA_{lab}_f{f}_s{s}.flow.txt"), "w") as fh:
                    fh.write("0.000000000 Type FLOW_EVENT SrcID 1 Ev START FlowID 1 Flowsize 1000000\n")
                    fh.write("0.000000000 Type FLOW_EVENT SrcID 2 Ev START FlowID 2 Flowsize 3000000\n")
                    fh.write("0.001000000 Type FLOW_EVENT SrcID 1 Ev FINISH FlowID 1 Bytes 1000000 Pkts 1\n")
                    fh.write("0.001000000 Type FLOW_EVENT SrcID 2 Ev FINISH FlowID 2 Bytes 3000000 Pkts 1\n")
    a = aggregate(d, "expA", "ops", failed, seeds)
    assert abs(a[0]["goodput"][0] - 32.0) < 1e-6, a[0]
    assert abs(a[0]["avg_fct"][0] - 1000.0) < 1e-6, a[0]
    assert abs(a[0]["cr"][0] - 1.0) < 1e-9, a[0]
    shutil.rmtree(d)
    print("ok perf_figs aggregation selftest")

if __name__ == "__main__":
    selftest()
```

- [ ] **Step 2: Run the selftest**

Run: `cd /home/leo/htsim/htsim/sim/datacenter/prism_eval/common && python3 perf_figs.py`
Expected: `ok perf_figs aggregation selftest`.

- [ ] **Step 3: Stage & checkpoint** (do NOT commit)
```bash
cd /home/leo/htsim && git add -f htsim/sim/datacenter/prism_eval/common/perf_figs.py
git commit -m "prism_eval: common/perf_figs.py (generic perf+mechanism figures, parameterized) + selftest"
```

---

### Task 3: Rewrite `expA_asymmetric/make_figs.py` as a thin wrapper; verify figures unchanged

**Files:** Rewrite `prism_eval/expA_asymmetric/make_figs.py`

- [ ] **Step 1: Snapshot the committed figures (for byte-comparison)**

Run:
```bash
cd /home/leo/htsim
git show HEAD:htsim/sim/datacenter/prism_eval/expA_asymmetric/figs/figA1_main_perf.png > /tmp/old_figA1.png
git show HEAD:htsim/sim/datacenter/prism_eval/expA_asymmetric/figs/figA2_mechanism.png > /tmp/old_figA2.png
md5sum /tmp/old_figA1.png /tmp/old_figA2.png
```
Record the two md5s.

- [ ] **Step 2: Replace make_figs.py with the thin wrapper (verbatim)**

Overwrite `htsim/sim/datacenter/prism_eval/expA_asymmetric/make_figs.py`:
```python
#!/usr/bin/env python3
"""Experiment A (asymmetric fabric, trimming/default) figures -- thin wrapper over
common/perf_figs.py. Renders figA1_main_perf + figA2_mechanism from ./data into ./figs.
  python3 make_figs.py            # render
  python3 make_figs.py --selftest # aggregation self-check
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import perf_figs  # noqa: E402

DATA = os.path.join(HERE, "data")
FIGS = os.path.join(HERE, "figs")
BASELINES = [("ops", "OPS+NSCC", "ops"), ("reps", "REPS+NSCC", "reps"), ("prism", "PRISM", "prism")]
FAILED = [0, 2, 4, 8, 12]
SEEDS = [13, 14, 15, 16, 17]
XLABEL = "# constrained core->agg links (-failed)"

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        perf_figs.selftest()
    else:
        os.makedirs(FIGS, exist_ok=True)
        perf_figs.render_main_perf(DATA, FIGS, "expA", BASELINES, FAILED, SEEDS, "figA1_main_perf", XLABEL)
        perf_figs.render_mechanism(DATA, FIGS, "expA", "figA2_mechanism", 8)
```

- [ ] **Step 3: Re-render and verify the figures are byte-identical to the committed ones**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter/prism_eval/expA_asymmetric
python3 make_figs.py --selftest
python3 make_figs.py 2>&1 | grep -E '\[figA1_main_perf\]|\[figA2_mechanism\]'
md5sum figs/figA1_main_perf.png figs/figA2_mechanism.png
```
Compare the two new PNG md5s to the Step-1 md5s. Expected: **identical** (the plotting code is unchanged, just relocated; matplotlib PNGs are deterministic). If they differ, the refactor changed rendering — investigate before proceeding (do NOT accept a silent figure change). The `[figA2_mechanism]` line now also prints the floor-MD fraction (~0.05) and the fair cut counts (2687 / 3155) — that is expected new output, not a figure change.

- [ ] **Step 4: Stage & checkpoint** (do NOT commit)
```bash
cd /home/leo/htsim && git add htsim/sim/datacenter/prism_eval/expA_asymmetric/make_figs.py
git commit -m "prism_eval: expA_asymmetric make_figs -> thin wrapper over perf_figs (figures unchanged)"
```
(PNG bytes unchanged, so no figure files need re-staging; the PDF timestamp churn can be discarded with `git checkout -- <pdfs>` if it appears.)

---

### Task 4: New `expA_delaydriven/` group (wrapper + repro + README)

**Files:** Create `prism_eval/expA_delaydriven/make_figs.py`, `repro.sh`, `README.md`

- [ ] **Step 1: make_figs.py thin wrapper**

Create `htsim/sim/datacenter/prism_eval/expA_delaydriven/make_figs.py`:
```python
#!/usr/bin/env python3
"""Experiment A, DELAY-DRIVEN regime (-disable_trim) figures -- thin wrapper over
common/perf_figs.py. Renders figA1dd_main_perf + figA2dd_mechanism from ./data into ./figs.
  python3 make_figs.py            # render
  python3 make_figs.py --selftest # aggregation self-check
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import perf_figs  # noqa: E402

DATA = os.path.join(HERE, "data")
FIGS = os.path.join(HERE, "figs")
BASELINES = [("ops", "OPS+NSCC", "ops"), ("reps", "REPS+NSCC", "reps"), ("prism", "PRISM", "prism")]
FAILED = [0, 2, 4, 8, 12]
SEEDS = [13, 14, 15, 16, 17]
XLABEL = "# constrained core->agg links (-failed), delay-driven (-disable_trim)"

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        perf_figs.selftest()
    else:
        os.makedirs(FIGS, exist_ok=True)
        perf_figs.render_main_perf(DATA, FIGS, "expA", BASELINES, FAILED, SEEDS, "figA1dd_main_perf", XLABEL)
        perf_figs.render_mechanism(DATA, FIGS, "expA", "figA2dd_mechanism", 8)
```

- [ ] **Step 2: repro.sh (= Exp A repro + EXTRA_ARGS="-disable_trim")**

Create `htsim/sim/datacenter/prism_eval/expA_delaydriven/repro.sh`:
```bash
#!/bin/bash
# Experiment A, DELAY-DRIVEN regime: identical to expA_asymmetric but every run adds
# EXTRA_ARGS="-disable_trim" (no trimming, 5xBDP buffer -> queues build, delay-MD drives cwnd).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../common" && pwd)"
DC="$(cd "$HERE/../.." && pwd)"
REL="prism_eval/expA_delaydriven"
cd "$DC"
[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first"; exit 1; }
mkdir -p "$REL/data"
SEEDS="13 14 15 16 17"; FAILEDS="0 2 4 8 12"; TOPO=fat_tree_128_1os.topo
DD="-disable_trim"   # the delay-driven knob

echo "== self-test analysis =="
python3 "$HERE/make_figs.py" --selftest
( cd "$COMMON/tests" && python3 test_metrics.py >/dev/null && echo "ok common metrics selftest" )

echo "== generate workload (many2many: 64 -> 16 pod0, 2MB) =="
python3 "$COMMON/gen/many2many.py" "$REL/data/m2m.cm" 64 16 pairs 2000000 128 16
CM="$REL/data/m2m.cm"; OUT="$REL/data"

echo "== main sweep (delay-driven): 3 baselines x failed{0,2,4,8,12} x 5 seeds =="
for f in $FAILEDS; do for s in $SEEDS; do
  PATHS=8 END_MS=2 EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" nscc oblivious "$f" "$TOPO" "$s" "$CM" flow,sink "expA_ops_f${f}_s${s}" "$OUT"
  PATHS=8 END_MS=2 EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" nscc reps      "$f" "$TOPO" "$s" "$CM" flow,sink "expA_reps_f${f}_s${s}" "$OUT"
  PATHS=8 END_MS=2 EXTRA_ARGS="$DD" PRISM_EPOCH="$OUT/expA_prism_f${f}_s${s}.epoch.csv" \
    bash "$COMMON/run_lib.sh" prism reps "$f" "$TOPO" "$s" "$CM" flow,sink "expA_prism_f${f}_s${s}" "$OUT"
done; done

echo "== mechanism condition: failed=8, seed=13, all 3 with PRISM_PATHRTT =="
PATHS=8 END_MS=2 EXTRA_ARGS="$DD" PRISM_PATHRTT="$OUT/expA_ops_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" nscc oblivious 8 "$TOPO" 13 "$CM" flow,sink expA_ops_mech "$OUT"
PATHS=8 END_MS=2 EXTRA_ARGS="$DD" PRISM_PATHRTT="$OUT/expA_reps_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" nscc reps 8 "$TOPO" 13 "$CM" flow,sink expA_reps_mech "$OUT"
PATHS=8 END_MS=2 EXTRA_ARGS="$DD" PRISM_EPOCH="$OUT/expA_prism_mech.epoch.csv" PRISM_PATHRTT="$OUT/expA_prism_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" prism reps 8 "$TOPO" 13 "$CM" flow,sink expA_prism_mech "$OUT"

echo "== render figA1dd + figA2dd =="
python3 "$HERE/make_figs.py"
echo "== done: figs/figA1dd_main_perf.{png,pdf} figs/figA2dd_mechanism.{png,pdf} =="
```

- [ ] **Step 3: README.md (Result filled in Task 5)**

Create `htsim/sim/datacenter/prism_eval/expA_delaydriven/README.md`:
```markdown
# Experiment A — Delay-Driven Regime (-disable_trim)

**Why.** P2 (trimming default) found PRISM tied REPS+NSCC; data-mining showed the decomposition
was masked by loss/NACK-dominated cwnd control (PRISM's floor-MD governed only ~5% of cwnd
decreases). This variant adds `-disable_trim` (no trimming, 5xBDP buffer) so queues build and
delay-MD drives cwnd — the regime where the floor-vs-avg decomposition *can* dominate.

## Setup
Identical to `expA_asymmetric` (many2many 64->16 pod0, 2 MB; fat_tree_128_1os; -paths 8; -end 2;
baselines OPS+NSCC / REPS+NSCC / PRISM; -failed {0,2,4,8,12}; seeds {13..17}; mechanism at
failed=8, seed=13) **plus `EXTRA_ARGS="-disable_trim"` on every run**.

## Figures
- `figs/figA1dd_main_perf` — goodput / avg-FCT / P99-FCT vs # constrained links.
- `figs/figA2dd_mechanism` — signal (REPS+NSCC avg/floor vs PRISM C_cc vs target) + cwnd(t);
  prints fair per-ACK cut counts and the **floor-MD fraction** (decisive: trimming baseline ~0.05).

## Result
<!-- Filled from the run (Task 5). Report honestly per the pre-registration: (i) floor-MD
     fraction vs ~0.05; (ii) does PRISM beat REPS+NSCC on goodput/FCT now? State which
     pre-registered branch this lands in (thesis sharpens / accept negative). -->

## Honest scope
- Pre-registered: floor-MD fraction up + PRISM wins -> "reroutable AND delay-driven" thesis;
  still tied -> accept negative/scoping. No tuning to force a win. FCT over completed flows
  (completion_rate surfaced); goodput window-free.
- 128-node many2many only; if `-disable_trim` alone doesn't raise the floor-MD fraction, a
  larger buffer (`-queue_size_bdp_factor`) is the documented next lever.

## Reproduce
```
bash prism_eval/expA_delaydriven/repro.sh   # from sim/datacenter; ~75 sweep + 3 mechanism sims
```
```

- [ ] **Step 4: chmod + syntax check + selftest**

Run:
```bash
chmod +x /home/leo/htsim/htsim/sim/datacenter/prism_eval/expA_delaydriven/repro.sh
bash -n /home/leo/htsim/htsim/sim/datacenter/prism_eval/expA_delaydriven/repro.sh && echo "syntax ok"
cd /home/leo/htsim/htsim/sim/datacenter/prism_eval/expA_delaydriven && python3 make_figs.py --selftest
```
Expected: `syntax ok` and `ok perf_figs aggregation selftest`.

- [ ] **Step 5: Stage & checkpoint** (do NOT commit)
```bash
cd /home/leo/htsim && git add -f htsim/sim/datacenter/prism_eval/expA_delaydriven/make_figs.py \
  htsim/sim/datacenter/prism_eval/expA_delaydriven/repro.sh htsim/sim/datacenter/prism_eval/expA_delaydriven/README.md
git commit -m "prism_eval: expA_delaydriven group (Exp A + -disable_trim) wrapper/repro/README"
```

---

### Task 5: Run end-to-end, inspect, honest results (controller-owned)

**Files:** Modify `expA_delaydriven/README.md`; produce `figs/figA1dd_*`, `figA2dd_*`.

> Controller note: the run + interpretation are done by the controller (not a subagent), as in P2 — the scientific result and honesty gating are owned here.

- [ ] **Step 1: Run (~78 sims, ~4-8 min — exceeds the 2-min default timeout; use timeout 600000 ms or background)**

```bash
cd /home/leo/htsim/htsim/sim/datacenter
bash prism_eval/expA_delaydriven/repro.sh 2>&1 | tail -25
```
Capture the `[figA1dd_main_perf]` per-baseline table and the `[figA2dd_mechanism]` floor-MD fraction + fair cut counts.

- [ ] **Step 2: Check completion + the decisive floor-MD fraction**

- Read the printed floor-MD fraction. **If it did not rise meaningfully above ~0.05**, `-disable_trim` did not make control delay-driven (overflow drops still dominate) — note it; the documented next lever is a larger buffer (`EXTRA_ARGS="-disable_trim -queue_size_bdp_factor 20"`). Do not interpret the perf comparison as the thesis test until the regime is actually delay-driven.
- Check completion_rate per cell:
```bash
cd /home/leo/htsim/htsim/sim/datacenter
python3 - <<'PY'
import os, sys; sys.path.insert(0,"prism_eval/common"); import metrics
D="prism_eval/expA_delaydriven/data"; bad=[]
for lab in ("ops","reps","prism"):
  for f in (0,2,4,8,12):
    for s in (13,14,15,16,17):
      p=f"{D}/expA_{lab}_f{f}_s{s}.flow.txt"
      if os.path.exists(p):
        cr=metrics.fct_stats(p)["completion_rate"]
        if cr<0.999: bad.append((lab,f,s,round(cr,2)))
print("completion<1 cells:", bad[:20], "..." if len(bad)>20 else "")
PY
```

- [ ] **Step 3: Visually inspect both figures**

Read `prism_eval/expA_delaydriven/figs/figA1dd_main_perf.png` and `figA2dd_mechanism.png`. Confirm 3 panels × 3 baselines (Fig1) and the signal + cwnd panels (Fig2).

- [ ] **Step 4: Fill README Result honestly**

Edit the `## Result` section with: the floor-MD fraction (vs ~0.05), the goodput/FCT comparison vs `-failed` (PRISM vs REPS+NSCC vs OPS), completion caveats, and an explicit statement of which pre-registered branch this lands in (thesis sharpens, or accept negative). Report whichever way it comes out; no tuning.

- [ ] **Step 5: Stage & checkpoint** (do NOT commit)
```bash
cd /home/leo/htsim && git add -f \
  htsim/sim/datacenter/prism_eval/expA_delaydriven/README.md \
  htsim/sim/datacenter/prism_eval/expA_delaydriven/figs/figA1dd_main_perf.png \
  htsim/sim/datacenter/prism_eval/expA_delaydriven/figs/figA1dd_main_perf.pdf \
  htsim/sim/datacenter/prism_eval/expA_delaydriven/figs/figA2dd_mechanism.png \
  htsim/sim/datacenter/prism_eval/expA_delaydriven/figs/figA2dd_mechanism.pdf
git commit -m "prism_eval: expA delay-driven results (figA1dd/figA2dd) + honest README"
```

---

## Done criteria
- `EXTRA_ARGS` knob works (`-disable_trim` reaches htsim_uec); `perf_figs.py` selftest passes.
- `expA_asymmetric` figures byte-identical after the refactor (md5 match).
- `expA_delaydriven/repro.sh` reproduces figA1dd + figA2dd; the floor-MD fraction is reported.
- README states the honest outcome and which pre-registered branch (thesis sharpens / accept negative) it lands in.

## Out of scope
- Larger-buffer / lossless variants unless the floor-MD fraction shows `-disable_trim` alone didn't bite; 1024-node scale; permutation; STrack; oversubscribed/incast.
