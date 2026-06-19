# Backfill Swift / MSwift / MNSCC into expB_oversub_asym + expD_scale1024 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the three delay-CC competitor arms (`swift`→REPS+Swift, `mswift`→REPS+MSwift, `mnscc`→REPS+MNSCC) to the performance + fairness figures of the two generalization groups, matching the headline `expA_delaydriven`.

**Architecture:** Both groups' `make_figs.py` are BASELINES-driven thin wrappers over `common/perf_figs.py`; appending the 3 arms to `BASELINES` makes every performance/fairness panel render them once the data exists. `repro.sh` gains 3 runs per swept cell (REPS spray, only the CC varies) plus CC unit-test gates. No controller, generator, topology, or plot_style change.

**Tech Stack:** htsim_uec simulator (C++), bash repro scripts, Python/matplotlib figure renderers.

## Global Constraints

- Branch `prism-motivation-redesign`, **local only — NEVER push** (origin = spcl/HTSIM public upstream).
- **Do NOT git commit unless the user explicitly authorizes it this session.** The `Commit` steps below are written for completeness; if no authorization, SKIP them and leave changes in the working tree.
- **No controller change.** `htsim/sim/uec.cpp`, `htsim/sim/uec.h`, `htsim/sim/prism_decompose.h` MUST be byte-identical to HEAD when done. PRISM stays O(1).
- All new arms run on **REPS spray** (`LB=reps`); only the CC varies.
- Seeds `{13,14,15,16,17}`; `EXTRA_ARGS="-disable_trim"`; END: D1 & 4:1 = 8 ms, 8:1 = 12 ms.
- **Mechanism panels stay 4-arm** (OPS/REPS+NSCC/STrack/Prism) — do NOT touch any `render_mechanism*` call or the mechanism run blocks.
- `BASELINES` order (both folders), verbatim:
  `("ops","OPS+NSCC","ops"), ("reps","REPS+NSCC","reps"), ("swift","REPS+Swift","swift"), ("mswift","REPS+MSwift","mswift"), ("mnscc","REPS+MNSCC","mnscc"), ("strack","STrack","strack"), ("prism","Prism","prism")`
- Report progress every ~10 min during the long (1024-node) run, with analysis.
- Working dir for sim commands: `/home/leo/htsim/htsim/sim/datacenter`.

---

### Task 1: expB_oversub_asym — code edits (make_figs.py + repro.sh)

**Files:**
- Modify: `htsim/sim/datacenter/prism_eval/expB_oversub_asym/make_figs.py:22-23` (BASELINES)
- Modify: `htsim/sim/datacenter/prism_eval/expB_oversub_asym/repro.sh` (selftest block + main-sweep loop)

**Interfaces:**
- Consumes: `perf_figs.render_main_perf/render_fairness(data,figs,prefix,baselines,failed,seeds,stem,xlabel)` (BASELINES-driven; unchanged).
- Produces: data tags `expBa{8os,4os}_{swift,mswift,mnscc}_f{F}_s{S}.{flow,sink}.txt` consumed by Tasks 3.

- [ ] **Step 1: Replace BASELINES (make_figs.py)**

Replace:
```python
BASELINES = [("ops", "OPS+NSCC", "ops"), ("reps", "REPS+NSCC", "reps"),
             ("strack", "STrack", "strack"), ("prism", "Prism", "prism")]
```
with:
```python
BASELINES = [("ops", "OPS+NSCC", "ops"), ("reps", "REPS+NSCC", "reps"),
             ("swift", "REPS+Swift", "swift"), ("mswift", "REPS+MSwift", "mswift"),
             ("mnscc", "REPS+MNSCC", "mnscc"), ("strack", "STrack", "strack"),
             ("prism", "Prism", "prism")]
```

- [ ] **Step 2: Add CC unit-test gates to repro.sh selftest block**

