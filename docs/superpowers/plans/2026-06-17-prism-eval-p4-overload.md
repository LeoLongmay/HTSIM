# PRISM eval P4 — overload (oversubscription + incast) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the P4 fallback-correctness pillar — two read-only experiment groups (`expB_oversub/`, `expC_incast/`) showing PRISM correctly falls back to floor-driven CC under non-reroutable, path-wide overload (do-no-harm vs REPS+NSCC), in the delay-driven regime, with zero controller changes.

**Architecture:** Both groups reuse the `expA_delaydriven/` harness verbatim (`common/run_lib.sh`, generators, `metrics.py`, `perf_figs.py`). The x-axis stressor is encoded in the existing `f{v}` filename token (oversub ratio for B, fan-in for C); `perf_figs.render_main_perf` already takes an `xlabel` parameter so it needs no change. The single shared-code touch is a backward-compatible `mech_label` kwarg on `perf_figs.render_mechanism` so the mechanism-figure title reads "oversub=8:1" / "fan-in=64" instead of "-failed=8". Oversub is created by swapping the topo file (`fat_tree_128_{1,4,8}os.topo`, all verified drop-ins) with `-failed 0`; incast by `incast.py` on the symmetric `1os` topo with `-failed 0`.

**Tech Stack:** bash (repro harness), Python 3 + matplotlib (figures via `common/perf_figs.py`), the prebuilt `htsim_uec` binary, htsim `.topo`/`.cm` inputs.

---

## Conventions binding on every task (read first)

- **NO git commits during execution.** The user's standing rule ("do NOT git commit unless explicitly asked") overrides the writing-plans default of frequent commits. Every task ends by leaving changes in the working tree; a single milestone commit happens only at the end on **explicit user approval** (Task 8 note). Wherever a step says "stage", it means `git add`-ready, not committed.
- **No controller code changes anywhere in P4.** Read-only on PRISM (`uec.cpp`, `prism_decompose.h`, etc.). PRISM stays O(1).
- **Regime = delay-driven:** every sim run uses `EXTRA_ARGS="-disable_trim"`, `PATHS=8`, `NODES=128`, `END_MS` via `EXP_END` (default 8).
- **Arms (4):** `nscc oblivious` (OPS+NSCC, lower bound), `nscc reps` (REPS+NSCC), `prism reps` (PRISM), `strack reps` (STrack). Seeds `{13,14,15,16,17}`.
- **Honesty:** report results straight; if PRISM is worse on incast, say so and explain via the f0 mechanism. No forced positives, no final go/no-go.
- **Raw data** (`*.csv/*.txt/*.dat/*.stdout/*.idmap`) is gitignored; **figures** are committed with `git add -f`.
- The binary must exist: `htsim/sim/datacenter/htsim_uec` and `htsim/sim/build/parse_output`. If missing, build first:
  `cd htsim/sim/build && cmake --build . --target htsim_uec -j` (decoder target `parse_output`).
- All paths below are relative to the repo root `/home/leo/htsim` unless stated. The datacenter dir is
  `htsim/sim/datacenter/` (call it `DC`).

---

## File structure

| File | Responsibility | Task |
|---|---|---|
| `htsim/sim/datacenter/prism_eval/common/perf_figs.py` | + `_mech_label` helper, used in `render_mechanism` title/prints (backward-compatible) | 1 |
| `htsim/sim/datacenter/prism_eval/expB_oversub/make_figs.py` | thin wrapper: render figB1/figB2 from ./data | 2 |
| `htsim/sim/datacenter/prism_eval/expB_oversub/repro.sh` | one-command repro: selftest → workload → sweep → mechanism → figs | 2,3 |
| `htsim/sim/datacenter/prism_eval/expB_oversub/README.md` | setup, honest results, mechanism, caveats | 4 |
| `htsim/sim/datacenter/prism_eval/expB_oversub/figs/` | figB1_main_perf, figB2_mechanism (png+pdf) | 3 |
| `htsim/sim/datacenter/prism_eval/expC_incast/make_figs.py` | thin wrapper: render figC1/figC2 from ./data | 5 |
| `htsim/sim/datacenter/prism_eval/expC_incast/repro.sh` | one-command repro for incast | 5,6 |
| `htsim/sim/datacenter/prism_eval/expC_incast/README.md` | setup, honest results, mechanism, caveats | 7 |
| `htsim/sim/datacenter/prism_eval/expC_incast/figs/` | figC1_main_perf, figC2_mechanism (png+pdf) | 6 |
| `prism_eval/NARRATIVE.md`, `prism_eval/TARGET_REGIME.md`, memory roadmap | fold the now-measured fallback pillar | 8 |

