# PRISM Eval P0 — Harness Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the shared `prism_eval/common/` harness — workload generators, metric parsers (FCT + goodput), a unified simulator-run wrapper, and a shared plot style — so every later experiment group can generate traffic, run htsim_uec, and extract numbers with one code path.

**Architecture:** A new evaluation root `htsim/sim/datacenter/prism_eval/` parallel to the frozen motivation dir `mvp_runs3/`. All cross-group code lives in `common/`: flat Python modules (`gen/*.py`, `metrics.py`, `plot_style.py`) plus a Bash runner (`run_lib.sh`) that wraps the existing `htsim_uec` binary and decodes its `.dat` trace. Tests are plain-Python assert scripts (matching the existing `test_gen_overload.py` style), run via `python3`.

**Tech Stack:** Python 3 (stdlib only: `random`, `statistics`, `collections`), Bash, the prebuilt `htsim_uec` + `../build/parse_output` decoder, matplotlib (Agg).

---

> **COMMIT POLICY (overrides the skill's default):** The user has a standing instruction **not to `git commit` unless explicitly asked**. Each task below ends with a "Stage & checkpoint" step: run `git add` for the listed files and **pause** — do NOT run `git commit` until the user explicitly approves (commits may be batched at the end). Treat the `git commit` lines as the message to use *when* approval is given.

## File structure (created by this plan)

```
htsim/sim/datacenter/prism_eval/
├── .gitignore                 # ignore regenerable data (*.dat,*.txt,*.cm,*.stdout,*.idmap,*.ascii.tmp)
└── common/
    ├── plot_style.py          # shared matplotlib style + save() + palette
    ├── metrics.py             # fct_stats(), goodput_gbps(), parse_flow_events()
    ├── run_lib.sh             # unified htsim_uec runner + .dat decode
    ├── gen/
    │   ├── permutation.py     # random 1:1 sender↔receiver matching (derangement)
    │   ├── many2many.py       # sender group → receiver group (pairs | all)
    │   └── incast.py          # many→one (generalized from gen_incast)
    └── tests/
        ├── test_generators.py # selftests for the three generators
        └── test_metrics.py    # selftests for fct_stats + goodput_gbps
```

Algorithm code (PRISM/STrack) is **not** in this plan — it lands in `uec.cpp` in P1/P3.

---

### Task 1: Scaffold dirs, .gitignore, and shared plot style

**Files:**
- Create: `htsim/sim/datacenter/prism_eval/.gitignore`
- Create: `htsim/sim/datacenter/prism_eval/common/plot_style.py`
- Create dirs: `prism_eval/common/gen/`, `prism_eval/common/tests/`

- [ ] **Step 1: Create directories**

Run:
```bash
mkdir -p /home/leo/htsim/htsim/sim/datacenter/prism_eval/common/gen \
         /home/leo/htsim/htsim/sim/datacenter/prism_eval/common/tests
```

- [ ] **Step 2: Write `.gitignore`**

Create `htsim/sim/datacenter/prism_eval/.gitignore`:
```gitignore
# regenerable simulation data — figures are force-added per group with `git add -f`
*.dat
*.txt
*.cm
*.stdout
*.idmap
*.ascii.tmp
*.csv
__pycache__/
```

- [ ] **Step 3: Write `common/plot_style.py`**

Create `htsim/sim/datacenter/prism_eval/common/plot_style.py`:
```python
"""Shared matplotlib style + helpers for all prism_eval figures.
Keeps fonts/colors consistent across the paper. Agg backend (headless)."""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

# One palette for the whole evaluation. Keys are the baselines / signals.
COLORS = {
    "ops": "tab:gray",
    "reps": "tab:blue",
    "strack": "tab:orange",
    "prism": "tab:green",
    "ccc": "tab:red",      # C_cc / floor
    "spray": "tab:orange",  # C_spray / spread band
    "target": "gray",
}

def apply_style(font_size=12):
    """Apply the shared rcParams. Call once at the top of each make_figs.py."""
    plt.rcParams.update({
        "font.size": font_size,
        "axes.grid": True,
        "grid.alpha": 0.3,
        "figure.dpi": 140,
    })

def save(fig, stem, outdir):
    """Save a figure as both PNG and PDF under outdir, tightly cropped."""
    os.makedirs(outdir, exist_ok=True)
    for ext in ("png", "pdf"):
        fig.savefig(os.path.join(outdir, f"{stem}.{ext}"),
                    bbox_inches="tight", pad_inches=0.04)
```

- [ ] **Step 4: Verify it imports**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter/prism_eval/common && python3 -c "import plot_style; plot_style.apply_style(); print('ok plot_style', plot_style.COLORS['prism'])"
```
Expected: `ok plot_style tab:green`

- [ ] **Step 5: Stage & checkpoint** (do NOT commit until approved)

```bash
git add -f htsim/sim/datacenter/prism_eval/.gitignore htsim/sim/datacenter/prism_eval/common/plot_style.py
git commit -m "prism_eval P0: scaffold dirs, gitignore, shared plot style"
```

---

### Task 2: Permutation generator (TDD)

**Files:**
- Test: `prism_eval/common/tests/test_generators.py`
- Create: `prism_eval/common/gen/permutation.py`

- [ ] **Step 1: Write the failing test**

Create `htsim/sim/datacenter/prism_eval/common/tests/test_generators.py`:
```python
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "gen"))
import permutation  # noqa: E402