After the line `( cd "$COMMON/tests" && python3 test_metrics.py >/dev/null && echo "ok common metrics selftest" )` add:
```bash
( cd "$DC/.." && g++ -I. datacenter/prism_eval/common/tests/test_swift_cc.cpp -o /tmp/test_swift_cc && /tmp/test_swift_cc )
( cd "$DC/.." && g++ -I. datacenter/prism_eval/common/tests/test_mnscc_median.cpp -o /tmp/test_mnscc_median && /tmp/test_mnscc_median )
```

- [ ] **Step 3: Add 3 arms to the main-sweep loop in repro.sh**

In the `for R in 8os 4os; do … for f … for s …` loop, immediately AFTER the `strack` run line, add:
```bash
    PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" swift  reps "$f" "$T" "$s" "$CM" flow,sink "expBa${R}_swift_f${f}_s${s}"  "$OUT"
    PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" mswift reps "$f" "$T" "$s" "$CM" flow,sink "expBa${R}_mswift_f${f}_s${s}" "$OUT"
    PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" mnscc  reps "$f" "$T" "$s" "$CM" flow,sink "expBa${R}_mnscc_f${f}_s${s}"  "$OUT"
```
Leave the mechanism block (`figBa_mech`) and its 4 runs UNCHANGED.

- [ ] **Step 4: Verify the figure selftest still passes**

Run: `cd /home/leo/htsim/htsim/sim/datacenter/prism_eval/expB_oversub_asym && python3 make_figs.py --selftest`
Expected: `ok perf_figs aggregation selftest`

- [ ] **Step 5: Verify repro.sh syntax + the 3 new lines are present**

Run: `bash -n prism_eval/expB_oversub_asym/repro.sh && grep -c 'expBa${R}_\(swift\|mswift\|mnscc\)' prism_eval/expB_oversub_asym/repro.sh`
Expected: no syntax error; count `3`.

- [ ] **Step 6: Commit** *(only if commits authorized — else skip, leave in working tree)*

```bash
git add htsim/sim/datacenter/prism_eval/expB_oversub_asym/make_figs.py htsim/sim/datacenter/prism_eval/expB_oversub_asym/repro.sh
git commit -m "prism_eval: wire Swift/MSwift/MNSCC arms into expB_oversub_asym (code only)"
```

---

### Task 2: expD_scale1024 — code edits (make_figs.py + repro.sh)

**Files:**
- Modify: `htsim/sim/datacenter/prism_eval/expD_scale1024/make_figs.py:23-24` (BASELINES)
- Modify: `htsim/sim/datacenter/prism_eval/expD_scale1024/repro.sh` (selftest + D1, D2-4os, D2-8os sweep loops)

**Interfaces:**
- Consumes: `perf_figs.render_main_perf_split` (D1) and `render_main_perf`/`render_fairness` (D2) — BASELINES-driven, unchanged.
- Produces: data tags `expD1_{cc}_f{F}_s{S}`, `expD2_4os_{cc}_f{F}_s{S}`, `expD2_8os_{cc}_f{F}_s{S}` for cc∈{swift,mswift,mnscc}, consumed by Task 4.

- [ ] **Step 1: Replace BASELINES (make_figs.py)** — identical 7-arm list as Task 1 Step 1 (the Global Constraints `BASELINES` block). Replace the existing 4-arm list at lines 23-24.

- [ ] **Step 2: Add CC unit-test gates to repro.sh selftest block**

After the existing `… test_strack_cc.cpp … && /tmp/test_strack_cc )` line add:
```bash
( cd "$DC/.." && g++ -I. datacenter/prism_eval/common/tests/test_swift_cc.cpp -o /tmp/test_swift_cc && /tmp/test_swift_cc )
( cd "$DC/.." && g++ -I. datacenter/prism_eval/common/tests/test_mnscc_median.cpp -o /tmp/test_mnscc_median && /tmp/test_mnscc_median )
```

- [ ] **Step 3: Add 3 arms to the D1 sweep loop**