---

## Task 1: `perf_figs` — backward-compatible `mech_label` kwarg

**Why:** `render_mechanism`'s title/prints hardcode `-failed={mech_failed}`. For oversub/incast the stressor is a ratio/fan-in, so an honest title needs a label word. Make it a pure helper so it is unit-tested and the default path stays byte-identical for expA.

**Files:**
- Modify: `htsim/sim/datacenter/prism_eval/common/perf_figs.py`

- [ ] **Step 1: Add the failing assertions to `selftest()`**

In `perf_figs.py`, inside `def selftest():`, just before the final `print("ok perf_figs aggregation selftest")`, insert:

```python
    assert _mech_label(None, 8) == "-failed=8", _mech_label(None, 8)
    assert _mech_label("oversub=8:1", 8) == "oversub=8:1", _mech_label("oversub=8:1", 8)
    assert _mech_label("fan-in=64", 64) == "fan-in=64", _mech_label("fan-in=64", 64)
```

- [ ] **Step 2: Run the selftest to verify it fails**

Run: `cd htsim/sim/datacenter/prism_eval/common && python3 perf_figs.py`
Expected: `NameError: name '_mech_label' is not defined`.

- [ ] **Step 3: Add the helper**

In `perf_figs.py`, add immediately after the `_ms` function (around line 14):

```python
def _mech_label(mech_label, mech_failed):
    """Label for the mechanism figure's stressor. Defaults to the legacy `-failed=N` form
    (so expA output is byte-identical); pass an explicit label for non-failure stressors
    (oversub ratio, incast fan-in)."""
    return mech_label if mech_label else f"-failed={mech_failed}"
```

- [ ] **Step 4: Wire the helper into `render_mechanism`**

Change the signature (line 87) from:

```python
def render_mechanism(data_dir, figs_dir, tag_prefix, fig_stem, mech_failed, target_us=6.0, base_ns=13945):
```

to:

```python
def render_mechanism(data_dir, figs_dir, tag_prefix, fig_stem, mech_failed, target_us=6.0, base_ns=13945, mech_label=None):
```

Then, near the top of the function body (right after the early-return block that prints "mechanism logs missing"), add:

```python
    lbl = _mech_label(mech_label, mech_failed)
```

Replace the title line:

```python
    ax_sig.set_title(f"Mechanism @ -failed={mech_failed}", fontsize=11)
```

with:

```python
    ax_sig.set_title(f"Mechanism @ {lbl}", fontsize=11)
```

(Note: for the default `mech_label=None`, `lbl == "-failed=8"`, so the saved title is the exact
string "Mechanism @ -failed=8" as before — expA figures stay byte-identical.) Also update the three
diagnostic `print(...)` lines that contain `@failed={mech_failed}` to use `@{lbl}` instead — these
go to stdout only (not a committed artifact), and keep the label consistent.

- [ ] **Step 5: Run the selftest to verify it passes**

Run: `cd htsim/sim/datacenter/prism_eval/common && python3 perf_figs.py`
Expected: `ok perf_figs aggregation selftest` (no assertion error).

- [ ] **Step 6: Smoke-check expA still renders unchanged (regression)**

Run: `cd htsim/sim/datacenter/prism_eval/expA_delaydriven && python3 make_figs.py >/tmp/expA_render.log 2>&1; echo exit=$?`
Expected: `exit=0`, and `/tmp/expA_render.log` contains the `[figA2dd_mechanism]` lines with title-independent numbers unchanged. Then `cd ../../../../.. && git status --porcelain htsim/sim/datacenter/prism_eval/expA_delaydriven/figs` — expA fig bytes should be unchanged (the default `lbl` reproduces the old title exactly). If the PNGs differ, STOP and investigate before proceeding.

- [ ] **Step 7: Do NOT commit** — leave the modified `perf_figs.py` staged for the milestone commit (Task 8).

---

## Task 2: `expB_oversub` harness (files + wiring smoke test)

**Files:**
- Create: `htsim/sim/datacenter/prism_eval/expB_oversub/make_figs.py`
- Create: `htsim/sim/datacenter/prism_eval/expB_oversub/repro.sh`

- [ ] **Step 1: Create `make_figs.py`**

