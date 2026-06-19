# expD_scale1024 — failed=40 point + 1024-node offered-load figure — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `failed=40` point to expD_scale1024's D1 failed-sweep and a 1024-node open-loop offered-load figure (fixed failed=16), mirroring expA_delaydriven's load study.

**Architecture:** Both additions are on the D1 (1:1 `fat_tree_1024.topo`) fabric and reuse existing machinery (the 7-arm BASELINES renderers + the `poisson_load.py` generator). Task ordering keeps `make_figs.py` always renderable: the failed=40 axis change ships first (Task 1–2); the new `figD3_load` render call is added only in Task 3, after its load data exists, so no intermediate full-render references missing data.

**Tech Stack:** htsim_uec simulator (C++), bash repro scripts, Python/matplotlib renderers (`common/perf_figs.py`), `common/gen/poisson_load.py`.

## Global Constraints

- Branch `prism-motivation-redesign`, **local only — NEVER push** (origin = spcl/HTSIM public upstream).
- **Per-task LOCAL commits are authorized this session.** End every commit message body with `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`. Narrow `git add` (only the files the task changed — the working tree has unrelated untracked files; never `git add -A`).
- **No controller change.** `htsim/sim/uec.cpp`, `uec.h`, `prism_decompose.h` MUST stay byte-identical to HEAD. PRISM stays O(1).
- **7 arms; arm→(CC,LB):** ops=(nscc,oblivious), reps=(nscc,reps), prism=(prism,reps), strack=(strack,reps), swift=(swift,reps), mswift=(mswift,reps), mnscc=(mnscc,reps). All non-OPS on REPS spray; only the CC varies. BASELINES order unchanged (ops, reps, swift, mswift, mnscc, strack, prism).
- Seeds `{13,14,15,16,17}`; `EXTRA_ARGS="-disable_trim"`; both additions on `fat_tree_1024.topo` (1:1).
- **Mechanism figures stay 4-arm and unchanged**: figD1_mech_cwnd, figD1_mech_signal, figD2_mech must NOT be committed/altered. Re-render metadata churn on them is restored (`git checkout --`) and never committed.
- Offered-load: ρ ∈ {10,30,50,70,90}%, fixed `failed=16`, window 8000 µs, END 20 ms, REF_GBPS=6400 (6.4 Tbps = 64 receivers × 100 G). Data tags `expD3load_{arm}_L{rho}_s{seed}`. failed=40 data tags `expD1_{arm}_f40_s{seed}`.
- Working dir for sim commands: `/home/leo/htsim/htsim/sim/datacenter`.
- Report progress every ~10 min during the long (load) run, with analysis.

---

### Task 1: failed=40 — code edits (make_figs.py + repro.sh)

**Files:**
- Modify: `htsim/sim/datacenter/prism_eval/expD_scale1024/make_figs.py` (FAILED_D1)
- Modify: `htsim/sim/datacenter/prism_eval/expD_scale1024/repro.sh` (D1 sweep loop header)

**Interfaces:**
- Produces: data tags `expD1_{arm}_f40_s{seed}` consumed by Task 2; the figD1 renders pick up the new x-tick automatically.

- [ ] **Step 1: Add 40 to FAILED_D1 (make_figs.py)**

Find `FAILED_D1 = [0, 8, 16, 24, 32, 48]` and replace with:
```python
FAILED_D1 = [0, 8, 16, 24, 32, 40, 48]
```

- [ ] **Step 2: Add 40 to the D1 sweep loop (repro.sh)**

Find the D1 sweep loop header line `for f in 0 8 16 24 32 48; do for s in $SEEDS; do` and replace with:
```bash
for f in 0 8 16 24 32 40 48; do for s in $SEEDS; do
```
(Do NOT touch the D2 loops or the mechanism blocks.)

- [ ] **Step 3: Verify selftest + syntax**

Run: `cd /home/leo/htsim/htsim/sim/datacenter && python3 prism_eval/expD_scale1024/make_figs.py --selftest && bash -n prism_eval/expD_scale1024/repro.sh && grep -c 'for f in 0 8 16 24 32 40 48' prism_eval/expD_scale1024/repro.sh`
Expected: `ok perf_figs aggregation selftest`; no syntax error; count `1`.

