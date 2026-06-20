# PRISM ρ-gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in, default-off `-prism_spread_ratio` knob that tightens PRISM's HOLD-entry test to `c_spray ≥ max(T_spray, ρ·c_cc)`, then validate on the f0 (cost) and f8 (win) cells.

**Architecture:** A single defaulted parameter (`spread_ratio = 0.0`) on the pure, unit-tested `decide_region` in `prism_decompose.h`; a static scalar `UecSrc::_prism_spread_ratio` plumbed from a CLI flag exactly like `-prism_kappa`; a standalone sweep script under `expA_f0_diagnosis/` that rides the existing `run_lib.sh` via `EXTRA_ARGS`. Default (ρ=0) is byte-identical to today's PRISM.

**Tech Stack:** C++ (htsim/UEC simulator), bash repro scripts, Python aggregation (`common/perf_figs.py`, `common/metrics.py`).

## Global Constraints

- **Default-off byte-identical.** `_prism_spread_ratio = 0.0` (default) ⇒ `decide_region` returns the same region as today on every input. Copied verbatim from spec §3.
- **O(1) preserved.** Add exactly **one static scalar** + a multiply-compare in the existing per-epoch close. **Zero** new per-flow/per-path/per-packet state.
- **Rollback-able.** Runtime A/B = pass / omit `-prism_spread_ratio`; permanent revert = the ~7-line diff (+tests). **No FF to `main`, no default change, until the user reviews results.**
- **Spray unchanged.** Only the CC HOLD-entry test changes. REPS, loss path, kappa, T_spray semantics, epoch CSV schema untouched.
- **Communication in Chinese; no git commit unless the user explicitly asks (per-task local commits ARE authorized for this subagent-driven run); never push** (origin = spcl/HTSIM public upstream).
- **Working dir for all build/test commands:** `/home/leo/htsim/htsim/sim` unless stated otherwise.

---

### Task 1: ρ-gate in the pure decision function + unit tests

**Files:**
- Modify: `htsim/sim/prism_decompose.h:15-22` (extend `decide_region`)
- Test: `htsim/sim/datacenter/prism_eval/common/tests/test_prism_decompose.cpp` (add ρ-variant assertions)

**Interfaces:**
- Consumes: nothing (leaf change).
- Produces: `prism::decide_region(uint64_t c_cc, uint64_t c_spray, uint64_t t_cc, uint64_t t_spray, double spread_ratio = 0.0) -> prism::Region`. The 5th parameter defaults to `0.0`; `0.0` ⇒ identical behavior to the current 4-arg rule. Task 2 passes `_prism_spread_ratio` as the 5th argument.

- [ ] **Step 1: Write the failing test**

In `test_prism_decompose.cpp`, immediately after the existing `printf("ok decide_region\n");` line, insert:

```cpp
    // ρ-gate (combined-AND): spread_high = (c_spray >= t_spray) AND (c_spray >= rho*c_cc).
    // T_cc = T_spray = 6 (same arbitrary units as above). rho = 5.
    // Cost-type epoch: floor low (2<6), spread crosses absolute bar (7>=6) but NOT 5x floor (7<10) -> gate removes the HOLD.
    assert(decide_region(2, 7, 6, 6, 5.0) == INCREASE);  // rho-gate: spread does not dominate floor -> back to INCREASE
    assert(decide_region(2, 7, 6, 6)      == HOLD);       // 4-arg default (rho=0): unchanged -> still HOLD
    assert(decide_region(2, 7, 6, 6, 0.0) == HOLD);       // rho=0 explicit: byte-identical to today
    // Win-type epoch: spread massively dominates floor (20 >= 5*2=10) -> still HOLD.
    assert(decide_region(2, 20, 6, 6, 5.0) == HOLD);      // persistent large spread survives the gate
    // Clean-path edge: c_cc=0 -> rho*0=0, any spread>=t_spray stays HOLD (correct: a perfectly clean path exists).
    assert(decide_region(0, 20, 6, 6, 5.0) == HOLD);
    // Floor-high is unaffected by the gate: still DECREASE regardless of rho.
    assert(decide_region(9, 20, 6, 6, 5.0) == DECREASE);
    printf("ok decide_region rho-gate\n");
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `/home/leo/htsim/htsim/sim`):
```bash
g++ -I. datacenter/prism_eval/common/tests/test_prism_decompose.cpp -o /tmp/test_prism_dec && /tmp/test_prism_dec
```
Expected: **compile FAILS** with an error like `no matching function for call to 'decide_region(int, int, int, int, double)'` / `too many arguments` — the current `decide_region` takes only 4 parameters.

- [ ] **Step 3: Extend `decide_region` (minimal implementation)**

In `prism_decompose.h`, replace the function (lines 15-22):
```cpp
inline Region decide_region(uint64_t c_cc, uint64_t c_spray,
                            uint64_t t_cc, uint64_t t_spray,
                            double spread_ratio = 0.0) {
    bool floor_high  = c_cc >= t_cc;
    bool spread_high = (c_spray >= t_spray) &&
                       (spread_ratio <= 0.0 || (double)c_spray >= spread_ratio * (double)c_cc);
    if (!floor_high && !spread_high) return INCREASE;  // floor safe, paths balanced
    if (!floor_high &&  spread_high) return HOLD;       // clean path exists; let REPS rebalance
    return DECREASE;                                    // floor high: even the best path is queued
}
```
(Keep the existing doc comment on lines 12-14; only the signature + `spread_high` line change.)

- [ ] **Step 4: Run the test to verify it passes**

Run (from `/home/leo/htsim/htsim/sim`):
```bash
g++ -I. datacenter/prism_eval/common/tests/test_prism_decompose.cpp -o /tmp/test_prism_dec && /tmp/test_prism_dec
```
Expected: prints `ok decide_region`, `ok decide_region rho-gate`, `ok md_factor`, `ok decide_loss`, `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
cd /home/leo/htsim
git add htsim/sim/prism_decompose.h htsim/sim/datacenter/prism_eval/common/tests/test_prism_decompose.cpp
git commit -m "$(printf 'prism: rho-gate in decide_region (combined-AND, default-off)\n\nspread_high = (c_spray>=t_spray) AND (spread_ratio<=0 || c_spray>=rho*c_cc).\nDefaulted param spread_ratio=0.0 keeps all existing callers/tests identical.\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