```python
#!/usr/bin/env python3
"""Exp B, OVERSUBSCRIPTION (delay-driven, -disable_trim) figures -- thin wrapper over
common/perf_figs.py. Renders figB1_main_perf + figB2_mechanism from ./data into ./figs.
x-axis = oversubscription ratio {1,4,8}, encoded in the f{ratio} filename token (-failed is 0).
  python3 make_figs.py            # render
  python3 make_figs.py --selftest # aggregation self-check (shared perf_figs math)
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import perf_figs  # noqa: E402

DATA = os.path.join(HERE, "data")
FIGS = os.path.join(HERE, "figs")
BASELINES = [("ops", "OPS+NSCC", "ops"), ("reps", "REPS+NSCC", "reps"),
             ("strack", "STrack", "strack"), ("prism", "PRISM", "prism")]
RATIOS = [1, 4, 8]          # oversubscription ratio N:1 (x-axis) and the f{ratio} filename token
SEEDS = [13, 14, 15, 16, 17]
XLABEL = "oversubscription ratio (N:1), delay-driven (-disable_trim)"

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        perf_figs.selftest()
    else:
        os.makedirs(FIGS, exist_ok=True)
        perf_figs.render_main_perf(DATA, FIGS, "expB", BASELINES, RATIOS, SEEDS, "figB1_main_perf", XLABEL)
        perf_figs.render_mechanism(DATA, FIGS, "expB", "figB2_mechanism", 8, mech_label="oversub=8:1")
```

- [ ] **Step 2: Create `repro.sh`**

```bash
#!/bin/bash
# Exp B, OVERSUBSCRIPTION (delay-driven, -disable_trim): graded core bottleneck.
# x-axis = oversubscription ratio {1,4,8} via topo file; -failed=0 (oversub is the only stressor,
# orthogonal to expA's link-asymmetry axis). Same 64->16 m2m workload as expA_delaydriven.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../common" && pwd)"
DC="$(cd "$HERE/../.." && pwd)"
REL="prism_eval/expB_oversub"
cd "$DC"
[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first"; exit 1; }
mkdir -p "$REL/data"
SEEDS="13 14 15 16 17"
RATIOS="1 4 8"
declare -A TOPO=( [1]=fat_tree_128_1os.topo [4]=fat_tree_128_4os.topo [8]=fat_tree_128_8os.topo )
DD="-disable_trim"                # delay-driven knob
ENDV="${EXP_END:-8}"              # ms; deep no-trim queues need time to drain (see README caveat)

echo "== self-test analysis =="
python3 "$HERE/make_figs.py" --selftest
( cd "$COMMON/tests" && python3 test_metrics.py >/dev/null && echo "ok common metrics selftest" )

echo "== generate workload (many2many: 64 -> 16 pod0, 2MB; same as expA_delaydriven) =="
python3 "$COMMON/gen/many2many.py" "$REL/data/m2m.cm" 64 16 pairs 2000000 128 16
CM="$REL/data/m2m.cm"; OUT="$REL/data"

echo "== main sweep (oversub): 4 baselines x ratio{1,4,8} x 5 seeds =="
for r in $RATIOS; do for s in $SEEDS; do
  T="${TOPO[$r]}"
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" nscc oblivious 0 "$T" "$s" "$CM" flow,sink "expB_ops_f${r}_s${s}" "$OUT"
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" nscc reps      0 "$T" "$s" "$CM" flow,sink "expB_reps_f${r}_s${s}" "$OUT"
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_EPOCH="$OUT/expB_prism_f${r}_s${s}.epoch.csv" \
    bash "$COMMON/run_lib.sh" prism reps 0 "$T" "$s" "$CM" flow,sink "expB_prism_f${r}_s${s}" "$OUT"
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" strack reps   0 "$T" "$s" "$CM" flow,sink "expB_strack_f${r}_s${s}" "$OUT"
done; done

echo "== mechanism condition: ratio=8 (8os), seed=13, all 4 arms with PRISM_PATHRTT =="
T8="${TOPO[8]}"
PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_PATHRTT="$OUT/expB_ops_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" nscc oblivious 0 "$T8" 13 "$CM" flow,sink expB_ops_mech "$OUT"
PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_PATHRTT="$OUT/expB_reps_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" nscc reps 0 "$T8" 13 "$CM" flow,sink expB_reps_mech "$OUT"
PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_EPOCH="$OUT/expB_prism_mech.epoch.csv" PRISM_PATHRTT="$OUT/expB_prism_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" prism reps 0 "$T8" 13 "$CM" flow,sink expB_prism_mech "$OUT"
PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_PATHRTT="$OUT/expB_strack_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" strack reps 0 "$T8" 13 "$CM" flow,sink expB_strack_mech "$OUT"

echo "== render figB1 + figB2 =="
python3 "$HERE/make_figs.py"
echo "== done: figs/figB1_main_perf.{png,pdf} figs/figB2_mechanism.{png,pdf} =="
```

- [ ] **Step 3: Make repro.sh executable**

Run: `chmod +x htsim/sim/datacenter/prism_eval/expB_oversub/repro.sh`