def _parse_cm(text):
    """Parse a .cm string into [(src,dst),...] and validate the header counts."""
    lines = text.strip().split("\n")
    assert lines[0].startswith("Nodes "), lines[0]
    assert lines[1].startswith("Connections "), lines[1]
    declared = int(lines[1].split()[1])
    conns = []
    for ln in lines[2:]:
        lhs = ln.split(" start ")[0]          # "<s>-><d>"
        s, d = lhs.split("->")
        conns.append((int(s), int(d)))
    assert len(conns) == declared, (len(conns), declared)
    return conns

def test_permutation():
    text, conns = permutation.build(active_frac=0.5, size=1000, nodes=128, seed=1)
    assert _parse_cm(text) == conns
    srcs = [s for s, _ in conns]
    dsts = [d for _, d in conns]
    assert len(set(srcs)) == len(srcs), "senders must be distinct"
    assert len(set(dsts)) == len(dsts), "receivers must be distinct"
    assert all(s != d for s, d in conns), "no self-pair"
    assert all(0 <= s < 128 and 0 <= d < 128 for s, d in conns), "valid host ids"
    # determinism: same seed -> identical output
    text2, _ = permutation.build(active_frac=0.5, size=1000, nodes=128, seed=1)
    assert text2 == text
    # different seed -> different matching (overwhelmingly likely at this size)
    text3, _ = permutation.build(active_frac=0.5, size=1000, nodes=128, seed=2)
    assert text3 != text
    print("ok permutation")

if __name__ == "__main__":
    test_permutation()
    print("ALL PASS")
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter/prism_eval/common/tests && python3 test_generators.py
```
Expected: FAIL — `ModuleNotFoundError: No module named 'permutation'`

- [ ] **Step 3: Write minimal implementation**

Create `htsim/sim/datacenter/prism_eval/common/gen/permutation.py`:
```python
#!/usr/bin/env python3
"""Permutation .cm: a random one-to-one matching of active hosts (each active host
sends to exactly one distinct active host; no self-pairs). Deterministic given seed.
Uses Sattolo's algorithm so the matching is a single cycle (guaranteed derangement).
Connection-matrix `start` is in picoseconds (we use 0 = all start together).
Usage: permutation.py <out.cm> [active_frac] [size] [nodes] [seed]
"""
import sys, random

def _sattolo(items, rng):
    """In-place single-cycle shuffle (no fixed points for len>=2)."""
    a = items[:]
    for i in range(len(a) - 1, 0, -1):
        j = rng.randint(0, i - 1)   # strictly j < i -> no element stays in place
        a[i], a[j] = a[j], a[i]
    return a

def build(active_frac=1.0, size=2_000_000, nodes=128, seed=0):
    if not (0 < active_frac <= 1.0):
        raise ValueError(f"active_frac must be in (0,1], got {active_frac}")
    k = max(2, int(round(active_frac * nodes)))
    if k > nodes:
        k = nodes
    rng = random.Random(seed)
    senders = rng.sample(range(nodes), k)
    receivers = _sattolo(senders, rng)   # derangement of the same active set
    conns = list(zip(senders, receivers))
    lines = [f"Nodes {nodes}", f"Connections {len(conns)}"]
    lines += [f"{s}->{d} start 0 size {size}" for s, d in conns]
    return "\n".join(lines) + "\n", conns