### Task 2: plumb the `-prism_spread_ratio` flag and pass it at the call site

**Files:**
- Modify: `htsim/sim/uec.h:379` (add static member declaration, after `_prism_kappa`)
- Modify: `htsim/sim/uec.cpp:101` (add static definition, after `_prism_kappa`)
- Modify: `htsim/sim/uec.cpp:1554` (pass `_prism_spread_ratio` as 5th arg to `decide_region`)
- Modify: `htsim/sim/datacenter/main_uec_sf.cpp:182-185` (add `-prism_spread_ratio` parse block, after `-prism_kappa`)

**Interfaces:**
- Consumes: `prism::decide_region(..., double spread_ratio)` from Task 1.
- Produces: `UecSrc::_prism_spread_ratio` (static `double`, default `0.0`), set by CLI flag `-prism_spread_ratio <float>`. Task 3's sweep passes it via `EXTRA_ARGS`.

- [ ] **Step 1: Declare the static member in `uec.h`**

After line 379 (`static double _prism_kappa; ...`), insert:
```cpp
    static double          _prism_spread_ratio;  // -prism_spread_ratio; HOLD needs c_spray>=ratio*c_cc; 0 = off (today's rule)
```

- [ ] **Step 2: Define + default the static in `uec.cpp`**

After line 101 (`double UecSrc::_prism_kappa = 1.0;`), insert:
```cpp
double UecSrc::_prism_spread_ratio = 0.0;   // 0 = disabled: HOLD uses absolute t_spray only (today's PRISM)
```

- [ ] **Step 3: Add the CLI parse block in `main_uec_sf.cpp`**

After the `-prism_kappa` block (the one ending `i++;` at line ~185), insert a sibling `else if`:
```cpp
        } else if (!strcmp(argv[i], "-prism_spread_ratio")) {
            UecSrc::_prism_spread_ratio = atof(argv[i + 1]);
            cout << "prism_spread_ratio " << UecSrc::_prism_spread_ratio << endl;
            i++;
```

- [ ] **Step 4: Pass the ratio at the decide_region call site in `uec.cpp`**

At line 1554, change:
```cpp
        int region = prism::decide_region(c_cc, c_spray, _target_Qdelay, t_spray);
```
to:
```cpp
        int region = prism::decide_region(c_cc, c_spray, _target_Qdelay, t_spray, _prism_spread_ratio);
```

- [ ] **Step 5: Build htsim_uec**

Run:
```bash
cd /home/leo/htsim/htsim/sim/build && make htsim_uec -j 2>&1 | tail -5
```
Expected: links successfully; `datacenter/htsim_uec` (symlinked from `htsim/sim/datacenter/htsim_uec`) is rebuilt with no errors.

- [ ] **Step 6: Smoke-test the flag is wired + echoed (tiny 2-connection probe)**

