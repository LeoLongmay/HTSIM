# PRISM T_spray Tuning — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tune the existing `-prism_t_spray` knob to remove PRISM's failed=0 symmetric throughput penalty without eroding the failed≥4 asymmetric win, via a two-stage sweep (endpoints → validate) in a new `expA_tspray_tuning/` group.

**Architecture:** No controller code change — the sweep drives `-prism_t_spray` through `run_lib.sh`'s `EXTRA_ARGS`. A pure, unit-tested selector (`tspray_select.py`) encodes the pre-registered success criterion. `make_figs.py` aggregates via the shared `metrics.py`, renders a Stage-1 knee figure + a Stage-2 4-arm comparison (reusing the committed delay-driven baselines read-only). `repro.sh` runs Stage 1 always and Stage 2 when `TS_STAR` is set.

**Tech Stack:** bash (harness), Python 3 + matplotlib (analysis/figures), the prebuilt `htsim_uec`.

**Spec:** `docs/superpowers/specs/2026-06-16-prism-eval-tspray-tuning-design.md`

**Commit policy (user standing rule):** do NOT `git commit` unless explicitly asked. "Stage" steps `git add` only; the milestone commit (Task 6) runs solely on the user's approval.

---

## File Structure

| File | New/Mod | Responsibility |
|---|---|---|
| `htsim/sim/datacenter/prism_eval/expA_tspray_tuning/tspray_select.py` | **New** | Pure selector: apply the pre-registered criterion to Stage-1 aggregates → `T_spray*` or `None`. Has `selftest()`. |
| `htsim/sim/datacenter/prism_eval/expA_tspray_tuning/make_figs.py` | **New** | Aggregate (via `common/metrics.py`); `--stage1` (knee fig + criterion table + `T_spray*`); `--stage2 --ts-star N` (4-arm compare fig reusing delay-driven baselines); `--selftest`. |
| `htsim/sim/datacenter/prism_eval/expA_tspray_tuning/repro.sh` | **New** | Selftests; gen workload; Stage-1 sweep (50 sims) + `--stage1`; Stage-2 (25 sims, `TS_STAR`-gated) + `--stage2`. |
| `htsim/sim/datacenter/prism_eval/expA_tspray_tuning/README.md` | **New** (Task 6) | Honest write-up: knee, chosen `T_spray*`, f0 recovery, f8 win preservation, any f2/f4 regression, or contingency trigger. |
| `htsim/sim/datacenter/prism_eval/expA_tspray_tuning/figs/` | **New** | `figT1_knee.{png,pdf}`, `figT2_compare.{png,pdf}` (force-added). |

The `prism_eval/.gitignore` already ignores `*.txt *.csv *.cm *.stdout *.idmap *.dat __pycache__` — so the new `data/` is auto-gitignored; figures (`.png/.pdf`) are tracked.

---

## Task 1: `tspray_select.py` — pure selector + selftest (TDD)

**Files:** Create `htsim/sim/datacenter/prism_eval/expA_tspray_tuning/tspray_select.py`

- [ ] **Step 1: Write the module with a failing selftest first** (write `selftest()` + a stub `select_tspray` that returns `None`, so the asserts fail).

Create the file with this final content (the stub-first sequence is: first write `selftest()` and `def select_tspray(...): return None`, run `--selftest`, watch it assert-fail, then fill in the real body shown below):

