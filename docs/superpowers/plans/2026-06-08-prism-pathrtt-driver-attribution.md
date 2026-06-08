# PRISM Round 4 — 补齐判据 (iv) 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 per-path RTT 数据上加「公共基线」分解模式,并用两个隔离场景(整-pod 过载验 C_spray~非对称、incast 度扫描验 C_cc~负载)补齐 Round 3 缺的判据 (iv)。

**Architecture:** 纯 analysis 层加第二个基线模式(`global`:`q_i=rtt_i−B_flow`,基线在 C_spray 抵消),C++ 钩子不动。新增 whole-pod overload 流量生成器;`run_one.sh` 的 `-end` 参数化以满足 N=64 采样。先用 `global` 0 成本重算已有 CSV 预验证,再跑新 run、出 fig5–8。

**Tech Stack:** Python 3(stdlib + matplotlib,自带断言式测试,无 pytest);bash;htsim_uec C++ 仿真(已编译,不改)。

参考 spec:`docs/superpowers/specs/2026-06-08-prism-pathrtt-driver-attribution-design.md`。
所有工作目录 `/home/leo/htsim/htsim/sim/datacenter`(下称 `$DC`);中间文件入 `mvp_runs3/`。

---

## 文件结构(改/建)

- 修改 `mvp_runs3/pathrtt_analyze.py` — 加 `rtt_min_per_flow`;`decompose` 加 `baseline`/`rtt_min_flow` 参数;`aggregate_tag` 加 `baseline`/`win` 参数并把采样门改成「窗内原始样本数」;`analyze_tag` 加 `baseline`。
- 修改 `mvp_runs3/test_pathrtt_analyze.py` — 加 3 个 `global` 模式单测;更新聚合测试注释。
- 创建 `mvp_runs3/gen_overload.py` — whole-pod overload `.cm` 生成器。
- 创建 `mvp_runs3/test_gen_overload.py` — 生成器单测。
- 修改 `mvp_runs3/run_one.sh` — `-end` 由 `END` 环境变量控制(默认 2)。
- 修改 `mvp_runs3/make_figures.py` — 追加 fig5–fig8。
- 创建 `mvp_runs3/prevalidation.txt` — 预验证输出记录。
- 修改 `mvp_runs3/assessment.txt`、`mvp_runs3/discussion.md` — 追加 Round 4 结果。

---

## Task 1: 给 pathrtt_analyze 加 `global` 基线模式 + 窗内采样门

**Files:**
- Modify: `mvp_runs3/pathrtt_analyze.py`
- Test: `mvp_runs3/test_pathrtt_analyze.py`

- [ ] **Step 1: 写失败测试** — 在 `test_pathrtt_analyze.py` 末尾(`if __name__` 之前)加三个测试,并把它们登记进 `__main__`。

```python
def test_rtt_min_per_flow():
    rows = [(1000,0,10,300),(2000,0,20,100),(3000,0,10,250),(4000,1,30,500)]
    p = _csv(rows); data = A.parse_csv(p); os.unlink(p)
    mf = A.rtt_min_per_flow(data)
    assert mf[0] == 100, mf   # min over BOTH paths of flow0
    assert mf[1] == 500, mf
    print("ok rtt_min_per_flow")

def test_global_baseline_cancels():
    # flow0, 2 paths. global floor = 100 (min over all samples).
    # bin1 latest: path10=150, path20=200.
    # C_spray(global) = max(150,200)-min(150,200) = 50  (independent of baseline)
    # C_cc(global)    = min(150,200)-100         = 50
    rows = [(1000,0,10,100),(2000,0,20,100),
            (12000,0,10,150),(13000,0,20,200)]
    p = _csv(rows); data = A.parse_csv(p); os.unlink(p)
    mp = A.rtt_min_per_path(data); mf = A.rtt_min_per_flow(data)
    t, cs, cc = A.decompose(data, mp, 0, bin_ns=10000, t0=0, t1=20000,
                            baseline="global", rtt_min_flow=mf)
    assert cs == [0, 50], cs   # bin0 qs(0,0); bin1 qs(50,100) -> spray 50
    assert cc == [0, 50], cc
    print("ok global baseline cancels")

def test_global_vs_own_structural_slow():
    # path10 fast: min 100, latest 110.  path20 structurally slow: min 300, latest 320.
    # own:    q10=10, q20=20  -> C_spray=10  (slow path's slowness hidden in its own min)
    # global: B=100; q10=10, q20=220 -> C_spray=210  (slow path now shows in C_spray) = iv-a fix
    rows = [(1000,0,10,100),(2000,0,20,300),
            (12000,0,10,110),(13000,0,20,320)]
    p = _csv(rows); data = A.parse_csv(p); os.unlink(p)
    mp = A.rtt_min_per_path(data); mf = A.rtt_min_per_flow(data)
    _, cs_own, _  = A.decompose(data, mp, 0, bin_ns=10000, t0=10000, t1=20000)
    _, cs_glob, _ = A.decompose(data, mp, 0, bin_ns=10000, t0=10000, t1=20000,
                                baseline="global", rtt_min_flow=mf)
    assert cs_own == [10], cs_own
    assert cs_glob == [210], cs_glob
    print("ok global vs own structural slow (iv-a fix)")
```