- [ ] **Step 4: Verify the analysis selftest passes (no sims yet)**

Run: `cd htsim/sim/datacenter/prism_eval/expB_oversub && python3 make_figs.py --selftest`
Expected: `ok perf_figs aggregation selftest`.

- [ ] **Step 5: Wiring smoke test — one short run per topo, confirm output is produced**

This validates the topo files, the `-disable_trim` flag, and the filename wiring BEFORE the full sweep. Run from `DC`:

```bash
cd htsim/sim/datacenter
python3 prism_eval/common/gen/many2many.py /tmp/smoke_m2m.cm 64 16 pairs 2000000 128 16
for T in fat_tree_128_1os.topo fat_tree_128_4os.topo fat_tree_128_8os.topo; do
  PATHS=8 END_MS=2 EXTRA_ARGS=-disable_trim bash prism_eval/common/run_lib.sh \
    nscc reps 0 "$T" 13 /tmp/smoke_m2m.cm flow,sink "smoke_${T%.topo}" /tmp/expB_smoke
done
wc -l /tmp/expB_smoke/*.flow.txt
```

Expected: each `smoke_fat_tree_128_*os.flow.txt` is non-empty (FCT events present), and no `run_lib` error. If a topo file errors, STOP and fix wiring before the full sweep. Clean up: `rm -rf /tmp/expB_smoke /tmp/smoke_m2m.cm`.

- [ ] **Step 6: Do NOT commit** — leave `make_figs.py` and `repro.sh` in the working tree.

---

## Task 3: Run the `expB_oversub` sweep, verify completion, render figures

**Files:**
- Produces: `htsim/sim/datacenter/prism_eval/expB_oversub/data/*` (gitignored), `.../figs/figB1_main_perf.{png,pdf}`, `.../figs/figB2_mechanism.{png,pdf}`

- [ ] **Step 1: Run the full repro**

Run: `cd htsim/sim/datacenter/prism_eval/expB_oversub && bash repro.sh 2>&1 | tee /tmp/expB_repro.log`
(Long-running: 4 arms × 3 ratios × 5 seeds + 4 mechanism runs = 64 sims. May run in background.)
Expected: ends with `== done: figs/figB1_main_perf.{png,pdf} figs/figB2_mechanism.{png,pdf} ==`.

- [ ] **Step 2: Verify completion ratio (FCT validity gate)**

The `[figB1_main_perf]` lines printed by `make_figs.py` (captured in `/tmp/expB_repro.log`) include `cr=` per arm per ratio, and the figure foot-notes any cell with `completion<1`.
Expected: `cr ≈ 1.00` for all arms at all ratios. If any arm shows `cr < 0.999` (deep-queue drain not finished), re-run with a larger horizon: `EXP_END=16 bash repro.sh` and re-check. Record the final `EXP_END` used.

- [ ] **Step 3: Verify the mechanism figure rendered with floor-MD fraction**

In `/tmp/expB_repro.log`, confirm a `[figB2_mechanism] floor-MD fraction = ...` line is present and the title label is `oversub=8:1` (i.e. `Mechanism @ oversub=8:1` in the saved figure). The floor-MD fraction at 8:1 should be materially above the trimming baseline (~0.05), evidence PRISM is delay-driven and reacting to the floor.
Expected: a numeric floor-MD fraction printed; figB2 png+pdf exist in `figs/`.

- [ ] **Step 4: Extract the do-no-harm comparison for the README**

Run: `grep -E '^\[figB1_main_perf\]' /tmp/expB_repro.log`
This prints per-arm `f{ratio}: g=..,avgfct=..us,cr=..` for ops/reps/strack/prism. Record PRISM vs REPS+NSCC goodput and avg-FCT at each ratio (the do-no-harm headline) and note the sign/magnitude of any gap. **Do not edit numbers** — copy them as printed.

- [ ] **Step 5: Confirm figures exist**

Run: `ls -la htsim/sim/datacenter/prism_eval/expB_oversub/figs/`
Expected: `figB1_main_perf.png`, `figB1_main_perf.pdf`, `figB2_mechanism.png`, `figB2_mechanism.pdf`.

- [ ] **Step 6: Do NOT commit** — figures will be force-added in Task 8.

---

## Task 4: `expB_oversub/README.md` (honest, from actual numbers)

**Files:**
- Create: `htsim/sim/datacenter/prism_eval/expB_oversub/README.md`

- [ ] **Step 1: Write the README using the exact numbers extracted in Task 3**

The README MUST contain these sections, filled from `/tmp/expB_repro.log` (no invented numbers, no "TBD"):