```python
#!/usr/bin/env python3
"""Pure selector for the PRISM T_spray tuning experiment. Encodes the PRE-REGISTERED success
criterion (spec 2026-06-16-prism-eval-tspray-tuning-design.md §4) so the choice of T_spray* is
reproducible and not cherry-picked. No plotting / no htsim deps -> unit-testable standalone:
    python3 tspray_select.py --selftest
"""
import sys

def select_tspray(f0_goodput, f8_goodput, reps_f8_goodput, f0_floor, plateau_frac=0.02):
    """Pick T_spray* from Stage-1 endpoint aggregates.

    Args:
      f0_goodput: {t_spray_us: mean goodput Gbps at failed=0}
      f8_goodput: {t_spray_us: mean goodput Gbps at failed=8}
      reps_f8_goodput: REPS+NSCC mean goodput at failed=8 (the win reference)
      f0_floor: min f0 goodput to count as "recovered" (e.g. OPS+NSCC f0 level)
      plateau_frac: treat f0 within this fraction of the best as a plateau.

    Criterion: a T_spray PASSES iff f0_goodput >= f0_floor AND f8_goodput >= 1.15*reps_f8_goodput.
    Among passing values pick the one MAXIMIZING f0 goodput; on a plateau (within plateau_frac of
    the best passing f0) pick the SMALLEST T_spray (least deviation from default, least risk).

    Returns dict: {chosen, bar_f8, passing(sorted list), best_f0}. chosen is None if none pass
    (=> contingency: ratio-based spread test, separate spec).
    """
    bar_f8 = 1.15 * reps_f8_goodput
    passing = [ts for ts in sorted(f0_goodput)
               if f0_goodput[ts] >= f0_floor and f8_goodput[ts] >= bar_f8]
    if not passing:
        return {"chosen": None, "bar_f8": bar_f8, "passing": [], "best_f0": None}
    best_f0 = max(f0_goodput[ts] for ts in passing)
    chosen = min(ts for ts in passing if f0_goodput[ts] >= best_f0 * (1 - plateau_frac))
    return {"chosen": chosen, "bar_f8": bar_f8, "passing": passing, "best_f0": best_f0}

def selftest():
    # Case A: exactly one value threads it (raising T_spray recovers f0 but eventually dents f8).
    f0 = {6: 869, 12: 900, 18: 950, 24: 960, 36: 970}
    f8 = {6: 504, 12: 500, 18: 498, 24: 480, 36: 450}
    r = select_tspray(f0, f8, reps_f8_goodput=431, f0_floor=906)
    assert abs(r["bar_f8"] - 495.65) < 0.1, r
    assert r["passing"] == [18], r          # 12:f0<906; 24/36:f8<bar; 6:f0<906
    assert r["chosen"] == 18, r
    # Case B: plateau among passing -> pick smallest T_spray.
    f0b = {6: 869, 12: 910, 18: 950, 24: 952}
    f8b = {6: 504, 12: 500, 18: 498, 24: 496}
    rb = select_tspray(f0b, f8b, reps_f8_goodput=431, f0_floor=906)
    assert set(rb["passing"]) == {12, 18, 24}, rb
    assert rb["chosen"] == 18, rb           # best_f0=952; within 2% -> {18,24}; smallest=18
    # Case C: none pass (f0 never recovers) -> contingency.
    f0c = {6: 869, 12: 880, 18: 895}
    f8c = {6: 504, 12: 500, 18: 498}
    rc = select_tspray(f0c, f8c, reps_f8_goodput=431, f0_floor=906)
    assert rc["chosen"] is None and rc["passing"] == [], rc
    # Case D: f8 constraint binds (high f0 but win lost) -> excluded.
    f0d = {6: 869, 24: 980}
    f8d = {6: 504, 24: 470}
    rd = select_tspray(f0d, f8d, reps_f8_goodput=431, f0_floor=906)
    assert rd["chosen"] is None, rd         # 24 has great f0 but f8 470 < 495.65
    print("ok tspray_select")

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        print("usage: tspray_select.py --selftest")
```

- [ ] **Step 2: Run the selftest against the stub to verify it fails**

Run: `cd /home/leo/htsim/htsim/sim/datacenter/prism_eval/expA_tspray_tuning && python3 tspray_select.py --selftest`
Expected (with the stub `return None`): FAIL — `TypeError`/`AssertionError` (stub returns `None`, so `r["bar_f8"]` raises).

- [ ] **Step 3: Replace the stub with the real `select_tspray` body** (shown in Step 1).

- [ ] **Step 4: Run the selftest to verify it passes**

Run: `cd /home/leo/htsim/htsim/sim/datacenter/prism_eval/expA_tspray_tuning && python3 tspray_select.py --selftest`
Expected: PASS — prints `ok tspray_select`.

