# PRISM spread-persistence gate (Scheme A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in, default-off O(1) spread-persistence gate (smooth only the scalar `C_spray`, keep `C_cc` instantaneous; HOLD needs `c_spray ≥ δ·S_slow`), then validate on f0+f8.

**Architecture:** Two static knobs (`δ=_prism_spread_persist`, `β=_prism_spread_persist_beta`) plumbed like `-prism_kappa`, plus one per-flow scalar (`_prism_cspray_slow`, a slow EWMA of `C_spray`). The gate is applied at the epoch-close call site via an effective `t_spray` — `decide_region` (prism_decompose.h) is UNCHANGED. Default (δ=0) is byte-identical to today's PRISM.

**Tech Stack:** C++ (htsim/UEC simulator), bash repro scripts, Python aggregation (`common/perf_figs.py`, `common/metrics.py`).

## Global Constraints

- **Default-off byte-identical.** δ=0 ⇒ no persistence check, no `S_slow` update, `decide_region` called with today's `t_spray` ⇒ identical region on every input. Copied verbatim from spec §3.
- **O(1) preserved.** Two static scalars + ONE per-flow scalar (`_prism_cspray_slow`). Zero per-path state. `C_cc` stays instantaneous (`_prism_epoch_min`) — never smoothed (smoothing the floor was the prior backfire).
- **`decide_region` (prism_decompose.h) is UNCHANGED.** Gate applied at the call site via effective `t_spray`.
- **Binary/flag relationship (verbatim):** `htsim_uec` builds from `datacenter/main_uec.cpp` (`datacenter/CMakeLists.txt:48`); `-prism_kappa` is parsed in BOTH `main_uec.cpp` and `main_uec_sf.cpp`. New flags go in both. **Match each file's local style:** `main_uec.cpp` uses `!strcmp(argv[i],"…")` + `argv[i+1]` (no spaces); `main_uec_sf.cpp` uses `!strcmp(argv[i], "…")` + `argv[i + 1]` (spaces).
- **Rollback-able.** Runtime A/B = pass/omit `-prism_spread_persist`; permanent revert = the localized diff, `git revert`. No FF to `main`, no default change, until the user reviews results.
- **Spray unchanged.** Only the CC HOLD-entry test changes. REPS, loss path, kappa, T_spray semantics, epoch CSV schema untouched.
- **No git commit unless the user explicitly asks (per-task local commits ARE authorized for this subagent-driven run); never push** (origin = spcl/HTSIM public upstream).
- **Working dir for build/test commands:** `/home/leo/htsim/htsim/sim` unless stated otherwise.

---

### Task 1: spread-persistence gate logic + flag plumbing + build + smoke

**Files:**
- Modify: `htsim/sim/uec.h:379` (2 static decls) and `htsim/sim/uec.h:489` (1 per-flow member)
- Modify: `htsim/sim/uec.cpp` (add `#include <limits>`; 2 static defs after line 101; epoch-close logic at lines 1553–1555)
- Modify: `htsim/sim/datacenter/main_uec.cpp:199` (2 parse blocks, no-space style)
- Modify: `htsim/sim/datacenter/main_uec_sf.cpp` (2 parse blocks, space style, after the `-prism_kappa` block)

**Interfaces:**
- Consumes: `prism::decide_region(c_cc, c_spray, t_cc, t_spray)` (existing 4-arg pure function — unchanged).
- Produces: static `UecSrc::_prism_spread_persist` (δ, default 0.0), `UecSrc::_prism_spread_persist_beta` (β, default 0.03125), per-flow `_prism_cspray_slow` (slow EWMA of `C_spray`). CLI flags `-prism_spread_persist <δ>` and `-prism_spread_persist_beta <β>`. Task 2's sweep sets them via `EXTRA_ARGS`.

- [ ] **Step 1: Declare the two static knobs in `uec.h`**

After line 379 (`static double _prism_kappa; ...`), insert:
```cpp
    static double          _prism_spread_persist;       // -prism_spread_persist; HOLD needs c_spray>=δ*S_slow; 0 = off
    static double          _prism_spread_persist_beta;  // -prism_spread_persist_beta; slow-EWMA weight β for S_slow; default 1/32
```

