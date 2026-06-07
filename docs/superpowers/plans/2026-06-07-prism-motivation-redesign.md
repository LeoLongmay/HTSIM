# PRISM Motivation Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-run the congestion-decomposition motivation experiment under 128-flow permutation load, measuring C_spray/C_cc at the agg→core tier per agg-switch uplink bundle, to decide (via causal contrast + monotonicity) whether bottleneck congestion cleanly decomposes into an LB-removable part (C_spray) and a CC-only floor (C_cc).

**Architecture:** Pure measurement — no C++ changes. Three reusable scripts (a permutation `.cm` generator, a run helper, an analysis module) drive the existing `htsim_uec` binary via CLI flags, then post-process the logs by joining queue IDs to tier names via `idmap.txt`. Execution is two-phase: a smoke phase finds the failure-concentration knee `k`, then an adaptive matrix runs around `k`.

**Tech Stack:** C++ htsim binary (prebuilt, unchanged), bash, Python 3 (+ user-installed matplotlib), the project's `parse_output` decoder.

**Spec:** `docs/superpowers/specs/2026-06-07-prism-motivation-redesign-design.md`

**Working dir (all relative paths below are from here):** `/home/leo/htsim/htsim/sim/datacenter/`

---

## Verified mechanics (do not re-derive)

- Binary: `./htsim_uec` (symlink → `build/datacenter/htsim_uec`). Decoder: `../build/parse_output`.
- `-o <file>` sets the raw binary log path (default `logout.dat`). `parse_output <file> -ascii` prints decoded ASCII to stdout.
- `Logged::dump_idmap()` (called at `main_uec.cpp:1103`) writes `idmap.txt` (lines `<id> <name>`) to the **process CWD** on each run — **must be copied per-run before the next run overwrites it.**
- A queue logs only after the first packet traverses it; loggers exist on **all** tiers. Agg→core uplink queues are named `US{agg}->CS{core}(b)`; the `Pipe-US...` lines are pipes (must be excluded).
- `-failed N` degrades N agg→core uplinks to 25% linkspeed, filled sequentially from `agg_sw 0` (links 0..3), then `agg_sw 1`, etc. So: failed=2 → agg0 has 2 degraded + 2 good (mixed); failed=4 → agg0 fully degraded; failed=8 → agg0+agg1 fully degraded; failed=16 → pod0 (agg0–3) fully degraded.
- The LB algorithm is set by **`-load_balancing_algo reps|oblivious|mixed|...`** (main_uec.cpp:223; prints "Load balancing algorithm set to …"), NOT by `-strat` (which sets the *route* strategy ecmp/adaptive/… and silently defaults to ECMP if given an unrecognized value). Route strategy is left at its ECMP default, matching round 1. (Corrected after an initial run used `-strat` and silently fell back to the default MIXED LB.)
- Topology `fat_tree_128_1os.topo`: 128 host / 8 pod, 4 agg per pod, agg radix_up=4 (4 uplinks/agg), 32 agg → 128 agg→core uplinks. pod index = agg_index // 4.

---

## Task 1: Workspace + gitignore + precondition checks

**Files:**
- Create: `mvp_runs2/.gitignore`

- [ ] **Step 1: Create the output dir and gitignore for heavy/binary artifacts**

```bash
cd /home/leo/htsim/htsim/sim/datacenter
mkdir -p mvp_runs2
cat > mvp_runs2/.gitignore <<'EOF'
*.dat
*.q.txt
*.log
*.idmap
*.stdout
EOF
```

- [ ] **Step 2: Verify preconditions (binary, decoder, topology, matplotlib)**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter
ls -l ./htsim_uec ../build/parse_output topologies/fat_tree_128_1os.topo
python3 -c "import matplotlib; matplotlib.use('Agg'); print('matplotlib ok')"
```
Expected: all three paths exist; prints `matplotlib ok`. If matplotlib import fails, stop and report (it was installed user-level previously; do not modify the environment without flagging).

- [ ] **Step 3: Commit**

```bash
cd /home/leo/htsim
git add htsim/sim/datacenter/mvp_runs2/.gitignore
git commit -m "Add mvp_runs2 workspace + gitignore for experiment artifacts"
```

---

## Task 2: Permutation traffic generator

**Files:**
- Create: `mvp_runs2/gen_perm.py`
- Output (gitignored data, but regenerable): `mvp_runs2/perm.cm`

- [ ] **Step 1: Write the generator**

Create `mvp_runs2/gen_perm.py`:

```python
#!/usr/bin/env python3
"""Generate a 128-host cross-pod permutation .cm for htsim.
host i -> host (i+64) % 128 (a bijection; never i->i; always crosses pods).
Usage: python3 gen_perm.py <out.cm> [size_bytes] [nodes]
"""
import sys