- [ ] **Step 5: Stage (DO NOT COMMIT)**

```bash
git -C /home/leo/htsim add htsim/sim/datacenter/prism_eval/expA_tspray_tuning/tspray_select.py
```

---

## Task 2: `make_figs.py` — aggregation + knee + compare + selftest

**Files:** Create `htsim/sim/datacenter/prism_eval/expA_tspray_tuning/make_figs.py`

- [ ] **Step 1: Create the file** with this content:

```python
#!/usr/bin/env python3
"""Figures + criterion for the PRISM T_spray tuning experiment.
  python3 make_figs.py --selftest             # aggregation + selector smoke
  python3 make_figs.py --stage1               # knee fig + criterion table + recommended T_spray*
  python3 make_figs.py --stage2 --ts-star N   # 4-arm compare fig (reuses delay-driven baselines)
Reads local sweep data from ./data; reuses OPS/REPS/STrack/PRISM-default from ../expA_delaydriven/data.
"""
import os, sys, statistics
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import metrics          # noqa: E402
import plot_style       # noqa: E402
import tspray_select    # noqa: E402  (same dir)

DATA   = os.path.join(HERE, "data")
FIGS   = os.path.join(HERE, "figs")
REUSE  = os.path.join(HERE, "..", "expA_delaydriven", "data")  # committed baseline data (read-only)
SEEDS  = [13, 14, 15, 16, 17]
TSLIST = [6, 12, 18, 24, 36]
F0_FLOOR_LABEL = "OPS+NSCC f0"   # f0 recovery bar = OPS+NSCC f0 goodput (no longer the worst arm)

def _mean(xs):
    return statistics.mean(xs) if xs else float("nan")

def agg_arm(data_dir, tag, failed_list, seeds):
    """{failed: {'goodput':mean, 'avg_fct':mean, 'p99_fct':mean, 'cr':mean}} for files
    {data_dir}/{tag}_f{f}_s{s}.flow.txt ; skips missing cells."""
    out = {}
    for f in failed_list:
        g, a, p, c = [], [], [], []
        for s in seeds:
            fp = os.path.join(data_dir, f"{tag}_f{f}_s{s}.flow.txt")
            if not os.path.exists(fp):
                continue
            st = metrics.fct_stats(fp)
            g.append(metrics.aggregate_goodput_gbps(fp))
            a.append(st["avg_s"] * 1e6); p.append(st["p99_s"] * 1e6); c.append(st["completion_rate"])
        if g:
            out[f] = {"goodput": _mean(g), "avg_fct": _mean(a), "p99_fct": _mean(p), "cr": _mean(c)}
    return out

def stage1():
    """Aggregate the T_spray x {f0,f8} sweep, render the knee figure, print the criterion table
    and the selected T_spray* (or contingency)."""
    import matplotlib.pyplot as plt
    plot_style.apply_style(13)
    # sweep aggregates: {ts: {0:{...}, 8:{...}}}
    f0_g, f8_g, f0_a, f8_a = {}, {}, {}, {}
    for ts in TSLIST:
        a = agg_arm(DATA, f"tsweep_ts{ts}", [0, 8], SEEDS)
        if 0 in a: f0_g[ts] = a[0]["goodput"]; f0_a[ts] = a[0]["avg_fct"]
        if 8 in a: f8_g[ts] = a[8]["goodput"]; f8_a[ts] = a[8]["avg_fct"]
    # reference baselines from the committed delay-driven run
    reps = agg_arm(REUSE, "expA_reps", [0, 8], SEEDS)
    ops  = agg_arm(REUSE, "expA_ops",  [0], SEEDS)
    reps_f0, reps_f8 = reps[0]["goodput"], reps[8]["goodput"]
    f0_floor = ops[0]["goodput"]
    sel = tspray_select.select_tspray(f0_g, f8_g, reps_f8_goodput=reps_f8, f0_floor=f0_floor)
    # ---- figure: goodput (top) + avg-FCT (bottom) vs T_spray ----
    fig, (ax_g, ax_f) = plt.subplots(2, 1, figsize=(5.4, 7.0), sharex=True)
    xs = TSLIST
    ax_g.plot(xs, [f0_g[t] for t in xs], "o-", color=plot_style.COLORS["prism"], lw=2, label="PRISM goodput @f0")
    ax_g.plot(xs, [f8_g[t] for t in xs], "s--", color=plot_style.COLORS["prism"], lw=2, label="PRISM goodput @f8")
    ax_g.axhline(reps_f0, color=plot_style.COLORS["reps"], ls=":", lw=1.3, label=f"REPS+NSCC f0 ({reps_f0:.0f})")
    ax_g.axhline(f0_floor, color=plot_style.COLORS["ops"], ls=":", lw=1.3, label=f"{F0_FLOOR_LABEL} floor ({f0_floor:.0f})")
    ax_g.axhline(sel["bar_f8"], color=plot_style.COLORS["ccc"], ls="--", lw=1.3, label=f"f8 +15% bar ({sel['bar_f8']:.0f})")
    ax_g.set_ylabel("Goodput (Gbps)"); ax_g.grid(alpha=0.3); ax_g.legend(fontsize=8)
    title = f"T_spray* = {sel['chosen']} us" if sel["chosen"] is not None else "no static T_spray passes -> contingency"
    ax_g.set_title(title, fontsize=11)
    ax_f.plot(xs, [f0_a[t] for t in xs], "o-", color=plot_style.COLORS["prism"], lw=2, label="PRISM avg-FCT @f0")
    ax_f.plot(xs, [f8_a[t] for t in xs], "s--", color=plot_style.COLORS["prism"], lw=2, label="PRISM avg-FCT @f8")
    ax_f.set_ylabel("Avg FCT (us)"); ax_f.set_xlabel("T_spray (us)  [6 = default = target]")
    ax_f.set_xticks(xs); ax_f.grid(alpha=0.3); ax_f.legend(fontsize=8)
    plt.tight_layout(); plot_style.save(fig, "figT1_knee", FIGS); plt.close(fig)
    # ---- criterion table ----
    print(f"[stage1] f0_floor={f0_floor:.0f} (OPS f0) ; f8 win bar=1.15*REPS_f8={sel['bar_f8']:.0f} (REPS_f8={reps_f8:.0f})")
    for ts in TSLIST:
        passes = (ts in sel["passing"])
        print(f"  T_spray={ts:>2}us  f0_goodput={f0_g[ts]:6.1f}  f8_goodput={f8_g[ts]:6.1f}  "
              f"f0_fct={f0_a[ts]:6.0f}us  f8_fct={f8_a[ts]:6.0f}us  {'PASS' if passes else 'fail'}")
    if sel["chosen"] is not None:
        print(f"[stage1] SELECTED T_spray* = {sel['chosen']} us  "
              f"(recovers f0 to {f0_g[sel['chosen']]:.0f}, keeps f8 {f8_g[sel['chosen']]:.0f} >= bar {sel['bar_f8']:.0f}). "
              f"Run Stage 2:  TS_STAR={sel['chosen']} bash repro.sh")
    else:
        print("[stage1] NO static T_spray satisfies the criterion -> trigger CONTINGENCY "
              "(ratio-based spread test; see spec §4). Do NOT pick a value manually.")

def stage2(ts_star):
    """4-arm compare over full failed grid: PRISM-default & PRISM-tuned vs REPS+NSCC & STrack.
    Baselines + PRISM-default are reused read-only from ../expA_delaydriven/data."""
    import matplotlib.pyplot as plt
    plot_style.apply_style(13)
    failed = [0, 2, 4, 8, 12]
    arms = [  # (display, data_dir, tag, color)
        ("OPS+NSCC", REUSE, "expA_ops", plot_style.COLORS["ops"]),
        ("REPS+NSCC", REUSE, "expA_reps", plot_style.COLORS["reps"]),
        ("STrack", REUSE, "expA_strack", plot_style.COLORS["strack"]),
        ("PRISM (T_spray=6, default)", REUSE, "expA_prism", plot_style.COLORS["prism"]),
        (f"PRISM (T_spray={ts_star})", DATA, "tsval", "tab:purple"),
    ]
    aggs = [(disp, agg_arm(d, tag, failed, SEEDS), col) for (disp, d, tag, col) in arms]
    fig, axes = plt.subplots(3, 1, figsize=(5.4, 8.2), sharex=True)
    for ax, (key, ylab) in zip(axes, [("goodput", "Goodput (Gbps)"), ("avg_fct", "Avg FCT (us)"), ("p99_fct", "P99 FCT (us)")]):
        for (disp, ag, col) in aggs:
            xs = [f for f in failed if f in ag]
            ax.plot(xs, [ag[f][key] for f in xs], "o-", lw=2, ms=6, color=col, label=disp)
        ax.set_ylabel(ylab); ax.grid(alpha=0.3)
    axes[0].legend(fontsize=8); axes[0].set_title(f"T_spray tuning: default vs {ts_star}us", fontsize=11)
    axes[-1].set_xlabel("# constrained core->agg links (-failed), delay-driven"); axes[-1].set_xticks(failed)
    plt.tight_layout(); plot_style.save(fig, "figT2_compare", FIGS); plt.close(fig)
    # honest table
    for (disp, ag, _c) in aggs:
        print(f"[figT2_compare] {disp}: " + " ".join(
            f"f{f}:g={ag[f]['goodput']:.0f},afct={ag[f]['avg_fct']:.0f},cr={ag[f]['cr']:.2f}" for f in failed if f in ag))

def selftest():
    import tempfile, shutil
    d = tempfile.mkdtemp()
    # two cells of fabricated flow data; agg_arm must average goodput/fct and tolerate missing files
    for f in (0, 8):
        for s in SEEDS:
            with open(os.path.join(d, f"tsweep_ts18_f{f}_s{s}.flow.txt"), "w") as fh:
                fh.write("0.000000000 Type FLOW_EVENT SrcID 1 Ev START FlowID 1 Flowsize 1000000\n")
                fh.write("0.001000000 Type FLOW_EVENT SrcID 1 Ev FINISH FlowID 1 Bytes 1000000 Pkts 1\n")
    a = agg_arm(d, "tsweep_ts18", [0, 8], SEEDS)
    assert abs(a[0]["goodput"] - 8.0) < 1e-6, a       # 1e6 bytes*8 / 1e-3 s = 8 Gbps
    assert abs(a[0]["avg_fct"] - 1000.0) < 1e-6, a    # 1 ms = 1000 us
    assert 99 not in agg_arm(d, "nope", [99], SEEDS), "missing cells must be skipped"
    shutil.rmtree(d)
    tspray_select.selftest()
    print("ok tspray make_figs aggregation selftest")

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--stage2" in sys.argv:
        i = sys.argv.index("--ts-star"); stage2(int(sys.argv[i + 1]))
    elif "--stage1" in sys.argv:
        stage1()
    else:
        print("usage: make_figs.py [--selftest | --stage1 | --stage2 --ts-star N]")
```