并在 `if __name__ == "__main__":` 块里,`test_aggregate_cross_flow_median()` 之后、`print("ALL PASS")` 之前加:

```python
    test_rtt_min_per_flow()
    test_global_baseline_cancels()
    test_global_vs_own_structural_slow()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /home/leo/htsim/htsim/sim/datacenter && python3 mvp_runs3/test_pathrtt_analyze.py`
Expected: FAIL — `AttributeError: module 'pathrtt_analyze' has no attribute 'rtt_min_per_flow'`(或 `decompose() got an unexpected keyword argument 'baseline'`)。

- [ ] **Step 3: 实现** — 在 `pathrtt_analyze.py` 中:

(a) 在 `rtt_min_per_path` 函数之后加:

```python
def rtt_min_per_flow(rows):
    """flow -> min raw_rtt over ALL paths and time (the flow's empty-network floor B_flow)."""
    m = {}
    for t, flow, path, rtt in rows:
        if flow not in m or rtt < m[flow]:
            m[flow] = rtt
    return m
```

(b) 把 `decompose` 整体替换为(加 `baseline` / `rtt_min_flow` 两个参数,其余逻辑不变):

```python
def decompose(rows, rtt_min, flow_id, bin_ns=BIN_NS, t0=None, t1=None,
              baseline="own", rtt_min_flow=None):
    """For one flow: (times_ns, c_spray_ns, c_cc_ns), one entry per bin in [t0,t1).
    baseline='own':    q_i = rtt_i - rtt_min[(flow,i)]   (per-path own historical min)
    baseline='global': q_i = rtt_i - rtt_min_flow[flow]  (one floor for all paths; then
                       C_spray = max_i rtt_i - min_i rtt_i, the baseline cancels).
    Per bin, latest raw_rtt carried forward per path. Empty path-set bins are skipped."""
    fr = [r for r in rows if r[1] == flow_id]
    if not fr:
        return [], [], []
    if t0 is None:
        t0 = (fr[0][0] // bin_ns) * bin_ns
    if t1 is None:
        t1 = fr[-1][0] + 1
    if baseline == "global":
        base = rtt_min_flow[flow_id]
        base_of = lambda p: base
    else:
        base_of = lambda p: rtt_min[(flow_id, p)]
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
            qs = [latest[p] - base_of(p) for p in latest]
            times.append(b)
            cspray.append(max(qs) - min(qs))
            ccc.append(min(qs))
        b = bin_end
    return times, cspray, ccc
```

(c) 把 `aggregate_tag` 整体替换为(加 `baseline` / `win` 参数;采样门改为「窗内原始样本数 ≥ min_samples」,直接对应 spec「每流稳态窗 ≥200 样本」):

```python
def aggregate_tag(tag, min_samples=200, baseline="own", win=WIN):
    """Cross-flow robust statistic. For every flow with >= min_samples ACKs INSIDE the
    steady window `win`, compute its steady-window mean C_spray and C_cc; return the
    MEDIAN across flows. baseline selects 'own' (per-path min) or 'global' (flow floor).
    Returns {nflows, cspray_med, ccc_med} or None if no eligible flow."""
    import statistics
    rows = parse_csv(os.path.join(HERE, f"{tag}.pathrtt.csv"))
    if not rows:
        return None
    mp = rtt_min_per_path(rows)
    mf = rtt_min_per_flow(rows)
    inwin = collections.Counter(f for (t, f, p, r) in rows
                                if win[0] <= t / 1000.0 <= win[1])
    cs_list, cc_list = [], []
    for flow in inwin:
        if inwin[flow] < min_samples:
            continue
        t_ns, cs_ns, cc_ns = decompose(rows, mp, flow, baseline=baseline, rtt_min_flow=mf)
        t_us = [t / 1000.0 for t in t_ns]
        ssp = steady_stats(t_us, [x / 1000.0 for x in cs_ns], win[0], win[1])
        scc = steady_stats(t_us, [x / 1000.0 for x in cc_ns], win[0], win[1])
        if ssp["n"] > 0:
            cs_list.append(ssp["mean"]); cc_list.append(scc["mean"])
    if not cs_list:
        return None
    return {"nflows": len(cs_list),
            "cspray_med": statistics.median(cs_list),
            "ccc_med": statistics.median(cc_list)}
```

(d) `analyze_tag` 加 `baseline` 形参并透传(CLI 完整性)。把签名行 `def analyze_tag(tag):` 改为 `def analyze_tag(tag, baseline="own"):`,并把其中