1. **What this group tests** — one paragraph: oversubscription as a graded core bottleneck (1:1 → 4:1 → 8:1), the fallback-correctness question (does PRISM cut when `C_cc` rises, while staying do-no-harm vs REPS+NSCC?), delay-driven regime. State `-failed=0` (oversub is the only stressor) and `EXP_END` used.
2. **Setup** — topo files (`fat_tree_128_{1,4,8}os.topo`), workload (`many2many 64→16 pairs 2MB`), 4 arms, 5 seeds, `-disable_trim`, `PATHS=8`. One-line repro command.
3. **Results (do-no-harm)** — a small table of goodput + avg-FCT per arm per ratio (the `[figB1_main_perf]` numbers), with the PRISM-vs-REPS+NSCC gap called out per ratio. State plainly whether PRISM is do-no-harm (tie / small edge / small cost), citing the numbers.
4. **Mechanism** — the figB2 floor-MD fraction at 8:1 and what it shows (PRISM is delay-driven and reacts to the floor as the core saturates); reference `figB2_mechanism`.
5. **Honest verdict** — restate the framing: this is the fallback-correctness pillar, not a win-hunt; the contribution is correct floor-driven reaction under path-wide overload. Cross-link `../NARRATIVE.md` and `../TARGET_REGIME.md` (§3, Axis-2 / oversub).
6. **Caveats** — completion-stress note (deep no-trim queues; `EXP_END` chosen for cr≈1.0), 128-node dev scale, delay-driven regime only (trimming deferred to P5).

- [ ] **Step 2: Verify no placeholders**

Run: `grep -nE 'TBD|TODO|FIXME|XXX' htsim/sim/datacenter/prism_eval/expB_oversub/README.md`
Expected: no output.

- [ ] **Step 3: Verify cross-links resolve**

Run: `ls htsim/sim/datacenter/prism_eval/NARRATIVE.md htsim/sim/datacenter/prism_eval/TARGET_REGIME.md`
Expected: both exist.

- [ ] **Step 4: Do NOT commit.**

---

## Task 5: `expC_incast` harness (files + completion/wiring smoke test)

**Files:**
- Create: `htsim/sim/datacenter/prism_eval/expC_incast/make_figs.py`
- Create: `htsim/sim/datacenter/prism_eval/expC_incast/repro.sh`

- [ ] **Step 1: Create `make_figs.py`**

```python
#!/usr/bin/env python3
"""Exp C, INCAST (delay-driven, -disable_trim) figures -- thin wrapper over common/perf_figs.py.
Renders figC1_main_perf + figC2_mechanism from ./data into ./figs. Pure shared-bottleneck
fallback: N senders -> 1 dest on the symmetric 1os topo (-failed 0). x-axis = fan-in {8,32,64},
encoded in the f{fanin} filename token.
  python3 make_figs.py            # render
  python3 make_figs.py --selftest # aggregation self-check (shared perf_figs math)
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import perf_figs  # noqa: E402

DATA = os.path.join(HERE, "data")
FIGS = os.path.join(HERE, "figs")
BASELINES = [("ops", "OPS+NSCC", "ops"), ("reps", "REPS+NSCC", "reps"),
             ("strack", "STrack", "strack"), ("prism", "PRISM", "prism")]
FANIN = [8, 32, 64]         # incast fan-in (x-axis) and the f{fanin} filename token
SEEDS = [13, 14, 15, 16, 17]
XLABEL = "incast fan-in (senders : 1), delay-driven (-disable_trim)"

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        perf_figs.selftest()
    else:
        os.makedirs(FIGS, exist_ok=True)
        perf_figs.render_main_perf(DATA, FIGS, "expC", BASELINES, FANIN, SEEDS, "figC1_main_perf", XLABEL)
        perf_figs.render_mechanism(DATA, FIGS, "expC", "figC2_mechanism", 64, mech_label="fan-in=64")
```

- [ ] **Step 2: Create `repro.sh`**