- [ ] **Step 2: Verify the selftest passes** (validates `agg_arm` math + delegates to `tspray_select.selftest`)

Run: `cd /home/leo/htsim/htsim/sim/datacenter/prism_eval/expA_tspray_tuning && python3 make_figs.py --selftest`
Expected: prints `ok tspray_select` then `ok tspray make_figs aggregation selftest`.

- [ ] **Step 3: Confirm `metrics.fct_stats` returns the keys this file uses** (`avg_s`, `p99_s`, `completion_rate`)

Run: `cd /home/leo/htsim/htsim/sim/datacenter/prism_eval && python3 -c "import sys; sys.path.insert(0,'common'); import metrics, inspect; print([k for k in ['avg_s','p99_s','completion_rate']])"`
Expected: prints `['avg_s', 'p99_s', 'completion_rate']` — and the `--selftest` in Step 2 already exercised `avg_s`/goodput, so if it passed the keys are correct. (If `fct_stats` uses different key names, fix the references in `agg_arm` to match `common/metrics.py` and re-run Step 2.)

- [ ] **Step 4: Stage (DO NOT COMMIT)**

```bash
git -C /home/leo/htsim add htsim/sim/datacenter/prism_eval/expA_tspray_tuning/make_figs.py
```

---

## Task 3: `repro.sh` — Stage-1 sweep + Stage-2 gate + workload + smoke

