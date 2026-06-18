# expA_delaydriven Load-Sweep + ECMP Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an ECMP+NSCC single-path baseline to expA_delaydriven's existing `-failed` sweep, and a new open-loop Poisson "FCT vs offered-load" figure at fixed `-failed 8`.

**Architecture:** Pure-evaluation change (no PRISM/controller code touched, O(1) preserved). Reuse the existing harness (`run_lib.sh`) and the 3-panel renderer (`render_main_perf_split`); add one workload generator (`poisson_load.py`) and a backward-compatible `token` kwarg to the renderer so the load sweep can name its files `_L{rho}_` instead of `_f{failed}_`.

**Tech Stack:** htsim_uec (`main_uec.cpp`), bash harness, Python 3 + matplotlib (Agg). All under `htsim/sim/datacenter/`.

## Global Constraints

- **Working dir (DC):** `/home/leo/htsim/htsim/sim/datacenter`. Folder under test: `prism_eval/expA_delaydriven/`. Shared code: `prism_eval/common/`.
- **Do NOT git commit.** The user commits explicitly (project rule overrides the plan's commit steps). Each task ends *staged + reported* for review; the final task lists the exact `git add -f` commands for the user to run when ready.
- **Do NOT touch PRISM controller code** (`uec.cpp`, `prism_decompose.h`). This is evaluation-only; the O(1) decomposition stays unchanged.
- **`.cm` `start` token is picoseconds** (DE-RISKED 2026-06-18 by probe: `start 1000`→START at 1 ns, `start 1000000000`→1 ms, `start 8000000000`→8 ms with **no uint32 overflow**; the `timeFromUs` grep was a *different*, non-`-tm` code path). Flows must never start at t=0 (the simulator drops the START FLOW_EVENT) → first start clamped to ≥ 1 ps. The generator's human-facing `window_us` arg is converted ×1e6 to ps internally.
- **Regime knob:** every run carries `EXTRA_ARGS="-disable_trim"` (delay-driven, 5×BDP). Topo `fat_tree_128_1os.topo`, `NODES=128`, `PATHS=8`, `MTU=4150` (run_lib defaults). Seeds **{13,14,15,16,17}**.
- **Offered load ρ** is relative to aggregate receiver-access capacity `C = n_recv × 100 Gbps = 1.6 Tbps`; `ref_gbps = 1600`. ρ sweep `{0.1,0.3,0.5,0.7,0.9}`, filename-encoded as percent `{10,30,50,70,90}`.
- **Figures** are gitignored higher up → added with `git add -f`. `data/` stays gitignored (`*.cm/*.txt/*.csv/*.dat/*.stdout/*.idmap`).
- **Existing figures must not regress:** the renderer `token` kwarg defaults to `"f"`, keeping every current expA/expB/expD output byte-identical.

---

### Task 1: De-risk the `.cm` start-time unit

**Files:**
- None committed (investigation only; result recorded in Task 6's README and used as a repro.sh guard in Task 5).

**Interfaces:**
- Produces: the verified fact "`.cm` start = microseconds", which Task 2's generator and Task 5's guard depend on.

- [ ] **Step 1: Write a 2-flow probe `.cm`**

```bash
cd /home/leo/htsim/htsim/sim/datacenter
printf 'Nodes 128\nConnections 2\n80->0 start 1 size 2000000\n81->1 start 1000 size 2000000\n' > /tmp/unit_probe.cm
cat /tmp/unit_probe.cm
```

- [ ] **Step 2: Run it and extract START timestamps**

```bash
cd /home/leo/htsim/htsim/sim/datacenter
PATHS=8 END_MS=4 EXTRA_ARGS="-disable_trim" \
  bash prism_eval/common/run_lib.sh nscc reps 0 fat_tree_128_1os.topo 13 /tmp/unit_probe.cm flow probe /tmp/unit_probe
grep ' START ' /tmp/unit_probe/probe.flow.txt
```

Expected: two START lines. The leading field is simulation time in **seconds**. **RESULT (2026-06-18):** `start 1000` → START at `0.000000001` s (= 1 ns), so `start` is in **picoseconds** (1000 ps = 1 ns). A second probe (`start {1000000, 1000000000, 8000000000}`) gave `{0.000001, 0.001, 0.008}` s — confirming ps AND **no uint32 overflow** at the 8 ms window scale.

- [ ] **Step 3: Confirm the unit**

**Confirmed: `.cm` start = picoseconds, no overflow to ≥ 8 ms.** The generator (Task 2) emits start in ps; its `window_us` arg is converted ×1e6 to ps. The spec/plan were corrected from the earlier µs assumption.

- [ ] **Step 4: Report (no commit)**

Done by the controller; finding recorded in the progress ledger and propagated to Task 2 / Task 5.

---

### Task 2: `poisson_load.py` open-loop workload generator

**Files:**
- Create: `prism_eval/common/gen/poisson_load.py`

**Interfaces:**
- Consumes: verified µs start unit (Task 1).
- Produces: CLI `poisson_load.py <out.cm> <n_send> <n_recv> <size> <nodes> <hpp> <rho> <window_us> <ref_gbps> <seed>` and `build(n_send, n_recv, size, nodes, hpp, rho, window_us, ref_gbps, seed) -> (text:str, conns:list[(start_ps:int, src:int, dst:int)])`. `poisson_load.py --selftest` exits 0 on success. Task 5's repro.sh calls the CLI.

- [ ] **Step 1: Write the generator with an inline selftest**

```python
#!/usr/bin/env python3
"""Open-loop Poisson many-to-many .cm for offered-load sweeps. Senders (hosts OUTSIDE
pod0) send fixed-size flows INTO receivers (first n_recv pod0 hosts), arriving as a
Poisson process over a measurement window [1, window_us]. Each sender keeps its fixed
paired receiver (matches many2many.py 'pairs'), so only the temporal density changes
with load, not the spatial pattern.

Offered load rho is relative to aggregate receiver-access capacity C = n_recv*link_rate.
  lambda = rho * (ref_gbps*1e9) / (size*8)   flows/sec   (ref_gbps in Gbps, size in bytes)
Inter-arrivals ~ Exponential(lambda); start times are PICOSECONDS (the -tm loader interprets
the .cm `start` token as ps -- de-risked 2026-06-18: start 1000 -> 1 ns, 8e9 -> 8 ms, no
overflow). The human-facing `window_us` arg is converted x1e6 to ps. Flows never start at
t=0 (the simulator drops the START FLOW_EVENT), so the first start is clamped to >= 1 ps.

Usage: poisson_load.py <out.cm> <n_send> <n_recv> <size> <nodes> <hpp> <rho> <window_us> <ref_gbps> <seed>
       poisson_load.py --selftest
"""
import sys, random


def build(n_send, n_recv, size, nodes, hpp, rho, window_us, ref_gbps, seed):
    if n_recv < 1 or n_recv > hpp:
        raise ValueError(f"n_recv must be in [1,{hpp}], got {n_recv}")
    if rho <= 0 or ref_gbps <= 0 or size <= 0 or window_us <= 0:
        raise ValueError("rho, ref_gbps, size, window_us must all be > 0")
    senders = [h for h in range(nodes) if h // hpp != 0][:n_send]
    if len(senders) != n_send:
        raise ValueError(f"need {n_send} senders outside pod0, have {len(senders)}")
    receivers = list(range(n_recv))
    rng = random.Random(seed)
    lam_per_ps = rho * (ref_gbps * 1e9) / (size * 8) / 1e12   # flows per picosecond
    window_ps = window_us * 1e6                               # window_us is human-facing; emit ps
    conns = []
    t, i = 0.0, 0
    while True:
        t += rng.expovariate(lam_per_ps)        # inter-arrival, picoseconds
        if t > window_ps:
            break
        s_idx = i % n_send
        conns.append((max(1, int(round(t))), senders[s_idx], receivers[s_idx % n_recv]))
        i += 1
    conns.sort()
    lines = [f"Nodes {nodes}", f"Connections {len(conns)}"]
    lines += [f"{s}->{d} start {st} size {size}" for (st, s, d) in conns]
    return "\n".join(lines) + "\n", conns


def _selftest():
    # lambda = 0.5*1600e9/(2e6*8) = 5e4 flows/s; window 8000us = 8e9 ps -> ~400 flows.
    text, conns = build(64, 16, 2_000_000, 128, 16, 0.5, 8000, 1600, 13)
    n = len(conns)
    assert 320 <= n <= 480, f"flow count {n} outside ~400 +/-20%"
    lines = text.strip().split("\n")
    assert lines[0] == "Nodes 128", lines[0]
    assert lines[1] == f"Connections {n}", lines[1]
    assert len(lines) == n + 2, (len(lines), n)
    starts = [c[0] for c in conns]
    assert starts == sorted(starts), "starts not monotonic"
    assert starts[0] >= 1 and starts[-1] <= 8000 * 1_000_000, (starts[0], starts[-1])  # ps
    for st, s, d in conns:
        assert s // 16 != 0, f"sender {s} is inside pod0"
        assert 0 <= d < 16, f"receiver {d} out of range"
        assert d == ((s_off := senders_idx(s)) % 16), None  # placeholder; replaced below
    # determinism
    text2, _ = build(64, 16, 2_000_000, 128, 16, 0.5, 8000, 1600, 13)
    assert text2 == text, "non-deterministic for fixed seed"
    # rho scaling: doubling rho ~doubles flow count
    _, c_low = build(64, 16, 2_000_000, 128, 16, 0.25, 8000, 1600, 13)
    assert len(c_low) < n, (len(c_low), n)
    print(f"ok poisson_load selftest: {n} flows @rho=0.5, window=8000us (=8e9 ps)")


def main():
    if "--selftest" in sys.argv:
        _selftest()
        return
    a = sys.argv
    out = a[1]
    text, conns = build(int(a[2]), int(a[3]), int(a[4]), int(a[5]), int(a[6]),
                        float(a[7]), float(a[8]), float(a[9]), int(a[10]))
    with open(out, "w") as fh:
        fh.write(text)
    print(f"wrote {out}: {len(conns)} flows, rho={a[7]} window={a[8]}us ref={a[9]}Gbps seed={a[10]}")


if __name__ == "__main__":
    main()
```

NOTE: the line `assert d == ((s_off := senders_idx(s)) % 16) ...` above is a deliberate placeholder to remove in Step 2 — `senders_idx` is not defined. The pairing invariant is already guaranteed by construction (`receivers[s_idx % n_recv]`), so the selftest does not need to re-derive it.

- [ ] **Step 2: Remove the placeholder assertion line**

Delete the line containing `senders_idx` from `_selftest()` (the `for` loop keeps only the two real per-conn asserts: `s // 16 != 0` and `0 <= d < 16`).

- [ ] **Step 3: Run the selftest to verify it passes**

Run: `cd /home/leo/htsim/htsim/sim/datacenter && python3 prism_eval/common/gen/poisson_load.py --selftest`
Expected: `ok poisson_load selftest: <~400> flows @rho=0.5, window=8000us (=8e9 ps)`

- [ ] **Step 4: Eyeball a generated file**

```bash
cd /home/leo/htsim/htsim/sim/datacenter
python3 prism_eval/common/gen/poisson_load.py /tmp/load_probe.cm 64 16 2000000 128 16 0.5 8000 1600 13
head -4 /tmp/load_probe.cm; wc -l /tmp/load_probe.cm
```
Expected: header `Nodes 128` / `Connections N`, then `s->d start <us> size 2000000` lines; line count = N+2; N ≈ 400.

- [ ] **Step 5: Stage and report (no commit)**

```bash
git -C /home/leo/htsim add prism_eval/common/gen/poisson_load.py 2>/dev/null || git -C /home/leo/htsim/htsim/sim/datacenter add prism_eval/common/gen/poisson_load.py
```

---

### Task 3: Backward-compatible `token` kwarg in `perf_figs.py`

**Files:**
- Modify: `prism_eval/common/perf_figs.py` (`aggregate`, `render_main_perf`, `render_main_perf_split`, `render_fairness`, `selftest`)

**Interfaces:**
- Consumes: nothing new.
- Produces: `aggregate(data_dir, tag_prefix, label, failed, seeds, token="f")`, `render_main_perf_split(..., xlabel, token="f")`, `render_main_perf(..., xlabel, token="f")`, `render_fairness(..., fig_stem, xlabel, token="f")`. Task 4 (ECMP) relies on the unchanged default; Task 5 (load) calls with `token="L"`.

- [ ] **Step 1: Extend `selftest()` to cover `token="L"` (write the failing assertion first)**

In `prism_eval/common/perf_figs.py`, inside `selftest()`, immediately before `shutil.rmtree(d)`, add:

```python
    # token="L" (offered-load sweep) names files {prefix}_{label}_L{val}_s{seed}.flow.txt
    for s in seeds:
        with open(os.path.join(d, f"expAload_ops_L50_s{s}.flow.txt"), "w") as fh:
            fh.write("0.000000000 Type FLOW_EVENT SrcID 1 Ev START FlowID 1 Flowsize 2000000\n")
            fh.write("0.002000000 Type FLOW_EVENT SrcID 1 Ev FINISH FlowID 1 Bytes 2000000 Pkts 1\n")
    al = aggregate(d, "expAload", "ops", [50], seeds, token="L")
    assert 50 in al, al
    assert abs(al[50]["avg_fct"][0] - 2000.0) < 1e-6, al[50]   # 2 ms = 2000 us
    assert abs(al[50]["cr"][0] - 1.0) < 1e-9, al[50]
```

- [ ] **Step 2: Run the selftest to verify it fails**

Run: `cd /home/leo/htsim/htsim/sim/datacenter && python3 prism_eval/common/perf_figs.py`
Expected: FAIL with `TypeError: aggregate() got an unexpected keyword argument 'token'`.

- [ ] **Step 3: Add `token` to `aggregate()`**

Change the signature and the filename line:

```python
def aggregate(data_dir, tag_prefix, label, failed, seeds, token="f"):
    """Per-failed aggregates for one baseline: {f: {metric:(mean,std)}}; omit f with no data.
    `token` is the filename sweep prefix ('f' for -failed sweeps, 'L' for offered-load)."""
    out = {}
    for f in failed:
        g, afct, p99, cr = [], [], [], []
        for s in seeds:
            flow = os.path.join(data_dir, f"{tag_prefix}_{label}_{token}{f}_s{s}.flow.txt")
```

- [ ] **Step 4: Thread `token` through the three renderers**

`render_main_perf` — signature and the `aggregate` call:

```python
def render_main_perf(data_dir, figs_dir, tag_prefix, baselines, failed, seeds, fig_stem, xlabel, token="f"):
```
```python
    aggs = {lab: aggregate(data_dir, tag_prefix, lab, failed, seeds, token) for (lab, _d, _c) in baselines}
```

`render_main_perf_split` — signature and the `aggregate` call:

```python
def render_main_perf_split(data_dir, figs_dir, tag_prefix, baselines, failed, seeds, stem_prefix, xlabel, token="f"):
```
```python
    aggs = {lab: aggregate(data_dir, tag_prefix, lab, failed, seeds, token) for (lab, _d, _c) in baselines}
```

`render_fairness` — signature and the `_fair` filename:

```python
def render_fairness(data_dir, figs_dir, tag_prefix, baselines, failed, seeds, fig_stem, xlabel, token="f"):
```
```python
            fp = os.path.join(data_dir, f"{tag_prefix}_{lab}_{token}{f}_s{s}.flow.txt")
```

- [ ] **Step 5: Run the selftest to verify it passes**

Run: `cd /home/leo/htsim/htsim/sim/datacenter && python3 prism_eval/common/perf_figs.py`
Expected: `ok perf_figs aggregation selftest`

- [ ] **Step 6: Regression-check existing experiments' selftests**

Run: `cd /home/leo/htsim/htsim/sim/datacenter && python3 prism_eval/expA_delaydriven/make_figs.py --selftest && python3 prism_eval/expD_scale1024/make_figs.py --selftest`
Expected: both print `ok perf_figs aggregation selftest` (default `token="f"` → no behavior change).

- [ ] **Step 7: Stage and report (no commit)**

```bash
git -C /home/leo/htsim/htsim/sim/datacenter add prism_eval/common/perf_figs.py
```

---

### Task 4: ECMP+NSCC baseline wiring (Deliverable ①)

**Files:**
- Modify: `prism_eval/common/plot_style.py` (add `ecmp` color)
- Modify: `prism_eval/expA_delaydriven/make_figs.py` (`BASELINES`)
- Modify: `prism_eval/expA_delaydriven/repro.sh` (one run line in the main sweep)

**Interfaces:**
- Consumes: `render_main_perf_split` (unchanged default token).
- Produces: a 5th baseline arm `("ecmp","ECMP+NSCC","ecmp")` present in all expA perf/fairness figures and the `-failed` sweep data.

- [ ] **Step 1: Add the ECMP color**

In `prism_eval/common/plot_style.py`, in the `COLORS` dict, after the `"prism"` line add:

```python
    "ecmp": "tab:purple",  # single-path (no spray) anchor
```

- [ ] **Step 2: Add ECMP to `BASELINES`**

In `prism_eval/expA_delaydriven/make_figs.py`, change `BASELINES` to:

```python
BASELINES = [("ops", "OPS+NSCC", "ops"), ("reps", "REPS+NSCC", "reps"),
             ("strack", "STrack", "strack"), ("prism", "Prism", "prism"),
             ("ecmp", "ECMP+NSCC", "ecmp")]
```

- [ ] **Step 3: Add the ECMP run line to the main sweep**

In `prism_eval/expA_delaydriven/repro.sh`, inside the `for f in $FAILEDS; do for s in $SEEDS; do` loop (the "main sweep" block), after the `strack` line add:

```bash
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" nscc ecmp "$f" "$TOPO" "$s" "$CM" flow,sink "expA_ecmp_f${f}_s${s}" "$OUT"
```

- [ ] **Step 4: Smoke-test one ECMP run + render path**

```bash
cd /home/leo/htsim/htsim/sim/datacenter
python3 prism_eval/common/gen/many2many.py /tmp/smoke.cm 64 16 pairs 2000000 128 16
PATHS=8 END_MS=8 EXTRA_ARGS="-disable_trim" \
  bash prism_eval/common/run_lib.sh nscc ecmp 4 fat_tree_128_1os.topo 13 /tmp/smoke.cm flow,sink expA_ecmp_f4_s13 prism_eval/expA_delaydriven/data
ls -la prism_eval/expA_delaydriven/data/expA_ecmp_f4_s13.flow.txt
```
Expected: a non-empty `expA_ecmp_f4_s13.flow.txt` with `FLOW_EVENT` lines (confirms `LB=ecmp CC=nscc` runs and logs FCT).

- [ ] **Step 5: Verify `make_figs.py --selftest` still passes**

Run: `cd /home/leo/htsim/htsim/sim/datacenter && python3 prism_eval/expA_delaydriven/make_figs.py --selftest`
Expected: `ok perf_figs aggregation selftest`

- [ ] **Step 6: Stage and report (no commit)**

```bash
git -C /home/leo/htsim/htsim/sim/datacenter add prism_eval/common/plot_style.py prism_eval/expA_delaydriven/make_figs.py prism_eval/expA_delaydriven/repro.sh
```

---

### Task 5: Offered-load sweep wiring (Deliverable ②)

**Files:**
- Modify: `prism_eval/expA_delaydriven/repro.sh` (start-unit guard + offered-load section)
- Modify: `prism_eval/expA_delaydriven/make_figs.py` (`LOADS`, `XLABEL_LOAD`, the `render_main_perf_split(..., token="L")` call)

**Interfaces:**
- Consumes: `poisson_load.py` (Task 2), `render_main_perf_split(..., token="L")` (Task 3), ECMP arm (Task 4).
- Produces: data files `expAload_{arm}_L{rho}_s{seed}.flow.txt` and figures `figA3dd_load_{goodput,avg_fct,p99_fct}`.

- [ ] **Step 1: Add the start-unit guard to repro.sh**

In `prism_eval/expA_delaydriven/repro.sh`, immediately after the self-test block (after the `g++ ... test_strack_cc` line), add:

```bash
echo "== start-unit guard: confirm .cm 'start' is picoseconds + no overflow at the window scale =="
printf 'Nodes 128\nConnections 2\n80->0 start 1000000 size 2000000\n81->1 start 8000000000 size 2000000\n' > "$OUT/_unit_probe.cm"
PATHS=8 END_MS=12 EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" nscc reps 0 "$TOPO" 13 "$OUT/_unit_probe.cm" flow _unit_probe "$OUT"
python3 - "$OUT/_unit_probe.flow.txt" <<'PY'
import sys
starts = sorted(float(ln.split()[0]) for ln in open(sys.argv[1]) if " START " in ln)
assert len(starts) >= 2, f"probe produced too few START events: {starts}"
# start in ps: 1e6 ps -> 1us=0.000001s ; 8e9 ps -> 8ms=0.008s (also checks no uint32 overflow at 8ms)
assert 0.0079 < starts[-1] < 0.0081, f"start-unit NOT picoseconds / overflow (start 8e9 -> {starts[-1]}s)"
print("ok start-unit = picoseconds, no overflow at 8ms:", starts)
PY
```

NOTE: this guard references `$OUT`, `$COMMON`, `$TOPO`, `$DD` which are defined earlier in repro.sh — place it after `OUT="$REL/data"` is set (i.e., after the workload-generation block defines `OUT`). If `OUT` is defined below the self-test block, move this guard to just after the `CM=...; OUT=...` assignment.

- [ ] **Step 2: Add the offered-load sweep section to repro.sh**

In `prism_eval/expA_delaydriven/repro.sh`, after the mechanism-condition block (after the last `expA_strack_mech` run) and before the render call, add:

```bash
echo "== offered-load sweep (Poisson, failed=8, 2MB): 5 arms x rho{10,30,50,70,90}% x 5 seeds =="
LOAD_W_US=8000; LOAD_END=20; REF_GBPS=1600
for rho in 10 30 50 70 90; do
  rhof="$(python3 -c "print($rho/100.0)")"
  for s in $SEEDS; do
    LCM="$OUT/m2m_load_L${rho}_s${s}.cm"
    python3 "$COMMON/gen/poisson_load.py" "$LCM" 64 16 2000000 128 16 "$rhof" "$LOAD_W_US" "$REF_GBPS" "$s"
    PATHS=8 END_MS="$LOAD_END" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" nscc oblivious 8 "$TOPO" "$s" "$LCM" flow,sink "expAload_ops_L${rho}_s${s}" "$OUT"
    PATHS=8 END_MS="$LOAD_END" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" nscc reps      8 "$TOPO" "$s" "$LCM" flow,sink "expAload_reps_L${rho}_s${s}" "$OUT"
    PATHS=8 END_MS="$LOAD_END" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" prism reps     8 "$TOPO" "$s" "$LCM" flow,sink "expAload_prism_L${rho}_s${s}" "$OUT"
    PATHS=8 END_MS="$LOAD_END" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" strack reps    8 "$TOPO" "$s" "$LCM" flow,sink "expAload_strack_L${rho}_s${s}" "$OUT"
    PATHS=8 END_MS="$LOAD_END" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" nscc ecmp      8 "$TOPO" "$s" "$LCM" flow,sink "expAload_ecmp_L${rho}_s${s}" "$OUT"
  done
done
```

- [ ] **Step 3: Add the load render call to make_figs.py**

In `prism_eval/expA_delaydriven/make_figs.py`, after the `XLABEL = ...` line add:

```python
LOADS = [10, 30, 50, 70, 90]   # offered load rho*100 (% of 1.6 Tbps receiver-access capacity)
XLABEL_LOAD = "offered load (% of receiver-access capacity, 1.6 Tbps)"
```

and inside the `else:` render block, after the `render_mechanism_split(...)` line add:

```python
        perf_figs.render_main_perf_split(DATA, FIGS, "expAload", BASELINES, LOADS, SEEDS,
                                         "figA3dd_load", XLABEL_LOAD, token="L")
```

- [ ] **Step 4: Smoke-test the load path end-to-end (1 ρ, 1 seed, 2 arms)**

```bash
cd /home/leo/htsim/htsim/sim/datacenter
D=prism_eval/expA_delaydriven/data
python3 prism_eval/common/gen/poisson_load.py "$D/m2m_load_L50_s13.cm" 64 16 2000000 128 16 0.5 8000 1600 13
PATHS=8 END_MS=20 EXTRA_ARGS="-disable_trim" bash prism_eval/common/run_lib.sh nscc reps  8 fat_tree_128_1os.topo 13 "$D/m2m_load_L50_s13.cm" flow,sink expAload_reps_L50_s13 "$D"
PATHS=8 END_MS=20 EXTRA_ARGS="-disable_trim" bash prism_eval/common/run_lib.sh prism reps 8 fat_tree_128_1os.topo 13 "$D/m2m_load_L50_s13.cm" flow,sink expAload_prism_L50_s13 "$D"
python3 -c "import sys; sys.path.insert(0,'prism_eval/common'); import perf_figs; print(perf_figs.aggregate('$D','expAload','prism',[50],[13],token='L'))"
```
Expected: the final line prints a dict like `{50: {'goodput': (..), 'avg_fct': (..), 'p99_fct': (..), 'cr': (..)}}` with a non-NaN goodput — confirms the generator → run → token="L" aggregation chain works.

- [ ] **Step 5: Verify `make_figs.py --selftest` still passes**

Run: `cd /home/leo/htsim/htsim/sim/datacenter && python3 prism_eval/expA_delaydriven/make_figs.py --selftest`
Expected: `ok perf_figs aggregation selftest`

- [ ] **Step 6: Stage and report (no commit)**

```bash
git -C /home/leo/htsim/htsim/sim/datacenter add prism_eval/expA_delaydriven/repro.sh prism_eval/expA_delaydriven/make_figs.py
```

---

### Task 6: Full reproduction run + figures + docs

**Files:**
- Run: `prism_eval/expA_delaydriven/repro.sh` (regenerates all expA data + figures)
- Modify: `prism_eval/expA_delaydriven/README.md` (new "Offered-load sweep + ECMP anchor" section)
- Modify: `prism_eval/NARRATIVE.md` (one sentence in §3 + one Map row)

**Interfaces:**
- Consumes: Tasks 2–5.
- Produces: `figs/figA1dd_*` (now 5 lines), `figs/figA3dd_load_*`, and updated docs with REAL numbers.

- [ ] **Step 1: Run the full repro (background; ~1–2 h)**

```bash
cd /home/leo/htsim/htsim/sim/datacenter
mkdir -p prism_eval/expA_delaydriven/data
( bash prism_eval/expA_delaydriven/repro.sh > prism_eval/expA_delaydriven/data/repro.log 2>&1 ) &
echo "launched pid $!"
```

- [ ] **Step 2: Confirm completion and inspect the printed summaries**

```bash
cd /home/leo/htsim/htsim/sim/datacenter
tail -40 prism_eval/expA_delaydriven/data/repro.log
ls prism_eval/expA_delaydriven/figs/figA3dd_load_*.pdf prism_eval/expA_delaydriven/figs/figA1dd_*.pdf
```
Expected: `ok start-unit = microseconds`, the `[figA1dd]` and `[figA3dd_load]` per-baseline summary lines, and the six PDF/PNG files present. Capture the `[figA1dd]` (with ECMP) and `[figA3dd_load]` numbers for the README tables.

- [ ] **Step 3: Verify ECMP and the load curve behave sanely**

Confirm from the summary lines: (a) ECMP+NSCC is the worst arm under asymmetry (lowest goodput at high `-failed`); (b) along the load sweep, PRISM's avg/P99-FCT advantage over REPS+NSCC and STrack widens as ρ rises, and `cr` stays ~1 except possibly at ρ=90 (any cr<1 cell is auto-flagged on the figure). If ECMP is *not* worst, or PRISM shows no load-dependent widening, STOP and report — the result is unexpected and must be understood before writing it up.

- [ ] **Step 4: Write the README section with real numbers**

In `prism_eval/expA_delaydriven/README.md`, add a section (fill `<...>` from Step 2's printout):

```markdown
## Offered-load sweep + ECMP anchor

**ECMP+NSCC** (single path per flow, `LB=ecmp CC=nscc`) is added to the `-failed` sweep as the
conventional no-spray anchor: under asymmetry it is the worst arm (<...>), bracketing — with OPS — the
contribution of spraying. It is *context*, not PRISM's competition (REPS+NSCC and STrack are).

**Offered-load figure** (`figA3dd_load_*`): open-loop Poisson arrivals (`common/gen/poisson_load.py`),
fixed 2 MB flows, `-failed 8`. Offered load rho is relative to aggregate receiver-access capacity
C = 16 x 100 Gbps = 1.6 Tbps; lambda = rho*C/(2MB*8). Window 8 ms, END 20 ms, seeds {13-17}.
The `.cm` `start` token is picoseconds (verified by the repro.sh start-unit guard; window_us is converted x1e6 to ps in poisson_load.py).

| rho | goodput (Gbps) REPS / STrack / PRISM | avg FCT (ms) REPS / STrack / PRISM | cr |
|----:|---|---|---|
| 0.1 | <..> | <..> | <..> |
| 0.5 | <..> | <..> | <..> |
| 0.9 | <..> | <..> | <..> |

Reading: near-idle (low rho) the fabric carries little queue, there is no reroutable spread to decompose,
and PRISM ~ties; as rho -> saturation under the f8 asymmetry the spread appears and PRISM's FCT lead over
both REPS+NSCC and STrack widens (<...>). Any cr<1 cell is flagged on the figure.
```

- [ ] **Step 5: Update NARRATIVE.md**

In `prism_eval/NARRATIVE.md`, in the §3 first bullet (the `expA_delaydriven` win), append one sentence:

```markdown
  The advantage is also load-dependent: swept over offered load at fixed asymmetry (`figA3dd_load`),
  PRISM ~ties near-idle (no reroutable spread yet) and its FCT lead over REPS+NSCC and STrack widens as
  load approaches saturation — the floor-vs-spread structure of figS only becomes actionable once queues build.
```

and add a Map row after the `Eval (win)` row:

```markdown
| Eval (win, load) | `expA_delaydriven/` (figA3dd_load) | open-loop offered-load sweep: PRISM's FCT lead widens with load under asymmetry |
```

- [ ] **Step 6: Report for review and list the commit commands (no commit)**

Report the final figures and numbers. Provide the user these commands to run when they choose to commit (figs are gitignored → forced):

```bash
cd /home/leo/htsim/htsim/sim/datacenter
git add prism_eval/common/gen/poisson_load.py prism_eval/common/perf_figs.py prism_eval/common/plot_style.py \
        prism_eval/expA_delaydriven/make_figs.py prism_eval/expA_delaydriven/repro.sh \
        prism_eval/expA_delaydriven/README.md prism_eval/NARRATIVE.md \
        ../../../docs/superpowers/specs/2026-06-18-prism-eval-expA-loadsweep-design.md \
        ../../../docs/superpowers/plans/2026-06-18-prism-eval-expA-loadsweep.md
git add -f prism_eval/expA_delaydriven/figs/figA1dd_goodput.* prism_eval/expA_delaydriven/figs/figA1dd_avg_fct.* \
           prism_eval/expA_delaydriven/figs/figA1dd_p99_fct.* prism_eval/expA_delaydriven/figs/figA1dd_fairness.* \
           prism_eval/expA_delaydriven/figs/figA3dd_load_goodput.* prism_eval/expA_delaydriven/figs/figA3dd_load_avg_fct.* \
           prism_eval/expA_delaydriven/figs/figA3dd_load_p99_fct.*
```

---

## Self-Review

**Spec coverage:**
- ECMP+NSCC baseline (color, BASELINES, run line, re-render, not-in-mechanism) → Task 4 + Task 6. ✓
- Poisson generator (inputs, sender/receiver sets, λ, µs starts, selftest) → Task 2. ✓
- ρ definition / denominator 1.6 Tbps / sweep {10..90} → Global Constraints + Task 5. ✓
- Renderer token generalization, default "f", zero regression, selftest → Task 3. ✓
- Window/END sizing, 125 runs, calibration-by-reporting → Task 5 + Task 6 Step 3. ✓
- Start-unit de-risk (probe + repro.sh guard) → Task 1 + Task 5 Step 1. ✓
- Docs (README real numbers, NARRATIVE sentence + Map row) → Task 6. ✓
- Reproducibility (figs `git add -f`, data gitignored, seeds, selftests, no PRISM code) → Global Constraints + Task 6 Step 6. ✓

**Placeholder scan:** the only intentional placeholder (`senders_idx`) is explicitly flagged in Task 2 Step 1 and removed in Step 2; no other "TBD"/"add error handling"/"similar to" remain. README `<...>` are data-fill markers, correctly deferred to post-run (Task 6 Step 4) since the numbers do not exist until Step 2.

**Type consistency:** `build(...)` signature in Task 2 matches its CLI arg unpacking and the repro.sh call order in Task 5 (`out n_send n_recv size nodes hpp rho window_us ref_gbps seed`). `token` kwarg name and position (trailing, default `"f"`) consistent across `aggregate`/`render_main_perf`/`render_main_perf_split`/`render_fairness` (Task 3) and the `token="L"` call (Task 5 Step 3). Tag/filename convention `expAload_{arm}_L{rho}_s{seed}` consistent between repro.sh (Task 5 Step 2) and the render call's `tag_prefix="expAload"` + `token="L"` + `LOADS` (Task 5 Step 3).