In `for f in 0 8 16 24 32 48; do for s in $SEEDS; do …`, AFTER the `strack` line, add:
```bash
  run swift  reps      "$f" fat_tree_1024.topo "$END_D1" "$s" "$CM" flow,sink "expD1_swift_f${f}_s${s}"
  run mswift reps      "$f" fat_tree_1024.topo "$END_D1" "$s" "$CM" flow,sink "expD1_mswift_f${f}_s${s}"
  run mnscc  reps      "$f" fat_tree_1024.topo "$END_D1" "$s" "$CM" flow,sink "expD1_mnscc_f${f}_s${s}"
```

- [ ] **Step 4: Add 3 arms to the D2 4:1 sweep loop**

In `for f in 0 1 2 3 4; do for s in $SEEDS; do …` (fat_tree_1024_4os_100g.topo), AFTER the `strack` line, add:
```bash
  run swift  reps      "$f" fat_tree_1024_4os_100g.topo "$END_D1" "$s" "$CM" flow,sink "expD2_4os_swift_f${f}_s${s}"
  run mswift reps      "$f" fat_tree_1024_4os_100g.topo "$END_D1" "$s" "$CM" flow,sink "expD2_4os_mswift_f${f}_s${s}"
  run mnscc  reps      "$f" fat_tree_1024_4os_100g.topo "$END_D1" "$s" "$CM" flow,sink "expD2_4os_mnscc_f${f}_s${s}"
```

- [ ] **Step 5: Add 3 arms to the D2 8:1 sweep loop**

In `for f in 0 1 2 4; do for s in $SEEDS; do …` (fat_tree_1024_8os.topo, `$END_8OS`), AFTER the `strack` line, add:
```bash
  run swift  reps      "$f" fat_tree_1024_8os.topo "$END_8OS" "$s" "$CM" flow,sink "expD2_8os_swift_f${f}_s${s}"
  run mswift reps      "$f" fat_tree_1024_8os.topo "$END_8OS" "$s" "$CM" flow,sink "expD2_8os_mswift_f${f}_s${s}"
  run mnscc  reps      "$f" fat_tree_1024_8os.topo "$END_8OS" "$s" "$CM" flow,sink "expD2_8os_mnscc_f${f}_s${s}"
```
Leave both mechanism blocks (`figD1_mech`, `figD2_mech`) and their 4 runs UNCHANGED.

- [ ] **Step 6: Verify selftest + syntax**

Run: `cd /home/leo/htsim/htsim/sim/datacenter/prism_eval/expD_scale1024 && python3 make_figs.py --selftest && cd /home/leo/htsim/htsim/sim/datacenter && bash -n prism_eval/expD_scale1024/repro.sh && grep -c 'run \(swift\|mswift\|mnscc\) ' prism_eval/expD_scale1024/repro.sh`
Expected: `ok perf_figs aggregation selftest`; no syntax error; count `9` (3 arms × 3 loops).

- [ ] **Step 7: Commit** *(only if authorized — else skip)*

```bash
git add htsim/sim/datacenter/prism_eval/expD_scale1024/make_figs.py htsim/sim/datacenter/prism_eval/expD_scale1024/repro.sh
git commit -m "prism_eval: wire Swift/MSwift/MNSCC arms into expD_scale1024 (code only)"
```

---

### Task 3: expB_oversub_asym — generate data + render + README

**Files:**
- Create (data, gitignored): `htsim/sim/datacenter/prism_eval/expB_oversub_asym/data/expBa*_{swift,mswift,mnscc}_*.{flow,sink,stdout}`
- Modify: `htsim/sim/datacenter/prism_eval/expB_oversub_asym/README.md`
- Regenerate (figs): `figBa_8os_main`, `figBa_4os_main`, `figBa_4os_fairness` (`.png`+`.pdf`)

**Interfaces:**
- Consumes: Task 1's BASELINES + repro.sh edits.

- [ ] **Step 1: Build guard + binary present**

Run: `cd /home/leo/htsim/htsim/sim/build && make htsim_uec >/dev/null 2>&1; ls -x /home/leo/htsim/htsim/sim/datacenter/htsim_uec`
Expected: path printed (binary exists).