def main():
    out = sys.argv[1]
    size = int(sys.argv[2]) if len(sys.argv) > 2 else 30_000_000  # 30 MB
    nodes = int(sys.argv[3]) if len(sys.argv) > 3 else 128
    half = nodes // 2
    lines = [f"Nodes {nodes}", f"Connections {nodes}"]
    dests = set()
    for i in range(nodes):
        d = (i + half) % nodes
        assert d != i, f"self-loop at {i}"
        dests.add(d)
        lines.append(f"{i}->{d} start 0 size {size}")
    assert len(dests) == nodes, "not a bijection"
    with open(out, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {out}: {nodes} flows, size={size} bytes each")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Generate perm.cm and verify it**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter
python3 mvp_runs2/gen_perm.py mvp_runs2/perm.cm 30000000 128
head -3 mvp_runs2/perm.cm
grep -c '\->' mvp_runs2/perm.cm
awk -F'->| ' '/->/{print $2}' mvp_runs2/perm.cm | sort -n | uniq | wc -l
```
Expected: header `Nodes 128` / `Connections 128`; first flow `0->64 start 0 size 30000000`; `grep -c` prints `128`; the unique-destination count prints `128` (confirms bijection).

- [ ] **Step 3: Commit**

```bash
cd /home/leo/htsim
git add htsim/sim/datacenter/mvp_runs2/gen_perm.py
git commit -m "Add permutation .cm generator for PRISM motivation experiment"
```

---

## Task 3: Analysis module + unit tests (TDD)

**Files:**
- Create: `mvp_runs2/analyze2.py`
- Test: `mvp_runs2/test_analyze2.py` (self-contained, no pytest needed)

- [ ] **Step 1: Write the failing test**

Create `mvp_runs2/test_analyze2.py`:

```python
#!/usr/bin/env python3
"""Self-contained tests for analyze2 (no pytest). Run: python3 test_analyze2.py"""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze2 as A

def test_agg_core_groups_filters_layers():
    idmap = {
        1700: "US0->CS0(0)", 1701: "Pipe-US0->CS0(0)",
        1706: "US0->CS4(0)", 1712: "US0->CS8(0)", 1718: "US0->CS12(0)",
        1800: "US1->CS0(0)", 1806: "US1->CS4(0)",
        50: "LS0->US0(0)",     # tor->agg, must be excluded
        60: "US0->LS_3(0)",    # agg->tor downlink, must be excluded
        70: "LS0->DST2(0)",    # tor->host, must be excluded
    }
    g = A.agg_core_groups(idmap)
    assert set(g.keys()) == {0, 1}, g
    assert sorted(g[0]) == [1700, 1706, 1712, 1718], g[0]   # Pipe excluded
    assert sorted(g[1]) == [1800, 1806], g[1]
    print("ok agg_core_groups")

def test_pod_groups():
    groups = {0: [1700, 1706], 1: [1800], 2: [1900], 3: [2000], 4: [2100]}
    pods = A.pod_groups(groups)
    assert sorted(pods[0]) == [1700, 1706, 1800, 1900, 2000], pods[0]  # aggs 0..3
    assert sorted(pods[1]) == [2100], pods[1]                          # agg 4
    print("ok pod_groups")

def test_decompose_uses_p8_and_bundle():
    # agg0 uplinks at t=600us: [12450, 4150, 4150, 4150] bytes; plus a foreign queue
    q = (
        "0.000600000 Type QUEUE_APPROX ID 1700 Ev RANGE LastQ 12450 MinQ 0 MaxQ 12450\n"
        "0.000600000 Type QUEUE_APPROX ID 1706 Ev RANGE LastQ 4150 MinQ 0 MaxQ 4150\n"
        "0.000600000 Type QUEUE_APPROX ID 1712 Ev RANGE LastQ 4150 MinQ 0 MaxQ 4150\n"
        "0.000600000 Type QUEUE_APPROX ID 1718 Ev RANGE LastQ 4150 MinQ 0 MaxQ 4150\n"
        "0.000600000 Type QUEUE_APPROX ID 50 Ev RANGE LastQ 999999 MinQ 0 MaxQ 999999\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".q.txt", delete=False) as f:
        f.write(q); path = f.name
    keep = {1700, 1706, 1712, 1718}
    data = A.parse_q(path, keep)
    os.unlink(path)
    t, cs, cc = A.decompose_bundle(data, [1700, 1706, 1712, 1718])
    assert t == [600.0], t
    assert abs(cs[0] - 0.664) < 1e-6, cs   # (12450-4150)*8e-5
    assert abs(cc[0] - 0.332) < 1e-6, cc   # 4150*8e-5
    print("ok decompose (p[8] field, bundle filter)")

def test_steady_window():
    times = [100.0, 600.0, 1000.0, 1600.0]
    series = [9.0, 1.0, 3.0, 9.0]          # only 600 and 1000 fall in [500,1500]
    s = A.steady_stats(times, series, 500.0, 1500.0)
    assert s["n"] == 2, s
    assert abs(s["mean"] - 2.0) < 1e-9, s
    print("ok steady_stats window")

if __name__ == "__main__":
    test_agg_core_groups_filters_layers()
    test_pod_groups()
    test_decompose_uses_p8_and_bundle()
    test_steady_window()
    print("ALL PASS")
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter/mvp_runs2
python3 test_analyze2.py
```
Expected: FAIL — `ModuleNotFoundError: No module named 'analyze2'` (module not yet created).

- [ ] **Step 3: Write the analysis module**

Create `mvp_runs2/analyze2.py`:

```python
#!/usr/bin/env python3
"""Per-agg-bundle (and per-pod cross-check) congestion decomposition at the agg->core tier.
C_spray(set,t) = max-min, C_cc(set,t) = min, over the queues in that interchangeable set.
Usage: python3 analyze2.py <tag> [<tag> ...]   (reads mvp_runs2/<tag>.{idmap,q.txt})
"""
import sys, os, re, collections
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BYTES_TO_US = 8e-5          # 1 byte @100Gbps queueing delay: 8 bits / 100e9 * 1e6 us
AGGCORE_RE = re.compile(r'^US(\d+)->CS(\d+)')
HERE = os.path.dirname(os.path.abspath(__file__))

def load_idmap(path):
    """id(int) -> name(str)"""
    idmap = {}
    with open(path) as f:
        for line in f:
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            try:
                qid = int(parts[0])
            except ValueError:
                continue
            idmap[qid] = parts[1].strip()
    return idmap

def agg_core_groups(idmap):
    """agg_index(int) -> [queue_id,...] for US{agg}->CS{core} queues (excludes Pipe-*)."""
    groups = collections.defaultdict(list)
    for qid, name in idmap.items():
        if name.startswith("Pipe-"):
            continue
        m = AGGCORE_RE.match(name)
        if m:
            groups[int(m.group(1))].append(qid)
    return dict(groups)

def pod_groups(groups):
    """pod_index(int) -> [queue_id,...] (union of the pod's 4 agg uplink bundles). pod = agg//4."""
    pods = collections.defaultdict(list)
    for agg, ids in groups.items():
        pods[agg // 4].extend(ids)
    return dict(pods)

def parse_q(path, keep_ids):
    """time_us -> {qid: lastQ_bytes}, only for qid in keep_ids."""
    data = collections.defaultdict(dict)
    with open(path) as f:
        for line in f:
            p = line.split()
            # <t> Type QUEUE_APPROX ID <qid> Ev RANGE LastQ <bytes> MinQ <b> MaxQ <b>
            if len(p) < 9 or p[6] != "RANGE":
                continue
            qid = int(p[4])
            if qid not in keep_ids:
                continue
            data[float(p[0]) * 1e6][qid] = int(p[8])   # LastQ value is p[8], NOT literal p[7]
    return data

def decompose_bundle(data, group_ids):
    """(times, c_spray_us, c_cc_us) over samples where >=2 of the set's queues are present."""
    gset = set(group_ids)
    times, cs, cc = [], [], []
    for t in sorted(data):
        vals = [b for qid, b in data[t].items() if qid in gset]
        if len(vals) < 2:
            continue
        times.append(t)
        cs.append((max(vals) - min(vals)) * BYTES_TO_US)
        cc.append(min(vals) * BYTES_TO_US)
    return times, cs, cc

def steady_stats(times, series, lo=500.0, hi=1500.0):
    """mean/median/p95 over [lo,hi] us window."""
    w = sorted(v for t, v in zip(times, series) if lo <= t <= hi)
    if not w:
        return {"mean": 0.0, "median": 0.0, "p95": 0.0, "n": 0}
    n = len(w)
    return {"mean": sum(w) / n, "median": w[n // 2],
            "p95": w[min(n - 1, int(0.95 * n))], "n": n}

def analyze_tag(tag, focus_aggs=(0, 1), focus_pods=(0,), win=(500.0, 1500.0)):
    idmap = load_idmap(os.path.join(HERE, f"{tag}.idmap"))
    groups = agg_core_groups(idmap)
    pods = pod_groups(groups)
    keep = set(q for ids in groups.values() for q in ids)
    data = parse_q(os.path.join(HERE, f"{tag}.q.txt"), keep)

    def series_for(ids):
        t, cs, cc = decompose_bundle(data, ids)
        return t, cs, cc, steady_stats(t, cs, *win), steady_stats(t, cc, *win)

    lines = []
    # plot: focus aggs + focus pod
    fig, ax = plt.subplots(figsize=(10, 4))
    for agg in focus_aggs:
        if agg in groups:
            t, cs, cc, cs_s, cc_s = series_for(groups[agg])
            ax.plot(t, cs, linewidth=0.9, label=f"C_spray agg{agg}")
            ax.plot(t, cc, linewidth=0.9, linestyle="--", label=f"C_cc agg{agg}")
            lines.append(f"{tag:16s} agg{agg}: C_spray mean={cs_s['mean']:6.2f} p95={cs_s['p95']:6.2f}us"
                         f"  C_cc mean={cc_s['mean']:6.2f} p95={cc_s['p95']:6.2f}us median={cc_s['median']:6.2f} (n={cc_s['n']})")
    for pod in focus_pods:
        if pod in pods:
            t, cs, cc, cs_s, cc_s = series_for(pods[pod])
            lines.append(f"{tag:16s} POD{pod}: C_spray mean={cs_s['mean']:6.2f} p95={cs_s['p95']:6.2f}us"
                         f"  C_cc mean={cc_s['mean']:6.2f} p95={cc_s['p95']:6.2f}us median={cc_s['median']:6.2f} (n={cc_s['n']})")
    ax.axvspan(win[0], win[1], color="grey", alpha=0.12)
    ax.set_xlabel("time (us)"); ax.set_ylabel("queueing delay (us)")
    ax.set_title(tag); ax.legend(fontsize=8); ax.grid(alpha=0.3); ax.set_xlim(0, 2000)
    plt.tight_layout(); plt.savefig(os.path.join(HERE, f"{tag}.png"), dpi=130); plt.close()
    return "\n".join(lines)

if __name__ == "__main__":
    print("\n".join(analyze_tag(tag) for tag in sys.argv[1:]))
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter/mvp_runs2
python3 test_analyze2.py
```
Expected: prints `ok agg_core_groups` / `ok pod_groups` / `ok decompose (p[8] field, bundle filter)` / `ok steady_stats window` / `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
cd /home/leo/htsim
git add htsim/sim/datacenter/mvp_runs2/analyze2.py htsim/sim/datacenter/mvp_runs2/test_analyze2.py
git commit -m "Add agg->core decomposition analysis + unit tests"
```

---

## Task 4: Run helper

**Files:**
- Create: `mvp_runs2/run_one.sh`

- [ ] **Step 1: Write the helper**

Create `mvp_runs2/run_one.sh`:

```bash
#!/bin/bash
# Run one config: strat, failed, tag. Captures stdout + per-run idmap + agg-core q.txt.
set -euo pipefail
DC="$(cd "$(dirname "$0")/.." && pwd)"   # .../sim/datacenter
cd "$DC"
STRAT="$1"; FAILED="$2"; TAG="$3"
OUT=mvp_runs2
echo "[run_one] strat=$STRAT failed=$FAILED tag=$TAG"
./htsim_uec -topo topologies/fat_tree_128_1os.topo -tm "$OUT/perm.cm" -nodes 128 \
    -sender_cc_algo nscc -strat "$STRAT" -failed "$FAILED" -mtu 4150 \
    -log tor_upqueue -logtime_us 2 -end 2 -o "$OUT/$TAG.dat" > "$OUT/$TAG.stdout" 2>&1
cp idmap.txt "$OUT/$TAG.idmap"
../build/parse_output "$OUT/$TAG.dat" -ascii | grep ' QUEUE_APPROX ' | grep ' RANGE ' > "$OUT/$TAG.q.txt"
echo "[run_one] done $TAG  .dat=$(du -h "$OUT/$TAG.dat" | cut -f1)  q.txt_lines=$(wc -l < "$OUT/$TAG.q.txt")"
```

- [ ] **Step 2: Make executable and sanity-check the failure-injection line count helper**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter
chmod +x mvp_runs2/run_one.sh
bash -n mvp_runs2/run_one.sh && echo "syntax ok"
```
Expected: prints `syntax ok` (no execution yet).

- [ ] **Step 3: Commit**

```bash
cd /home/leo/htsim
git add htsim/sim/datacenter/mvp_runs2/run_one.sh
git commit -m "Add run_one.sh helper (run + capture idmap + decode agg-core queues)"
```

---

## Task 5: Phase 0 — smoke (baseline + find knee `k`, or STOP)

This phase is a **decision gate**. It establishes the symmetric baseline, then probes failure concentration to find the knee `k` where an irreducible C_cc floor appears at pod0/agg0 — or concludes that none does (degenerate → STOP and report, do not fabricate).

**Thresholds (numeric, decided up front):**
- "Floor present at level F" ⇔ at `-failed F`, **pod0** C_cc steady-window **median ≥ 2.0 µs** AND ≥ **3×** the failed=0 baseline pod0 C_cc median.
- `k` := the smallest probed F that satisfies "floor present".

- [ ] **Step 1: Run the symmetric baseline (reused later as the matrix's failed=0 point)**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter
time bash mvp_runs2/run_one.sh reps 0 reps_f0
```
Expected: stdout tail shows topology loaded, `Adding link failure` absent, run completes; helper prints `.dat` size and `q.txt_lines`. **Record wall-clock time and `.dat` size.** If wall-clock > ~5 min or `.dat` > ~1 GB, stop and report the budget concern before continuing (per spec: reduce `-end` to 1.5 or flow size to 20 MB, note the change).

- [ ] **Step 2: Probe the likely knee at failed=8**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter
bash mvp_runs2/run_one.sh reps 8 reps_f8
grep -c 'Adding link failure' mvp_runs2/reps_f8.stdout
```
Expected: `grep -c 'Adding link failure'` on `reps_f8.stdout` prints `8` (confirms injection). Helper prints sizes.

- [ ] **Step 3: Analyze baseline vs failed=8 and apply the floor test**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter
python3 mvp_runs2/analyze2.py reps_f0 reps_f8
```
Expected: prints agg0/agg1/POD0 lines for both tags. **Read the POD0 C_cc median:**
- If `reps_f8` POD0 C_cc median ≥ 2.0 µs and ≥ 3× `reps_f0` POD0 C_cc median → **floor present at 8.** Proceed to Step 4 to check whether a *lower* knee exists.
- If not → go to Step 5 (escalate).

- [ ] **Step 4: (Floor present at 8) Probe for a lower knee at failed=4, set `k`**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter
bash mvp_runs2/run_one.sh reps 4 reps_f4
python3 mvp_runs2/analyze2.py reps_f4
```
Decision:
- If `reps_f4` POD0 C_cc median passes the floor test → set **k = 4**.
- Else → set **k = 8**.
Record the chosen `k` in a note (`mvp_runs2/knee.txt`):
```bash
echo "k=<chosen>  (floor test: pod0 C_cc median >=2us and >=3x baseline)" > mvp_runs2/knee.txt
```
Then skip to Task 6.

- [ ] **Step 5: (No floor at 8) Escalate to failed=16 (whole pod0 egress at 25%)**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter
bash mvp_runs2/run_one.sh reps 16 reps_f16
grep -c 'Adding link failure' mvp_runs2/reps_f16.stdout
python3 mvp_runs2/analyze2.py reps_f16
```
Decision:
- If `reps_f16` POD0 C_cc median passes the floor test → set **k = 16**, write `mvp_runs2/knee.txt`, proceed to Task 6.
- If even failed=16 shows no floor (REPS reroutes around / no irreducible congestion) → **STOP.** This is a valid negative finding. Write `mvp_runs2/knee.txt` with `k=NONE (no floor up to failed=16)` and go straight to Task 7 to write the degenerate-conclusion assessment and report. Do **not** run the matrix or fabricate a floor.

- [ ] **Step 6: Commit the knee decision note**

```bash
cd /home/leo/htsim
git add -f htsim/sim/datacenter/mvp_runs2/knee.txt
git commit -m "Record smoke-phase knee decision (k) for failure concentration"
```

---

## Task 6: Phase 1 — adaptive matrix runs

Only if Task 5 found a floor (`k` ∈ {4, 8, 16}). Runs the comparison matrix around `k`. Substitute the actual `k`/`2k` numbers (2k capped at 16, the whole-pod0 limit) when running.

**Matrix (6 runs):**
| tag | strat | failed | purpose |
|---|---|---|---|
| `reps_f0`   | reps      | 0   | baseline (already run in Task 5) |
| `reps_f2`   | reps      | 2   | spray regime (agg0 mixed) — for §6(ii) |
| `reps_fk`   | reps      | k   | floor regime |
| `reps_f2k`  | reps      | 2k  | monotonicity — for §6(iv) |
| `obl_f2`    | oblivious | 2   | spray contrast vs `reps_f2` — for §6(ii) |
| `obl_fk`    | oblivious | k   | floor invariance vs `reps_fk` — for §6(iii) |

> Note vs spec: the spec's matrix was REPS×{0,k,2k}+Oblivious×{k}. This plan **adds `reps_f2` and `obl_f2`** (the failed=2 mixed-bundle pair) because §6(ii) "REPS C_spray ≪ Oblivious C_spray" can only be tested in the mixed-bundle (spray) regime, which `k`/`2k` (fully-degraded bundles) do not exhibit. If budget is tight, these two are the droppable ones — but then §6(ii) is untestable; flag that in the report.

- [ ] **Step 1: Run the REPS sweep points not already present**

Run (substitute k and 2k; `reps_fk` may already exist from Task 5 — skip if so):
```bash
cd /home/leo/htsim/htsim/sim/datacenter
bash mvp_runs2/run_one.sh reps 2 reps_f2
# bash mvp_runs2/run_one.sh reps <k> reps_fk     # skip if reps_f<k> already run in Task 5
bash mvp_runs2/run_one.sh reps <2k> reps_f2k
```
Expected: each prints `done` with `.dat` size and q.txt line count; `grep -c 'Adding link failure' mvp_runs2/reps_f2.stdout` → `2`.

- [ ] **Step 2: Run the Oblivious contrast points**

Run (substitute k):
```bash
cd /home/leo/htsim/htsim/sim/datacenter
bash mvp_runs2/run_one.sh oblivious 2 obl_f2
bash mvp_runs2/run_one.sh oblivious <k> obl_fk
grep -m1 'Load balancing algorithm set to' mvp_runs2/obl_f2.stdout
```
Expected: last grep prints `Load balancing algorithm set to  oblivious` (confirms LB mode actually changed).

- [ ] **Step 3: Sanity-check all matrix runs produced non-empty agg-core data**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter
for t in reps_f0 reps_f2 reps_fK reps_f2K obl_f2 obl_fK; do \
  echo "$t: $(wc -l < mvp_runs2/$t.q.txt 2>/dev/null || echo MISSING) q-lines, idmap $(grep -c 'US.*->CS' mvp_runs2/$t.idmap 2>/dev/null) agg-core names"; done
```
(Replace `reps_fK`/`reps_f2K`/`obl_fK` with the real `k`/`2k` tag names.) Expected: each tag has > 0 q-lines and 128 agg-core names. Any `MISSING`/0 → investigate that run's `.stdout` before analyzing.

---

## Task 7: Phase 2 — final analysis, judgment, report

**Files:**
- Create: `mvp_runs2/summary.txt` (generated)
- Create: `mvp_runs2/assessment.txt` (the structured written evaluation)

- [ ] **Step 1: Generate the summary table over all tags**

Run (use real tag names; include only tags that exist — if Task 5 STOPped, this is just the smoke tags):
```bash
cd /home/leo/htsim/htsim/sim/datacenter
python3 mvp_runs2/analyze2.py reps_f0 reps_f2 reps_fK reps_f2K obl_f2 obl_fK | tee mvp_runs2/summary.txt
```
Expected: a table with agg0/agg1/POD0 C_spray & C_cc (mean/p95/median) per tag, and one `.png` per tag in `mvp_runs2/`.

- [ ] **Step 2: Evaluate the four §6 criteria from the numbers**

Read `summary.txt` and check, recording each verdict (true/false + the numbers):
- (i) **floor**: `reps_fK`/`reps_f2K` POD0 (or agg0) C_cc median clearly > `reps_f0`.
- (ii) **LB removes spray**: `obl_f2` C_spray (agg0/POD0) ≫ `reps_f2` C_spray, at the same failed=2.
- (iii) **CC-only floor**: `obl_fK` C_cc ≈ `reps_fK` C_cc (LB choice doesn't move the floor).
- (iv) **monotonic**: C_cc increases across `reps_f0` → `reps_fK` → `reps_f2K`.
"Decomposition holds" ⇔ all four hold. Otherwise "degenerate / partial".

- [ ] **Step 3: Write the structured assessment**

Create `mvp_runs2/assessment.txt` with these sections (fill with the real numbers from Step 1–2; do NOT include a final go/no-go — that is the user's call):
- Header: scenario recap (128-flow permutation, -failed at agg→core, per-agg-bundle + per-pod metric, sampling 2µs / window [500,1500]µs).
- The summary table (paste from `summary.txt`).
- Criteria verdicts (i)–(iv), each with the numbers that decided it.
- Conclusion: one of `成立 / 部分成立 / 退化`, strictly per the four criteria.
- 意外 (surprises) and 下一步建议 (next step). **If conclusion ≠ 成立, do NOT recommend entering PRISM implementation** (spec constraint).

- [ ] **Step 4: Commit the text deliverables (data stays gitignored)**

```bash
cd /home/leo/htsim
git add -f htsim/sim/datacenter/mvp_runs2/summary.txt htsim/sim/datacenter/mvp_runs2/assessment.txt
git commit -m "Add PRISM motivation redesign results (summary + assessment)"
```

- [ ] **Step 5: Report to the user via the framework**

Present in chat: the summary table, the four criteria verdicts with numbers, the per-tag PNG list, and the structured conclusion (`成立/部分成立/退化`). State the budget actuals (wall-clock, `.dat` sizes) and any deviations (e.g., reduced flow size, dropped failed=2 pair). **Do not** draw the final go/no-go; defer to the user.

---

## Self-review notes (author checks)

- **Spec coverage:** topology/traffic/sim/analysis/judgment/matrix/constraints each map to Tasks 1–7. The spec's "smoke find knee then adaptive matrix" → Tasks 5–6. The per-agg-bundle metric → `agg_core_groups`+`decompose_bundle`; per-pod cross-check (plan addition) → `pod_groups`, flagged.
- **Placeholder scan:** `k`/`2k`/`K`/`2K` are intentional run-time-resolved values (decided in Task 5, recorded in `knee.txt`); every code file is complete. No TODO/TBD.
- **Type/name consistency:** `agg_core_groups` → dict[int,list]; `pod_groups` consumes it; `decompose_bundle(data, ids)`, `steady_stats(times, series, lo, hi)`, `parse_q(path, keep_ids)` signatures match between `analyze2.py` and `test_analyze2.py`. `BYTES_TO_US=8e-5` consistent with test expectations (0.664/0.332).
- **Known risk:** if smoke finds no floor up to failed=16, Task 5 Step 5 STOPs into Task 7's degenerate path — no fabricated matrix.
