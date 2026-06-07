# PRISM per-path-RTT Incast Demo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Demonstrate PRISM's congestion decomposition with the faithful per-path RTT metric — `q_i = rtt_i − rtt_min` per sender-chosen path, `C_cc = min_i q_i`, `C_spray = max_i q_i − min_i q_i` — in an incast-into-a-partially-degraded-pod scenario, producing figures that show C_cc is the LB-invariant floor (CC's job) and C_spray is the LB-removable spread (LB's job).

**Architecture:** A ~7-line read-only logging hook in `uec.cpp` emits `(time, flow, path_id, raw_rtt)` per valid ACK, gated by the `PRISM_PATHRTT` env var (no simulation-behavior change). Python post-processing builds per-path RTT tables and the decomposition. Incast traffic + `-failed` (which degrades the destination pod's core→agg ingress) creates a shared last-hop floor (C_cc) and asymmetric ingress spread (C_spray).

**Tech Stack:** htsim C++ (one logging hook + rebuild), bash, Python 3 (+ matplotlib).

**Spec:** `docs/superpowers/specs/2026-06-07-prism-pathrtt-incast-demo-design.md`

**Working dir (all relative paths from here):** `/home/leo/htsim/htsim/sim/datacenter/`

---

## Verified mechanics (do not re-derive)

- `-failed N` degrades the **core→agg downlink** (CS→US, `queues_nc_nup`) of the first ⌈N/4⌉ aggs to 25% (`fat_tree_topology.cpp:1013-1018`). pod0's aggs = US0–US3. So `-failed 8` degrades US0,US1 ingress; US2,US3 stay full. This bottlenecks traffic **destined to** the degraded pod.
- LB algorithm flag is **`-load_balancing_algo {reps|oblivious|...}`** (main_uec.cpp:223), NOT `-strat`.
- The per-PSN send record stores `path_id` (uec.h:251-252). At `uec.cpp:1047` (`raw_rtt = eventlist().now() - send_time;`), inside the valid-ACK block (uec.cpp:1031-1058, which already excludes probe-acks/invalid timestamps), `i->second.path_id`, `raw_rtt`, and `flowId()` (uec.h:236) are all in scope.
- `uec.cpp` already includes `<fstream>`, `<cstdlib>`, `<sstream>`; `timeAsNs()` is declared in `config.h` (pulled in via `uec.h`).
- Build: `cd /home/leo/htsim/htsim/sim && cmake --build build --target htsim_uec` (incremental, ~1-3 min). Binary symlink: `datacenter/htsim_uec`.
- No `-log` flag is needed: the hook is independent of htsim's logging system. Use `-o /dev/null` for the unused binary logfile.

---

## Task 1: Add the read-only per-path-RTT logging hook to uec.cpp

**Files:**
- Modify: `/home/leo/htsim/htsim/sim/uec.cpp` (insert after line 1047)

- [ ] **Step 1: Insert the hook**

Use Edit to replace this exact block in `uec.cpp` (around lines 1047-1049):

Old:
```cpp
        raw_rtt = eventlist().now() - send_time;

        if (!pkt.is_rts()) {
```
New:
```cpp
        raw_rtt = eventlist().now() - send_time;

        // PRISM: read-only per-path RTT log, gated by env var PRISM_PATHRTT.
        // No simulation-behavior change. Emits one CSV row per valid data ACK:
        //   time_ns,flow_id,path_id,raw_rtt_ns
        {
            static std::ofstream* prism_pathrtt_log = [](){
                const char* p = getenv("PRISM_PATHRTT");
                return (p && *p) ? new std::ofstream(p) : nullptr;
            }();
            if (prism_pathrtt_log) {
                (*prism_pathrtt_log) << (uint64_t)timeAsNs(eventlist().now()) << ','
                                     << flowId() << ',' << i->second.path_id << ','
                                     << (uint64_t)timeAsNs(raw_rtt) << '\n';
            }
        }

        if (!pkt.is_rts()) {
```

- [ ] **Step 2: Rebuild htsim_uec**

Run:
```bash
cd /home/leo/htsim/htsim/sim && cmake --build build --target htsim_uec 2>&1 | tail -5
```
Expected: compiles and links with no errors; ends with a built `htsim_uec` target (or "Built target htsim_uec"). If it fails to compile, STOP and report the error (do not work around by changing simulation logic).

- [ ] **Step 3: Smoke-verify the hook emits a sane CSV**

Run (single 4MB flow, env var set):
```bash
cd /home/leo/htsim/htsim/sim/datacenter
mkdir -p mvp_runs3
printf 'Nodes 128\nConnections 1\n0->100 start 0 size 4000000\n' > mvp_runs3/_hooktest.cm
PRISM_PATHRTT=mvp_runs3/_hooktest.csv ./htsim_uec -topo topologies/fat_tree_128_1os.topo \
   -tm mvp_runs3/_hooktest.cm -nodes 128 -sender_cc_algo nscc -load_balancing_algo reps \
   -failed 0 -mtu 4150 -end 2 -o /dev/null > mvp_runs3/_hooktest.stdout 2>&1
echo "exit=$?; rows=$(wc -l < mvp_runs3/_hooktest.csv)"; head -3 mvp_runs3/_hooktest.csv
echo "distinct path_ids: $(awk -F, '{print $3}' mvp_runs3/_hooktest.csv | sort -u | wc -l)"
```
Expected: exit 0; rows > 0; each line is 4 comma-separated integers `time_ns,flow_id,path_id,raw_rtt_ns` with raw_rtt_ns in a plausible range (a few thousand to tens of thousands ns); distinct path_ids > 1 (REPS sprays). Then verify the hook is OFF without the env var:
```bash
cd /home/leo/htsim/htsim/sim/datacenter
rm -f mvp_runs3/_off.csv
./htsim_uec -topo topologies/fat_tree_128_1os.topo -tm mvp_runs3/_hooktest.cm -nodes 128 \
   -sender_cc_algo nscc -load_balancing_algo reps -failed 0 -mtu 4150 -end 2 -o /dev/null >/dev/null 2>&1
test ! -f mvp_runs3/_off.csv && echo "OK: no CSV written without env var"
```
Expected: prints `OK: no CSV written without env var`.

- [ ] **Step 4: Commit**

```bash
cd /home/leo/htsim
git add htsim/sim/uec.cpp
git commit -m "Add read-only per-path RTT logging hook (env-gated PRISM_PATHRTT)"
```
(Do not commit the `_hooktest.*` scratch files — Task 2 adds a `.gitignore` covering them.)

---

## Task 2: Incast traffic generator + workspace gitignore

**Files:**
- Create: `mvp_runs3/.gitignore`
- Create: `mvp_runs3/gen_incast.py`
- Output (gitignored): `mvp_runs3/incast.cm`

- [ ] **Step 1: Create the gitignore**

```bash
cd /home/leo/htsim/htsim/sim/datacenter
cat > mvp_runs3/.gitignore <<'EOF'
*.cm
*.csv
*.stdout
*.png
*.dat
_hooktest*
_off*
EOF
```

- [ ] **Step 2: Write the generator**

Create `mvp_runs3/gen_incast.py`:
```python
#!/usr/bin/env python3
"""Generate an incast .cm: N senders (all OUTSIDE the dest's pod) -> one dest host.
Senders outside the dest pod guarantees traffic crosses the core into the dest pod,
so it traverses the (possibly -failed) core->agg ingress links.
Usage: python3 gen_incast.py <out.cm> [n_senders] [dest] [size_bytes] [nodes] [hosts_per_pod]
"""
import sys

def build(n=32, dest=0, size=20_000_000, nodes=128, hpp=16):
    dest_pod = dest // hpp
    senders = [h for h in range(nodes) if h // hpp != dest_pod][:n]
    if len(senders) != n:
        raise ValueError(f"need {n} senders outside pod{dest_pod}, only {len(senders)} available")
    lines = [f"Nodes {nodes}", f"Connections {n}"]
    lines += [f"{s}->{dest} start 0 size {size}" for s in senders]
    return "\n".join(lines) + "\n", senders

def main():
    out = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 32
    dest = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    size = int(sys.argv[4]) if len(sys.argv) > 4 else 20_000_000
    nodes = int(sys.argv[5]) if len(sys.argv) > 5 else 128
    hpp = int(sys.argv[6]) if len(sys.argv) > 6 else 16
    text, senders = build(n, dest, size, nodes, hpp)
    open(out, "w").write(text)
    print(f"wrote {out}: {n} senders {senders[0]}..{senders[-1]} -> host{dest} (pod{dest//hpp}), size {size}")

if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Generate and verify**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter
python3 mvp_runs3/gen_incast.py mvp_runs3/incast.cm 32 0 20000000 128 16
head -2 mvp_runs3/incast.cm; echo "connections: $(grep -c '\->' mvp_runs3/incast.cm)"
awk -F'->| ' '/->/{print ($1<16)?"BAD":"ok"}' mvp_runs3/incast.cm | sort | uniq -c
```
Expected: `Nodes 128` / `Connections 32`; first flow `16->0 start 0 size 20000000`; connections = 32; the BAD/ok check shows 32 `ok` and no `BAD` (all senders are hosts ≥16, i.e. outside pod0); dest is host 0.

- [ ] **Step 4: Commit**

```bash
cd /home/leo/htsim
git add htsim/sim/datacenter/mvp_runs3/.gitignore htsim/sim/datacenter/mvp_runs3/gen_incast.py
git commit -m "Add incast .cm generator + mvp_runs3 gitignore"
```

---

## Task 3: Per-path RTT decomposition analysis + unit tests (TDD)

**Files:**
- Create: `mvp_runs3/pathrtt_analyze.py`
- Test: `mvp_runs3/test_pathrtt_analyze.py` (self-contained, no pytest)

- [ ] **Step 1: Write the failing test**

Create `mvp_runs3/test_pathrtt_analyze.py`:
```python
#!/usr/bin/env python3
"""Self-contained tests for pathrtt_analyze (no pytest). Run: python3 test_pathrtt_analyze.py"""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pathrtt_analyze as A

def _csv(rows):
    f = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False)
    for r in rows:
        f.write(",".join(str(x) for x in r) + "\n")
    f.close()
    return f.name

def test_rtt_min_per_path():
    rows = [(1000,0,10,100),(12000,0,10,150),(2000,0,20,200),(13000,0,20,260)]
    p = _csv(rows); data = A.parse_csv(p); os.unlink(p)
    mins = A.rtt_min_per_path(data)
    assert mins[(0,10)] == 100, mins
    assert mins[(0,20)] == 200, mins
    print("ok rtt_min_per_path")

def test_decompose_bins_and_carryforward():
    # flow 0, two paths. bin=10000ns (10us). t in [0,30000).
    rows = [(1000,0,10,100),(2000,0,20,200),    # bin0: latest 100,200 -> q 0,0
            (12000,0,10,150),(13000,0,20,260)]  # bin1: latest 150,260 -> q 50,60
    p = _csv(rows); data = A.parse_csv(p); os.unlink(p)
    mins = A.rtt_min_per_path(data)
    times, cspray, ccc = A.decompose(data, mins, flow_id=0, bin_ns=10000, t0=0, t1=30000)
    # three bins: [0,10000) [10000,20000) [20000,30000)
    assert times == [0, 10000, 20000], times
    # bin0: q10=0, q20=0 -> ccc=0, cspray=0
    assert ccc[0] == 0 and cspray[0] == 0, (ccc, cspray)
    # bin1: q10=150-100=50, q20=260-200=60 -> ccc=50, cspray=10
    assert ccc[1] == 50 and cspray[1] == 10, (ccc, cspray)
    # bin2: no new samples -> carry forward latest (150,260) -> same as bin1
    assert ccc[2] == 50 and cspray[2] == 10, (ccc, cspray)
    print("ok decompose (binning + carry-forward + min/max)")

def test_steady_stats():
    s = A.steady_stats([100,600,1000,1600],[9.0,1.0,3.0,9.0],500,1500)
    assert s["n"]==2 and abs(s["mean"]-2.0)<1e-9 and abs(s["median"]-2.0)<1e-9, s
    print("ok steady_stats")

if __name__ == "__main__":
    test_rtt_min_per_path()
    test_decompose_bins_and_carryforward()
    test_steady_stats()
    print("ALL PASS")
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter/mvp_runs3
python3 test_pathrtt_analyze.py
```
Expected: FAIL — `ModuleNotFoundError: No module named 'pathrtt_analyze'`.

- [ ] **Step 3: Write the analysis module**

Create `mvp_runs3/pathrtt_analyze.py`:
```python
#!/usr/bin/env python3
"""Decompose per-path RTT into C_cc = min_i q_i and C_spray = max_i q_i - min_i q_i,
where q_i = (latest raw_rtt on path i) - (historical min raw_rtt on path i), per flow.
Reads the PRISM_PATHRTT CSV: time_ns,flow_id,path_id,raw_rtt_ns
Usage: python3 pathrtt_analyze.py <tag> [<tag> ...]   (reads mvp_runs3/<tag>.pathrtt.csv)
"""
import sys, os, collections
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
BIN_NS = 10_000          # 10 us bins
WIN = (500.0, 1500.0)    # steady window, us

def parse_csv(path):
    """-> list of (t_ns, flow, path, rtt_ns), all ints, sorted by time."""
    rows = []
    with open(path) as f:
        for line in f:
            p = line.split(",")
            if len(p) != 4:
                continue
            try:
                rows.append((int(p[0]), int(p[1]), int(p[2]), int(p[3])))
            except ValueError:
                continue
    rows.sort(key=lambda r: r[0])
    return rows

def rtt_min_per_path(rows):
    """(flow,path) -> min raw_rtt over the whole run."""
    m = {}
    for t, flow, path, rtt in rows:
        k = (flow, path)
        if k not in m or rtt < m[k]:
            m[k] = rtt
    return m

def decompose(rows, rtt_min, flow_id, bin_ns=BIN_NS, t0=None, t1=None):
    """For one flow: (times_ns, c_spray_ns, c_cc_ns), one entry per bin in [t0,t1).
    Per bin, q_i = (latest raw_rtt seen on path i up to bin end) - rtt_min[(flow,i)],
    over paths observed so far (carry-forward last rtt). Empty path-set bins are skipped."""
    fr = [r for r in rows if r[1] == flow_id]
    if not fr:
        return [], [], []
    if t0 is None:
        t0 = (fr[0][0] // bin_ns) * bin_ns
    if t1 is None:
        t1 = fr[-1][0] + 1
    latest = {}        # path -> latest raw_rtt seen
    idx = 0
    times, cspray, ccc = [], [], []
    b = t0
    while b < t1:
        bin_end = b + bin_ns
        while idx < len(fr) and fr[idx][0] < bin_end:
            _, _, path, rtt = fr[idx]
            latest[path] = rtt
            idx += 1
        if latest:
            qs = [latest[p] - rtt_min[(flow_id, p)] for p in latest]
            times.append(b)
            cspray.append(max(qs) - min(qs))
            ccc.append(min(qs))
        b = bin_end
    return times, cspray, ccc

def steady_stats(times_us, series, lo=WIN[0], hi=WIN[1]):
    w = sorted(v for t, v in zip(times_us, series) if lo <= t <= hi)
    if not w:
        return {"mean": 0.0, "median": 0.0, "p95": 0.0, "n": 0}
    n = len(w)
    return {"mean": sum(w)/n, "median": (w[(n-1)//2]+w[n//2])/2,
            "p95": w[min(n-1, int(0.95*n))], "n": n}

def representative_flow(rows):
    """flow_id with the most RTT samples (best per-path statistics)."""
    c = collections.Counter(r[1] for r in rows)
    return c.most_common(1)[0][0] if c else None

def analyze_tag(tag):
    rows = parse_csv(os.path.join(HERE, f"{tag}.pathrtt.csv"))
    mins = rtt_min_per_path(rows)
    flow = representative_flow(rows)
    t_ns, cs_ns, cc_ns = decompose(rows, mins, flow)
    t_us = [t/1000.0 for t in t_ns]
    cs_us = [x/1000.0 for x in cs_ns]
    cc_us = [x/1000.0 for x in cc_ns]
    cs_s = steady_stats(t_us, cs_us)
    cc_s = steady_stats(t_us, cc_us)

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(t_us, cs_us, label="C_spray = max-min", linewidth=1.0)
    ax.plot(t_us, cc_us, label="C_cc = min", linewidth=1.0, linestyle="--")
    ax.axvspan(WIN[0], WIN[1], color="grey", alpha=0.12)
    ax.set_xlabel("time (us)"); ax.set_ylabel("per-path queueing delay q (us)")
    ax.set_title(f"{tag} (flow {flow}, {len(mins)} paths)")
    ax.legend(fontsize=8); ax.grid(alpha=0.3); ax.set_xlim(0, 2000)
    plt.tight_layout(); plt.savefig(os.path.join(HERE, f"{tag}.png"), dpi=130); plt.close()

    npaths = len({p for (f, p) in mins if f == flow})
    print(f"{tag:14s} flow{flow} npaths={npaths:3d} samples={len(rows):6d}  "
          f"C_spray mean={cs_s['mean']:6.2f} p95={cs_s['p95']:6.2f}us  "
          f"C_cc mean={cc_s['mean']:6.2f} p95={cc_s['p95']:6.2f}us")
    return {"tag": tag, "cspray": cs_s, "ccc": cc_s, "flow": flow, "npaths": npaths}

if __name__ == "__main__":
    for tag in sys.argv[1:]:
        analyze_tag(tag)
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter/mvp_runs3
python3 test_pathrtt_analyze.py
```
Expected: prints `ok rtt_min_per_path` / `ok decompose (binning + carry-forward + min/max)` / `ok steady_stats` / `ALL PASS`.

- [ ] **Step 5: Commit**

```bash
cd /home/leo/htsim
git add htsim/sim/datacenter/mvp_runs3/pathrtt_analyze.py htsim/sim/datacenter/mvp_runs3/test_pathrtt_analyze.py
git commit -m "Add per-path RTT decomposition analysis + unit tests"
```

---

## Task 4: Run helper

**Files:**
- Create: `mvp_runs3/run_one.sh`

- [ ] **Step 1: Write the helper**

Create `mvp_runs3/run_one.sh`:
```bash
#!/bin/bash
# Run one config with per-path RTT logging. Args: lb_algo, failed, tag, [cm_file].
set -euo pipefail
DC="$(cd "$(dirname "$0")/.." && pwd)"   # .../sim/datacenter
cd "$DC"
LB="$1"; FAILED="$2"; TAG="$3"; CM="${4:-mvp_runs3/incast.cm}"
OUT=mvp_runs3
echo "[run_one] lb=$LB failed=$FAILED tag=$TAG cm=$CM"
PRISM_PATHRTT="$OUT/$TAG.pathrtt.csv" ./htsim_uec \
    -topo topologies/fat_tree_128_1os.topo -tm "$CM" -nodes 128 \
    -sender_cc_algo nscc -load_balancing_algo "$LB" -failed "$FAILED" -mtu 4150 \
    -end 2 -o /dev/null > "$OUT/$TAG.stdout" 2>&1
echo "[run_one] done $TAG: $(wc -l < "$OUT/$TAG.pathrtt.csv") rtt rows; $(grep -m1 'Load balancing algorithm set to' "$OUT/$TAG.stdout")"
```

- [ ] **Step 2: Make executable + syntax check**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter
chmod +x mvp_runs3/run_one.sh
bash -n mvp_runs3/run_one.sh && echo "syntax ok"
```
Expected: `syntax ok`.

- [ ] **Step 3: Commit**

```bash
cd /home/leo/htsim
git add htsim/sim/datacenter/mvp_runs3/run_one.sh
git commit -m "Add run_one.sh helper for per-path RTT incast runs"
```

---

## Task 5: Phase 0 — decisive smoke run + sample-sufficiency checkpoint

This is a **gate**. The risk (per spec §7) is too few RTT samples per path. Verify the decisive run produces enough per-path data AND shows both C_spray and C_cc non-zero, before committing to the full matrix.

- [ ] **Step 1: Run the decisive config (REPS, incast, failed=8)**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter
time bash mvp_runs3/run_one.sh reps 8 reps_a8
grep -c 'Adding link failure' mvp_runs3/reps_a8.stdout
```
Expected: `[run_one] done reps_a8: <rows> rtt rows; Load balancing algorithm set to  reps`; the `Adding link failure` count is 8 (US0,US1 ingress degraded). Record wall-clock and row count.

- [ ] **Step 2: Analyze and check sample sufficiency + non-zero decomposition**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter
python3 mvp_runs3/pathrtt_analyze.py reps_a8
```
Expected: prints one line with `npaths`, `samples`, and steady-window `C_spray`/`C_cc`.
**Gate (all must hold to proceed):**
- representative flow `npaths >= 4` and total `samples >= 1000` (enough per-path data; rule of thumb ≥ a few samples per path per steady window). 
- `C_cc mean > 0` (a real floor — the incast shared bottleneck shows up on every path).
- `C_spray mean > 0` (asymmetry produces path spread).
- `mvp_runs3/reps_a8.png` exists and the two curves are visibly distinct.

**If the gate fails, STOP and report** with the numbers, and the likely fix (do not silently proceed):
- too few samples/paths → raise incast persistence (larger flow `size`, or `-end 3`), or reduce sender count, or incast to a few hosts instead of one (regenerate `incast.cm`);
- `C_cc ≈ 0` → incast not saturating the shared last hop → increase sender count `N` or flow size;
- `C_spray ≈ 0` → asymmetry not biting the measured flow's paths → check the flow's senders actually traverse US0/US1; consider `-failed 4`/`12`.

- [ ] **Step 3: Record the smoke outcome**

```bash
cd /home/leo/htsim/htsim/sim/datacenter
python3 mvp_runs3/pathrtt_analyze.py reps_a8 > mvp_runs3/smoke.txt
echo "smoke recorded:"; cat mvp_runs3/smoke.txt
cd /home/leo/htsim && git add -f htsim/sim/datacenter/mvp_runs3/smoke.txt && git commit -m "Record Phase-0 smoke (decisive run sample-sufficiency + nonzero decomposition)"
```

---

## Task 6: Phase 1 — full experiment matrix

Only after Task 5's gate passes. Reuse `mvp_runs3/incast.cm` (N=32→host0) except where a config needs a different incast degree (regenerate to a distinct `.cm`).

- [ ] **Step 1: LB ablation + symmetric control**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter
bash mvp_runs3/run_one.sh oblivious 8 obl_a8     # LB ablation: expect higher C_spray, similar C_cc
bash mvp_runs3/run_one.sh reps 0 reps_a0          # symmetric control: expect C_spray~0, C_cc>0
grep -m1 'Load balancing algorithm set to' mvp_runs3/obl_a8.stdout
```
Expected: each prints `done` with row counts; `obl_a8` confirms `oblivious`.

- [ ] **Step 2: Asymmetry sweep (REPS, failed 0/4/8/12)**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter
for F in 4 12; do bash mvp_runs3/run_one.sh reps $F reps_a$F; done
# reps_a0 (failed 0) and reps_a8 (failed 8) already exist from Task 5/Step 1
```
Expected: `reps_a4`, `reps_a12` produced with the right `Adding link failure` counts (4 and 12).

- [ ] **Step 3: Load sweep (incast degree 16/32/64; 32 already = reps_a8)**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter
python3 mvp_runs3/gen_incast.py mvp_runs3/incast16.cm 16 0 20000000 128 16
python3 mvp_runs3/gen_incast.py mvp_runs3/incast64.cm 64 0 20000000 128 16
bash mvp_runs3/run_one.sh reps 8 reps_n16 mvp_runs3/incast16.cm
bash mvp_runs3/run_one.sh reps 8 reps_n64 mvp_runs3/incast64.cm
```
Expected: both produce non-empty `.pathrtt.csv`. (`reps_n32` ≡ `reps_a8`.)

- [ ] **Step 4: Sanity-check all runs produced data**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter
for t in reps_a0 reps_a4 reps_a8 reps_a12 obl_a8 reps_n16 reps_n64; do \
  echo "$t: $(wc -l < mvp_runs3/$t.pathrtt.csv 2>/dev/null || echo MISSING) rows"; done
```
Expected: every tag has > 0 rows; no `MISSING`. Investigate any empty file's `.stdout` before analyzing.

---

## Task 7: Phase 2 — figures, summary, assessment, report

**Files:**
- Create: `mvp_runs3/summary.txt`, `mvp_runs3/assessment.txt`
- Create: `mvp_runs3/make_figures.py` (the 4 demonstration figures from spec §5)

- [ ] **Step 1: Per-tag decomposition table + per-tag PNGs**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter
python3 mvp_runs3/pathrtt_analyze.py reps_a0 reps_a4 reps_a8 reps_a12 obl_a8 reps_n16 reps_n64 | tee mvp_runs3/summary.txt
```
Expected: a row per tag (npaths, samples, C_spray mean/p95, C_cc mean/p95) and one `.png` per tag.

- [ ] **Step 2: Write the 4 demonstration figures**

Create `mvp_runs3/make_figures.py`:
```python
#!/usr/bin/env python3
"""Four demonstration figures for the PRISM per-path-RTT decomposition.
Run: python3 make_figures.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pathrtt_analyze as A

HERE = os.path.dirname(os.path.abspath(__file__))

def steady(tag):
    rows = A.parse_csv(os.path.join(HERE, f"{tag}.pathrtt.csv"))
    mins = A.rtt_min_per_path(rows); flow = A.representative_flow(rows)
    t, cs, cc = A.decompose(rows, mins, flow)
    t_us=[x/1000 for x in t]; cs_us=[x/1000 for x in cs]; cc_us=[x/1000 for x in cc]
    return A.steady_stats(t_us,cs_us)["mean"], A.steady_stats(t_us,cc_us)["mean"], (t_us,cs_us,cc_us)

# Fig 1: decisive run time series
_,_,(t,cs,cc) = steady("reps_a8")
plt.figure(figsize=(10,4)); plt.plot(t,cs,label="C_spray = max-min"); plt.plot(t,cc,"--",label="C_cc = min")
plt.axvspan(500,1500,color="grey",alpha=0.12); plt.xlabel("time (us)"); plt.ylabel("per-path q (us)")
plt.title("Decisive run (REPS, incast, failed=8): C_spray and C_cc"); plt.legend(); plt.grid(alpha=.3); plt.xlim(0,2000)
plt.tight_layout(); plt.savefig(f"{HERE}/fig1_decisive.png",dpi=130); plt.close()

# Fig 2: LB contrast (REPS vs OBLIVIOUS at failed=8)
rs,rc,_ = steady("reps_a8"); os_,oc,_ = steady("obl_a8")
x=[0,1]; w=0.35
plt.figure(figsize=(7,4))
plt.bar([i-w/2 for i in x],[rs,rc],w,label="REPS"); plt.bar([i+w/2 for i in x],[os_,oc],w,label="OBLIVIOUS")
plt.xticks(x,["C_spray","C_cc"]); plt.ylabel("steady mean per-path q (us)")
plt.title("LB contrast @ failed=8: LB lowers C_spray, not C_cc"); plt.legend(); plt.grid(alpha=.3,axis="y")
plt.tight_layout(); plt.savefig(f"{HERE}/fig2_lb_contrast.png",dpi=130); plt.close()

# Fig 3: symmetric vs asymmetric (REPS failed 0 vs 8)
s0,c0,_ = steady("reps_a0"); s8,c8,_ = steady("reps_a8")
plt.figure(figsize=(7,4))
plt.bar([i-w/2 for i in x],[s0,c0],w,label="failed=0 (sym)"); plt.bar([i+w/2 for i in x],[s8,c8],w,label="failed=8 (asym)")
plt.xticks(x,["C_spray","C_cc"]); plt.ylabel("steady mean per-path q (us)")
plt.title("Asymmetry turns on C_spray; C_cc present in both (incast)"); plt.legend(); plt.grid(alpha=.3,axis="y")
plt.tight_layout(); plt.savefig(f"{HERE}/fig3_sym_vs_asym.png",dpi=130); plt.close()

# Fig 4: sweeps -- C_spray vs failed; C_cc vs incast degree
fails=[0,4,8,12]; spray=[steady(f"reps_a{f}")[0] for f in fails]
degs=[16,32,64]; cctags=["reps_n16","reps_a8","reps_n64"]; ccv=[steady(t)[1] for t in cctags]
fig,(a1,a2)=plt.subplots(1,2,figsize=(11,4))
a1.plot(fails,spray,"o-"); a1.set_xlabel("-failed (asymmetry)"); a1.set_ylabel("C_spray mean (us)")
a1.set_title("C_spray grows with asymmetry (LB territory)"); a1.grid(alpha=.3)
a2.plot(degs,ccv,"s-"); a2.set_xlabel("incast degree N"); a2.set_ylabel("C_cc mean (us)")
a2.set_title("C_cc grows with load (CC territory)"); a2.grid(alpha=.3)
plt.tight_layout(); plt.savefig(f"{HERE}/fig4_sweeps.png",dpi=130); plt.close()
print("wrote fig1_decisive.png fig2_lb_contrast.png fig3_sym_vs_asym.png fig4_sweeps.png")
```

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter && python3 mvp_runs3/make_figures.py && ls -la mvp_runs3/fig*.png
```
Expected: prints the 4 filenames; all 4 PNGs exist.

- [ ] **Step 3: Evaluate the §6 criteria and write the assessment**

Read `summary.txt` and the figures, then check (record each verdict with numbers):
- decisive `reps_a8`: C_spray mean > 0 AND C_cc mean > 0, curves distinct (fig1);
- LB removes spray: `obl_a8` C_spray ≫ `reps_a8` C_spray (fig2);
- CC owns floor: `obl_a8` C_cc ≈ `reps_a8` C_cc (fig2);
- orthogonal drivers: C_spray rises with failed (fig4 left), ~flat in C_cc; C_cc rises with incast degree (fig4 right).

Create `mvp_runs3/assessment.txt` with: scenario recap; the summary table; the four verdicts each with numbers; conclusion (`分解成立 / 部分成立 / 退化`, strictly per criteria); 意外; 下一步. (If conclusion ≠ 成立, do not recommend entering PRISM implementation.)

- [ ] **Step 4: Commit text deliverables**

```bash
cd /home/leo/htsim
git add htsim/sim/datacenter/mvp_runs3/make_figures.py
git add -f htsim/sim/datacenter/mvp_runs3/summary.txt htsim/sim/datacenter/mvp_runs3/assessment.txt
git commit -m "Add per-path RTT incast results: figures + summary + assessment"
```

- [ ] **Step 5: Report to the user**

Present: the 4 demonstration figures (paths), the summary table, the four criteria verdicts with numbers, and the structured conclusion. State budget actuals and any deviations from the design (e.g. tuned incast degree/flow size from the smoke gate). Do not draw the final go/no-go.

---

## Self-review notes (author checks)

- **Spec coverage:** §1 hook → Task 1; §2 metric → Task 3 (`rtt_min_per_path`/`decompose`); §3 scenario → Task 2 + run_one; §4 matrix → Tasks 5-6; §5 figures → Task 7; §6 judgment → Task 7 Step 3; §7 sample-sufficiency risk → Task 5 gate.
- **Placeholder scan:** every file's full code is present; commands have expected output; no TBD/TODO. The smoke gate has concrete numeric thresholds and explicit fixes.
- **Type/name consistency:** `parse_csv`→list of 4-tuples; `rtt_min_per_path`→dict keyed `(flow,path)`; `decompose(rows, rtt_min, flow_id, bin_ns, t0, t1)`→`(times_ns, cspray_ns, ccc_ns)`; `steady_stats(times_us, series, lo, hi)`. Test and module and `make_figures.py` use these identically. CSV field order `time_ns,flow_id,path_id,raw_rtt_ns` matches the C++ hook in Task 1.
- **Known risk:** Task 5 is a hard gate; if incast doesn't produce sufficient per-path samples or a nonzero floor, it stops for a reported tuning decision rather than proceeding to a meaningless matrix.
