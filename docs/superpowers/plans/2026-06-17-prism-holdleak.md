# PRISM HOLD-leak — do-no-harm controlled experiment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a flag-gated, default-OFF `_prism_hold_leak` knob that lets PRISM's window grow a leak-scaled fraction of the proportional-AI during HOLD, then sweep it to test whether it recovers part of the f0 symmetric cost without eroding the f8/f12 win — keeping PRISM O(1).

**Architecture:** One static scalar `_prism_hold_leak ∈ [0,1]` (default 0 = byte-identical to today's PRISM). When >0, two small branches in `updateCwndOnAck_PRISM` accumulate and apply a leak-scaled *proportional* increase during HOLD only (no `fast_increase`, no `_eta`; DECREASE/cuts untouched). A new read-only experiment group sweeps `leak × failed × seed`, computes f0-recovery and f8/f12-erosion vs leak=0, and emits an honest verdict.

**Tech Stack:** C++ (htsim `UecSrc`), CMake build, bash harness, Python 3 + matplotlib analysis (reusing `prism_eval/common`).

---

## Conventions binding on every task (read first)

- **NO git commits during execution.** The user's standing rule overrides the writing-plans "frequent commits" default. End each task with changes in the working tree; one milestone commit only on **explicit user approval** (Task 5). "Stage" means `git add`-ready, never committed.
- **Default OFF is sacred:** `_prism_hold_leak` defaults to `0.0`, and both new branches are gated by `_prism_hold_leak > 0.0`, so leak=0 is byte-identical to committed PRISM. This is verified in Task 1.
- **O(1):** one scalar, reusing existing `_inc_bytes`. No per-path state anywhere.
- **Reviewers review the working-tree diff** (`git diff`), since nothing is committed.
- **Rebuild after the controller change:** `cd htsim/sim/build && cmake --build . --target htsim_uec -j` (binary symlinked at `htsim/sim/datacenter/htsim_uec`).
- Paths are relative to repo root `/home/leo/htsim`; datacenter dir = `htsim/sim/datacenter/` (DC).
- Honest reporting: report the full leak×failed table and a clear positive/negative verdict; a net-negative tradeoff is recorded straight (like loss-decomp / persistence), and the leak=0 default is kept.

---

## File structure

| File | Responsibility | Task |
|---|---|---|
| `htsim/sim/uec.h` | declare `static double _prism_hold_leak;` | 1 |
| `htsim/sim/uec.cpp` | static def `= 0.0`; per-ACK HOLD-leak accumulate branch; HOLD-leak fulfill branch | 1 |
| `htsim/sim/datacenter/main_uec.cpp` | parse `-prism_hold_leak` | 1 |
| `htsim/sim/datacenter/main_uec_sf.cpp` | parse `-prism_hold_leak` (mirror; for consistency) | 1 |
| `htsim/sim/datacenter/prism_eval/expA_holdleak/holdleak_analyze.py` | aggregate sweep, verdict, figure, `--selftest` | 2 |
| `htsim/sim/datacenter/prism_eval/expA_holdleak/repro.sh` | build check, selftest, workload, sweep, render | 2,3 |
| `htsim/sim/datacenter/prism_eval/expA_holdleak/README.md` | setup, do-no-harm table, honest verdict | 4 |
| `htsim/sim/datacenter/prism_eval/expA_holdleak/figs/figHL_holdleak.{png,pdf}` | goodput vs leak per failed | 3 |

---

## Task 1: Controller change — `_prism_hold_leak` (flag-gated, default OFF)

**Files:** Modify `htsim/sim/uec.h`, `htsim/sim/uec.cpp`, `htsim/sim/datacenter/main_uec.cpp`, `htsim/sim/datacenter/main_uec_sf.cpp`.

- [ ] **Step 1: Declare the static member in `uec.h`**

After the line `static double _prism_kappa;    // epoch length = kappa * base_rtt; default 1.0` (uec.h ~373), add:

```cpp
    static double _prism_hold_leak;  // -prism_hold_leak; default 0.0 (== today's PRISM, frozen HOLD).
                                     // >0: HOLD grows leak * proportional-AI (no fast_increase/_eta). O(1).
```

- [ ] **Step 2: Define the static in `uec.cpp`**

After `double UecSrc::_prism_kappa = 1.0;` (uec.cpp ~99), add:

```cpp
double UecSrc::_prism_hold_leak = 0.0;   // default off -> HOLD freezes the window (byte-identical PRISM)
```

- [ ] **Step 3: Add the per-ACK HOLD-leak accumulate branch in `updateCwndOnAck_PRISM`**

Replace the in-epoch action block (uec.cpp ~1513–1518):

```cpp
    if (_prism_region == prism::INCREASE) {
        simtime_picosec inc_delay = _prism_ccc;
        if (_target_Qdelay > 0 && inc_delay > _target_Qdelay - 1)
            inc_delay = _target_Qdelay - 1;
        proportional_increase(newly_acked_bytes, inc_delay);
    }
```

with:

```cpp
    if (_prism_region == prism::INCREASE) {
        simtime_picosec inc_delay = _prism_ccc;
        if (_target_Qdelay > 0 && inc_delay > _target_Qdelay - 1)
            inc_delay = _target_Qdelay - 1;
        proportional_increase(newly_acked_bytes, inc_delay);
    } else if (_prism_region == prism::HOLD && _prism_hold_leak > 0.0) {
        // HOLD-leak prototype (default 0 == OFF): accumulate a leak-scaled proportional-AI budget
        // ONLY -- no fast_increase (no cold-start ramp), no _eta (no creep). Applied by the gated
        // HOLD fulfill branch below. Mirrors proportional_increase()'s core increment, scaled.
        simtime_picosec inc_delay = _prism_ccc;
        if (_target_Qdelay > 0 && inc_delay > _target_Qdelay - 1)
            inc_delay = _target_Qdelay - 1;
        _inc_bytes += (mem_b)(_prism_hold_leak * _alpha * (double)newly_acked_bytes
                              * (double)(_target_Qdelay - inc_delay));
    }
```

- [ ] **Step 4: Add the HOLD-leak fulfill branch**

Replace the fulfill block (uec.cpp ~1579–1584):

```cpp
    set_cwnd_bounds();
    if (_prism_region == prism::INCREASE
            && (_received_bytes > _adjust_bytes_threshold
                || eventlist().now() - _last_adjust_time > _adjust_period_threshold)) {
        fulfill_adjustment();
    }
    set_cwnd_bounds();
```

with:

```cpp
    set_cwnd_bounds();
    if (_prism_region == prism::INCREASE
            && (_received_bytes > _adjust_bytes_threshold
                || eventlist().now() - _last_adjust_time > _adjust_period_threshold)) {
        fulfill_adjustment();
    } else if (_prism_region == prism::HOLD && _prism_hold_leak > 0.0
            && (_received_bytes > _adjust_bytes_threshold
                || eventlist().now() - _last_adjust_time > _adjust_period_threshold)) {
        // Apply the leaked proportional budget ONLY (no periodic _eta), then reset like
        // fulfill_adjustment so the leak applies at most once per adjust window (same cadence as
        // INCREASE), making `leak` a clean rate dial.
        _cwnd += _inc_bytes / _cwnd;
        _inc_bytes = 0;
        _received_bytes = 0;
        _last_adjust_time = eventlist().now();
    }
    set_cwnd_bounds();
```

(The epoch-boundary block at ~1539–1546 that zeroes `_inc_bytes` on `region != INCREASE` is left
UNCHANGED: it drops the prior INCREASE epoch's budget and any HOLD-epoch leftover at the boundary —
negligible — while the per-ACK branch re-accumulates fresh leak during each HOLD epoch.)

- [ ] **Step 5: Parse `-prism_hold_leak` in `main_uec.cpp`**

After the `-prism_kappa` else-if block (main_uec.cpp ~197–200, ending `i++;`), add:

```cpp
        } else if (!strcmp(argv[i],"-prism_hold_leak")) {
            UecSrc::_prism_hold_leak = atof(argv[i+1]);
            cout << "prism_hold_leak " << UecSrc::_prism_hold_leak << endl;
            i++;
```

- [ ] **Step 6: Parse `-prism_hold_leak` in `main_uec_sf.cpp`**

After that file's `-prism_kappa` else-if block (main_uec_sf.cpp ~182–184), add the same block:

```cpp
        } else if (!strcmp(argv[i], "-prism_hold_leak")) {
            UecSrc::_prism_hold_leak = atof(argv[i + 1]);
            cout << "prism_hold_leak " << UecSrc::_prism_hold_leak << endl;
            i++;
```

(Match this file's existing brace/indent/`i++` style exactly; if its kappa block omits `i++` or uses
a different increment, mirror that.)

- [ ] **Step 7: Build**

Run: `cd htsim/sim/build && cmake --build . --target htsim_uec -j`
Expected: builds with no errors; `htsim/sim/datacenter/htsim_uec` updated.

- [ ] **Step 8: Verify leak=0 is a no-op (byte-identical) and the flag is wired**

Run from DC (`htsim/sim/datacenter`):

```bash
cd /home/leo/htsim/htsim/sim/datacenter
python3 prism_eval/common/gen/many2many.py /tmp/hl_m2m.cm 64 16 pairs 2000000 128 16
run() { PATHS=8 END_MS=8 EXTRA_ARGS="$2" bash prism_eval/common/run_lib.sh prism reps 0 \
        fat_tree_128_1os.topo 13 /tmp/hl_m2m.cm flow,sink "$1" /tmp/hl_t >/dev/null 2>&1; }
run noflag "-disable_trim"
run leak0   "-disable_trim -prism_hold_leak 0"
run leak50  "-disable_trim -prism_hold_leak 0.5"
python3 - <<'PY'
import sys; sys.path.insert(0,"prism_eval/common"); import metrics
g=lambda t: metrics.aggregate_goodput_gbps(f"/tmp/hl_t/{t}.flow.txt")
n,z,h=g("noflag"),g("leak0"),g("leak50")
print(f"noflag={n:.10f}  leak0={z:.10f}  leak0.5={h:.10f}")
assert abs(n-z)<1e-9, "leak=0 must equal no-flag (default-off no-op)"
print("OK leak=0 byte-identical;", "leak>0 CHANGES behavior" if abs(h-z)>1e-6 else "WARN leak>0 had no effect")
PY
rm -rf /tmp/hl_t /tmp/hl_m2m.cm
```

Expected: `noflag == leak0` exactly (assert passes); `leak0.5` differs from `leak0` (flag wired and
active). If `leak0.5` does not differ, STOP — the branches are not firing; investigate before Task 2.

- [ ] **Step 9: Do NOT commit** — leave the controller change in the working tree.

---

## Task 2: `expA_holdleak` harness (analysis + repro) + wiring smoke

**Files:** Create `htsim/sim/datacenter/prism_eval/expA_holdleak/holdleak_analyze.py`, `.../repro.sh`.

- [ ] **Step 1: Create `holdleak_analyze.py`**

```python
#!/usr/bin/env python3
"""Analyze the HOLD-leak sweep: does a leak recover f0 without eroding the f8/f12 win? Reads
hl_prism_l{code}_f{failed}_s{seed}.flow.txt (code = round(leak*100)) and hl_reps_f{failed}_s{seed}
.flow.txt. Pre-registered verdict: a leak is ADMISSIBLE iff f8 AND f12 goodput stay within
max(3% of leak=0, 1 SD) of leak=0; POSITIVE iff some admissible leak recovers >= 1/3 of the f0
goodput gap (leak=0 -> REPS+NSCC). Reuses common/metrics.py + plot_style.py.
  python3 holdleak_analyze.py            # verdict + figHL_holdleak
  python3 holdleak_analyze.py --selftest # logic self-check
"""
import os, sys, statistics
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import metrics       # noqa: E402
import plot_style    # noqa: E402

LEAKS = [(0, 0.0), (10, 0.1), (25, 0.25), (50, 0.5), (75, 0.75), (100, 1.0)]  # (code, leak)
FAILEDS = [0, 2, 4, 8, 12]
SEEDS = [13, 14, 15, 16, 17]

def _ms(v):
    return (statistics.mean(v), statistics.pstdev(v)) if v else (float("nan"), float("nan"))

def _agg_goodput(data_dir, name_of):
    """{failed: (mean,std)} aggregating goodput over seeds; name_of(failed,seed)->flow filename."""
    out = {}
    for f in FAILEDS:
        gs = []
        for s in SEEDS:
            fp = os.path.join(data_dir, name_of(f, s))
            if os.path.exists(fp):
                gs.append(metrics.aggregate_goodput_gbps(fp))
        if gs:
            out[f] = _ms(gs)
    return out

def analyze(data_dir):
    prism = {code: _agg_goodput(data_dir, lambda f, s, c=code: f"hl_prism_l{c}_f{f}_s{s}.flow.txt")
             for code, _leak in LEAKS}
    reps = _agg_goodput(data_dir, lambda f, s: f"hl_reps_f{f}_s{s}.flow.txt")
    return prism, reps

def evaluate(prism, reps):
    """Return (rows, admissible, best). rows: per-leak dict with f0 recovery + f8/f12 deltas + ok."""
    base = prism.get(0, {})
    g0_f0 = base.get(0, (float("nan"), 0))[0]
    g_reps_f0 = reps.get(0, (float("nan"), 0))[0]
    gap = g_reps_f0 - g0_f0
    rows, admissible = [], []
    for code, leak in LEAKS:
        if code == 0:
            continue
        ok, notes = True, []
        for f in (8, 12):
            b = base.get(f); cur = prism.get(code, {}).get(f)
            if not b or not cur:
                ok = False; notes.append(f"f{f} missing"); continue
            tol = max(0.03 * b[0], b[1])           # 3% of leak=0 mean, or 1 SD, whichever larger
            if cur[0] < b[0] - tol:
                ok = False; notes.append(f"f{f}:{cur[0]:.0f}<{b[0]-tol:.0f}")
        gf0 = prism.get(code, {}).get(0, (float("nan"), 0))[0]
        rec = (gf0 - g0_f0) / gap if gap > 0 else float("nan")
        row = {"leak": leak, "f0": gf0, "recovery": rec,
               "f8": prism.get(code, {}).get(8, (float("nan"), 0))[0],
               "f12": prism.get(code, {}).get(12, (float("nan"), 0))[0],
               "ok": ok, "notes": notes}
        rows.append(row)
        if ok and rec == rec and rec >= 1.0 / 3.0:
            admissible.append(row)
    best = max(admissible, key=lambda r: r["recovery"]) if admissible else None
    return rows, admissible, best, (g0_f0, g_reps_f0, gap)

def verdict(prism, reps):
    rows, admissible, best, (g0_f0, g_reps_f0, gap) = evaluate(prism, reps)
    out = [f"f0: leak=0 PRISM={g0_f0:.0f}  REPS+NSCC={g_reps_f0:.0f}  gap={gap:.0f} Gbps "
           f"(recover >=1/3 => f0 >= {g0_f0 + gap/3:.0f})"]
    for r in rows:
        out.append(f"  leak={r['leak']:<4}: f0={r['f0']:.0f} (recovery {r['recovery']:.0%})  "
                   f"f8={r['f8']:.0f}  f12={r['f12']:.0f}  do-no-harm="
                   + ("OK" if r["ok"] else "VIOLATED " + ";".join(r["notes"])))
    if best:
        out.append(f"VERDICT: POSITIVE -- leak={best['leak']} recovers {best['recovery']:.0%} of the "
                   f"f0 gap with f8/f12 do-no-harm.")
    else:
        out.append("VERDICT: NEGATIVE -- no leak both recovers >=1/3 of f0 AND keeps f8/f12 "
                   "do-no-harm. Keep _prism_hold_leak=0 (O(1) PRISM unchanged).")
    return "\n".join(out)

def render(prism, reps, figs_dir):
    import matplotlib.pyplot as plt
    plot_style.apply_style(13)
    fig, ax = plt.subplots(1, 1, figsize=(6.4, 4.0))
    leaks = [lk for _c, lk in LEAKS]
    colors = {0: "tab:gray", 2: "tab:purple", 4: "tab:blue", 8: "tab:green", 12: "tab:red"}
    for f in FAILEDS:
        ys = [prism.get(c, {}).get(f, (float("nan"), 0))[0] for c, _lk in LEAKS]
        ax.plot(leaks, ys, marker="o", lw=2.0, color=colors[f], label=f"PRISM failed={f}")
        if f in reps:
            ax.axhline(reps[f][0], color=colors[f], ls="--", lw=1.0, alpha=0.7)
    ax.set_xlabel("HOLD-leak  (-prism_hold_leak)")
    ax.set_ylabel("Goodput (Gbps)")
    ax.set_title("HOLD-leak sweep (dashed = REPS+NSCC reference)", fontsize=11)
    ax.grid(alpha=0.3); ax.legend(fontsize=8, ncol=2)
    plt.tight_layout()
    plot_style.save(fig, "figHL_holdleak", figs_dir)
    plt.close(fig)

def selftest():
    # synthetic: leak=0 f0=900 reps f0=1000 (gap 100, need f0>=933 for >=1/3).
    # leak=0.5 recovers f0 to 960 (>=933) and keeps f8/f12 flat -> admissible & positive.
    # leak=1.0 recovers f0 fully but craters f8 -> do-no-harm VIOLATED.
    prism = {
        0:   {0: (900, 5), 8: (500, 5), 12: (430, 5)},
        50:  {0: (960, 5), 8: (498, 5), 12: (431, 5)},
        100: {0: (1000, 5), 8: (300, 5), 12: (250, 5)},
    }
    reps = {0: (1000, 5), 8: (505, 5), 12: (435, 5)}
    # pad missing leak codes so evaluate() iterates cleanly
    for c, _lk in LEAKS:
        prism.setdefault(c, {0: (900, 5), 8: (500, 5), 12: (430, 5)})
    rows, admissible, best, _ = evaluate(prism, reps)
    by = {r["leak"]: r for r in rows}
    assert by[0.5]["ok"] and by[0.5]["recovery"] >= 1.0 / 3.0, by[0.5]
    assert not by[1.0]["ok"], by[1.0]            # f8 300 < 505-tol -> violated
    assert best is not None and best["leak"] == 0.5, best
    print("ok holdleak_analyze selftest")

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        DATA = os.path.join(HERE, "data"); FIGS = os.path.join(HERE, "figs")
        os.makedirs(FIGS, exist_ok=True)
        prism, reps = analyze(DATA)
        print(verdict(prism, reps))
        render(prism, reps, FIGS)
        print(f"[holdleak] wrote {FIGS}/figHL_holdleak.{{png,pdf}}")
```

- [ ] **Step 2: Create `repro.sh`**

```bash
#!/bin/bash
# expA_holdleak: do-no-harm controlled experiment for the HOLD-leak prototype (flag-gated, default
# OFF). Sweeps -prism_hold_leak x failed x seed (PRISM) + REPS+NSCC reference, delay-driven, 2MB
# many2many (same as expA_delaydriven). Reports whether a leak recovers f0 without eroding f8/f12.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../common" && pwd)"
DC="$(cd "$HERE/../.." && pwd)"
REL="prism_eval/expA_holdleak"
cd "$DC"
[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first"; exit 1; }
mkdir -p "$REL/data"
SEEDS="13 14 15 16 17"; FAILEDS="0 2 4 8 12"
LEAKS="0 0.1 0.25 0.5 0.75 1.0"
declare -A CODE=( [0]=0 [0.1]=10 [0.25]=25 [0.5]=50 [0.75]=75 [1.0]=100 )
DD="-disable_trim"; ENDV="${EXP_END:-8}"; TOPO=fat_tree_128_1os.topo

echo "== selftest =="
python3 "$HERE/holdleak_analyze.py" --selftest
( cd "$COMMON/tests" && python3 test_metrics.py >/dev/null && echo "ok common metrics selftest" )

echo "== workload (many2many 64->16 pod0, 2MB) =="
python3 "$COMMON/gen/many2many.py" "$REL/data/m2m.cm" 64 16 pairs 2000000 128 16
CM="$REL/data/m2m.cm"; OUT="$REL/data"

echo "== REPS+NSCC reference: failed{0,2,4,8,12} x 5 seeds =="
for f in $FAILEDS; do for s in $SEEDS; do
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" nscc reps "$f" "$TOPO" "$s" "$CM" flow,sink "hl_reps_f${f}_s${s}" "$OUT"
done; done

echo "== PRISM HOLD-leak sweep: leak{0,0.1,0.25,0.5,0.75,1.0} x failed x 5 seeds =="
for L in $LEAKS; do C="${CODE[$L]}"; for f in $FAILEDS; do for s in $SEEDS; do
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD -prism_hold_leak $L" \
    bash "$COMMON/run_lib.sh" prism reps "$f" "$TOPO" "$s" "$CM" flow,sink "hl_prism_l${C}_f${f}_s${s}" "$OUT"
done; done; done

echo "== analyze (verdict + figHL) =="
python3 "$HERE/holdleak_analyze.py"
echo "== done: figs/figHL_holdleak.{png,pdf} =="
```

- [ ] **Step 3: Make repro.sh executable**

Run: `chmod +x htsim/sim/datacenter/prism_eval/expA_holdleak/repro.sh`

- [ ] **Step 4: Analysis selftest passes**

Run: `cd htsim/sim/datacenter/prism_eval/expA_holdleak && python3 holdleak_analyze.py --selftest`
Expected: `ok holdleak_analyze selftest`.

- [ ] **Step 5: Wiring smoke (one leak, one failed, one seed)**

Run from DC:
```bash
cd /home/leo/htsim/htsim/sim/datacenter
python3 prism_eval/common/gen/many2many.py /tmp/hl_smoke.cm 64 16 pairs 2000000 128 16
PATHS=8 END_MS=8 EXTRA_ARGS="-disable_trim -prism_hold_leak 0.5" bash prism_eval/common/run_lib.sh \
  prism reps 0 fat_tree_128_1os.topo 13 /tmp/hl_smoke.cm flow,sink hl_prism_l50_f0_s13 /tmp/hl_smoke_out
wc -l /tmp/hl_smoke_out/hl_prism_l50_f0_s13.flow.txt
rm -rf /tmp/hl_smoke_out /tmp/hl_smoke.cm
```
Expected: non-empty flow file, no run_lib error. If empty/errors, STOP and report BLOCKED.

- [ ] **Step 6: Do NOT commit.**

---

## Task 3: Run the HOLD-leak sweep, verify, render, extract verdict

**Files:** Produces `.../expA_holdleak/data/*` (gitignored) + `.../figs/figHL_holdleak.{png,pdf}`.

- [ ] **Step 1: Run the full sweep**

Run: `cd htsim/sim/datacenter/prism_eval/expA_holdleak && bash repro.sh 2>&1 | tee /tmp/hl_repro.log`
(Long: 6 leaks × 5 failed × 5 seeds PRISM + 5×5 REPS = 175 sims; may run in background.)
Expected: ends with `== done: figs/figHL_holdleak.{png,pdf} ==`.

- [ ] **Step 2: Completion-ratio sanity**

Run: `grep -c FLOW_EVENT htsim/sim/datacenter/prism_eval/expA_holdleak/data/hl_prism_l50_f12_s13.flow.txt`
Then spot-check a few flow files have FINISH events (each completed flow → 2 FLOW_EVENT lines, 64 flows → ~128 lines). The 2MB/END=8 setting matches expA (cr≈1.0); if any cell looks far short, re-run with `EXP_END=12` and record it.

- [ ] **Step 3: Capture the verdict + table**

Run: `python3 htsim/sim/datacenter/prism_eval/expA_holdleak/holdleak_analyze.py` (re-runs the analysis on the data; also in `/tmp/hl_repro.log`).
Record VERBATIM the per-leak lines (f0 recovery %, f8, f12, do-no-harm OK/VIOLATED) and the final `VERDICT:` line. **Do not edit numbers.**

- [ ] **Step 4: Confirm the figure exists**

Run: `ls -la htsim/sim/datacenter/prism_eval/expA_holdleak/figs/`
Expected: `figHL_holdleak.png`, `figHL_holdleak.pdf`.

- [ ] **Step 5: Do NOT commit.**

---

## Task 4: `expA_holdleak/README.md` (honest verdict from actual numbers)

**Files:** Create `htsim/sim/datacenter/prism_eval/expA_holdleak/README.md`.

- [ ] **Step 1: Write the README from the Task-3 numbers**

Required sections (no placeholders; fill from `/tmp/hl_repro.log`):

1. **What this tests** — the HOLD-leak prototype (flag-gated, default OFF, O(1)); the question (can a
   leak recover part of the f0 cost without eroding the f8/f12 win?); why it is a blunt tradeoff, and
   that (a)/(b) were ruled out first (cite `../probe_avgdisc/`). Note default `_prism_hold_leak=0` ==
   today's PRISM, verified byte-identical.
2. **Setup** — flag `-prism_hold_leak`; sweep `leak ∈ {0,0.1,0.25,0.5,0.75,1.0}` × `failed ∈
   {0,2,4,8,12}` × seeds {13–17}; PRISM swept + REPS+NSCC reference; delay-driven 2 MB many2many;
   `EXP_END` used. One-line repro.
3. **Pre-registered criteria** — admissible: f8 AND f12 within max(3%,1 SD) of leak=0; positive: some
   admissible leak recovers ≥ 1/3 of the f0 (leak=0→REPS) gap.
4. **Results** — the leak×{f0,f8,f12} goodput table (the analyzer's lines), with f0-recovery% and the
   f8/f12 do-no-harm verdict per leak; reference `figs/figHL_holdleak`.
5. **Verdict** — POSITIVE (name the leak, the recovery, the f8/f12 cost) or NEGATIVE (state plainly
   that no leak satisfies both; keep `leak=0`, PRISM stays O(1)). Either way, state it is a tradeoff,
   not a free fix.
6. **Disposition** — if NEGATIVE: the flag stays default-0 (kept as an off-by-default knob or to be
   reverted per the user); the symmetric cost stands as the characterized O(1) cost. Cross-link
   `../expA_f0_diagnosis/`, `../probe_avgdisc/`, `../NARRATIVE.md`, `../TARGET_REGIME.md`.

- [ ] **Step 2: No placeholders**

Run: `grep -nE 'TBD|TODO|FIXME|XXX' htsim/sim/datacenter/prism_eval/expA_holdleak/README.md`
Expected: no output.

- [ ] **Step 3: Cross-links resolve**

Run: `ls htsim/sim/datacenter/prism_eval/expA_f0_diagnosis/README.md htsim/sim/datacenter/prism_eval/probe_avgdisc/README.md htsim/sim/datacenter/prism_eval/NARRATIVE.md htsim/sim/datacenter/prism_eval/TARGET_REGIME.md`
Expected: all exist.

- [ ] **Step 4: Do NOT commit.**

---

## Task 5: Fold the result into memory; present milestone (no commit)

**Files:** Modify `/home/leo/.claude/projects/-home-leo-htsim/memory/prism-eval-roadmap.md`.

- [ ] **Step 1: Update the roadmap memory**

Append a HOLD-leak block: the prototype built (flag-gated, default 0, O(1), byte-identical verified),
the probe that preceded it (avg-discriminator refuted), the sweep result (POSITIVE leak + numbers, or
NEGATIVE), and the disposition (kept off-by-default / reverted). Note the commit chain entry is
pending user approval.

- [ ] **Step 2: Final verification**

Run:
```bash
cd htsim/sim/datacenter/prism_eval
python3 expA_holdleak/holdleak_analyze.py --selftest
python3 common/perf_figs.py
ls expA_holdleak/figs/
git -C /home/leo/htsim status --porcelain | grep -E 'uec\.(cpp|h)$|main_uec' && echo "controller change present (expected)"
```
Expected: selftests pass; figure present; controller files show as modified.

- [ ] **Step 3: Present the milestone for user approval (DO NOT commit)**

Summarize: the controller change (flag, default-0 byte-identical, O(1)), the verdict (positive/
negative with numbers), the proposed disposition, and the full change set. If NEGATIVE, explicitly
ask whether to keep the flag off-by-default or `git checkout`-revert the 4 controller files (as with
the persistence prototype). The milestone commit (with `git add -f` for figures) happens only on
explicit approval.

---

## Self-review notes (author)

- **Spec coverage:** §2 mechanism → Task 1 (Steps 3–4 = the two branches; Step 1–2 = scalar; 5–6 =
  flag parse in both mains; 7 = rebuild; 8 = byte-identical+wired verification). §3.1 controller →
  Task 1. §3.2 group → Tasks 2–4. §4 sweep+criteria → repro.sh (Task 2) + holdleak_analyze
  evaluate()/verdict() (Task 2) + Task 3. §5 verification → Task 1 Step 8 (byte-identical, monotonic
  via leak0.5≠leak0) + Task 3. §6/§7/§8 → conventions + Task 4/5.
- **Placeholder scan:** none; the only runtime-determined values are the sweep numbers (filled in
  Task 3/4 from the log) and a possible `EXP_END` bump (Task 3 Step 2, with a concrete trigger).
- **Type/name consistency:** filename token `hl_prism_l{code}_f{f}_s{s}` (code = round(leak*100))
  matches between repro.sh's `CODE` map and holdleak_analyze's `LEAKS` codes; `hl_reps_f{f}_s{s}`
  consistent; flag name `-prism_hold_leak` / member `_prism_hold_leak` consistent across uec.h,
  uec.cpp, both mains, and repro.sh; `evaluate()`/`verdict()`/`render()` names consistent in the
  script and its `__main__`.