```python
    mins = rtt_min_per_path(rows)
    flow = representative_flow(rows)
    t_ns, cs_ns, cc_ns = decompose(rows, mins, flow)
```

替换为

```python
    mins = rtt_min_per_path(rows)
    minf = rtt_min_per_flow(rows)
    flow = representative_flow(rows)
    t_ns, cs_ns, cc_ns = decompose(rows, mins, flow, baseline=baseline, rtt_min_flow=minf)
```

- [ ] **Step 4: 更新聚合测试注释**(语义已从「总样本数」改为「窗内样本数」,断言不变)。把 `test_aggregate_cross_flow_median` 里这两行注释

```python
        # min_samples filter: each flow has 6 samples; requiring 7 -> no eligible flow
        assert A.aggregate_tag("_testagg", min_samples=7) is None
```

改为

```python
        # min_samples filter is on IN-WINDOW samples: each flow has 4 in [500,1500]us
        # (the 400us sample is pre-window); requiring 7 -> no eligible flow
        assert A.aggregate_tag("_testagg", min_samples=7) is None
```

- [ ] **Step 5: 跑全部测试确认通过**

Run: `cd /home/leo/htsim/htsim/sim/datacenter && python3 mvp_runs3/test_pathrtt_analyze.py`
Expected: 打印各 `ok ...` 行 + `ALL PASS`(共 9 个测试)。

- [ ] **Step 6: 提交**

```bash
cd /home/leo/htsim
git add htsim/sim/datacenter/mvp_runs3/pathrtt_analyze.py htsim/sim/datacenter/mvp_runs3/test_pathrtt_analyze.py
git commit -m "Round 4: add global-baseline decomposition mode + in-window sample gate"
```

---

## Task 2: 预验证 — 用 `global` 重算已有 incast CSV(无新仿真)

**Files:**
- Create: `mvp_runs3/prevalidation.txt`(命令输出记录)

目的:在最不利场景(Round 3 incast,有最后一跳遮挡)下,看 `global` 基线是否已把
C_spray 对 `-failed` 从「反转」修正为「单调升」。若是,即为强信号。

- [ ] **Step 1: 跑预验证打印**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter
python3 - <<'PY' | tee mvp_runs3/prevalidation.txt
import sys; sys.path.insert(0, "mvp_runs3")
import pathrtt_analyze as A
print("Pre-validation: re-analyze EXISTING Round-3 incast CSVs with both baselines")
print("tag        | own  C_spray/C_cc | global C_spray/C_cc | nflows")
for tag in ("reps_a0","reps_a4","reps_a8","reps_a12","obl_a8"):
    o = A.aggregate_tag(tag, baseline="own")
    g = A.aggregate_tag(tag, baseline="global")
    if not o or not g:
        print(f"{tag:10s} | (no eligible flow / missing CSV)"); continue
    print(f"{tag:10s} | {o['cspray_med']:5.2f} / {o['ccc_med']:4.2f}      | "
          f"{g['cspray_med']:6.2f} / {g['ccc_med']:4.2f}       | {g['nflows']}")