- [ ] **Step 2: Declare the per-flow scalar in `uec.h`**

After line 489 (`simtime_picosec _prism_cspray = 0; ...`), insert:
```cpp
    simtime_picosec _prism_cspray_slow   = 0;  // Scheme A: slow EWMA of scalar C_spray (0 = uninit); C_cc stays instantaneous
```

- [ ] **Step 3: Add the include + static definitions in `uec.cpp`**

Near the top of `uec.cpp`, with the other `#include` lines, add (if not already present):
```cpp
#include <limits>
```
After line 101 (`double UecSrc::_prism_kappa = 1.0;`), insert:
```cpp
double UecSrc::_prism_spread_persist = 0.0;        // 0 = disabled: no persistence gate (today's PRISM)
double UecSrc::_prism_spread_persist_beta = 0.03125;  // 1/32: slow baseline, ~32-epoch memory
```

- [ ] **Step 4: Insert the persistence logic at the epoch-close**

In `uec.cpp`, the current epoch-close block reads:
```cpp
        simtime_picosec c_cc = _prism_epoch_min;
        simtime_picosec c_spray = _prism_epoch_max - _prism_epoch_min;
        int region = prism::decide_region(c_cc, c_spray, _target_Qdelay, t_spray);
```
Replace the third line so the block becomes:
```cpp
        simtime_picosec c_cc = _prism_epoch_min;
        simtime_picosec c_spray = _prism_epoch_max - _prism_epoch_min;
        // PRISM Scheme A (spread-persistence gate, default OFF): release HOLD on a draining transient
        // -- a spread far below its own slow baseline. C_cc stays instantaneous (do NOT smooth the floor).
        // compare-then-update: decide on the prior baseline, then fold in this epoch's spread.
        simtime_picosec t_spray_eff = t_spray;
        if (_prism_spread_persist > 0.0) {
            bool persistent = (_prism_cspray_slow == 0) ||
                ((double)c_spray >= _prism_spread_persist * (double)_prism_cspray_slow);
            if (!persistent)
                t_spray_eff = std::numeric_limits<simtime_picosec>::max();
            _prism_cspray_slow = (_prism_cspray_slow == 0) ? c_spray
                : (simtime_picosec)(_prism_spread_persist_beta * (double)c_spray
                    + (1.0 - _prism_spread_persist_beta) * (double)_prism_cspray_slow);
        }
        int region = prism::decide_region(c_cc, c_spray, _target_Qdelay, t_spray_eff);
```
(Note: `_prism_cspray_slow == 0` doubles as the "first epoch / no baseline" sentinel. A genuine `c_spray == 0` epoch keeps it 0, which is harmless — a 0 spread is below `t_spray` so it never makes `spread_high` true regardless.)

- [ ] **Step 5: Add the CLI parse blocks in `main_uec.cpp` (no-space style)**

After the `-prism_kappa` block (ends at line ~200 with `i++;`), insert two sibling `else if` blocks matching this file's local style (`argv[i],"…"` and `argv[i+1]`):
```cpp
        } else if (!strcmp(argv[i],"-prism_spread_persist")) {
            UecSrc::_prism_spread_persist = atof(argv[i+1]);
            cout << "prism_spread_persist " << UecSrc::_prism_spread_persist << endl;
            i++;
        } else if (!strcmp(argv[i],"-prism_spread_persist_beta")) {
            UecSrc::_prism_spread_persist_beta = atof(argv[i+1]);
            cout << "prism_spread_persist_beta " << UecSrc::_prism_spread_persist_beta << endl;
            i++;
```

- [ ] **Step 6: Add the CLI parse blocks in `main_uec_sf.cpp` (space style)**