Run (from `/home/leo/htsim/htsim/sim/datacenter`):
```bash
printf 'Nodes 128\nConnections 2\n80->0 start 1000000 size 2000000\n81->1 start 2000000 size 2000000\n' > /tmp/_rg_probe.cm
PATHS=8 END_MS=12 EXTRA_ARGS="-disable_trim -prism_spread_ratio 5" \
  bash prism_eval/common/run_lib.sh prism reps 0 fat_tree_128_1os.topo 13 /tmp/_rg_probe.cm flow _rg_probe /tmp
grep -c "prism_spread_ratio 5" /tmp/_rg_probe.stdout
```
Expected: prints `1` (the flag was parsed and echoed). A run **without** the flag must NOT print that line:
```bash
PATHS=8 END_MS=12 EXTRA_ARGS="-disable_trim" \
  bash prism_eval/common/run_lib.sh prism reps 0 fat_tree_128_1os.topo 13 /tmp/_rg_probe.cm flow _rg_probe0 /tmp
grep -c "prism_spread_ratio" /tmp/_rg_probe0.stdout || true
```
Expected: prints `0`.

- [ ] **Step 7: Commit**

```bash
cd /home/leo/htsim
git add htsim/sim/uec.h htsim/sim/uec.cpp htsim/sim/datacenter/main_uec_sf.cpp
git commit -m "$(printf 'prism: -prism_spread_ratio flag plumbed to decide_region (default 0.0 = off)\n\nStatic scalar UecSrc::_prism_spread_ratio, parsed like -prism_kappa, passed\nas the 5th decide_region arg. O(1): one scalar, no per-flow state.\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

### Task 3: validation sweep (f0+f8 × ρ{0,3,5,8}) + summary table + acceptance

**Files:**
- Create: `htsim/sim/datacenter/prism_eval/expA_f0_diagnosis/ratio_gate_sweep.sh`
- Create: `htsim/sim/datacenter/prism_eval/expA_f0_diagnosis/ratio_gate_summary.py`

**Interfaces:**
- Consumes: the rebuilt `htsim_uec` (Task 2) understanding `-prism_spread_ratio`; `common/run_lib.sh`; `common/gen/many2many.py`; `common/perf_figs.py::aggregate`.
- Produces: `data/rgate_rho{ρ}_f{failed}_s{seed}.flow.txt` (gitignored) and a printed acceptance table.

- [ ] **Step 1: Write the sweep script**

Create `htsim/sim/datacenter/prism_eval/expA_f0_diagnosis/ratio_gate_sweep.sh`:
```bash
#!/bin/bash
# ρ-gate validation: PRISM (reps spray) on the byte-identical expA_delaydriven workload
# (many2many 64->16 pod0, 2MB), delay-driven, failed{0,8} x rho{0,3,5,8} x seed{13..17}.
# rho=0 = regression replica of today's PRISM. Rides run_lib.sh via EXTRA_ARGS; run_lib unchanged.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../common" && pwd)"
DC="$(cd "$HERE/../.." && pwd)"
REL="prism_eval/expA_f0_diagnosis"
cd "$DC"
[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first"; exit 1; }
mkdir -p "$REL/data"
SEEDS="13 14 15 16 17"; FAILEDS="0 8"; RHOS="0 3 5 8"
TOPO=fat_tree_128_1os.topo; DD="-disable_trim"; ENDV="${EXP_END:-8}"
OUT="$REL/data"

echo "== selftests gate the run (decide_region rho-gate + common metrics) =="
( cd "$DC/.." && g++ -I. datacenter/prism_eval/common/tests/test_prism_decompose.cpp -o /tmp/test_prism_dec && /tmp/test_prism_dec )
( cd "$COMMON/tests" && python3 test_metrics.py >/dev/null && echo "ok common metrics selftest" )

echo "== generate byte-identical workload (many2many 64->16 pod0, 2MB) =="
python3 "$COMMON/gen/many2many.py" "$OUT/m2m.cm" 64 16 pairs 2000000 128 16
CM="$OUT/m2m.cm"

echo "== sweep: failed{0,8} x rho{0,3,5,8} x 5 seeds (40 runs) =="
for rho in $RHOS; do for f in $FAILEDS; do for s in $SEEDS; do
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD -prism_spread_ratio $rho" \
    bash "$COMMON/run_lib.sh" prism reps "$f" "$TOPO" "$s" "$CM" flow "rgate_rho${rho}_f${f}_s${s}" "$OUT"
done; done; done

echo "== summary =="
python3 "$HERE/ratio_gate_summary.py"
```
Then make it executable:
```bash
chmod +x /home/leo/htsim/htsim/sim/datacenter/prism_eval/expA_f0_diagnosis/ratio_gate_sweep.sh
```

- [ ] **Step 2: Write the summary aggregator**

Create `htsim/sim/datacenter/prism_eval/expA_f0_diagnosis/ratio_gate_summary.py`:
```python
#!/usr/bin/env python3
"""ρ-gate acceptance table: PRISM goodput/avg-FCT at failed{0,8} for rho{0,3,5,8},
vs the rho=0 baseline and the REPS+NSCC reference (reused from expA_delaydriven/data)."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import perf_figs  # noqa: E402

DATA = os.path.join(HERE, "data")
EXPA = os.path.join(HERE, "..", "expA_delaydriven", "data")
SEEDS = [13, 14, 15, 16, 17]
FAILED = [0, 8]
RHOS = [0, 3, 5, 8]

# REPS+NSCC reference (the arm PRISM is trying to recover toward at f0).
reps = perf_figs.aggregate(EXPA, "expA", "reps", FAILED, SEEDS)
# PRISM per-rho: tag_prefix="rgate", label=f"rho{rho}", token="f".
prism = {rho: perf_figs.aggregate(DATA, "rgate", f"rho{rho}", FAILED, SEEDS) for rho in RHOS}

def g(d, f):   return d[f]["goodput"][0] if f in d else float("nan")
def a(d, f):   return d[f]["avg_fct"][0] if f in d else float("nan")

print(f"\n{'cell':>6} | {'arm':>14} | {'goodput Gbps':>13} | {'avg-FCT us':>11} | {'Δgoodput vs ρ=0':>16}")
print("-" * 78)
for f in FAILED:
    base_g = g(prism[0], f)
    print(f"{('f'+str(f)):>6} | {'REPS+NSCC':>14} | {g(reps,f):>13.1f} | {a(reps,f):>11.0f} |")
    for rho in RHOS:
        dg = g(prism[rho], f) - base_g
        tag = "PRISM ρ=0(base)" if rho == 0 else f"PRISM ρ={rho}"
        print(f"{('f'+str(f)):>6} | {tag:>14} | {g(prism[rho],f):>13.1f} | {a(prism[rho],f):>11.0f} | {dg:>+16.1f}")
    print("-" * 78)
print("\nAcceptance: at f0 some ρ raises goodput toward REPS (Δ>0, FCT down); at f8 that same ρ keeps")
print("goodput within seed-noise of ρ=0. Report the knee ρ. If none qualifies -> honest-null, revert.")
```

- [ ] **Step 3: Run the sweep**

Run:
```bash
bash /home/leo/htsim/htsim/sim/datacenter/prism_eval/expA_f0_diagnosis/ratio_gate_sweep.sh 2>&1 | tail -40
```
Expected: unit test prints `ALL PASS`; 40 `[run_lib]` lines; then the summary table. (~20–80 min wall; report progress every ~10 min per the user's standing preference.)

- [ ] **Step 4: Inspect acceptance**

Read the printed table. Confirm:
1. **Regression:** `PRISM ρ=0(base)` f0/f8 goodput+avg-FCT match the known current PRISM numbers (f0 ≈ 869 Gbps / 945 µs; f8 ≈ 504 Gbps / 1518 µs — from `expA_f0_diagnosis/README.md`, 5-seed means; allow seed-noise).
2. **Effect:** at some ρ, **f0 goodput rises toward REPS+NSCC (Δ>0) and avg-FCT falls**, AND at f8 that same ρ keeps goodput within seed-noise of ρ=0 (win preserved). Note the knee ρ in the report back to the user.
3. **Honest-null:** if no ρ satisfies (2), report it as a negative result — do not pick a ρ that erodes f8.

This step has no commit (analysis only); the result is reported to the user for the §6 review gate.

- [ ] **Step 5: Commit the scripts (not the data)**

```bash
cd /home/leo/htsim
git add htsim/sim/datacenter/prism_eval/expA_f0_diagnosis/ratio_gate_sweep.sh \
        htsim/sim/datacenter/prism_eval/expA_f0_diagnosis/ratio_gate_summary.py
git commit -m "$(printf 'prism: rho-gate validation sweep (f0+f8 x rho{0,3,5,8}) + summary table\n\nRides run_lib.sh via EXTRA_ARGS; raw data gitignored. rho=0 = regression\nreplica. Acceptance: f0 cost down AND f8 win preserved at chosen rho.\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Post-implementation (NOT tasks — gated on user review)

- Report the acceptance table + knee ρ to the user. **Do NOT** change any default, **do NOT** FF to `main`.
- If accepted: discuss whether to promote (still as opt-in flag) and/or build Scheme A (EWMA) as the principled comparison — separate spec.
- If honest-null: the default-off design means nothing downstream changed; optionally `git revert` the three task commits.