- [ ] **Step 2: Run ONLY the 3 new arms incrementally (existing 4-arm data is kept)**

```bash
cd /home/leo/htsim/htsim/sim/datacenter
COMMON=prism_eval/common; OUT=prism_eval/expB_oversub_asym/data; CM=$OUT/m2m.cm
python3 $COMMON/gen/many2many.py $CM 64 16 pairs 2000000 128 16   # deterministic; ensures CM present
declare -A TOPO=( [4os]=fat_tree_128_4os.topo [8os]=fat_tree_128_8os.topo )
for R in 8os 4os; do
  if [ "$R" = 8os ]; then FS="0 2 4 8"; else FS="0 4 8 12"; fi
  T=${TOPO[$R]}
  for f in $FS; do for s in 13 14 15 16 17; do for cc in swift mswift mnscc; do
    PATHS=8 END_MS=8 EXTRA_ARGS=-disable_trim bash $COMMON/run_lib.sh $cc reps $f $T $s $CM flow,sink "expBa${R}_${cc}_f${f}_s${s}" $OUT
  done; done; done
done
```
Expected: 120 `[run_lib] done …` lines. (Equivalent to `bash repro.sh`, which reproduces all 7 from scratch.)

- [ ] **Step 3: Assert data coverage (3 arms × 8 cells × 5 seeds = 120 sink files)**

Run: `ls prism_eval/expB_oversub_asym/data/expBa*_{swift,mswift,mnscc}_f*_s*.sink.txt | wc -l`
Expected: `120`.

- [ ] **Step 4: Re-render + capture numbers**

Run: `cd prism_eval/expB_oversub_asym && python3 make_figs.py 2>&1 | tee /tmp/expBa_render.txt`
Expected: per-arm lines for all 7 arms incl. `REPS+Swift`, `REPS+MSwift`, `REPS+MNSCC` for both `[figBa_8os_main]` and `[figBa_4os_main]`; no traceback.

- [ ] **Step 5: Assert mechanism figure unchanged (4-arm story intact)**

Run: `git diff --stat -- prism_eval/expB_oversub_asym/figs/figBa_mech.pdf`
Expected: empty (figBa_mech not regenerated/changed). If non-empty, investigate — the mechanism call must not have been touched.

- [ ] **Step 6: Verify legend visually**

Read `prism_eval/expB_oversub_asym/figs/figBa_4os_main.pdf` (page 1). Confirm 7 legend entries in order OPS+NSCC, REPS+NSCC, REPS+Swift, REPS+MSwift, REPS+MNSCC, STrack, Prism.

- [ ] **Step 7: Update README.md with measured 7-arm numbers**

Extend the results table(s) to include REPS+Swift/REPS+MSwift/REPS+MNSCC, numbers copied verbatim from `/tmp/expBa_render.txt` (goodput, avg-FCT, p99, cr per failed). State honestly per cell whether each new arm beats/ties/loses PRISM. Keep the "requested -failed vs actual degraded core links" caveat.

- [ ] **Step 8: Commit** *(only if authorized — else skip)*

```bash
git add -f prism_eval/expB_oversub_asym/figs/figBa_8os_main.* prism_eval/expB_oversub_asym/figs/figBa_4os_main.* prism_eval/expB_oversub_asym/figs/figBa_4os_fairness.*
git add prism_eval/expB_oversub_asym/README.md
git commit -m "prism_eval: expB_oversub_asym 7-arm figures + README (Swift/MSwift/MNSCC)"
```

---

### Task 4: expD_scale1024 — generate data + render + README (LONG, 1024-node)

**Files:**
- Create (data, gitignored): `…/expD_scale1024/data/expD1_*_{swift,mswift,mnscc}_*`, `…/expD2_4os_*`, `…/expD2_8os_*`
- Modify: `htsim/sim/datacenter/prism_eval/expD_scale1024/README.md`
- Regenerate (figs): `figD1_{goodput,avg_fct,p99_fct}`, `figD1_fairness`, `figD2_4os_main`, `figD2_8os_main`, `figD2_4os_fairness`