**Files:** Create `htsim/sim/datacenter/prism_eval/expA_tspray_tuning/repro.sh`

- [ ] **Step 1: Create the script** with this content:

```bash
#!/bin/bash
# PRISM T_spray tuning (delay-driven regime). Stage 1 always; Stage 2 when TS_STAR is set.
# Sweeps the EXISTING -prism_t_spray knob via run_lib.sh EXTRA_ARGS -- no controller code change.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../common" && pwd)"
DC="$(cd "$HERE/../.." && pwd)"
REL="prism_eval/expA_tspray_tuning"
cd "$DC"
[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first"; exit 1; }
mkdir -p "$REL/data"
SEEDS="13 14 15 16 17"; TSLIST="6 12 18 24 36"; TOPO=fat_tree_128_1os.topo
DD="-disable_trim"; ENDV="${EXP_END:-8}"

echo "== self-tests =="
python3 "$HERE/tspray_select.py" --selftest
python3 "$HERE/make_figs.py" --selftest

echo "== generate workload (many2many 64->16 pod0, 2MB; same args as expA_delaydriven => identical) =="
python3 "$COMMON/gen/many2many.py" "$REL/data/m2m.cm" 64 16 pairs 2000000 128 16
CM="$REL/data/m2m.cm"; OUT="$REL/data"
# Guard: the reused baselines were generated with the same args; confirm byte-identical workload.
if [ -f "$DC/prism_eval/expA_delaydriven/data/m2m.cm" ]; then
  diff -q "$CM" "$DC/prism_eval/expA_delaydriven/data/m2m.cm" \
    || { echo "ERROR: workload differs from expA_delaydriven -- Stage-2 reuse would not be apples-to-apples"; exit 1; }
fi

echo "== Stage 1: T_spray {$(echo $TSLIST)} x failed {0,8} x 5 seeds =="
for ts in $TSLIST; do for f in 0 8; do for s in $SEEDS; do
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD -prism_t_spray $ts" \
    bash "$COMMON/run_lib.sh" prism reps "$f" "$TOPO" "$s" "$CM" flow,sink "tsweep_ts${ts}_f${f}_s${s}" "$OUT"
done; done; done

echo "== Stage 1 analysis (knee fig + criterion + T_spray*) =="
python3 "$HERE/make_figs.py" --stage1

if [ -n "${TS_STAR:-}" ]; then
  echo "== Stage 2: validate PRISM at T_spray=$TS_STAR over failed {0,2,4,8,12} x 5 seeds =="
  for f in 0 2 4 8 12; do for s in $SEEDS; do
    PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD -prism_t_spray $TS_STAR" \
      bash "$COMMON/run_lib.sh" prism reps "$f" "$TOPO" "$s" "$CM" flow,sink "tsval_f${f}_s${s}" "$OUT"
  done; done
  echo "== Stage 2 figure (figT2_compare) =="
  python3 "$HERE/make_figs.py" --stage2 --ts-star "$TS_STAR"
  echo "== done: figs/figT1_knee.* figs/figT2_compare.* =="
else
  echo "TS_STAR unset -> Stage 2 skipped. Pick T_spray* from the Stage-1 table above, then run:"
  echo "    TS_STAR=<us> bash $REL/repro.sh"
  echo "== done: figs/figT1_knee.* =="
fi
```