```bash
#!/bin/bash
# Exp C, INCAST (delay-driven, -disable_trim): pure shared downstream bottleneck.
# x-axis = fan-in {8,32,64} senders -> 1 dest, symmetric fat_tree_128_1os, -failed=0.
# Message size 1MB (keeps 64:1 tractable in the deep no-trim regime). Tests that PRISM falls
# back to floor-driven CC (C_cc high, C_spray small/transient) and does NOT misuse spray.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../common" && pwd)"
DC="$(cd "$HERE/../.." && pwd)"
REL="prism_eval/expC_incast"
cd "$DC"
[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first"; exit 1; }
mkdir -p "$REL/data"
SEEDS="13 14 15 16 17"
FANIN="8 32 64"
TOPO=fat_tree_128_1os.topo        # symmetric: pure shared bottleneck at the dest ingress
SIZE="${INCAST_SIZE:-1000000}"    # 1MB default; override for the optional 2MB alignment point
DD="-disable_trim"
ENDV="${EXP_END:-8}"

echo "== self-test analysis =="
python3 "$HERE/make_figs.py" --selftest
( cd "$COMMON/tests" && python3 test_metrics.py >/dev/null && echo "ok common metrics selftest" )

echo "== generate incast workloads (fan-in {8,32,64} -> host0, ${SIZE}B) =="
for n in $FANIN; do
  python3 "$COMMON/gen/incast.py" "$REL/data/incast_${n}.cm" "$n" 0 "$SIZE" 128 16
done
OUT="$REL/data"

echo "== main sweep (incast): 4 baselines x fan-in{8,32,64} x 5 seeds =="
for n in $FANIN; do for s in $SEEDS; do
  CM="$REL/data/incast_${n}.cm"
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" nscc oblivious 0 "$TOPO" "$s" "$CM" flow,sink "expC_ops_f${n}_s${s}" "$OUT"
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" nscc reps      0 "$TOPO" "$s" "$CM" flow,sink "expC_reps_f${n}_s${s}" "$OUT"
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_EPOCH="$OUT/expC_prism_f${n}_s${s}.epoch.csv" \
    bash "$COMMON/run_lib.sh" prism reps 0 "$TOPO" "$s" "$CM" flow,sink "expC_prism_f${n}_s${s}" "$OUT"
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" strack reps   0 "$TOPO" "$s" "$CM" flow,sink "expC_strack_f${n}_s${s}" "$OUT"
done; done

echo "== mechanism condition: fan-in=64, seed=13, all 4 arms with PRISM_PATHRTT =="
CM64="$REL/data/incast_64.cm"
PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_PATHRTT="$OUT/expC_ops_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" nscc oblivious 0 "$TOPO" 13 "$CM64" flow,sink expC_ops_mech "$OUT"
PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_PATHRTT="$OUT/expC_reps_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" nscc reps 0 "$TOPO" 13 "$CM64" flow,sink expC_reps_mech "$OUT"
PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_EPOCH="$OUT/expC_prism_mech.epoch.csv" PRISM_PATHRTT="$OUT/expC_prism_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" prism reps 0 "$TOPO" 13 "$CM64" flow,sink expC_prism_mech "$OUT"
PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_PATHRTT="$OUT/expC_strack_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" strack reps 0 "$TOPO" 13 "$CM64" flow,sink expC_strack_mech "$OUT"

echo "== render figC1 + figC2 =="
python3 "$HERE/make_figs.py"
echo "== done: figs/figC1_main_perf.{png,pdf} figs/figC2_mechanism.{png,pdf} =="
```

- [ ] **Step 3: Make repro.sh executable**

Run: `chmod +x htsim/sim/datacenter/prism_eval/expC_incast/repro.sh`

- [ ] **Step 4: Verify the analysis selftest passes**

Run: `cd htsim/sim/datacenter/prism_eval/expC_incast && python3 make_figs.py --selftest`
Expected: `ok perf_figs aggregation selftest`.

- [ ] **Step 5: Completion/wiring smoke test at the worst case (fan-in 64)**

The 64:1 case is the completion-stress risk (64×1MB into one 100Gbps host ≈ 5ms at line rate + deep queue). Validate it finishes before the full sweep. Run from `DC`:

```bash
cd htsim/sim/datacenter
python3 prism_eval/common/gen/incast.py /tmp/smoke_incast64.cm 64 0 1000000 128 16
PATHS=8 END_MS=8 EXTRA_ARGS=-disable_trim bash prism_eval/common/run_lib.sh \
  nscc reps 0 fat_tree_128_1os.topo 13 /tmp/smoke_incast64.cm flow,sink smoke64 /tmp/expC_smoke
python3 - <<'PY'
import sys; sys.path.insert(0, "prism_eval/common")
import metrics
st = metrics.fct_stats("/tmp/expC_smoke/smoke64.flow.txt")
print("completion_rate=", st["completion_rate"], "avg_fct_us=", st["avg_s"]*1e6)
PY
```

Expected: `completion_rate` ≈ 1.0. If it is `< 0.999`, the deep-queue 64:1 drain needs more time — set the sweep horizon higher (`EXP_END=16`, and/or reduce to `INCAST_SIZE=500000`) and record the choice for Task 6. Clean up: `rm -rf /tmp/expC_smoke /tmp/smoke_incast64.cm`.

