# expE_permutation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the `expE_permutation/` experiment group (repro.sh + make_figs.py + README) that runs permutation traffic × failed-links at 128 and 1024 nodes and renders goodput/avg-FCT/p99-FCT figures.

**Architecture:** A new self-contained experiment group mirroring `expA_delaydriven`/`expD_scale1024`: `repro.sh` generates per-seed permutation `.cm` via the committed `common/gen/permutation.py` and drives the sweep through `common/run_lib.sh`; `make_figs.py` is a thin wrapper over `common/perf_figs.py::render_main_perf_split`. No controller change; no shared-code change.

**Tech Stack:** bash repro scripts, the htsim/UEC `htsim_uec` binary, Python figure rendering (`perf_figs.py`).

## Global Constraints

- **No controller change; no shared-code change.** Reuses `permutation.py`, `run_lib.sh`, `perf_figs.py`, `metrics.py`, `plot_style.py` unchanged. Only the 3 new files under `expE_permutation/` are added.
- **Two scales, mirror expA/expD:** 128 → `fat_tree_128_1os.topo`, FAILED_128=`{0,2,4,6,8,10,12}`; 1024 → `fat_tree_1024.topo`, FAILED_1024=`{0,8,16,24,32,40,48}`. NODES=1024 for the 1024 runs.
- **7 arms (CC,LB):** ops=(nscc,oblivious), reps=(nscc,reps), strack=(strack,reps), mnscc=(mnscc,reps), swift=(swift,reps), mswift=(mswift,reps), prism=(prism,reps). PRISM run carries `PRISM_EPOCH`.
- **Tags:** `expEp128_{arm}_f{failed}_s{seed}` and `expEp1024_{arm}_f{failed}_s{seed}` (so `perf_figs.aggregate` resolves `.flow.txt`).
- **Workload:** `permutation.py <out.cm> 1.0 2000000 <nodes> <seed>` — per-seed (different derangement per seed), full permutation, 2 MB/flow.
- **Regime:** `-disable_trim`, END=8 ms (override `EXP_END` if a cell is completion-stressed), PATHS=8, seeds {13,14,15,16,17}. **flow-only logging** (logspec `flow`). 1024 runs **sequential** (shared `idmap.txt`).
- **Figures:** `figE_p128_{goodput,avg_fct,p99_fct}` + `figE_p1024_{...}` via `render_main_perf_split(..., goodput_tbps=True)`; goodput Tbps, FCT ms. **No fairness, no mechanism panel.**
- **Reproducible:** data gitignored by the existing `prism_eval/.gitignore` (`*.txt`,`*.cm`,`*.csv`,…); figures `git add -f`; selftests gate `repro.sh`.
- **No git commit unless the user explicitly asks (per-task local commits ARE authorized for this subagent-driven run); never push.**
- **Working dir for git:** `/home/leo/htsim`. The `htsim_uec` binary is at `htsim/sim/datacenter/htsim_uec` (run_lib cd's there).

---

### Task 1: create expE_permutation group (repro.sh + make_figs.py + README) + smoke

**Files:**
- Create: `htsim/sim/datacenter/prism_eval/expE_permutation/repro.sh`
- Create: `htsim/sim/datacenter/prism_eval/expE_permutation/make_figs.py`
- Create: `htsim/sim/datacenter/prism_eval/expE_permutation/README.md`

**Interfaces:**
- Consumes: `common/gen/permutation.py` (`permutation.py <out> <active_frac> <size> <nodes> <seed>`); `common/run_lib.sh` (`run_lib.sh CC LB FAILED TOPO SEED CM LOGSPEC TAG OUTDIR`, env `PATHS/NODES/END_MS/EXTRA_ARGS/PRISM_EPOCH`); `perf_figs.render_main_perf_split(data_dir, figs_dir, tag_prefix, baselines, failed, seeds, stem_prefix, xlabel, token="f", goodput_tbps=False)`; `perf_figs.selftest()`.
- Produces: the experiment group; figures `figE_p128_*` / `figE_p1024_*` (rendered by the controller after the full sweep).

- [ ] **Step 1: Create `make_figs.py`**

Create `htsim/sim/datacenter/prism_eval/expE_permutation/make_figs.py`:
```python
#!/usr/bin/env python3
"""expE_permutation figures -- thin wrapper over common/perf_figs.py. Renders two performance
triplets from ./data into ./figs: figE_p128_{goodput,avg_fct,p99_fct} (128-node) and
figE_p1024_{...} (1024-node). Permutation traffic x failed-links, delay-driven.
  python3 make_figs.py            # render
  python3 make_figs.py --selftest # aggregation self-check (shared perf_figs math)
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import perf_figs  # noqa: E402

DATA = os.path.join(HERE, "data"); FIGS = os.path.join(HERE, "figs")
BASELINES = [("ops", "OPS+NSCC", "ops"), ("reps", "REPS+NSCC", "reps"),
             ("swift", "REPS+Swift", "swift"), ("mswift", "REPS+MSwift", "mswift"),
             ("mnscc", "REPS+MNSCC", "mnscc"), ("strack", "STrack", "strack"),
             ("prism", "Prism", "prism")]
SEEDS = [13, 14, 15, 16, 17]
FAILED_128 = [0, 2, 4, 6, 8, 10, 12]
FAILED_1024 = [0, 8, 16, 24, 32, 40, 48]
XLABEL = "Number of failed links"

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        perf_figs.selftest()
    else:
        os.makedirs(FIGS, exist_ok=True)
        perf_figs.render_main_perf_split(DATA, FIGS, "expEp128", BASELINES, FAILED_128, SEEDS,
                                         "figE_p128", XLABEL, goodput_tbps=True)
        perf_figs.render_main_perf_split(DATA, FIGS, "expEp1024", BASELINES, FAILED_1024, SEEDS,
                                         "figE_p1024", XLABEL, goodput_tbps=True)
```

- [ ] **Step 2: Create `repro.sh`**

Create `htsim/sim/datacenter/prism_eval/expE_permutation/repro.sh`:
```bash
#!/bin/bash
# expE_permutation: permutation traffic x failed-links. Tests whether PRISM's delay-driven
# asymmetric-fabric advantage (shown on incast-style many2many in expA/expD) generalizes to a
# uniform random permutation (the STrack/MSwift LB benchmark; no incast, no receiver oversub).
# Two scales: P1=128 (fat_tree_128_1os), P2=1024 (fat_tree_1024). delay-driven, flow-only logging.
#   bash repro.sh            # full sweep + render
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
COMMON="$(cd "$HERE/../common" && pwd)"
DC="$(cd "$HERE/../.." && pwd)"
REL="prism_eval/expE_permutation"
cd "$DC"
[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first"; exit 1; }
mkdir -p "$REL/data"
SEEDS="13 14 15 16 17"
DD="-disable_trim"
ENDV="${EXP_END:-8}"
OUT="$REL/data"
FAILED_128="0 2 4 6 8 10 12"
FAILED_1024="0 8 16 24 32 40 48"
ARMS_CC=(nscc nscc prism strack mnscc swift mswift)
ARMS_LB=(oblivious reps reps reps reps reps reps)
ARMS_TAG=(ops reps prism strack mnscc swift mswift)

echo "== self-test analysis =="
python3 "$HERE/make_figs.py" --selftest
( cd "$COMMON/tests" && python3 test_metrics.py >/dev/null && echo "ok common metrics selftest" )
( cd "$DC/.." && g++ -I. datacenter/prism_eval/common/tests/test_strack_cc.cpp -o /tmp/test_strack_cc && /tmp/test_strack_cc )
( cd "$DC/.." && g++ -I. datacenter/prism_eval/common/tests/test_mnscc_median.cpp -o /tmp/test_mnscc_median && /tmp/test_mnscc_median )
( cd "$DC/.." && g++ -I. datacenter/prism_eval/common/tests/test_swift_cc.cpp -o /tmp/test_swift_cc && /tmp/test_swift_cc )

run_arm() { # scale_tag nodes topo failed seed cm
  local pfx="$1" nodes="$2" topo="$3" f="$4" s="$5" cm="$6" i tag epoch
  for i in "${!ARMS_TAG[@]}"; do
    tag="${pfx}_${ARMS_TAG[$i]}_f${f}_s${s}"
    epoch=""
    [ "${ARMS_TAG[$i]}" = prism ] && epoch="PRISM_EPOCH=$OUT/${tag}.epoch.csv"
    env $epoch PATHS=8 NODES="$nodes" END_MS="$ENDV" EXTRA_ARGS="$DD" \
      bash "$COMMON/run_lib.sh" "${ARMS_CC[$i]}" "${ARMS_LB[$i]}" "$f" "$topo" "$s" "$cm" flow "$tag" "$OUT"
  done
}

echo "== P1: 128-node permutation x failed{$FAILED_128} x 7 arms x 5 seeds =="
for s in $SEEDS; do python3 "$COMMON/gen/permutation.py" "$OUT/perm128_s${s}.cm" 1.0 2000000 128 "$s"; done
for f in $FAILED_128; do for s in $SEEDS; do
  run_arm expEp128 128 fat_tree_128_1os.topo "$f" "$s" "$OUT/perm128_s${s}.cm"
done; done

echo "== P2: 1024-node permutation x failed{$FAILED_1024} x 7 arms x 5 seeds (sequential; shared idmap) =="
for s in $SEEDS; do python3 "$COMMON/gen/permutation.py" "$OUT/perm1024_s${s}.cm" 1.0 2000000 1024 "$s"; done
for f in $FAILED_1024; do for s in $SEEDS; do
  run_arm expEp1024 1024 fat_tree_1024.topo "$f" "$s" "$OUT/perm1024_s${s}.cm"
done; done

echo "== render figE_p128_* + figE_p1024_* =="
python3 "$HERE/make_figs.py"
echo "== done: figs/figE_p128_*.{png,pdf} figs/figE_p1024_*.{png,pdf} =="
```
Then make it executable:
```bash
chmod +x /home/leo/htsim/htsim/sim/datacenter/prism_eval/expE_permutation/repro.sh
```

- [ ] **Step 3: Create `README.md`**

Create `htsim/sim/datacenter/prism_eval/expE_permutation/README.md`:
```markdown
# expE_permutation — permutation traffic × failed-links

## 1. What this group tests

Whether PRISM's **delay-driven asymmetric-fabric advantage** — shown on the incast-style many2many
workload in `../expA_delaydriven` (128) and `../expD_scale1024` (1024) — **generalizes to a uniform
random permutation**, the standard load-balancer benchmark used by STrack and MSwift. A permutation
has **no incast and no receiver oversubscription**, so any difference is attributable to the fabric
(failed links), not a fan-in hotspot. This adds the comparability point those papers expect and
addresses the "PRISM only wins on a contrived incast" critique.

**Pre-registered expectation:**
- **f0 (symmetric permutation):** the canonical LB benchmark; spraying arms balance evenly. PRISM is
  expected to be **do-no-harm or carry a small f0-style cost** (the transient-spread under-growth of
  `../expA_f0_diagnosis`) — **not a win**.
- **f>0 (asymmetric):** PRISM's spread-aware decomposition should avoid degraded paths → **modest win
  or at least do-no-harm**. A **tie everywhere is an acceptable result** (do-no-harm on the standard
  benchmark).

## 2. Setup

| Parameter | P1 (128) | P2 (1024) |
|---|---|---|
| Topology | `fat_tree_128_1os.topo` (3-tier, 100G, 1:1) | `fat_tree_1024.topo` (3-tier, 100G, 1:1) |
| Failed-link sweep | {0,2,4,6,8,10,12} | {0,8,16,24,32,40,48} |
| Workload | full random permutation, 2 MB/flow, per-seed | full random permutation, 2 MB/flow, per-seed |
| Regime | delay-driven (`-disable_trim`), END=8 ms, PATHS=8 | same (sequential; shared idmap) |
| Arms | OPS+NSCC, REPS+NSCC, REPS+Swift, REPS+MSwift, REPS+MNSCC, STrack, Prism | same |
| Seeds | 13–17 | 13–17 |

**One-command repro:** `bash repro.sh`. Raw data gitignored; figures committed with `git add -f`.

## 3. Caveat (honest)

`permutation.py` produces a **random derangement** (the standard permutation, as in STrack/MSwift),
not a guaranteed cross-pod matching. On 128 nodes (8 pods) ≈ 1/8 of pairs land **intra-pod** and do
not traverse the core, so failed **core** links bite only the ≈ 7/8 cross-pod flows. This is inherent
to a uniform permutation and is noted, not engineered around.

## 4. Results

Rendered figures: `figs/figE_p128_{goodput,avg_fct,p99_fct}` and `figs/figE_p1024_{...}`. The 5-seed
mean tables are added here after `repro.sh` completes (numbers reported straight whichever way they land).
```

- [ ] **Step 4: Selftest + a 1-cell smoke (do NOT run the full 490-run sweep)**

The controller runs the full sweep; you only prove the pipeline works end-to-end on one cell. From `/home/leo/htsim/htsim/sim/datacenter`:
```bash
# (a) selftests gate
python3 prism_eval/expE_permutation/make_figs.py --selftest
( cd prism_eval/common/tests && python3 test_metrics.py >/dev/null && echo "ok common metrics selftest" )
# (b) permutation workload generates a valid .cm
python3 prism_eval/common/gen/permutation.py prism_eval/expE_permutation/data/perm128_s13.cm 1.0 2000000 128 13
head -2 prism_eval/expE_permutation/data/perm128_s13.cm
# (c) one cell runs and produces a non-empty flow.txt (prism, failed=8, seed 13, 128)
PATHS=8 END_MS=8 EXTRA_ARGS="-disable_trim" PRISM_EPOCH=prism_eval/expE_permutation/data/expEp128_prism_f8_s13.epoch.csv \
  bash prism_eval/common/run_lib.sh prism reps 8 fat_tree_128_1os.topo 13 prism_eval/expE_permutation/data/perm128_s13.cm flow expEp128_prism_f8_s13 prism_eval/expE_permutation/data
wc -l < prism_eval/expE_permutation/data/expEp128_prism_f8_s13.flow.txt
# (d) make_figs.py runs without crashing (figs will be sparse with one cell — that's fine for the smoke)
python3 prism_eval/expE_permutation/make_figs.py 2>&1 | tail -2
```
Expected: selftests print OK; `perm128_s13.cm` first line is `Nodes 128`, second is `Connections 128`; the flow.txt is non-empty (lines > 0); `make_figs.py` completes without a traceback (it renders sparse figures from the single cell). Report the cr/goodput of the smoke cell if printed.

- [ ] **Step 5: Commit the three group files (not the data/figs)**

```bash
cd /home/leo/htsim
git add htsim/sim/datacenter/prism_eval/expE_permutation/repro.sh \
        htsim/sim/datacenter/prism_eval/expE_permutation/make_figs.py \
        htsim/sim/datacenter/prism_eval/expE_permutation/README.md
git status --short -- htsim/sim/datacenter/prism_eval/expE_permutation/   # confirm only the 3 files (data/ gitignored)
git commit -m "$(printf 'prism_eval: expE_permutation group (permutation x failed-links, 128+1024)\n\nNew experiment group mirroring expA/expD with a uniform random permutation\nworkload (reuses common/gen/permutation.py). repro.sh (7 arms x failed x 5\nseeds x 2 scales = 490 runs, flow-only) + make_figs.py (figE_p128/p1024\ngoodput/avg/p99) + README (pre-registered expectation + caveat). No\ncontroller change; shared code untouched.\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```
Expected: the `git status` line shows ONLY the 3 files staged (`repro.sh`, `make_figs.py`, `README.md`) — no `data/` files (gitignored).

---

## Post-implementation (controller-run; gated on the user's review of results)

- Controller runs `bash prism_eval/expE_permutation/repro.sh` (490 runs, long — report progress ~every 10 min; 1024 cells are heavier). Probe completion: if any cell has cr<1, re-run that scale with a larger `EXP_END`.
- Controller renders (repro does this), inspects the 6 figures + per-cell aggregates, fills the README §4 results tables with the honest 5-seed means (PRISM vs REPS+NSCC at f0 and at the f>0 cells), and **surgically commits** the 6 figures (`git add -f figE_p128_*`, `figE_p1024_*`) + the README results edit.
- Report the outcome to the user (does the asymmetric advantage generalize to permutation? f0 do-no-harm?). **Do NOT FF to `main`** pending the user's review.