print()
print("iv-a pre-check: is global C_spray monotonic up over reps_a0<a4<a8<a12?")
vals = [A.aggregate_tag(f"reps_a{f}", baseline="global") for f in (0,4,8,12)]
seq = [v["cspray_med"] for v in vals if v]
print("  global C_spray sequence (f=0,4,8,12):", [round(x,2) for x in seq])
print("  monotonic non-decreasing:", all(a<=b for a,b in zip(seq, seq[1:])))
PY
```
Expected: 打印一张 own-vs-global 对照表 + global C_spray 序列与单调判断。这是观察步骤
(逻辑已在 Task 1 测过),不论单调与否都如实记录;incast 遮挡仍在,**即使这里未单调也不
否定方案**——干净判据靠 Task 6 的场景 A。

- [ ] **Step 2: 提交**

```bash
cd /home/leo/htsim
git add htsim/sim/datacenter/mvp_runs3/prevalidation.txt
git commit -m "Round 4: pre-validation of global baseline on existing incast CSVs"
```

---

## Task 3: whole-pod overload 流量生成器

**Files:**
- Create: `mvp_runs3/gen_overload.py`
- Test: `mvp_runs3/test_gen_overload.py`

- [ ] **Step 1: 写失败测试** — 创建 `mvp_runs3/test_gen_overload.py`:

```python
#!/usr/bin/env python3
"""Self-contained tests for gen_overload (no pytest). Run: python3 test_gen_overload.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen_overload as G

def test_counts_and_placement():
    text, conns = G.build(n_senders=8, dest_pod=0, n_dests=4, size=20_000_000,
                          nodes=128, hpp=16)
    assert len(conns) == 8, conns
    # every sender is OUTSIDE pod0; every dest is INSIDE pod0
    for s, d in conns:
        assert s // 16 != 0, (s, d)
        assert 0 <= d < 4, (s, d)
    # round-robin over the 4 dests -> each dest used exactly twice
    used = sorted(d for _, d in conns)
    assert used == [0, 0, 1, 1, 2, 2, 3, 3], used
    assert "Nodes 128" in text and "Connections 8" in text
    print("ok gen_overload counts + placement")

def test_guards():
    try:
        G.build(n_senders=8, dest_pod=0, n_dests=20, nodes=128, hpp=16)  # n_dests>hpp
        assert False, "expected ValueError for n_dests>hpp"
    except ValueError:
        pass
    try:
        G.build(n_senders=200, dest_pod=0, n_dests=4, nodes=128, hpp=16)  # too many senders
        assert False, "expected ValueError for too many senders"
    except ValueError:
        pass
    print("ok gen_overload guards")

if __name__ == "__main__":
    test_counts_and_placement()
    test_guards()
    print("ALL PASS")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd /home/leo/htsim/htsim/sim/datacenter && python3 mvp_runs3/test_gen_overload.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'gen_overload'`。

- [ ] **Step 3: 实现** — 创建 `mvp_runs3/gen_overload.py`:

```python
#!/usr/bin/env python3
"""Generate a whole-pod overload .cm: n_senders (all OUTSIDE dest_pod) -> n_dests hosts
INSIDE dest_pod, round-robin. Senders outside the pod force traffic across the core into
dest_pod, traversing the (possibly -failed) core->agg ingress. Spreading over several dest
hosts keeps the asymmetric ingress (not a single last-hop host) the differentiating
bottleneck. Usage:
  python3 gen_overload.py <out.cm> [n_senders] [dest_pod] [n_dests] [size] [nodes] [hpp]