- [ ] **Step 6: Do NOT commit.**

---

## Task 6: Run the `expC_incast` sweep, verify completion, render figures

**Files:**
- Produces: `.../expC_incast/data/*` (gitignored), `.../figs/figC1_main_perf.{png,pdf}`, `.../figs/figC2_mechanism.{png,pdf}`

- [ ] **Step 1: Run the full repro** (apply the `EXP_END`/`INCAST_SIZE` chosen in Task 5 step 5)

Run: `cd htsim/sim/datacenter/prism_eval/expC_incast && EXP_END=<chosen> bash repro.sh 2>&1 | tee /tmp/expC_repro.log`
Expected: ends with `== done: figs/figC1_main_perf.{png,pdf} figs/figC2_mechanism.{png,pdf} ==`.

- [ ] **Step 2: Verify completion ratio**

Check the `[figC1_main_perf]` lines in `/tmp/expC_repro.log` for `cr≈1.0` at every fan-in/arm; the figure foot-notes any `completion<1` cell. If any cell is short, bump `EXP_END` and re-run. Record the final horizon.

- [ ] **Step 3: Verify the mechanism figure + fallback evidence**

In `/tmp/expC_repro.log`, confirm `[figC2_mechanism]` printed the floor-MD fraction and the title label is `fan-in=64`. Expect the floor-MD fraction high and PRISM in the floor-driven regime (the epoch log should show high `C_cc`, small `C_spray`). Record these for the README.

- [ ] **Step 4: Extract the do-no-harm comparison**

Run: `grep -E '^\[figC1_main_perf\]' /tmp/expC_repro.log`
Record PRISM vs REPS+NSCC goodput/avg-FCT per fan-in. **Report whatever the numbers say** — the pre-registered expectation (from the f0 diagnosis) is tie-or-small-cost, not a win. Copy numbers verbatim.

- [ ] **Step 5: Confirm figures exist**

Run: `ls -la htsim/sim/datacenter/prism_eval/expC_incast/figs/`
Expected: `figC1_main_perf.{png,pdf}`, `figC2_mechanism.{png,pdf}`.

- [ ] **Step 6: Do NOT commit.**

---

## Task 7: `expC_incast/README.md` (honest, from actual numbers)

**Files:**
- Create: `htsim/sim/datacenter/prism_eval/expC_incast/README.md`

- [ ] **Step 1: Write the README using the exact numbers from `/tmp/expC_repro.log`**

Required sections (no invented numbers, no "TBD"):

1. **What this group tests** — pure shared downstream bottleneck (N→1 on a symmetric fabric, no reroutable structure by construction); the fallback question (does PRISM behave like floor-driven CC and NOT misuse spray?). State the pre-registered expectation: **tie or small cost, not a win** (f0 generalization).
2. **Setup** — `incast.py` fan-in {8,32,64} → host0, symmetric `fat_tree_128_1os.topo`, `-failed 0`, message size (1MB, or the value used), 4 arms, 5 seeds, `-disable_trim`, the `EXP_END` used. One-line repro command.
3. **Results (do-no-harm / cost)** — goodput + avg-FCT per arm per fan-in table; PRISM-vs-REPS+NSCC gap per fan-in stated plainly (including if PRISM is worse). 
4. **Mechanism** — figC2 floor-MD fraction at fan-in 64 + the C_cc-high / C_spray-small-or-transient picture, showing PRISM correctly identifies path-wide overload and falls back to the floor; reference `figC2_mechanism`. If PRISM under-grows, explicitly connect it to the f0 finding (`../expA_f0_diagnosis/`): HOLDing on a transient spread costs a little on a shared bottleneck.
5. **Honest verdict** — fallback-correctness pillar: PRISM does not mistake shared-bottleneck overload for reroutable imbalance; the small cost (if any) is the same characterized O(1) cost as f0, not a defect. Cross-link `../NARRATIVE.md`, `../TARGET_REGIME.md` (§3/§5, Axis-2 out), `../expA_f0_diagnosis/`.
6. **Caveats** — completion-stress (`EXP_END`/size choice), 128-node dev scale, delay-driven regime only.

- [ ] **Step 2: Verify no placeholders**

Run: `grep -nE 'TBD|TODO|FIXME|XXX' htsim/sim/datacenter/prism_eval/expC_incast/README.md`
Expected: no output.

- [ ] **Step 3: Verify cross-links resolve**

Run: `ls htsim/sim/datacenter/prism_eval/NARRATIVE.md htsim/sim/datacenter/prism_eval/TARGET_REGIME.md htsim/sim/datacenter/prism_eval/expA_f0_diagnosis/README.md`
Expected: all exist.

