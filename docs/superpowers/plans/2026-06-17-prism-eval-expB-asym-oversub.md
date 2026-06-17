# PRISM eval — expB asymmetric oversubscription Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only experiment group testing whether PRISM's delay-driven asymmetric win (expA, 1:1 fabric) extends to an oversubscribed core — sweeping #failed links at fixed oversub {4:1, 8:1} — and report the win/tie verdict honestly.

**Architecture:** New group `expB_oversub_asym/` reusing the expA/expB harness verbatim. The oversub ratio is the topo file (`fat_tree_128_{4,8}os.topo`); the asymmetry axis is `-failed N` (degrades core-tier links to 25% speed). Figures via the existing `perf_figs.render_main_perf` (x=#failed, one per ratio) + `render_mechanism`. Zero controller change, zero shared-code change.

**Tech Stack:** bash harness, Python 3 + matplotlib (`common/perf_figs.py`), prebuilt `htsim_uec`.

---

## Conventions binding on every task (read first)

- **NO git commits during execution** (user's standing rule). End each task with changes in the working tree; one milestone commit only on explicit user approval (Task 4). Reviewers review the working-tree diff.
- **No controller change; no shared-code change** — reuse the existing `perf_figs.render_main_perf` / `render_mechanism` (both present and committed). Only the new group's 3 files are created.
- Paths relative to repo root `/home/leo/htsim`; datacenter dir = `htsim/sim/datacenter/` (DC). Binary `htsim/sim/datacenter/htsim_uec` is built and committed (O(1) PRISM, no `-prism_hold_leak`).
- Honest reporting: the per-ratio goodput/FCT table and a clear win/tie verdict; a tie/no-win is reported as plainly as a win.
- Raw data (`*.csv/*.txt/*.dat/*.cm/*.stdout/*.idmap`) gitignored; figures `git add -f`.

---

## File structure

| File | Responsibility | Task |
|---|---|---|
| `htsim/sim/datacenter/prism_eval/expB_oversub_asym/make_figs.py` | thin wrapper: render figBa_4os_main, figBa_8os_main, figBa_mech | 1 |
| `htsim/sim/datacenter/prism_eval/expB_oversub_asym/repro.sh` | build check, selftest, workload, failed-cap report, sweep, mechanism, render | 1,2 |
| `htsim/sim/datacenter/prism_eval/expB_oversub_asym/README.md` | setup, per-ratio results, honest win/tie verdict | 3 |
| `htsim/sim/datacenter/prism_eval/expB_oversub_asym/figs/figBa_{4os_main,8os_main,mech}.{png,pdf}` | figures | 2 |

---

## Task 1: `expB_oversub_asym` harness + failed-cap determination

**Files:** Create `htsim/sim/datacenter/prism_eval/expB_oversub_asym/make_figs.py`, `.../repro.sh`.

- [ ] **Step 1: Create `make_figs.py`**

```python
#!/usr/bin/env python3
"""expB asymmetric-oversub figures -- thin wrapper over common/perf_figs.py. Renders
figBa_4os_main + figBa_8os_main (goodput / avg-FCT / P99-FCT vs #failed, 4 arms) + figBa_mech
(mechanism at 4:1, failed=8) from ./data into ./figs.
  python3 make_figs.py            # render
  python3 make_figs.py --selftest # aggregation self-check (shared perf_figs math)
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import perf_figs  # noqa: E402

DATA = os.path.join(HERE, "data"); FIGS = os.path.join(HERE, "figs")
BASELINES = [("ops", "OPS+NSCC", "ops"), ("reps", "REPS+NSCC", "reps"),
             ("strack", "STrack", "strack"), ("prism", "Prism", "prism")]
SEEDS = [13, 14, 15, 16, 17]
# Valid #failed per oversub ratio. Oversub reduces agg->core links, so a requested failed count
# can exceed available links (clamped). Task 1's pre-check drops any clamped value from these lists.
FAILED_4OS = [0, 2, 4, 8]
FAILED_8OS = [0, 2, 4, 8]

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        perf_figs.selftest()
    else:
        os.makedirs(FIGS, exist_ok=True)
        perf_figs.render_main_perf(DATA, FIGS, "expBa4os", BASELINES, FAILED_4OS, SEEDS,
                                   "figBa_4os_main", "# failed core links (-failed) @ 4:1 oversub, delay-driven")
        perf_figs.render_main_perf(DATA, FIGS, "expBa8os", BASELINES, FAILED_8OS, SEEDS,
                                   "figBa_8os_main", "# failed core links (-failed) @ 8:1 oversub, delay-driven")
        perf_figs.render_mechanism(DATA, FIGS, "expBa4os", "figBa_mech", 8, mech_label="4:1 oversub, failed=8")
```

- [ ] **Step 2: Create `repro.sh`**

```bash
#!/bin/bash
# expB asymmetric oversubscription: does PRISM's delay-driven asymmetric win extend to an
# oversubscribed core? Sweeps #failed x 4 arms at fixed oversub {4:1, 8:1}, delay-driven, 2MB
# many2many (same workload as expA/expB). Orthogonal asymmetry axis on top of the committed
# symmetric expB_oversub/. No controller change.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../common" && pwd)"
DC="$(cd "$HERE/../.." && pwd)"
REL="prism_eval/expB_oversub_asym"
cd "$DC"
[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first"; exit 1; }
mkdir -p "$REL/data"
SEEDS="13 14 15 16 17"; DD="-disable_trim"; ENDV="${EXP_END:-8}"
FAILED_4OS="0 2 4 8"; FAILED_8OS="0 2 4 8"
declare -A TOPO=( [4os]=fat_tree_128_4os.topo [8os]=fat_tree_128_8os.topo )

echo "== selftest =="
python3 "$HERE/make_figs.py" --selftest
( cd "$COMMON/tests" && python3 test_metrics.py >/dev/null && echo "ok common metrics selftest" )

echo "== workload (many2many 64->16 pod0, 2MB) =="
python3 "$COMMON/gen/many2many.py" "$REL/data/m2m.cm" 64 16 pairs 2000000 128 16
CM="$REL/data/m2m.cm"; OUT="$REL/data"

echo "== failed-cap report: actual degraded-link count at failed=8 per topo =="
for R in 4os 8os; do
  PATHS=8 END_MS=1 EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" nscc reps 8 "${TOPO[$R]}" 13 "$CM" flow "precheck_${R}_f8" "$OUT" >/dev/null 2>&1 || true
  n=$(grep -c 'Failure:' "$OUT/precheck_${R}_f8.stdout" 2>/dev/null || echo 0)
  echo "  $R: failed=8 degraded $n core links ($([ "${n:-0}" -ge 8 ] && echo 'OK, keep 8' || echo "CAPPED at $n -> drop 8 from FAILED_$R here and in make_figs.py"))"
done

echo "== main sweep: {4os,8os} x failed x 4 arms x 5 seeds =="
for R in 4os 8os; do
  if [ "$R" = 4os ]; then FS="$FAILED_4OS"; else FS="$FAILED_8OS"; fi
  T="${TOPO[$R]}"
  for f in $FS; do for s in $SEEDS; do
    PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" nscc oblivious "$f" "$T" "$s" "$CM" flow,sink "expBa${R}_ops_f${f}_s${s}" "$OUT"
    PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" nscc reps      "$f" "$T" "$s" "$CM" flow,sink "expBa${R}_reps_f${f}_s${s}" "$OUT"
    PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_EPOCH="$OUT/expBa${R}_prism_f${f}_s${s}.epoch.csv" \
      bash "$COMMON/run_lib.sh" prism reps "$f" "$T" "$s" "$CM" flow,sink "expBa${R}_prism_f${f}_s${s}" "$OUT"
    PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" strack reps   "$f" "$T" "$s" "$CM" flow,sink "expBa${R}_strack_f${f}_s${s}" "$OUT"
  done; done
done

echo "== mechanism: 4:1, failed=8, seed=13, all 4 arms with PRISM_PATHRTT =="
T="${TOPO[4os]}"
PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_PATHRTT="$OUT/expBa4os_ops_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" nscc oblivious 8 "$T" 13 "$CM" flow,sink expBa4os_ops_mech "$OUT"
PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_PATHRTT="$OUT/expBa4os_reps_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" nscc reps 8 "$T" 13 "$CM" flow,sink expBa4os_reps_mech "$OUT"
PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_EPOCH="$OUT/expBa4os_prism_mech.epoch.csv" PRISM_PATHRTT="$OUT/expBa4os_prism_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" prism reps 8 "$T" 13 "$CM" flow,sink expBa4os_prism_mech "$OUT"
PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_PATHRTT="$OUT/expBa4os_strack_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" strack reps 8 "$T" 13 "$CM" flow,sink expBa4os_strack_mech "$OUT"

echo "== render figBa_4os_main + figBa_8os_main + figBa_mech =="
python3 "$HERE/make_figs.py"
echo "== done: figs/figBa_{4os_main,8os_main,mech}.{png,pdf} =="
```

- [ ] **Step 3: Make repro.sh executable**

Run: `chmod +x htsim/sim/datacenter/prism_eval/expB_oversub_asym/repro.sh`

- [ ] **Step 4: Analysis selftest**

Run: `cd htsim/sim/datacenter/prism_eval/expB_oversub_asym && python3 make_figs.py --selftest`
Expected: `ok perf_figs aggregation selftest`.

- [ ] **Step 5: failed-cap pre-check + wiring smoke (run from DC)**

Determine the real degraded-link count at failed=8 on each topo (so the sweep/figures use valid failed values) AND confirm one run produces output:

```bash
cd /home/leo/htsim/htsim/sim/datacenter
python3 prism_eval/common/gen/many2many.py /tmp/bxa.cm 64 16 pairs 2000000 128 16
for R in 4os 8os; do
  T=fat_tree_128_${R}.topo
  PATHS=8 END_MS=2 EXTRA_ARGS="-disable_trim" bash prism_eval/common/run_lib.sh nscc reps 8 "$T" 13 /tmp/bxa.cm flow,sink "bxa_${R}_f8" /tmp/bxa_out >/dev/null 2>&1
  n=$(grep -c 'Failure:' /tmp/bxa_out/bxa_${R}_f8.stdout 2>/dev/null || echo 0)
  lines=$(grep -c FLOW_EVENT /tmp/bxa_out/bxa_${R}_f8.flow.txt 2>/dev/null || echo 0)
  echo "$R: failed=8 -> $n degraded links, $lines FLOW_EVENT lines"
done
rm -rf /tmp/bxa_out /tmp/bxa.cm
```

Expected: each topo runs (non-empty FLOW_EVENT) and prints a degraded-link count `n`.
**Decision:** for each topo, if `n < 8`, EDIT both `FAILED_${R}` in `repro.sh` and `FAILED_${R^}OS` in `make_figs.py` to drop 8 (and any other swept value `> n`), keeping only valid `{0,2,4,...} ≤ n`. Record the cap for the README. If `n ≥ 8`, keep `{0,2,4,8}`. If a topo errors entirely, report BLOCKED.

- [ ] **Step 6: Do NOT commit.**

---

## Task 2: Run the sweep, verify completion, render, extract the verdict

**Files:** Produces `.../expB_oversub_asym/data/*` (gitignored) + `.../figs/figBa_{4os_main,8os_main,mech}.{png,pdf}`.

- [ ] **Step 1: Run the full repro** (with any failed-cap edits from Task 1)

Run: `cd htsim/sim/datacenter/prism_eval/expB_oversub_asym && bash repro.sh 2>&1 | tee /tmp/bxa_repro.log`
(2 ratios × ≤4 failed × 4 arms × 5 seeds + 4 mechanism = up to 164 sims; may run in background.)
Expected: ends with `== done: figs/figBa_{4os_main,8os_main,mech}.{png,pdf} ==`. Note the failed-cap report lines.

- [ ] **Step 2: Completion-ratio gate**

In `/tmp/bxa_repro.log`, the `[figBa_4os_main]` / `[figBa_8os_main]` lines print `cr=` per arm per failed. Confirm cr≈1.00 everywhere. If any cell is short (deep no-trim queues + heavy degradation), re-run `EXP_END=12 bash repro.sh` and re-check; record the final `EXP_END`.

- [ ] **Step 3: Capture the per-ratio goodput/FCT lines**

Run: `grep -E '^\[figBa_(4os|8os)_main\]' /tmp/bxa_repro.log`
Record VERBATIM the per-arm `f{failed}:g=..,avgfct=..us,cr=..` lines for both ratios.

- [ ] **Step 4: Compute the pre-registered verdict (per ratio)**

For each oversub ratio, at failed ∈ {4, 8} (the asymmetry-win region), compute PRISM goodput vs REPS+NSCC and vs STrack as a percentage. Apply the bar: a **win** = PRISM exceeds **both** by **≥ 5%**. State per ratio: WIN (the asymmetric advantage extends to oversub) / TIE-or-NO-WIN (advantage is non-blocking-specific) / MIXED (goodput ties but FCT differs — note direction). Just the arithmetic; no spin.

- [ ] **Step 5: Verify the mechanism figure**

In `/tmp/bxa_repro.log`, confirm `[figBa_mech] floor-MD fraction = ...` printed and the title label is `4:1 oversub, failed=8`. Record the floor-MD fraction + per-ACK cut counts (PRISM vs REPS vs STrack).

- [ ] **Step 6: Confirm figures exist**

Run: `ls -la htsim/sim/datacenter/prism_eval/expB_oversub_asym/figs/`
Expected: `figBa_4os_main.{png,pdf}`, `figBa_8os_main.{png,pdf}`, `figBa_mech.{png,pdf}`.

- [ ] **Step 7: Do NOT commit.**

---

## Task 3: `expB_oversub_asym/README.md` (honest, from actual numbers)

**Files:** Create `htsim/sim/datacenter/prism_eval/expB_oversub_asym/README.md`.

- [ ] **Step 1: Write the README from the Task-2 numbers**

Required sections (no "TBD"/placeholders; fill from `/tmp/bxa_repro.log`):

1. **What this tests** — does PRISM's delay-driven asymmetric win (expA, 1:1) extend to an
   oversubscribed core? Orthogonal asymmetry axis (`-failed`) on top of oversub; cite `../expA_delaydriven/`
   (the 1:1 win) and `../expB_oversub/` (the symmetric-oversub fallback = the failed=0 column). State it
   is an honest empirical test, not a guaranteed win.
2. **Setup** — topos `fat_tree_128_{4,8}os.topo`; x=#failed (the swept set per ratio, noting any cap and
   the actual degraded-link count from the failed-cap report); 4 arms; seeds {13–17}; delay-driven 2 MB
   many2many; `EXP_END` used. One-line repro.
3. **Pre-registered verdict bar** — win = PRISM goodput exceeds BOTH REPS+NSCC and STrack by ≥5% at
   failed≥4, per oversub ratio (mirrors expA).
4. **Results** — per-ratio goodput + avg-FCT tables (the `[figBa_*_main]` numbers), with PRISM-vs-REPS+NSCC
   and PRISM-vs-STrack deltas at failed≥4; reference `figBa_4os_main` / `figBa_8os_main`.
5. **Mechanism** — figBa_mech floor-MD fraction at 4:1/failed=8 + cut counts; what it shows.
6. **Verdict** — per ratio: WIN (extends) / TIE-or-NO-WIN (non-blocking-specific) / MIXED, stated plainly
   from the numbers. Cross-link `../NARRATIVE.md`, `../TARGET_REGIME.md`, `../expA_delaydriven/`,
   `../expB_oversub/`. Note the failed-cap if any.

- [ ] **Step 2: No placeholders**

Run: `grep -nE 'TBD|TODO|FIXME|XXX' htsim/sim/datacenter/prism_eval/expB_oversub_asym/README.md`
Expected: no output.

- [ ] **Step 3: Cross-links resolve**

Run: `ls htsim/sim/datacenter/prism_eval/NARRATIVE.md htsim/sim/datacenter/prism_eval/TARGET_REGIME.md htsim/sim/datacenter/prism_eval/expA_delaydriven/README.md htsim/sim/datacenter/prism_eval/expB_oversub/README.md`
Expected: all exist.

- [ ] **Step 4: Do NOT commit.**

---

## Task 4: Final verification; present milestone (no commit)

**Files:** Modify `/home/leo/.claude/projects/-home-leo-htsim/memory/prism-eval-roadmap.md` (memory; outside git).

- [ ] **Step 1: Update the roadmap memory**

Append an expB-asym block: the question, the per-ratio verdict (WIN/TIE with numbers), the failed-cap (if any), and whether it strengthens or bounds the thesis (does the asymmetric win extend to oversub?). Note commit pending user approval.

- [ ] **Step 2: Final verification**

Run:
```bash
cd htsim/sim/datacenter/prism_eval
python3 expB_oversub_asym/make_figs.py --selftest
ls expB_oversub_asym/figs/
git -C /home/leo/htsim status --porcelain | grep -E 'uec\.(cpp|h)|main_uec' && echo "UNEXPECTED controller change" || echo "ok: no controller change"
```
Expected: selftest passes; 3 figures (×2) present; no controller change.

- [ ] **Step 3: Present the milestone for user approval (DO NOT commit)**

Summarize: the per-ratio win/tie verdict (does the asymmetric advantage extend to oversub?), the mechanism evidence, the failed-cap (if any), and the change set (new group only). The milestone commit (figures `git add -f`; raw data excluded) happens only on explicit approval.

---

## Self-review notes (author)

- **Spec coverage:** §2.1 group → Tasks 1–3 (make_figs/repro/README/figs). §3 design (2 ratios × failed × 4 arms; failed cap; delay-driven; mechanism at 4:1/f8) → repro.sh (Task 1) + Task 1 Step 5 cap-check + Task 2. §4 metrics/figures/verdict → render_main_perf×2 + render_mechanism (make_figs) + Task 2 Step 4 verdict. §5/§6/§7 → conventions + Task 4.
- **Placeholder scan:** none; runtime-determined = the failed cap (resolved in Task 1 Step 5 with a concrete rule) and the sweep numbers (Task 2/3 from the log) and a possible `EXP_END` bump (concrete trigger).
- **Type/name consistency:** tag prefixes `expBa4os` / `expBa8os` consistent between repro.sh (`expBa${R}_<arm>_f${f}_s${s}`) and make_figs (`render_main_perf(..., "expBa4os"/"expBa8os", ...)` reading `{prefix}_{label}_f{f}_s{s}`); mechanism prefix `expBa4os` + `_<arm>_mech` consistent with `render_mechanism`'s expected `{prefix}_reps_mech.pathrtt.csv` etc.; `FAILED_4OS`/`FAILED_8OS` lists mirrored between the two files; `render_main_perf` / `render_mechanism` signatures match the committed `perf_figs.py` (incl. the `mech_label` kwarg).