def main():
    out = sys.argv[1]
    active_frac = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
    size = int(sys.argv[3]) if len(sys.argv) > 3 else 2_000_000
    nodes = int(sys.argv[4]) if len(sys.argv) > 4 else 128
    seed = int(sys.argv[5]) if len(sys.argv) > 5 else 0
    text, conns = build(active_frac, size, nodes, seed)
    with open(out, "w") as fh:
        fh.write(text)
    print(f"wrote {out}: {len(conns)} flows, active_frac={active_frac}, nodes={nodes}, seed={seed}")

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter/prism_eval/common/tests && python3 test_generators.py
```
Expected: `ok permutation` then `ALL PASS`

- [ ] **Step 5: Stage & checkpoint** (do NOT commit until approved)

```bash
git add -f htsim/sim/datacenter/prism_eval/common/gen/permutation.py htsim/sim/datacenter/prism_eval/common/tests/test_generators.py
git commit -m "prism_eval P0: permutation generator + selftest"
```

---

### Task 3: Many-to-many generator (TDD)

**Files:**
- Modify: `prism_eval/common/tests/test_generators.py` (add two tests + call them)
- Create: `prism_eval/common/gen/many2many.py`

- [ ] **Step 1: Add failing tests**

In `test_generators.py`, add `import many2many` next to the `import permutation` line:
```python
import permutation  # noqa: E402
import many2many  # noqa: E402
```
Then add these two functions before the `if __name__` block:
```python
def test_many2many_pairs():
    text, conns = many2many.build(n_send=8, n_recv=4, pattern="pairs",
                                  size=1000, nodes=128, hpp=16, seed=1)
    assert _parse_cm(text) == conns
    assert len(conns) == 8, len(conns)
    assert all(d < 16 for _, d in conns), "receivers in pod0"
    assert all(s >= 16 for s, _ in conns), "senders outside pod0"
    print("ok many2many pairs")

def test_many2many_all():
    text, conns = many2many.build(n_send=3, n_recv=4, pattern="all",
                                  size=1000, nodes=128, hpp=16, seed=1)
    assert _parse_cm(text) == conns
    assert len(conns) == 12, "cross product 3x4"
    print("ok many2many all")
```
And update the `__main__` block to call them:
```python
if __name__ == "__main__":
    test_permutation()
    test_many2many_pairs()
    test_many2many_all()
    print("ALL PASS")
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter/prism_eval/common/tests && python3 test_generators.py
```
Expected: FAIL — `ModuleNotFoundError: No module named 'many2many'`

- [ ] **Step 3: Write minimal implementation**

Create `htsim/sim/datacenter/prism_eval/common/gen/many2many.py`:
```python
#!/usr/bin/env python3
"""Many-to-many .cm: a sender group (hosts OUTSIDE pod0) sends into a receiver group
(the first n_recv hosts of pod0), forcing traffic across the core into the (possibly
-failed) ingress. pattern='pairs': each sender -> one pod0 receiver, round-robin.
pattern='all': cross product (each sender -> every receiver). `start` in picoseconds.
Usage: many2many.py <out.cm> [n_send] [n_recv] [pattern] [size] [nodes] [hpp] [seed]
"""
import sys