- [ ] **Step 4: Do NOT commit.**

---

## Task 8: Fold P4 into the narrative + memory (and prepare the milestone commit)

**Files:**
- Modify: `htsim/sim/datacenter/prism_eval/NARRATIVE.md`
- Modify: `htsim/sim/datacenter/prism_eval/TARGET_REGIME.md`
- Modify: `/home/leo/.claude/projects/-home-leo-htsim/memory/prism-eval-roadmap.md`

- [ ] **Step 1: Update `NARRATIVE.md`**

In §3 (or its boundary/cost bullets), add one bullet recording that the fallback side is now **measured**: oversubscription (`expB_oversub/`) shows PRISM cuts correctly as the core saturates (floor-MD rises, do-no-harm vs REPS+NSCC), and incast (`expC_incast/`) confirms correct floor-driven fallback on a pure shared bottleneck (state the measured tie/cost). Update the Map table with two rows (Eval (fallback): expB_oversub, expC_incast). Use the actual numbers from the READMEs.

- [ ] **Step 2: Update `TARGET_REGIME.md`**

§3 (Axis 2 — reroutable vs shared-bottleneck) and §5 (boundary) currently cite only f0 for the shared-bottleneck case. Add that the boundary is now **measured at graded scale**: oversub 1→4→8 (expB) and incast 8→32→64 (expC), PRISM falls back to floor-driven CC correctly (do-no-harm under oversub; the characterized small cost under pure incast). Add the two groups to the Map table. Keep the measured-vs-asserted layering intact.

- [ ] **Step 2b: Verify cross-links still resolve**

Run: `grep -oE '\.\./[A-Za-z0-9_./]+\.md|expA_f0_diagnosis|expB_oversub|expC_incast' htsim/sim/datacenter/prism_eval/NARRATIVE.md htsim/sim/datacenter/prism_eval/TARGET_REGIME.md | sort -u`
Manually confirm each referenced path exists.

- [ ] **Step 3: Update the roadmap memory**

Append a P4 status block to `prism-eval-roadmap.md`: the fallback-correctness pillar built (expB_oversub + expC_incast), the do-no-harm result for oversub and the tie/cost result for incast (with numbers), the `mech_label` perf_figs touch (no controller change, O(1) preserved), and the commit-chain entry (to be filled when committed). Mark P4 done; remaining = 1024 scale, P5 sensitivity, Approach B.

- [ ] **Step 4: Final verification — selftests + figures present**

Run:
```bash
cd htsim/sim/datacenter/prism_eval
python3 expB_oversub/make_figs.py --selftest
python3 expC_incast/make_figs.py --selftest
python3 common/perf_figs.py
ls expB_oversub/figs/ expC_incast/figs/
```
Expected: all selftests print `ok ...`; both figs dirs contain the 4 figure files each (png+pdf ×2).

- [ ] **Step 5: Present the milestone for user approval (DO NOT commit yet)**

Summarize to the user: files added (two groups + perf_figs touch + doc folds), the honest results (oversub do-no-harm; incast tie/cost), and the proposed single milestone commit. The commit (with `git add -f` for the figures) happens **only after explicit user approval**, per the standing rule. Proposed commit message stem: `prism_eval P4: fallback-correctness pillar (oversub do-no-harm + incast floor-driven fallback)`.

---

## Self-review notes (author)

- **Spec coverage:** §2.1 expB → Tasks 2–4; §2.2 expC → Tasks 5–7; §2.3 perf_figs touch → Task 1 (narrowed to `mech_label` only, since `render_main_perf` already takes `xlabel` — a smaller, lower-risk change than the spec anticipated; expA figures stay byte-identical); §3.1 common settings → conventions block + every run line; §3.2 oversub graded sweep → Task 3; §3.3 incast + completion-stress → Tasks 5–6; §3.4 mechanism → repro mechanism blocks + Task 3/6 step 3; §4 metrics/figures → make_figs wrappers; §5 honest expected results → README tasks + Task 6 step 4; §6/§7/§8 → conventions block + Task 8.
- **Placeholder scan:** README tasks specify exact sections + the exact log lines to source numbers from (not "TBD"); the only run-time-determined values are `EXP_END`/`INCAST_SIZE`, which are resolved by the completion gates in Tasks 3/5/6 and recorded.
- **Type/name consistency:** filename token `f{ratio}`/`f{fanin}` matches `perf_figs.aggregate`'s `{tag_prefix}_{label}_f{f}_s{seed}.flow.txt`; tag prefixes `expB`/`expC` match the `make_figs.py` calls; `mech_label` kwarg name consistent across Task 1 and the wrapper calls in Tasks 2/5.