- [ ] **Step 4: Commit**

```bash
cd /home/leo/htsim
git add htsim/sim/datacenter/prism_eval/expD_scale1024/make_figs.py htsim/sim/datacenter/prism_eval/expD_scale1024/repro.sh
git commit -m "prism_eval: expD D1 failed-sweep adds failed=40 point (code only)" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: failed=40 — generate data + render figD1 + README

**Files:**
- Create (data, gitignored): `…/expD_scale1024/data/expD1_{arm}_f40_s{seed}.{flow,sink,stdout}`
- Modify: `…/expD_scale1024/README.md` (D1 results table — add the f40 row)
- Regenerate (figs): `figD1_{goodput,avg_fct,p99_fct}`, `figD1_fairness`

**Interfaces:**
- Consumes: Task 1's FAILED_D1 + loop edits.

- [ ] **Step 1: Build guard**

Run: `cd /home/leo/htsim/htsim/sim/build && make htsim_uec >/dev/null 2>&1; ls -x /home/leo/htsim/htsim/sim/datacenter/htsim_uec`
Expected: binary path printed.

- [ ] **Step 2: Run all 7 arms at failed=40 (incremental)**

```bash
cd /home/leo/htsim/htsim/sim/datacenter
COMMON=prism_eval/common; OUT=prism_eval/expD_scale1024/data; CM=$OUT/m2m256.cm
python3 $COMMON/gen/many2many.py $CM 256 64 pairs 2000000 1024 64   # deterministic; ensures CM present
run_arm() { PATHS=8 NODES=1024 END_MS=8 EXTRA_ARGS=-disable_trim bash $COMMON/run_lib.sh "$1" "$2" 40 fat_tree_1024.topo "$3" $CM flow,sink "expD1_$4_f40_s$3" $OUT; }
for s in 13 14 15 16 17; do
  run_arm nscc   oblivious "$s" ops
  run_arm nscc   reps      "$s" reps
  run_arm prism  reps      "$s" prism
  run_arm strack reps      "$s" strack
  run_arm swift  reps      "$s" swift
  run_arm mswift reps      "$s" mswift
  run_arm mnscc  reps      "$s" mnscc
done
```
Expected: 35 `[run_lib] done …` lines.

- [ ] **Step 3: Assert coverage (35 sink files)**

Run: `ls prism_eval/expD_scale1024/data/expD1_*_f40_s*.sink.txt | wc -l`
Expected: `35`.

- [ ] **Step 4: Render + capture numbers**

Run: `cd prism_eval/expD_scale1024 && python3 make_figs.py 2>&1 | tee /tmp/expD_f40_render.txt`
Expected: `[figD1]` lines now include an `f40:` cell for all 7 arms; no traceback. (figD3_load does not exist yet — correct.)

- [ ] **Step 5: Restore mechanism-figure churn (keep them 4-arm, uncommitted)**

```bash
cd /home/leo/htsim
git checkout -- htsim/sim/datacenter/prism_eval/expD_scale1024/figs/figD1_mech_cwnd.pdf htsim/sim/datacenter/prism_eval/expD_scale1024/figs/figD1_mech_cwnd.png htsim/sim/datacenter/prism_eval/expD_scale1024/figs/figD1_mech_signal.pdf htsim/sim/datacenter/prism_eval/expD_scale1024/figs/figD1_mech_signal.png htsim/sim/datacenter/prism_eval/expD_scale1024/figs/figD2_mech.pdf htsim/sim/datacenter/prism_eval/expD_scale1024/figs/figD2_mech.png 2>/dev/null; true
git status --short htsim/sim/datacenter/prism_eval/expD_scale1024/figs/ | grep -E 'mech' && echo "WARN mech still dirty" || echo "mech clean"
```
Expected: `mech clean`.

- [ ] **Step 6: Update README D1 table with the f40 row**

Add the failed=40 row to the D1 results table(s), numbers copied verbatim from `/tmp/expD_f40_render.txt` (goodput/avg-FCT/p99/cr per arm at f40). State the f40 result honestly (per-arm vs PRISM); flag cr<1 if any. Match the table's existing structure.

- [ ] **Step 7: Commit**

```bash
cd /home/leo/htsim
git add -f htsim/sim/datacenter/prism_eval/expD_scale1024/figs/figD1_goodput.* htsim/sim/datacenter/prism_eval/expD_scale1024/figs/figD1_avg_fct.* htsim/sim/datacenter/prism_eval/expD_scale1024/figs/figD1_p99_fct.* htsim/sim/datacenter/prism_eval/expD_scale1024/figs/figD1_fairness.*
git add htsim/sim/datacenter/prism_eval/expD_scale1024/README.md
git commit -m "prism_eval: expD D1 figures + README — failed=40 point (7 arms)" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: offered-load figure — repro block + run + render + README (LONG, ~1–1.5 h)