**Interfaces:**
- Consumes: Task 2's BASELINES + repro.sh edits.

- [ ] **Step 1: Run the 3 new arms incrementally (background; ~20–25 min; report every ~10 min)**

```bash
cd /home/leo/htsim/htsim/sim/datacenter
COMMON=prism_eval/common; OUT=prism_eval/expD_scale1024/data; CM=$OUT/m2m256.cm
python3 $COMMON/gen/many2many.py $CM 256 64 pairs 2000000 1024 64   # deterministic; ensures CM present
# D1 (1:1)
for f in 0 8 16 24 32 48; do for s in 13 14 15 16 17; do for cc in swift mswift mnscc; do
  PATHS=8 NODES=1024 END_MS=8 EXTRA_ARGS=-disable_trim bash $COMMON/run_lib.sh $cc reps $f fat_tree_1024.topo $s $CM flow,sink "expD1_${cc}_f${f}_s${s}" $OUT
done; done; done
# D2 4:1
for f in 0 1 2 3 4; do for s in 13 14 15 16 17; do for cc in swift mswift mnscc; do
  PATHS=8 NODES=1024 END_MS=8 EXTRA_ARGS=-disable_trim bash $COMMON/run_lib.sh $cc reps $f fat_tree_1024_4os_100g.topo $s $CM flow,sink "expD2_4os_${cc}_f${f}_s${s}" $OUT
done; done; done
# D2 8:1 (END=12)
for f in 0 1 2 4; do for s in 13 14 15 16 17; do for cc in swift mswift mnscc; do
  PATHS=8 NODES=1024 END_MS=12 EXTRA_ARGS=-disable_trim bash $COMMON/run_lib.sh $cc reps $f fat_tree_1024_8os.topo $s $CM flow,sink "expD2_8os_${cc}_f${f}_s${s}" $OUT
done; done; done
```
Expected: 225 `[run_lib] done …` lines (D1 90 + 4:1 75 + 8:1 60). MUST be sequential (run_lib writes shared `idmap.txt`).

- [ ] **Step 2: Assert data coverage**

Run: `ls prism_eval/expD_scale1024/data/expD1_{swift,mswift,mnscc}_f*_s*.sink.txt | wc -l; ls prism_eval/expD_scale1024/data/expD2_4os_{swift,mswift,mnscc}_f*_s*.sink.txt | wc -l; ls prism_eval/expD_scale1024/data/expD2_8os_{swift,mswift,mnscc}_f*_s*.sink.txt | wc -l`
Expected: `90`, `75`, `60`.

- [ ] **Step 3: Re-render + capture numbers**

Run: `cd prism_eval/expD_scale1024 && python3 make_figs.py 2>&1 | tee /tmp/expD_render.txt`
Expected: 7-arm lines for `[figD1]`, `[figD2_4os_main]`, `[figD2_8os_main]`; no traceback.

- [ ] **Step 4: Assert mechanism figures unchanged**

Run: `git diff --stat -- prism_eval/expD_scale1024/figs/figD1_mech_cwnd.pdf prism_eval/expD_scale1024/figs/figD1_mech_signal.pdf prism_eval/expD_scale1024/figs/figD2_mech.pdf`
Expected: empty.

- [ ] **Step 5: Verify legend visually**

Read `prism_eval/expD_scale1024/figs/figD1_goodput.pdf` (page 1). Confirm 7 entries in the §Global-Constraints order.

- [ ] **Step 6: Update README.md** with measured 7-arm numbers from `/tmp/expD_render.txt`; honest per-cell win/tie/loss; flag 8:1 cells where cr<1 (FCT confounded — goodput+cr only).

- [ ] **Step 7: Commit** *(only if authorized — else skip)*