- [ ] **Step 2: Make it executable**

Run: `chmod +x /home/leo/htsim/htsim/sim/datacenter/prism_eval/expA_tspray_tuning/repro.sh`

- [ ] **Step 3: Smoke-test ONE Stage-1 cell** (wiring check — the `-prism_t_spray` knob reaches the binary)

Run (from `/home/leo/htsim/htsim/sim/datacenter`):
```bash
mkdir -p /tmp/ts_smoke
python3 prism_eval/common/gen/many2many.py /tmp/ts_smoke/m2m.cm 64 16 pairs 2000000 128 16
PATHS=8 END_MS=8 EXTRA_ARGS="-disable_trim -prism_t_spray 18" \
  bash prism_eval/common/run_lib.sh prism reps 0 fat_tree_128_1os.topo 13 /tmp/ts_smoke/m2m.cm flow,sink tsweep_ts18_f0_s13 /tmp/ts_smoke
grep -c "prism_t_spray 18" /tmp/ts_smoke/tsweep_ts18_f0_s13.stdout
ls -la /tmp/ts_smoke/tsweep_ts18_f0_s13.flow.txt
```
Expected: the grep prints `1` (binary echoed `prism_t_spray 18` — confirms the knob parsed), and the `.flow.txt` exists and is non-empty.