**Files:**
- Modify: `…/expD_scale1024/repro.sh` (new offered-load sweep block + done-line echo)
- Modify: `…/expD_scale1024/make_figs.py` (LOADS/XLABEL_LOAD + figD3_load render call) — **added AFTER the load data exists** (Step 4) so intermediate full-renders never reference missing data
- Create (data, gitignored): `…/data/m2m256_load_L{rho}_s{seed}.cm`, `…/data/expD3load_{arm}_L{rho}_s{seed}.{flow,sink,stdout}`
- Modify: `…/expD_scale1024/README.md` (new offered-load subsection)
- Create (figs): `figD3_load_{goodput,avg_fct,p99_fct}` (.png+.pdf)

**Interfaces:**
- Consumes: the 7-arm BASELINES (already in make_figs.py); `perf_figs.render_main_perf_split(..., token="L")`.

- [ ] **Step 1: Add the offered-load sweep block to repro.sh**

Insert AFTER the D2 mechanism block and BEFORE the `echo "== render figures =="` line:
```bash
echo "== offered-load sweep (Poisson, failed=16, 1:1): 7 arms x rho{10,30,50,70,90}% x 5 seeds =="
LOAD_W_US=8000; LOAD_END=20; REF_GBPS=6400; LOAD_FAILED=16
for rho in 10 30 50 70 90; do
  rhof="$(python3 -c "print($rho/100.0)")"
  for s in $SEEDS; do
    LCM="$OUT/m2m256_load_L${rho}_s${s}.cm"
    python3 "$COMMON/gen/poisson_load.py" "$LCM" 256 64 2000000 1024 64 "$rhof" "$LOAD_W_US" "$REF_GBPS" "$s"
    PATHS=8 NODES=1024 END_MS="$LOAD_END" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" nscc   oblivious "$LOAD_FAILED" fat_tree_1024.topo "$s" "$LCM" flow,sink "expD3load_ops_L${rho}_s${s}"    "$OUT"
    PATHS=8 NODES=1024 END_MS="$LOAD_END" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" nscc   reps      "$LOAD_FAILED" fat_tree_1024.topo "$s" "$LCM" flow,sink "expD3load_reps_L${rho}_s${s}"   "$OUT"
    PATHS=8 NODES=1024 END_MS="$LOAD_END" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" prism  reps      "$LOAD_FAILED" fat_tree_1024.topo "$s" "$LCM" flow,sink "expD3load_prism_L${rho}_s${s}"  "$OUT"
    PATHS=8 NODES=1024 END_MS="$LOAD_END" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" strack reps      "$LOAD_FAILED" fat_tree_1024.topo "$s" "$LCM" flow,sink "expD3load_strack_L${rho}_s${s}" "$OUT"
    PATHS=8 NODES=1024 END_MS="$LOAD_END" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" swift  reps      "$LOAD_FAILED" fat_tree_1024.topo "$s" "$LCM" flow,sink "expD3load_swift_L${rho}_s${s}"  "$OUT"
    PATHS=8 NODES=1024 END_MS="$LOAD_END" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" mswift reps      "$LOAD_FAILED" fat_tree_1024.topo "$s" "$LCM" flow,sink "expD3load_mswift_L${rho}_s${s}" "$OUT"
    PATHS=8 NODES=1024 END_MS="$LOAD_END" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" mnscc  reps      "$LOAD_FAILED" fat_tree_1024.topo "$s" "$LCM" flow,sink "expD3load_mnscc_L${rho}_s${s}"  "$OUT"
  done
done
```
Then update the final `echo "== done: …"` line to also mention `figs/figD3_load_*`.