```bash
git add -f prism_eval/expD_scale1024/figs/figD1_goodput.* prism_eval/expD_scale1024/figs/figD1_avg_fct.* prism_eval/expD_scale1024/figs/figD1_p99_fct.* prism_eval/expD_scale1024/figs/figD1_fairness.* prism_eval/expD_scale1024/figs/figD2_4os_main.* prism_eval/expD_scale1024/figs/figD2_8os_main.* prism_eval/expD_scale1024/figs/figD2_4os_fairness.*
git add prism_eval/expD_scale1024/README.md
git commit -m "prism_eval: expD_scale1024 7-arm figures + README (Swift/MSwift/MNSCC)"
```

---

### Task 5: NARRATIVE Map update + whole-branch verification

**Files:**
- Modify: `htsim/sim/datacenter/prism_eval/NARRATIVE.md` (Map rows)

- [ ] **Step 1: Broaden the Map evidence rows**

In the "Eval (vs median CC)", "Eval (vs Swift)", "Eval (vs MSwift)" rows, change the artifact column from "expA_delaydriven only" to also cite `expB_oversub_asym (4:1)` + `expD_scale1024`, with wording driven by the measured result from Tasks 3-4 (no presupposed outcome — if a new arm ties/wins at some scale cell, say so).

- [ ] **Step 2: Verify the PRISM controller is byte-identical to HEAD**

Run: `cd /home/leo/htsim && git diff --stat HEAD -- htsim/sim/uec.cpp htsim/sim/uec.h htsim/sim/prism_decompose.h`
Expected: empty (no controller change).

- [ ] **Step 3: Re-run both selftests as a final gate**

Run: `cd /home/leo/htsim/htsim/sim/datacenter && python3 prism_eval/expB_oversub_asym/make_figs.py --selftest && python3 prism_eval/expD_scale1024/make_figs.py --selftest`
Expected: two `ok perf_figs aggregation selftest`.

- [ ] **Step 4: Final whole-branch review** (subagent-driven flow: dispatch the final reviewer over the task range; address Critical/Important before declaring done).

- [ ] **Step 5: Commit** *(only if authorized — else skip)*

```bash
git add htsim/sim/datacenter/prism_eval/NARRATIVE.md
git commit -m "prism_eval: NARRATIVE Map — generalization evidence for Swift/MSwift/MNSCC"
```

---

## Self-Review

**Spec coverage:** §3 scope (perf+fairness yes, mech no) → Tasks 1-4 edit only BASELINES + sweep loops, mechanism untouched (Task 3 Step 5, Task 4 Step 4 assert this). §4 legend order → Global Constraints + Task 1/2 Step 1 + visual checks. §5 file changes → Tasks 1-2. §6 reproducibility (selftests, incremental run, canonical repro) → Task 1 Step 2 / Task 2 Step 2 / Task 3-4 run blocks. §7 docs → Task 3 Step 7, Task 4 Step 6, Task 5 Step 1. §8 runtime → Task 4 framed as long/background. §10 acceptance: AC1 selftest+render (T1.4,T2.6,T3.4,T4.3,T5.3); AC2 mech unchanged (T3.5,T4.4); AC3 coverage (T3.3,T4.2); AC4 README numbers (T3.7,T4.6); AC5 controller unchanged (T5.2). All covered.

**Placeholder scan:** No TBD/TODO; every code/command step shows exact content. README-text steps reference the captured `/tmp/*_render.txt` as the data source (not a placeholder — the numbers are produced at run time and must be copied verbatim).

**Type/name consistency:** Tag schemes `expBa{R}_{cc}_f{f}_s{s}` and `expD{1,2_4os,2_8os}_{cc}_f{f}_s{s}` are identical between the repro.sh edits (Tasks 1-2) and the incremental run blocks (Tasks 3-4) and the coverage asserts. `run_lib.sh` positional args (CC LB FAILED TOPO SEED CM LOGSPEC TAG OUTDIR) match every invocation. BASELINES block identical across both make_figs.py.