- [ ] **Step 4: Confirm the workload generator is deterministic** (so Stage-2 reuse is apples-to-apples)

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter
python3 prism_eval/common/gen/many2many.py /tmp/ts_a.cm 64 16 pairs 2000000 128 16
python3 prism_eval/common/gen/many2many.py /tmp/ts_b.cm 64 16 pairs 2000000 128 16
diff -q /tmp/ts_a.cm /tmp/ts_b.cm && echo "deterministic: identical"
```
Expected: `deterministic: identical`. (If they differ, the generator is seeded; in that case the plan's Stage-2 reuse is invalid — STOP and report, so we instead point `CM` at `../expA_delaydriven/data/m2m.cm` directly.)

- [ ] **Step 5: Stage (DO NOT COMMIT)**

```bash
git -C /home/leo/htsim add htsim/sim/datacenter/prism_eval/expA_tspray_tuning/repro.sh
```

---

## Task 4: Run Stage 1 + select T_spray* — controller-owned

**Files:** none (produces gitignored `data/` + `figs/figT1_knee.*`).

- [ ] **Step 1: Run Stage 1**

Run (from `/home/leo/htsim/htsim/sim/datacenter`): `bash prism_eval/expA_tspray_tuning/repro.sh`
Expected: selftests pass; 50 sims; `figT1_knee.{png,pdf}` rendered; prints the criterion table + either `SELECTED T_spray* = N us` or the contingency message.

- [ ] **Step 2: Record the criterion table and the selected value** (or contingency trigger). Inspect `figT1_knee.png` to confirm the knee shape matches the table.

- [ ] **Step 3: Branch on the outcome.**
  - If `T_spray*` selected → proceed to Task 5 with `TS_STAR=<that value>`.
  - If contingency triggered (no static value passes) → STOP Task 5/6; report to the user that a static T_spray cannot thread it and that the ratio-based spread test (spec §4) is the next step (a new brainstorm→spec→plan). Do NOT hand-pick a value.

---

## Task 5: Run Stage 2 at T_spray* — controller-owned

**Files:** none (produces gitignored `data/` + `figs/figT2_compare.*`).

- [ ] **Step 1: Run Stage 2 at the selected value**

Run (from `/home/leo/htsim/htsim/sim/datacenter`): `TS_STAR=<value from Task 4> bash prism_eval/expA_tspray_tuning/repro.sh`
Expected: re-runs Stage 1 (cached-cheap is fine) + 25 Stage-2 sims; renders `figT2_compare.{png,pdf}`; prints the 5-arm table.

- [ ] **Step 2: Read the full-grid comparison.** Confirm against the criterion: PRISM-tuned f0 goodput ≥ f0_floor AND PRISM-tuned f8 ≥ +15% bar, AND check the intermediate levels (f2/f4) for any regression vs PRISM-default. Note all numbers honestly (goodput, avg-FCT, cr per level).

---

## Task 6: Honest write-up + memory + commit — controller-owned

**Files:**
- Create: `htsim/sim/datacenter/prism_eval/expA_tspray_tuning/README.md`
- Modify (after milestone): memory `prism-eval-roadmap.md` + `MEMORY.md` pointer.

- [ ] **Step 1: Write the README** — setup; the knee table + chosen `T_spray*` (with the pre-registered rule quoted); the Stage-2 4-arm result table; an explicit honest verdict: did `T_spray*` recover f0 to ≥ OPS level while keeping f8 ≥ +15%? Any f2/f4 regression? State it straight, no cherry-picking. If contingency triggered, the README documents that static tuning failed and points to the ratio-test next step.

- [ ] **Step 2: Milestone commit (ON USER APPROVAL ONLY)** — per the commit policy, ask the user first. On approval:

```bash
git -C /home/leo/htsim add -f \
  htsim/sim/datacenter/prism_eval/expA_tspray_tuning/figs/figT1_knee.png \
  htsim/sim/datacenter/prism_eval/expA_tspray_tuning/figs/figT1_knee.pdf \
  htsim/sim/datacenter/prism_eval/expA_tspray_tuning/figs/figT2_compare.png \
  htsim/sim/datacenter/prism_eval/expA_tspray_tuning/figs/figT2_compare.pdf