- [ ] **Step 2: Build guard + run the 175 load sims (incremental, sequential; report every ~10 min)**

```bash
cd /home/leo/htsim/htsim/sim/datacenter
COMMON=prism_eval/common; OUT=prism_eval/expD_scale1024/data
for rho in 10 30 50 70 90; do
  rhof="$(python3 -c "print($rho/100.0)")"
  for s in 13 14 15 16 17; do
    LCM="$OUT/m2m256_load_L${rho}_s${s}.cm"
    python3 $COMMON/gen/poisson_load.py "$LCM" 256 64 2000000 1024 64 "$rhof" 8000 6400 "$s"
    for spec in "nscc oblivious ops" "nscc reps reps" "prism reps prism" "strack reps strack" "swift reps swift" "mswift reps mswift" "mnscc reps mnscc"; do
      set -- $spec
      PATHS=8 NODES=1024 END_MS=20 EXTRA_ARGS=-disable_trim bash $COMMON/run_lib.sh "$1" "$2" 16 fat_tree_1024.topo "$s" "$LCM" flow,sink "expD3load_$3_L${rho}_s${s}" $OUT
    done
  done
done
```
Expected: 175 `[run_lib] done …` lines. Sequential (shared idmap.txt). This is the ~1–1.5 h step.

- [ ] **Step 3: Assert coverage (175 sink files)**

Run: `ls prism_eval/expD_scale1024/data/expD3load_*_L*_s*.sink.txt | wc -l`
Expected: `175`.

- [ ] **Step 4: Add the figD3_load render call to make_figs.py**

Add the two constants near the other D-constants:
```python
LOADS = [10, 30, 50, 70, 90]
XLABEL_LOAD = "offered load (% of receiver-access capacity, 6.4 Tbps; failed=16)"
```
Add this render call at the end of the `else:` render block (after the D2 calls):
```python
        perf_figs.render_main_perf_split(DATA, FIGS, "expD3load", BASELINES, LOADS, SEEDS,
                                         "figD3_load", XLABEL_LOAD, token="L")
```

- [ ] **Step 5: Render everything + capture numbers**

Run: `cd prism_eval/expD_scale1024 && python3 make_figs.py 2>&1 | tee /tmp/expD_load_render.txt`
Expected: `[figD3_load]` per-arm lines for all 7 arms at L10/30/50/70/90 (with cr per cell); plus the existing figD1/figD2 lines; no traceback.

- [ ] **Step 6: Restore mechanism-figure churn (uncommitted)**

```bash
cd /home/leo/htsim
git checkout -- htsim/sim/datacenter/prism_eval/expD_scale1024/figs/figD1_mech_cwnd.pdf htsim/sim/datacenter/prism_eval/expD_scale1024/figs/figD1_mech_cwnd.png htsim/sim/datacenter/prism_eval/expD_scale1024/figs/figD1_mech_signal.pdf htsim/sim/datacenter/prism_eval/expD_scale1024/figs/figD1_mech_signal.png htsim/sim/datacenter/prism_eval/expD_scale1024/figs/figD2_mech.pdf htsim/sim/datacenter/prism_eval/expD_scale1024/figs/figD2_mech.png 2>/dev/null; true
git status --short htsim/sim/datacenter/prism_eval/expD_scale1024/figs/ | grep -E 'mech' && echo "WARN mech dirty" || echo "mech clean"
```
Expected: `mech clean`.

- [ ] **Step 7: Verify figD3_load legend**

Read `prism_eval/expD_scale1024/figs/figD3_load_goodput.pdf` (page 1). Confirm 7 legend entries in BASELINES order (OPS+NSCC, REPS+NSCC, REPS+Swift, REPS+MSwift, REPS+MNSCC, STrack, Prism) and x-axis = offered load.

- [ ] **Step 8: Update README with the offered-load subsection**