"""
import sys

def build(n_senders=32, dest_pod=0, n_dests=8, size=20_000_000, nodes=128, hpp=16):
    if n_dests > hpp:
        raise ValueError(f"n_dests {n_dests} > hosts_per_pod {hpp}")
    dests = [dest_pod * hpp + j for j in range(n_dests)]
    senders = [h for h in range(nodes) if h // hpp != dest_pod][:n_senders]
    if len(senders) != n_senders:
        raise ValueError(f"need {n_senders} senders outside pod{dest_pod}, "
                         f"only {len(senders)} available")
    conns = [(s, dests[i % n_dests]) for i, s in enumerate(senders)]
    lines = [f"Nodes {nodes}", f"Connections {len(conns)}"]
    lines += [f"{s}->{d} start 0 size {size}" for s, d in conns]
    return "\n".join(lines) + "\n", conns

def main():
    out = sys.argv[1]
    n_senders = int(sys.argv[2]) if len(sys.argv) > 2 else 32
    dest_pod  = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    n_dests   = int(sys.argv[4]) if len(sys.argv) > 4 else 8
    size      = int(sys.argv[5]) if len(sys.argv) > 5 else 20_000_000
    nodes     = int(sys.argv[6]) if len(sys.argv) > 6 else 128
    hpp       = int(sys.argv[7]) if len(sys.argv) > 7 else 16
    text, conns = build(n_senders, dest_pod, n_dests, size, nodes, hpp)
    with open(out, "w") as fh:
        fh.write(text)
    print(f"wrote {out}: {len(conns)} flows, {n_senders} senders -> {n_dests} hosts "
          f"in pod{dest_pod}, size {size}")

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd /home/leo/htsim/htsim/sim/datacenter && python3 mvp_runs3/test_gen_overload.py`
Expected: `ok gen_overload counts + placement` / `ok gen_overload guards` / `ALL PASS`。

- [ ] **Step 5: 提交**

```bash
cd /home/leo/htsim
git add htsim/sim/datacenter/mvp_runs3/gen_overload.py htsim/sim/datacenter/mvp_runs3/test_gen_overload.py
git commit -m "Round 4: add whole-pod overload traffic generator"
```

---

## Task 4: `run_one.sh` 的 `-end` 参数化

**Files:**
- Modify: `mvp_runs3/run_one.sh`

场景 B(N=64)需要更长仿真时间才能在稳态窗内取够 ≥200 样本/流;场景 A 沿用默认 2ms。

- [ ] **Step 1: 改 run_one.sh** — 在 `PATHS="${PATHS:-8}"` 行之后加一行:

```bash
END="${END:-2}"
```

并把运行命令里的 `-end 2` 改为 `-end "$END"`(该行当前为
`-paths "$PATHS" -end 2 -o "$OUT/$TAG.dat" > "$OUT/$TAG.stdout" 2>&1`):

```bash
    -paths "$PATHS" -end "$END" -o "$OUT/$TAG.dat" > "$OUT/$TAG.stdout" 2>&1
```

并把开头的 echo 行加上 END 以便核对(当前为
`echo "[run_one] lb=$LB failed=$FAILED tag=$TAG cm=$CM paths=$PATHS"`):

```bash
echo "[run_one] lb=$LB failed=$FAILED tag=$TAG cm=$CM paths=$PATHS end=$END"
```

- [ ] **Step 2: 语法自检**

Run: `cd /home/leo/htsim/htsim/sim/datacenter && bash -n mvp_runs3/run_one.sh && echo OK`
Expected: `OK`(无语法错)。功能验证在 Task 5/6 的实跑中完成。

- [ ] **Step 3: 提交**

```bash
cd /home/leo/htsim
git add htsim/sim/datacenter/mvp_runs3/run_one.sh
git commit -m "Round 4: make run_one.sh -end configurable via END env (default 2)"
```

---

## Task 5: 场景 B 实跑 + fig8(C_cc ~ 负载)

**Files:**
- Create: `mvp_runs3/incast_n{16,32,64}.cm`(生成物)、`mvp_runs3/B_reps_n*.{pathrtt.csv,dat,stdout}`(运行产物)
- Modify: `mvp_runs3/make_figures.py`

- [ ] **Step 1: 生成三个 incast .cm(对称拓扑,改变 incast 度)**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter
python3 mvp_runs3/gen_incast.py mvp_runs3/incast_n16.cm 16 0
python3 mvp_runs3/gen_incast.py mvp_runs3/incast_n32.cm 32 0
python3 mvp_runs3/gen_incast.py mvp_runs3/incast_n64.cm 64 0
```
Expected: 三行 `wrote ... N senders ... -> host0 (pod0) ...`。

- [ ] **Step 2: 跑三个 run(`-failed 0` 对称,`END=8` 长仿真)**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter
END=8 bash mvp_runs3/run_one.sh reps 0 B_reps_n16 mvp_runs3/incast_n16.cm
END=8 bash mvp_runs3/run_one.sh reps 0 B_reps_n32 mvp_runs3/incast_n32.cm
END=8 bash mvp_runs3/run_one.sh reps 0 B_reps_n64 mvp_runs3/incast_n64.cm
```
Expected: 每行 `[run_one] done B_reps_n..: <K> rtt rows; Load balancing algorithm set to REPS`,K 为数万行。若某行 `Load balancing algorithm set to` 不是 REPS,停下排查(LB flag 名)。

- [ ] **Step 3: 验证窗内采样达标 + C_cc 单调**(窗 `[1000,7000]µs`)

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter
python3 - <<'PY'
import sys; sys.path.insert(0, "mvp_runs3")
import pathrtt_analyze as A
WB = (1000.0, 7000.0)
seq = []
for n in (16, 32, 64):
    g = A.aggregate_tag(f"B_reps_n{n}", baseline="global", win=WB)
    assert g is not None, f"N={n}: no flow with >=200 in-window samples (raise END or window)"
    print(f"N={n}: nflows={g['nflows']} C_cc(global)={g['ccc_med']:.3f}us "
          f"C_spray(global)={g['cspray_med']:.3f}us")
    seq.append(g["ccc_med"])
print("C_cc monotonic up:", all(a < b for a, b in zip(seq, seq[1:])), seq)
PY
```
Expected: 三行各 `nflows>0`、无断言失败(每流窗内 ≥200 样本)。`C_cc monotonic up` 期望 `True`。
若 N=64 触发断言(样本仍不足),把 Step 2 的 `END=8` 提到 `END=12` 并把本 Step 与 fig8 的窗
改为 `(1000.0, 11000.0)`,重跑 N=64。

- [ ] **Step 4: 给 make_figures.py 追加 fig8** — 在文件末尾 `print("wrote ...")` 行**之前**插入:

```python
# Fig 8 — Scenario B: C_cc rises with incast degree (load), symmetric topo.
WB = (1000.0, 7000.0)
def medB(tag, baseline):
    a = A.aggregate_tag(tag, baseline=baseline, win=WB)
    return a["ccc_med"] if a else None
Ns = [16, 32, 64]
cc_own  = [medB(f"B_reps_n{n}", "own")    for n in Ns]
cc_glob = [medB(f"B_reps_n{n}", "global") for n in Ns]
plt.figure(figsize=(7, 4))
xo = [n for n, v in zip(Ns, cc_own)  if v is not None]; yo = [v for v in cc_own  if v is not None]
xg = [n for n, v in zip(Ns, cc_glob) if v is not None]; yg = [v for v in cc_glob if v is not None]
plt.plot(xo, yo, "o--", label="own baseline")
plt.plot(xg, yg, "s-",  label="global baseline")
plt.xlabel("incast degree N (load)"); plt.ylabel("C_cc cross-flow median (us)")
plt.title("Scenario B (symmetric, REPS): C_cc floor rises with load")
plt.legend(); plt.grid(alpha=0.3); plt.xticks(Ns)
plt.tight_layout(); plt.savefig(f"{HERE}/fig8_ccc_vs_load.png", dpi=130); plt.close()
print("wrote fig8_ccc_vs_load.png")
```

- [ ] **Step 5: 生成 fig8 并确认文件存在**

Run: `cd /home/leo/htsim/htsim/sim/datacenter && python3 mvp_runs3/make_figures.py && ls -la mvp_runs3/fig8_ccc_vs_load.png`
Expected: 打印含 `wrote fig8_ccc_vs_load.png`;`ls` 显示文件非空。(注意:此时 fig5–7 依赖的场景 A 数据尚未跑,make_figures 里 fig5–7 的代码将在 Task 6 加入;本步只验 fig8。)

- [ ] **Step 6: 提交**

```bash
cd /home/leo/htsim
git add htsim/sim/datacenter/mvp_runs3/incast_n*.cm htsim/sim/datacenter/mvp_runs3/B_reps_n*.pathrtt.csv \
        htsim/sim/datacenter/mvp_runs3/B_reps_n*.stdout htsim/sim/datacenter/mvp_runs3/make_figures.py \
        htsim/sim/datacenter/mvp_runs3/fig8_ccc_vs_load.png
git commit -m "Round 4 Scenario B: incast-degree sweep + fig8 (C_cc vs load)"
```

---

## Task 6: 场景 A 实跑 + fig5/6/7(C_spray ~ 非对称)

**Files:**
- Create: `mvp_runs3/overload.cm`、`mvp_runs3/A_obl_f*.{pathrtt.csv,dat,stdout}`、`mvp_runs3/A_reps_f8.*`
- Modify: `mvp_runs3/make_figures.py`

- [ ] **Step 1: 生成 whole-pod overload .cm**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter
python3 mvp_runs3/gen_overload.py mvp_runs3/overload.cm 32 0 8
```
Expected: `wrote mvp_runs3/overload.cm: 32 flows, 32 senders -> 8 hosts in pod0, size 20000000`。

- [ ] **Step 2: 跑非对称扫描(Oblivious)+ REPS 对照(均 `END=2`)**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter
END=2 bash mvp_runs3/run_one.sh oblivious 0  A_obl_f0  mvp_runs3/overload.cm
END=2 bash mvp_runs3/run_one.sh oblivious 4  A_obl_f4  mvp_runs3/overload.cm
END=2 bash mvp_runs3/run_one.sh oblivious 8  A_obl_f8  mvp_runs3/overload.cm
END=2 bash mvp_runs3/run_one.sh oblivious 12 A_obl_f12 mvp_runs3/overload.cm
END=2 bash mvp_runs3/run_one.sh reps      8  A_reps_f8 mvp_runs3/overload.cm
```
Expected: 前四行 `Load balancing algorithm set to OBLIVIOUS`,末行 `REPS`;各数万 rtt rows。

- [ ] **Step 3: 验证采样达标 + C_spray(global) 对 -failed 单调升**(默认窗 `[500,1500]µs`)

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter
python3 - <<'PY'
import sys; sys.path.insert(0, "mvp_runs3")
import pathrtt_analyze as A
print("Scenario A (OBL): C_spray own vs global across -failed")
seq = []
for f in (0, 4, 8, 12):
    o = A.aggregate_tag(f"A_obl_f{f}", baseline="own")
    g = A.aggregate_tag(f"A_obl_f{f}", baseline="global")
    assert o and g, f"f={f}: no eligible flow (>=200 in-window); raise n_senders down or END up"
    print(f"  f={f:2d}: own C_spray={o['cspray_med']:6.2f}  global C_spray={g['cspray_med']:6.2f}  "
          f"global C_cc={g['ccc_med']:5.2f}  nflows={g['nflows']}")
    seq.append(g["cspray_med"])
print("global C_spray monotonic up (f=0<4<8<12):", all(a < b for a, b in zip(seq, seq[1:])), seq)
r = A.aggregate_tag("A_reps_f8", baseline="global"); o = A.aggregate_tag("A_obl_f8", baseline="global")
print(f"LB @ f8 (global): REPS C_spray={r['cspray_med']:.2f} vs OBL {o['cspray_med']:.2f} "
      f"| C_cc REPS {r['ccc_med']:.2f} vs OBL {o['ccc_med']:.2f}")
PY
```
Expected: 5 行无断言失败;`global C_spray monotonic up` 期望 `True`(对称小、非对称大);REPS C_spray < OBL。
若某 `f` 触发「no eligible flow」断言:把 Step 1 的 `gen_overload.py ... 32 ...` 改小发送端数
(如 `24`)重生成 overload.cm 并重跑该 `f`(更少流 → 每流速率更高 → 窗内样本更多)。

- [ ] **Step 4: 给 make_figures.py 追加 fig5/6/7** — 在 Task 5 插入的 fig8 代码块**之前**插入:

```python
# ---- Round 4 Scenario A figures (global baseline = the iv-a metric) ----
def medA(tag, baseline, key):
    a = A.aggregate_tag(tag, baseline=baseline)   # default window [500,1500]us
    return a[key] if a else None

# Fig 5 — own vs global C_spray across -failed (global restores monotonicity).
fails = [0, 4, 8, 12]
own_s  = [medA(f"A_obl_f{f}", "own",    "cspray_med") for f in fails]
glob_s = [medA(f"A_obl_f{f}", "global", "cspray_med") for f in fails]
plt.figure(figsize=(7.5, 4))
xo = [f for f, v in zip(fails, own_s)  if v is not None]; yo = [v for v in own_s  if v is not None]
xg = [f for f, v in zip(fails, glob_s) if v is not None]; yg = [v for v in glob_s if v is not None]
plt.plot(xo, yo, "o--", label="own baseline (q_i = rtt_i - path-own-min)")
plt.plot(xg, yg, "s-",  label="global baseline (q_i = rtt_i - flow floor)")
plt.xlabel("-failed (asymmetry)"); plt.ylabel("C_spray cross-flow median (us)")
plt.title("Scenario A (OBL): global baseline restores C_spray vs asymmetry")
plt.legend(); plt.grid(alpha=0.3); plt.xticks(fails)
plt.tight_layout(); plt.savefig(f"{HERE}/fig5_baseline_compare.png", dpi=130); plt.close()

# Fig 6 — symmetric (f0) vs asymmetric (f8), global baseline.
s0 = medA("A_obl_f0", "global", "cspray_med"); c0 = medA("A_obl_f0", "global", "ccc_med")
s8 = medA("A_obl_f8", "global", "cspray_med"); c8 = medA("A_obl_f8", "global", "ccc_med")
plt.figure(figsize=(7, 4))
plt.bar([i - w/2 for i in x], [s0, c0], w, label="failed=0 (sym)")
plt.bar([i + w/2 for i in x], [s8, c8], w, label="failed=8 (asym)")
plt.xticks(x, ["C_spray", "C_cc"]); plt.ylabel("cross-flow median q (us), global baseline")
plt.title("Scenario A: symmetric vs asymmetric (global baseline)")
plt.legend(); plt.grid(alpha=0.3, axis="y")
plt.tight_layout(); plt.savefig(f"{HERE}/fig6_sym_vs_asym_global.png", dpi=130); plt.close()

# Fig 7 — LB contrast @ f8 (global): REPS lowers C_spray, leaves C_cc.
rs = medA("A_reps_f8", "global", "cspray_med"); rc = medA("A_reps_f8", "global", "ccc_med")
os_ = medA("A_obl_f8", "global", "cspray_med"); oc = medA("A_obl_f8", "global", "ccc_med")
plt.figure(figsize=(7, 4))
plt.bar([i - w/2 for i in x], [rs, rc], w, label="REPS")
plt.bar([i + w/2 for i in x], [os_, oc], w, label="OBLIVIOUS")
plt.xticks(x, ["C_spray", "C_cc"]); plt.ylabel("cross-flow median q (us), global baseline")
plt.title("Scenario A @ failed=8: REPS << OBL on C_spray; equal on C_cc")
plt.legend(); plt.grid(alpha=0.3, axis="y")
plt.tight_layout(); plt.savefig(f"{HERE}/fig7_lb_contrast_global.png", dpi=130); plt.close()
```

(注:`x` 和 `w` 已在 make_figures.py 上方定义为 `x=[0,1]`、`w=0.35`,fig6/7 直接复用。)

- [ ] **Step 5: 生成全部图并确认 fig5/6/7 存在**

Run: `cd /home/leo/htsim/htsim/sim/datacenter && python3 mvp_runs3/make_figures.py && ls -la mvp_runs3/fig5_baseline_compare.png mvp_runs3/fig6_sym_vs_asym_global.png mvp_runs3/fig7_lb_contrast_global.png`
Expected: 三个 png 均非空。

- [ ] **Step 6: 提交**

```bash
cd /home/leo/htsim
git add htsim/sim/datacenter/mvp_runs3/overload.cm htsim/sim/datacenter/mvp_runs3/A_obl_f*.pathrtt.csv \
        htsim/sim/datacenter/mvp_runs3/A_obl_f*.stdout htsim/sim/datacenter/mvp_runs3/A_reps_f8.pathrtt.csv \
        htsim/sim/datacenter/mvp_runs3/A_reps_f8.stdout htsim/sim/datacenter/mvp_runs3/make_figures.py \
        htsim/sim/datacenter/mvp_runs3/fig5_baseline_compare.png \
        htsim/sim/datacenter/mvp_runs3/fig6_sym_vs_asym_global.png \
        htsim/sim/datacenter/mvp_runs3/fig7_lb_contrast_global.png
git commit -m "Round 4 Scenario A: whole-pod overload sweep + fig5/6/7 (C_spray vs asymmetry)"
```

---

## Task 7: 汇总 — 更新 assessment.txt 与 discussion.md

**Files:**
- Modify: `mvp_runs3/assessment.txt`、`mvp_runs3/discussion.md`

- [ ] **Step 1: 在 `assessment.txt` 末尾追加 Round 4 段** — 用 Task 5/6 实测数填空(下面方括号占位用真实数替换),内容含:场景 A/B 设置、global 基线公式、fig5–8 读数、(iv-a)/(iv-b) 判定(依 spec §5 定义)、最终「部分成立→是否升级为成立」结论。模板:

```
ROUND 4 — Driver attribution (criterion iv), 2026-06-08
=======================================================
Metric: global baseline q_i = rtt_i - B_flow (B_flow = flow's min raw RTT over all
paths/time). Then C_spray = max_i rtt_i - min_i rtt_i (baseline cancels), C_cc = min_i
rtt_i - B_flow. Compared side-by-side with the own-min baseline.

Scenario A (whole-pod overload -> 8 hosts in pod0, OBL; failed sweep): tests iv-a.
  f=0/4/8/12  global C_spray = [..]/[..]/[..]/[..] us ; monotonic up = [YES/NO] (fig5/6)
  own    C_spray = [..]/[..]/[..]/[..] us  (reproduces fig3 reversal under own-min)
  LB @ f8 (global): REPS C_spray [..] vs OBL [..] ; C_cc [..] ~ [..] (fig7)
Scenario B (incast-degree sweep, symmetric, REPS): tests iv-b.
  N=16/32/64  global C_cc = [..]/[..]/[..] us ; monotonic up = [YES/NO] (fig8)
  in-window samples/flow all >= 200 = [YES/NO]

VERDICT:
  iv-a (C_spray ~ asymmetry): [成立/不成立] — fig5 global monotonic [YES/NO] AND
       A_obl_f0 < A_obl_f8 [YES/NO].
  iv-b (C_cc ~ load): [成立/不成立] — fig8 monotonic [YES/NO], samples ok [YES/NO].
  (iv) overall: [补齐/未补齐].
  Pre-validation (existing incast CSVs, global): C_spray monotonic = [YES/NO]
       (mvp_runs3/prevalidation.txt).

CONCLUSION: [若 iv 补齐: 分解 + LB/CC 职责分离 + 驱动可归因, 三者成立;
            否则: 仍部分成立, 说明哪条不成立]. 不对 PRISM 机制性能做任何声称;
            最终 go/no-go 由用户裁定。
```

- [ ] **Step 2: 更新 `discussion.md`** — 改 §0 一句话现状(若 iv 补齐则改为「核心命题成立且驱动可归因」)、在 §5 后加 Round 4 结果小节(引用 fig5–8 与上面读数)、把 §9「下一步」标注为已执行并写明结论。保持 §11 约束原文不动。

- [ ] **Step 3: 验证图与文交叉一致** — 确认 assessment 中引用的每个数字都能在对应 `aggregate_tag` 输出复现:

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter
python3 mvp_runs3/test_pathrtt_analyze.py && python3 mvp_runs3/test_gen_overload.py
```
Expected: 两个 `ALL PASS`(回归确认分析代码仍正确)。

- [ ] **Step 4: 提交**

```bash
cd /home/leo/htsim
git add htsim/sim/datacenter/mvp_runs3/assessment.txt htsim/sim/datacenter/mvp_runs3/discussion.md
git commit -m "Round 4: assessment + discussion update (criterion iv verdict)"
```

---

## 自检笔记(已核对)

- **Spec 覆盖**:§2 指标→Task 1;§6 预验证→Task 2;§3 场景A→Task 3+6;§4 场景B→Task 5;
  fig5–8(§5)→Task 5/6;采样门(§3/§4)→Task 1 的窗内门 + Task 5 Step 3 / Task 6 Step 3 验证;
  约束(§7)→Task 7 结论措辞 + 无新 C++。
- **类型一致**:`decompose(..., baseline, rtt_min_flow)`、`aggregate_tag(tag, min_samples, baseline, win)`、
  `rtt_min_per_flow(rows)`、`gen_overload.build(n_senders, dest_pod, n_dests, size, nodes, hpp)`
  在所有 Task 中签名一致。
- **采样兜底**:N=64 不够样本 → 提 END + 加宽窗(Task 5 Step 3 已写);场景 A 不够 → 减发送端
  (Task 6 Step 3 已写)。
- **诚实失败**:每个验证步都规定「期望值」但不预设结论;若单调不成立按 spec §5 如实判「未补齐」,
  不强行宣称成立、不建议进入 PRISM 实现阶段。
```