def build(n_send=8, n_recv=4, pattern="pairs", size=2_000_000,
          nodes=128, hpp=16, seed=0):
    if n_recv < 1 or n_recv > hpp:
        raise ValueError(f"n_recv must be in [1,{hpp}], got {n_recv}")
    receivers = list(range(n_recv))                       # pod0 hosts 0..n_recv-1
    senders = [h for h in range(nodes) if h // hpp != 0][:n_send]  # outside pod0
    if len(senders) != n_send:
        raise ValueError(f"need {n_send} senders outside pod0, have {len(senders)}")
    if pattern == "pairs":
        conns = [(s, receivers[i % n_recv]) for i, s in enumerate(senders)]
    elif pattern == "all":
        conns = [(s, d) for s in senders for d in receivers]
    else:
        raise ValueError(f"pattern must be 'pairs' or 'all', got {pattern}")
    lines = [f"Nodes {nodes}", f"Connections {len(conns)}"]
    lines += [f"{s}->{d} start 0 size {size}" for s, d in conns]
    return "\n".join(lines) + "\n", conns

def main():
    out = sys.argv[1]
    n_send = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    n_recv = int(sys.argv[3]) if len(sys.argv) > 3 else 4
    pattern = sys.argv[4] if len(sys.argv) > 4 else "pairs"
    size = int(sys.argv[5]) if len(sys.argv) > 5 else 2_000_000
    nodes = int(sys.argv[6]) if len(sys.argv) > 6 else 128
    hpp = int(sys.argv[7]) if len(sys.argv) > 7 else 16
    seed = int(sys.argv[8]) if len(sys.argv) > 8 else 0
    text, conns = build(n_send, n_recv, pattern, size, nodes, hpp, seed)
    with open(out, "w") as fh:
        fh.write(text)
    print(f"wrote {out}: {len(conns)} flows, {n_send}->{n_recv} pattern={pattern}")

if __name__ == "__main__":
    main()
```
(`seed` is accepted for a uniform generator interface; this deterministic pattern does not need it yet.)

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter/prism_eval/common/tests && python3 test_generators.py
```
Expected: `ok permutation` / `ok many2many pairs` / `ok many2many all` / `ALL PASS`

- [ ] **Step 5: Stage & checkpoint** (do NOT commit until approved)

```bash
git add -f htsim/sim/datacenter/prism_eval/common/gen/many2many.py htsim/sim/datacenter/prism_eval/common/tests/test_generators.py
git commit -m "prism_eval P0: many2many generator + selftest"
```

---

### Task 4: Incast generator (TDD)

**Files:**
- Modify: `prism_eval/common/tests/test_generators.py` (add one test + call it)
- Create: `prism_eval/common/gen/incast.py`

- [ ] **Step 1: Add failing test**

In `test_generators.py`, add `import incast` after the other gen imports:
```python
import incast  # noqa: E402
```
Add this function before `if __name__`:
```python
def test_incast():
    text, conns = incast.build(n=32, dest=0, size=1000, nodes=128, hpp=16)
    assert _parse_cm(text) == conns
    assert len(conns) == 32, len(conns)
    assert all(d == 0 for _, d in conns), "all -> dest 0"
    assert all(s // 16 != 0 for s, _ in conns), "senders outside dest pod"
    # staggered start: distinct picosecond offsets
    text2, _ = incast.build(n=4, dest=0, size=1000, nodes=128, hpp=16,
                            stagger_ps=1000)
    starts = [int(ln.split(" start ")[1].split(" size ")[0])
              for ln in text2.strip().split("\n")[2:]]
    assert starts == [0, 1000, 2000, 3000], starts
    print("ok incast")
```
Update `__main__`:
```python
if __name__ == "__main__":
    test_permutation()
    test_many2many_pairs()
    test_many2many_all()
    test_incast()
    print("ALL PASS")
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter/prism_eval/common/tests && python3 test_generators.py
```
Expected: FAIL — `ModuleNotFoundError: No module named 'incast'`

- [ ] **Step 3: Write minimal implementation**

Create `htsim/sim/datacenter/prism_eval/common/gen/incast.py`:
```python
#!/usr/bin/env python3
"""Incast .cm: N senders (all OUTSIDE the dest's pod) -> one dest host. Optional
per-flow start stagger (picoseconds) so senders ramp in slightly offset. Senders
outside the dest pod force traffic across the core into the (possibly -failed) ingress.
Usage: incast.py <out.cm> [n] [dest] [size] [nodes] [hpp] [stagger_ps]
"""
import sys

def build(n=32, dest=0, size=2_000_000, nodes=128, hpp=16, stagger_ps=0):
    dest_pod = dest // hpp
    if dest >= nodes:
        raise ValueError(f"dest {dest} >= nodes {nodes}")
    senders = [h for h in range(nodes) if h // hpp != dest_pod][:n]
    if len(senders) != n:
        raise ValueError(f"need {n} senders outside pod{dest_pod}, have {len(senders)}")
    conns = [(s, dest) for s in senders]
    lines = [f"Nodes {nodes}", f"Connections {n}"]
    lines += [f"{s}->{dest} start {i * stagger_ps} size {size}"
              for i, s in enumerate(senders)]
    return "\n".join(lines) + "\n", conns

def main():
    out = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 32
    dest = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    size = int(sys.argv[4]) if len(sys.argv) > 4 else 2_000_000
    nodes = int(sys.argv[5]) if len(sys.argv) > 5 else 128
    hpp = int(sys.argv[6]) if len(sys.argv) > 6 else 16
    stagger_ps = int(sys.argv[7]) if len(sys.argv) > 7 else 0
    text, conns = build(n, dest, size, nodes, hpp, stagger_ps)
    with open(out, "w") as fh:
        fh.write(text)
    print(f"wrote {out}: {n} senders -> host{dest}, stagger={stagger_ps}ps")

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter/prism_eval/common/tests && python3 test_generators.py
```
Expected: `ok incast` plus the earlier `ok` lines and `ALL PASS`

- [ ] **Step 5: Stage & checkpoint** (do NOT commit until approved)

```bash
git add -f htsim/sim/datacenter/prism_eval/common/gen/incast.py htsim/sim/datacenter/prism_eval/common/tests/test_generators.py
git commit -m "prism_eval P0: incast generator (with start stagger) + selftest"
```

---

### Task 5: FCT parser (TDD)

**Files:**
- Test: `prism_eval/common/tests/test_metrics.py`
- Create: `prism_eval/common/metrics.py`

- [ ] **Step 1: Write the failing test**

Create `htsim/sim/datacenter/prism_eval/common/tests/test_metrics.py`:
```python
import os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import metrics  # noqa: E402

def test_fct_stats():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "f.flow.txt")
    with open(p, "w") as fh:
        # 3 flows start at t=0, finish at 1ms/2ms/3ms -> FCT 1/2/3 ms
        for fid, tf in [(1, 0.001), (2, 0.002), (3, 0.003)]:
            fh.write(f"0.000000000 Type FLOW_EVENT SrcID {fid} Ev START "
                     f"FlowID {fid} Flowsize 1000\n")
            fh.write(f"{tf:.9f} Type FLOW_EVENT SrcID {fid} Ev FINISH "
                     f"FlowID {fid} Bytes 1000 Pkts 1\n")
        # one flow that started but never finished (no FINISH line)
        fh.write("0.000000000 Type FLOW_EVENT SrcID 4 Ev START "
                 "FlowID 4 Flowsize 1000\n")
    s = metrics.fct_stats(p)
    assert s["completed"] == 3, s
    assert s["total_started"] == 4, s
    assert abs(s["completion_rate"] - 0.75) < 1e-9, s
    assert abs(s["avg_s"] - 0.002) < 1e-9, s
    assert abs(s["max_s"] - 0.003) < 1e-9, s
    assert abs(s["p50_s"] - 0.002) < 1e-9, s
    print("ok fct_stats")

if __name__ == "__main__":
    test_fct_stats()
    print("ALL PASS")
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter/prism_eval/common/tests && python3 test_metrics.py
```
Expected: FAIL — `ModuleNotFoundError: No module named 'metrics'`

- [ ] **Step 3: Write minimal implementation**

Create `htsim/sim/datacenter/prism_eval/common/metrics.py`:
```python
"""Metric parsers for prism_eval. Reads decoded-ASCII htsim logs (produced by
run_lib.sh): flow events (FCT) and UEC_SINK RATE (goodput). Stdlib only."""
import collections
import statistics

def parse_flow_events(path):
    """Return (starts, finishes) dicts keyed by (srcid, flowid).
      starts[key]    = start_time_seconds
      finishes[key]  = (finish_time_seconds, bytes)
    Line format (decoded):
      <t> Type FLOW_EVENT SrcID <id> Ev START  FlowID <fid> Flowsize <b>
      <t> Type FLOW_EVENT SrcID <id> Ev FINISH FlowID <fid> Bytes <b> Pkts <p>
    """
    starts, finishes = {}, {}
    with open(path) as fh:
        for ln in fh:
            t = ln.split()
            if "FLOW_EVENT" not in t:
                continue
            time = float(t[0])
            srcid = int(t[t.index("SrcID") + 1])
            ev = t[t.index("Ev") + 1]
            fid = int(t[t.index("FlowID") + 1])
            key = (srcid, fid)
            if ev == "START":
                starts[key] = time
            elif ev == "FINISH":
                nbytes = int(t[t.index("Bytes") + 1])
                finishes[key] = (time, nbytes)
    return starts, finishes

def _percentile(sorted_vals, p):
    """Nearest-rank percentile on a pre-sorted, non-empty list."""
    if not sorted_vals:
        return float("nan")
    i = int(round(p / 100.0 * (len(sorted_vals) - 1)))
    i = max(0, min(len(sorted_vals) - 1, i))
    return sorted_vals[i]

def fct_stats(flow_path):
    """Flow-completion-time stats (seconds) from a decoded flow-event log.
    Only flows with both START and FINISH count toward FCT; started-but-unfinished
    flows count toward total_started and lower completion_rate."""
    starts, finishes = parse_flow_events(flow_path)
    fcts = sorted(tf - starts[k] for k, (tf, _) in finishes.items() if k in starts)
    total = len(starts)
    completed = len(fcts)
    return {
        "completed": completed,
        "total_started": total,
        "completion_rate": (completed / total) if total else float("nan"),
        "avg_s": statistics.mean(fcts) if fcts else float("nan"),
        "p50_s": _percentile(fcts, 50),
        "p95_s": _percentile(fcts, 95),
        "p99_s": _percentile(fcts, 99),
        "max_s": fcts[-1] if fcts else float("nan"),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter/prism_eval/common/tests && python3 test_metrics.py
```
Expected: `ok fct_stats` then `ALL PASS`

- [ ] **Step 5: Stage & checkpoint** (do NOT commit until approved)

```bash
git add -f htsim/sim/datacenter/prism_eval/common/metrics.py htsim/sim/datacenter/prism_eval/common/tests/test_metrics.py
git commit -m "prism_eval P0: FCT parser (flow events) + selftest"
```

---

### Task 6: Goodput parser (TDD)

**Files:**
- Modify: `prism_eval/common/tests/test_metrics.py` (add test + call it)
- Modify: `prism_eval/common/metrics.py` (add `goodput_gbps`)

- [ ] **Step 1: Add failing test**

In `test_metrics.py`, add before `if __name__`:
```python
def test_goodput():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "g.sink.txt")
    with open(p, "w") as fh:
        # two receivers, steady rates 40 Gbps + 10 Gbps = 50 Gbps, in-window
        for t in ("0.000600000", "0.001000000"):
            fh.write(f"{t} Type UEC_SINK ID 10 Ev RATE CAck 1 "
                     f"ReorderBuffer 0 Rate 40000000000\n")
            fh.write(f"{t} Type UEC_SINK ID 11 Ev RATE CAck 1 "
                     f"ReorderBuffer 0 Rate 10000000000\n")
    g = metrics.goodput_gbps(p, window_s=(0.5e-3, 1.5e-3))
    assert abs(g - 50.0) < 1e-9, g
    print("ok goodput")
```
Update `__main__`:
```python
if __name__ == "__main__":
    test_fct_stats()
    test_goodput()
    print("ALL PASS")
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter/prism_eval/common/tests && python3 test_metrics.py
```
Expected: FAIL — `AttributeError: module 'metrics' has no attribute 'goodput_gbps'`

- [ ] **Step 3: Write minimal implementation**

Append to `htsim/sim/datacenter/prism_eval/common/metrics.py`:
```python
def goodput_gbps(sink_path, window_s=(0.5e-3, 1.5e-3)):
    """Steady-window aggregate goodput (Gbps) = mean over in-window timestamps of the
    summed UEC_SINK Rate (bits/s). Line format (decoded):
      <t> Type UEC_SINK ID <id> Ev RATE CAck <c> ReorderBuffer <r> Rate <bits/s>
    (Rate is token index 12.) Doubles as the utilization signal used by figG/figI."""
    per_t = collections.defaultdict(float)
    with open(sink_path) as fh:
        for ln in fh:
            p = ln.split()
            if len(p) >= 13 and "UEC_SINK" in p:
                per_t[float(p[0])] += float(p[12])
    tail = [v / 1e9 for t, v in per_t.items() if window_s[0] <= t <= window_s[1]]
    return statistics.mean(tail) if tail else 0.0
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter/prism_eval/common/tests && python3 test_metrics.py
```
Expected: `ok fct_stats` / `ok goodput` / `ALL PASS`

- [ ] **Step 5: Stage & checkpoint** (do NOT commit until approved)

```bash
git add -f htsim/sim/datacenter/prism_eval/common/metrics.py htsim/sim/datacenter/prism_eval/common/tests/test_metrics.py
git commit -m "prism_eval P0: goodput parser + selftest"
```

---

### Task 7: Unified simulator runner `run_lib.sh`

**Files:**
- Create: `prism_eval/common/run_lib.sh`

- [ ] **Step 1: Write `run_lib.sh`**

Create `htsim/sim/datacenter/prism_eval/common/run_lib.sh`:
```bash
#!/bin/bash
# common/run_lib.sh -- unified htsim_uec runner for prism_eval.
# Runs ONE simulation, decodes the .dat trace ONCE, and extracts the requested text
# logs. flow_events (FCT) is on by default in the binary; sink/queue need -log flags.
# Per-path RTT is emitted directly by the binary when env PRISM_PATHRTT is set.
#
# Usage:
#   bash common/run_lib.sh CC LB FAILED TOPO SEED CM LOGSPEC TAG OUTDIR
# Positional args:
#   CC       sender_cc_algo: nscc|dctcp|constant|prism|strack
#   LB       load_balancing_algo: reps|oblivious|ecmp|...
#   FAILED   # degraded core->agg downlinks (0 = none)
#   TOPO     topology filename under topologies/ (e.g. fat_tree_128_1os.topo)
#   SEED     RNG seed (int)
#   CM       traffic matrix .cm path, relative to the datacenter dir
#   LOGSPEC  comma list subset of {flow,sink,queue}; include 'flow' for FCT
#   TAG      output basename
#   OUTDIR   output dir, relative to the datacenter dir (created if absent)
# Env knobs: PATHS(8) END_MS(2) MTU(4150) NODES(128) TQD(unset) KEEPDAT(unset)
#            PRISM_PATHRTT(unset -> path "$OUTDIR/$TAG.pathrtt.csv" if you export it)
set -euo pipefail
CC="$1"; LB="$2"; FAILED="$3"; TOPO="$4"; SEED="$5"; CM="$6"; LOGSPEC="$7"; TAG="$8"; OUTDIR="$9"
DC="$(cd "$(dirname "$0")/../.." && pwd)"   # common -> prism_eval -> datacenter
cd "$DC"
PATHS="${PATHS:-8}"; END_MS="${END_MS:-2}"; MTU="${MTU:-4150}"; NODES="${NODES:-128}"
BIN=./htsim_uec
DECODER=../build/parse_output
[ -x "$BIN" ] || { echo "ERROR: $BIN missing -- build htsim_uec first"; exit 1; }
[ -x "$DECODER" ] || { echo "ERROR: $DECODER missing -- build it first"; exit 1; }
mkdir -p "$OUTDIR"
TQD_ARG=""; [ -n "${TQD:-}" ] && TQD_ARG="-target_q_delay ${TQD}"
LOGARGS=""
case ",$LOGSPEC," in *,sink,*)  LOGARGS="$LOGARGS -log sink";; esac
case ",$LOGSPEC," in *,queue,*) LOGARGS="$LOGARGS -log tor_downqueue";; esac
echo "[run_lib] cc=$CC lb=$LB failed=$FAILED topo=$TOPO seed=$SEED cm=$CM log=$LOGSPEC tag=$TAG"
$BIN -topo "topologies/$TOPO" -tm "$CM" -nodes "$NODES" \
     -sender_cc_algo "$CC" -load_balancing_algo "$LB" -failed "$FAILED" -mtu "$MTU" \
     -paths "$PATHS" -seed "$SEED" $TQD_ARG $LOGARGS -end "$END_MS" \
     -o "$OUTDIR/$TAG.dat" > "$OUTDIR/$TAG.stdout" 2>&1
ASCII="$OUTDIR/$TAG.ascii.tmp"
"$DECODER" "$OUTDIR/$TAG.dat" -ascii > "$ASCII" 2>/dev/null || true
case ",$LOGSPEC," in *,flow,*)  grep ' FLOW_EVENT ' "$ASCII" > "$OUTDIR/$TAG.flow.txt" || true;; esac
case ",$LOGSPEC," in *,sink,*)  grep ' UEC_SINK ' "$ASCII" > "$OUTDIR/$TAG.sink.txt" || true;; esac
case ",$LOGSPEC," in *,queue,*) grep ' QUEUE_APPROX ' "$ASCII" | grep ' RANGE ' > "$OUTDIR/$TAG.q.txt" || true;; esac
cp idmap.txt "$OUTDIR/$TAG.idmap" 2>/dev/null || true
rm -f "$ASCII"
[ -n "${KEEPDAT:-}" ] || rm -f "$OUTDIR/$TAG.dat"
echo "[run_lib] done $TAG"
```

- [ ] **Step 2: Make it executable**

Run:
```bash
chmod +x /home/leo/htsim/htsim/sim/datacenter/prism_eval/common/run_lib.sh
```

- [ ] **Step 3: Smoke the arg-parsing without a full run (binary present check)**

Run (expects the binary checks to pass and then a real short run; if the binary is missing it errors cleanly):
```bash
cd /home/leo/htsim/htsim/sim/datacenter && ls -l htsim_uec ../build/parse_output
```
Expected: both paths exist (symlink + decoder). If `../build/parse_output` is missing, build it before Task 8.

- [ ] **Step 4: Stage & checkpoint** (do NOT commit until approved)

```bash
git add -f htsim/sim/datacenter/prism_eval/common/run_lib.sh
git commit -m "prism_eval P0: unified htsim_uec runner (run_lib.sh)"
```

---

### Task 8: End-to-end smoke — FCT sanity on a 1-flow run

**Files:**
- Create: `prism_eval/common/tests/smoke_fct.sh`

This proves the whole spine works: generate traffic → run sim → decode → parse FCT. A single 4 MB flow at 100 Gbps should complete in roughly `size/rate + RTT` ≈ 0.32 ms + ~14 µs, i.e. comfortably in (0.2 ms, 2 ms), with completion_rate 1.0.

- [ ] **Step 1: Write the smoke script**

Create `htsim/sim/datacenter/prism_eval/common/tests/smoke_fct.sh`:
```bash
#!/bin/bash
# End-to-end smoke: 1-flow run -> FCT in a plausible band, completion_rate==1.0.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"           # common/tests
COMMON="$(cd "$HERE/.." && pwd)"                # common
DC="$(cd "$COMMON/.." && pwd)"                  # prism_eval
DATA="$DC/_smoke"                               # under prism_eval (gitignored)
REL="prism_eval/_smoke"                         # path relative to datacenter for run_lib
mkdir -p "$DATA"
# 1 sender outside pod0 -> host0, 4 MB
python3 "$COMMON/gen/incast.py" "$DATA/smoke.cm" 1 0 4000000 128 16
END_MS=2 PATHS=8 bash "$COMMON/run_lib.sh" nscc reps 0 fat_tree_128_1os.topo 13 \
    "$REL/smoke.cm" flow,sink smoke "$REL"
python3 - "$DATA/smoke.flow.txt" "$COMMON/metrics.py" <<'PY'
import sys, importlib.util as u
flow_path, metrics_path = sys.argv[1], sys.argv[2]
spec = u.spec_from_file_location("metrics", metrics_path)
metrics = u.module_from_spec(spec)
spec.loader.exec_module(metrics)
s = metrics.fct_stats(flow_path)
print("FCT stats:", s)
assert s["completed"] == 1, s
assert abs(s["completion_rate"] - 1.0) < 1e-9, s
assert 0.0002 < s["avg_s"] < 0.002, ("FCT out of sane band", s)
print("ok smoke_fct")
PY
echo "SMOKE PASS"
```

> Note: the inline Python imports `metrics.py` by file path (`spec_from_file_location`) so the smoke works regardless of cwd. The `_smoke/` dir sits under `prism_eval/` and is covered by the `.gitignore` from Task 1.

- [ ] **Step 2: Ensure the decoder exists, then run the smoke**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter
[ -x ../build/parse_output ] || (cd ../build && cmake --build . --target parse_output -j)
bash prism_eval/common/tests/smoke_fct.sh
```
Expected (values approximate): a `FCT stats: {...}` line with `completed: 1`, then `ok smoke_fct` and `SMOKE PASS`.

- [ ] **Step 3: Clean up smoke artifacts**

Run:
```bash
rm -rf /home/leo/htsim/htsim/sim/datacenter/prism_eval/_smoke
```

- [ ] **Step 4: Run the full selftest suite once more (regression)**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter/prism_eval/common/tests && python3 test_generators.py && python3 test_metrics.py
```
Expected: both end with `ALL PASS`.

- [ ] **Step 5: Stage & checkpoint** (do NOT commit until approved)

```bash
git add -f htsim/sim/datacenter/prism_eval/common/tests/smoke_fct.sh
git commit -m "prism_eval P0: end-to-end FCT smoke (gen -> run -> decode -> parse)"
```

---

## Done criteria for P0

- `common/gen/{permutation,many2many,incast}.py` produce valid `.cm` files; `test_generators.py` → `ALL PASS`.
- `common/metrics.py` parses FCT (avg/p50/p95/p99/max + completion_rate) and goodput; `test_metrics.py` → `ALL PASS`.
- `common/run_lib.sh` runs htsim_uec, decodes the `.dat` once, and emits `flow.txt`/`sink.txt`/`q.txt` on request.
- `common/plot_style.py` applies a shared style and saves PNG+PDF.
- `smoke_fct.sh` proves the full spine end-to-end with a sane 1-flow FCT.

## Deferred to later phases (intentionally NOT in P0)

- **Utilization (rigorous, topology-aware):** P0 uses goodput as the utilization signal (as the motivation did); a link-set-normalized utilization is defined in P2 where the topology/link set is fixed. No placeholder is added here.
- **PRISM-internal parsers** (`C_cc`/`C_spray`/cwnd time series, four-region occupancy, # cwnd cuts): land in P1 alongside the controller that emits the epoch log.
- **collective / flowsize generators:** P6.