After the `-prism_kappa` block in `main_uec_sf.cpp`, insert two sibling `else if` blocks matching THIS file's local style (`argv[i], "…"` and `argv[i + 1]`):
```cpp
        } else if (!strcmp(argv[i], "-prism_spread_persist")) {
            UecSrc::_prism_spread_persist = atof(argv[i + 1]);
            cout << "prism_spread_persist " << UecSrc::_prism_spread_persist << endl;
            i++;
        } else if (!strcmp(argv[i], "-prism_spread_persist_beta")) {
            UecSrc::_prism_spread_persist_beta = atof(argv[i + 1]);
            cout << "prism_spread_persist_beta " << UecSrc::_prism_spread_persist_beta << endl;
            i++;
```

- [ ] **Step 7: Build htsim_uec**

Run:
```bash
cd /home/leo/htsim/htsim/sim/build && make htsim_uec -j 2>&1 | tail -5
```
Expected: links successfully, no errors; `datacenter/htsim_uec` rebuilt.

- [ ] **Step 8: Smoke-test (flags wired + echoed + δ>0 runs; δ=0/absent path clean)**

From `/home/leo/htsim/htsim/sim/datacenter`:
```bash
OUT=/tmp/persist_smoke; mkdir -p "$OUT"
python3 prism_eval/common/gen/many2many.py "$OUT/m2m.cm" 64 16 pairs 2000000 128 16
# (a) gate ON: both flags echoed, run completes
PATHS=8 END_MS=8 EXTRA_ARGS="-disable_trim -prism_spread_persist 0.5 -prism_spread_persist_beta 0.0625" \
  bash prism_eval/common/run_lib.sh prism reps 8 fat_tree_128_1os.topo 13 "$OUT/m2m.cm" flow persist_on "$OUT"
grep -c "prism_spread_persist 0.5" "$OUT/persist_on.stdout"
grep -c "prism_spread_persist_beta 0.0625" "$OUT/persist_on.stdout"
wc -l < "$OUT/persist_on.flow.txt"
# (b) gate OFF (no flags): neither echoed
PATHS=8 END_MS=8 EXTRA_ARGS="-disable_trim" \
  bash prism_eval/common/run_lib.sh prism reps 8 fat_tree_128_1os.topo 13 "$OUT/m2m.cm" flow persist_off "$OUT"
grep -c "prism_spread_persist" "$OUT/persist_off.stdout" || true
```
Expected: (a) prints `1`, `1`, and a non-zero line count (flow.txt non-empty); (b) prints `0`.

- [ ] **Step 9: Commit**