git -C /home/leo/htsim add \
  htsim/sim/datacenter/prism_eval/expA_tspray_tuning/tspray_select.py \
  htsim/sim/datacenter/prism_eval/expA_tspray_tuning/make_figs.py \
  htsim/sim/datacenter/prism_eval/expA_tspray_tuning/repro.sh \
  htsim/sim/datacenter/prism_eval/expA_tspray_tuning/README.md \
  docs/superpowers/specs/2026-06-16-prism-eval-tspray-tuning-design.md \
  docs/superpowers/plans/2026-06-16-prism-eval-tspray-tuning.md
git -C /home/leo/htsim commit -m "prism_eval: T_spray tuning -- mitigate f0 symmetric penalty"
```

- [ ] **Step 3: Update memory** (`prism-eval-roadmap.md` status: T_spray tuning done + one-line result + chosen value; or contingency-triggered) — only after the user approves.

---

## Self-Review (against the spec)

**Spec coverage:**
- §1 goal (mitigate f0 penalty via T_spray) → Tasks 3–5. ✓
- §2 mechanism evidence → already gathered (in spec); not re-derived in the plan (the experiment tests it). ✓
- §3 two-stage, T_spray {6,12,18,24,36}, delay-driven, seeds {13..17}, endpoints {0,8} then full grid, reuse baselines → Task 3 (repro.sh stages), Task 2 (`stage2` reads `REUSE`). ✓
- §4 pre-registered criterion + selection rule + contingency → Task 1 (`select_tspray`, unit-tested incl. the contingency `None` case) + Task 4 Step 3 (branch on contingency). ✓
- §5 reproducibility (seeds, EXTRA_ARGS knob, raw gitignored, figs add, selftest in repro, TS_STAR-gated Stage 2, workload byte-identity guard) → Task 3. ✓
- §6 non-goals (no controller code change; ratio test deferred; honest reporting incl. regressions) → no `uec.*` edits anywhere; Task 4/5/6 report straight. ✓

**Placeholder scan:** all code shown in full; no TBD. `T_spray*` is a runtime-selected value (Task 4), not a placeholder; Tasks 5/6 are explicitly controller-owned and parameterized by it. ✓

**Type/name consistency:** `select_tspray(f0_goodput, f8_goodput, reps_f8_goodput, f0_floor, plateau_frac)` returns `{chosen, bar_f8, passing, best_f0}` — used identically in `make_figs.stage1`. `agg_arm(data_dir, tag, failed_list, seeds)` returns `{f: {goodput, avg_fct, p99_fct, cr}}` — keys match every consumer in `stage1`/`stage2`. Tags consistent: Stage-1 `tsweep_ts{ts}_f{f}_s{s}`, Stage-2 `tsval_f{f}_s{s}`, reused `expA_{ops,reps,strack,prism}_f{f}_s{s}`. Figure stems `figT1_knee` / `figT2_compare` consistent across make_figs, repro.sh, and Task 6. ✓