Add a new "Offered-load sweep (1:1, failed=16)" subsection: a 7-arm × 5-ρ table with numbers verbatim from `/tmp/expD_load_render.txt` (goodput + cr always; avg-FCT/p99 too but **flag every cr<1 cell and do not use FCT as the headline where cr<1**). State honestly how the win behaves with load. Note REF=6.4 Tbps, window 8 ms, END 20 ms.

- [ ] **Step 9: Commit**

```bash
cd /home/leo/htsim
git add htsim/sim/datacenter/prism_eval/expD_scale1024/repro.sh htsim/sim/datacenter/prism_eval/expD_scale1024/make_figs.py htsim/sim/datacenter/prism_eval/expD_scale1024/README.md
git add -f htsim/sim/datacenter/prism_eval/expD_scale1024/figs/figD3_load_goodput.* htsim/sim/datacenter/prism_eval/expD_scale1024/figs/figD3_load_avg_fct.* htsim/sim/datacenter/prism_eval/expD_scale1024/figs/figD3_load_p99_fct.*
git commit -m "prism_eval: expD 1024-node offered-load figure (figD3_load, failed=16, 7 arms)" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: NARRATIVE note + whole-branch verification

**Files:**
- Modify: `htsim/sim/datacenter/prism_eval/NARRATIVE.md` (Map — load row)

- [ ] **Step 1: Extend the load Map row**

In NARRATIVE.md's Map, the "Eval (win, load)" row currently cites `expA_delaydriven/` (figA3dd_load) only. Add that the offered-load win also reproduces at 1024-node scale, citing `expD_scale1024/` (figD3_load, failed=16), with wording driven by the measured Task-3 result (no presupposition — if some arm ties/wins at a ρ cell, say so; flag the cr<1 confound at high ρ).

- [ ] **Step 2: Verify controller byte-identical**

Run: `cd /home/leo/htsim && git diff --stat HEAD -- htsim/sim/uec.cpp htsim/sim/uec.h htsim/sim/prism_decompose.h`
Expected: empty.

- [ ] **Step 3: Re-run the selftest gate**

Run: `cd /home/leo/htsim/htsim/sim/datacenter && python3 prism_eval/expD_scale1024/make_figs.py --selftest`
Expected: `ok perf_figs aggregation selftest`.

- [ ] **Step 4: Commit**

```bash
cd /home/leo/htsim
git add htsim/sim/datacenter/prism_eval/NARRATIVE.md
git commit -m "prism_eval: NARRATIVE Map — offered-load win reproduces at 1024 scale (figD3_load)" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:** §3 item A (failed=40) → Tasks 1–2. §3 item B (offered-load) → Task 3. §4 make_figs FAILED_D1 + repro D1 loop → Task 1. §5 poisson generator args + repro load block + figD3_load render call → Task 3 Steps 1/4. §6 file changes → all tasks. §7 reproducibility (incremental run, canonical repro) → Task 2 Step 2 / Task 3 Steps 1–2. §8 runtime → Task 3 framed long. §10 acceptance: AC1 selftest+render (T1.3, T2.4, T3.5); AC2 mech unchanged (T2.5, T3.6); AC3 coverage (T2.3=35, T3.3=175); AC4 README/NARRATIVE honest + cr-flag (T2.6, T3.8, T4.1); AC5 controller byte-identical (T4.2). All covered.

**Placeholder scan:** No TBD/TODO; every code/command step is complete. README/NARRATIVE steps cite the captured `/tmp/*_render.txt` as the verbatim number source (produced at run time — not a placeholder).

**Type/name consistency:** Tag schemes `expD1_{arm}_f40_s{seed}` (Task 1 produces / Task 2 asserts) and `expD3load_{arm}_L{rho}_s{seed}` (Task 3 repro block, incremental run, coverage assert, and the render `tag_prefix="expD3load"` + `token="L"` all agree). Arm keys (ops/reps/prism/strack/swift/mswift/mnscc) match the (CC,LB) mapping in every run invocation and the BASELINES keys. `render_main_perf_split(..., "figD3_load", XLABEL_LOAD, token="L")` matches the expA load-figure signature. FAILED_D1 list identical in make_figs.py and the repro D1 loop header.