```bash
cd /home/leo/htsim
git add htsim/sim/uec.h htsim/sim/uec.cpp htsim/sim/datacenter/main_uec.cpp htsim/sim/datacenter/main_uec_sf.cpp
git commit -m "$(printf 'prism: Scheme A spread-persistence gate (default-off, O(1))\n\nSlow per-flow EWMA of scalar C_spray (_prism_cspray_slow); HOLD-entry\nrequires c_spray>=delta*S_slow via effective t_spray at the call site;\nC_cc stays instantaneous; decide_region unchanged. Flags\n-prism_spread_persist (delta, 0=off) + -prism_spread_persist_beta\n(default 1/32) in both mains. O(1): 2 statics + 1 per-flow scalar.\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

### Task 2: validation sweep (f0+f8 × δ × β) + summary + acceptance

**Files:**
- Create: `htsim/sim/datacenter/prism_eval/expA_f0_diagnosis/persist_sweep.sh`
- Create: `htsim/sim/datacenter/prism_eval/expA_f0_diagnosis/persist_summary.py`

**Interfaces:**
- Consumes: the rebuilt `htsim_uec` (Task 1) understanding `-prism_spread_persist`/`-prism_spread_persist_beta`; `common/run_lib.sh`; `common/gen/many2many.py`; `common/perf_figs.py::aggregate`.
- Produces: `data/persist_d{δ}_b{β}_f{failed}_s{seed}.flow.txt` (gitignored) and a printed acceptance table.

**SCOPE NOTE for the implementer:** write both scripts at FULL scope, prove them on a small smoke, and commit — **do NOT run the full 50-run sweep** (the controller runs that long experiment and reports progress). The committed `persist_sweep.sh` keeps full scope.

- [ ] **Step 1: Write the sweep script**

Create `htsim/sim/datacenter/prism_eval/expA_f0_diagnosis/persist_sweep.sh`:
```bash
#!/bin/bash
# Scheme A (spread-persistence) validation: PRISM (reps spray) on the byte-identical expA_delaydriven
# workload (many2many 64->16 pod0, 2MB), delay-driven, failed{0,8}. Configs: delta=0 baseline (today's
# PRISM) + delta{0.5,1.0} x beta{1/16,1/64}. Rides run_lib.sh via EXTRA_ARGS; run_lib unchanged.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../common" && pwd)"
DC="$(cd "$HERE/../.." && pwd)"
cd "$DC"
[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first"; exit 1; }
REL="prism_eval/expA_f0_diagnosis"; OUT="$REL/data"; mkdir -p "$OUT"
SEEDS="13 14 15 16 17"; FAILEDS="0 8"
DELTAS="0.5 1.0"; BETAS="0.0625 0.015625"   # beta 1/16, 1/64 (bracket the 1/32 default)
TOPO=fat_tree_128_1os.topo; DD="-disable_trim"; ENDV="${EXP_END:-8}"

echo "== selftests gate the run =="
( cd "$DC/.." && g++ -I. datacenter/prism_eval/common/tests/test_prism_decompose.cpp -o /tmp/test_prism_dec && /tmp/test_prism_dec )
( cd "$COMMON/tests" && python3 test_metrics.py >/dev/null && echo "ok common metrics selftest" )

echo "== generate byte-identical workload (many2many 64->16 pod0, 2MB) =="
python3 "$COMMON/gen/many2many.py" "$OUT/m2m.cm" 64 16 pairs 2000000 128 16
CM="$OUT/m2m.cm"

echo "== delta=0 baseline (today's PRISM) x failed{0,8} x 5 seeds =="
for f in $FAILEDS; do for s in $SEEDS; do
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD -prism_spread_persist 0" \
    bash "$COMMON/run_lib.sh" prism reps "$f" "$TOPO" "$s" "$CM" flow "persist_d0_b0_f${f}_s${s}" "$OUT"
done; done

echo "== delta{0.5,1.0} x beta{1/16,1/64} x failed{0,8} x 5 seeds =="
for d in $DELTAS; do for b in $BETAS; do for f in $FAILEDS; do for s in $SEEDS; do
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD -prism_spread_persist $d -prism_spread_persist_beta $b" \
    bash "$COMMON/run_lib.sh" prism reps "$f" "$TOPO" "$s" "$CM" flow "persist_d${d}_b${b}_f${f}_s${s}" "$OUT"
done; done; done; done

echo "== summary =="
python3 "$HERE/persist_summary.py"
```
Then:
```bash
chmod +x /home/leo/htsim/htsim/sim/datacenter/prism_eval/expA_f0_diagnosis/persist_sweep.sh
```

- [ ] **Step 2: Write the summary aggregator**

Create `htsim/sim/datacenter/prism_eval/expA_f0_diagnosis/persist_summary.py`:
```python
#!/usr/bin/env python3
"""Scheme A acceptance table: PRISM goodput/avg-FCT at failed{0,8} for the delta=0 baseline and
each (delta,beta), vs that baseline and the REPS+NSCC reference (reused from expA_delaydriven/data)."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import perf_figs  # noqa: E402

DATA = os.path.join(HERE, "data")
EXPA = os.path.join(HERE, "..", "expA_delaydriven", "data")
SEEDS = [13, 14, 15, 16, 17]
FAILED = [0, 8]
CONFIGS = [("d0_b0", "delta=0 (base)")] + [
    (f"d{d}_b{b}", f"delta={d} beta={b}")
    for d in ("0.5", "1.0") for b in ("0.0625", "0.015625")]

reps = perf_figs.aggregate(EXPA, "expA", "reps", FAILED, SEEDS)
prism = {lab: perf_figs.aggregate(DATA, "persist", lab, FAILED, SEEDS) for lab, _ in CONFIGS}

def g(d, f): return d[f]["goodput"][0] if f in d else float("nan")
def a(d, f): return d[f]["avg_fct"][0] if f in d else float("nan")

print(f"\n{'cell':>5} | {'config':>20} | {'goodput Gbps':>13} | {'avg-FCT us':>11} | {'Δgoodput vs base':>16}")
print("-" * 82)
for f in FAILED:
    base_g = g(prism["d0_b0"], f)
    print(f"{('f'+str(f)):>5} | {'REPS+NSCC':>20} | {g(reps,f):>13.1f} | {a(reps,f):>11.0f} |")
    for lab, name in CONFIGS:
        dg = g(prism[lab], f) - base_g
        print(f"{('f'+str(f)):>5} | {name:>20} | {g(prism[lab],f):>13.1f} | {a(prism[lab],f):>11.0f} | {dg:>+16.1f}")
    print("-" * 82)
print("\nAcceptance: some (delta,beta) raises f0 goodput toward REPS (Δ>0, FCT down) AND keeps f8 within")
print("seed-noise of delta=0. If BOTH betas show no f0 effect -> null robust to beta. Else widen beta.")
```

- [ ] **Step 3: Smoke-validate the scripts (2 cells, ~3–5 min — NOT the full sweep)**

From `/home/leo/htsim/htsim/sim/datacenter`:
```bash
OUT=prism_eval/expA_f0_diagnosis/data
python3 prism_eval/common/gen/many2many.py "$OUT/m2m.cm" 64 16 pairs 2000000 128 16
PATHS=8 END_MS=8 EXTRA_ARGS="-disable_trim -prism_spread_persist 0" \
  bash prism_eval/common/run_lib.sh prism reps 8 fat_tree_128_1os.topo 13 "$OUT/m2m.cm" flow persist_d0_b0_f8_s13 "$OUT"
PATHS=8 END_MS=8 EXTRA_ARGS="-disable_trim -prism_spread_persist 1.0 -prism_spread_persist_beta 0.0625" \
  bash prism_eval/common/run_lib.sh prism reps 8 fat_tree_128_1os.topo 13 "$OUT/m2m.cm" flow persist_d1.0_b0.0625_f8_s13 "$OUT"
python3 prism_eval/expA_f0_diagnosis/persist_summary.py
```
Expected: both flow.txt produced non-empty; `persist_summary.py` runs without error and prints the table — f8 shows numbers for `delta=0 (base)` and `delta=1.0 beta=0.0625` (single seed), other cells `nan` (expected for the smoke). Sanity: both f8 goodputs are plausible (hundreds of Gbps), not zero/nan. (This confirms the tag↔aggregate label algebra `persist_d{δ}_b{β}_f{f}_s{s}` resolves.)

- [ ] **Step 4: Commit the scripts (not the data)**

```bash
cd /home/leo/htsim
git add htsim/sim/datacenter/prism_eval/expA_f0_diagnosis/persist_sweep.sh \
        htsim/sim/datacenter/prism_eval/expA_f0_diagnosis/persist_summary.py
git commit -m "$(printf 'prism: Scheme A persistence validation sweep (f0+f8 x delta x beta) + summary\n\nRides run_lib.sh via EXTRA_ARGS; raw data gitignored. delta=0 = regression\nreplica. 50 runs at full scope; controller runs the sweep. Acceptance:\nf0 cost down AND f8 win preserved at some (delta,beta).\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Post-implementation (NOT tasks — controller-run + gated on user review)

- Controller runs `persist_sweep.sh` (50 runs, ~25–90 min, progress ~every 10 min), then reports the acceptance table.
- Confirm: δ=0 baseline reproduces current PRISM (f0 ≈ 869/945, f8 ≈ 504/1518); whether any (δ,β) recovers f0 while preserving f8; whether both β agree (null robust to β).
- **Do NOT** change any default or FF to `main`. Report result to the user for the disposition decision (revert vs keep; document the result + correct the f0-diagnosis "O(paths) regardless" claim per spec §7).
