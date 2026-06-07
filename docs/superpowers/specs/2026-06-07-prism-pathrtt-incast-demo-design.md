# PRISM per-path-RTT 拥塞分解 + Incast 非对称演示 — 设计文档

- 日期: 2026-06-07
- 状态: 已获用户批准(brainstorming)
- 前置: 第二轮(队列型 C_cc,REPS+NSCC permutation)结论"退化"已被**推翻**——经速率空间验证,不可消除拥塞确实存在(目的=pod0 的流被钉在 ~25Gbps,REPS≈OBL,LB 无法消除),只是队列型指标 + 测错层(`-failed` 实际降 core→agg **下行**,见 §0)看不见它。详见 `mvp_runs2/assessment.txt`(已含更正)与对话记录。
- 目标转变: 从"判定是否退化"转为"**用忠实于 PRISM 定义的 per-path 指标,跑出体现 idea 有效性的数据图**"。

---

## 0. 关键既往事实(已在本仓库代码核实)

1. **`-failed N` 降的是 core→agg 下行链路**(`fat_tree_topology.cpp:1013-1018`:故障降速施加在 `queues_nc_nup` = CS→US 下行),即目标 pod 的**入口**。降速 = 线速 × `failed_link_ratio`(0.25)。`-failed N` 顺序填充 agg_sw0,1,2,3…(每 agg 4 条上行索引)。pod0 的 4 个 agg = US0–US3(由 idmap `LS0->US0..3` 确认)。
2. **LB 算法 flag 是 `-load_balancing_algo {reps|oblivious|...}`**,不是 `-strat`(后者是路由策略,给非法值会静默回退默认 MIXED)。
3. **NSCC 只维护 flow 级 `_base_rtt`(uec.cpp),无 per-path RTT 表**;无 per-packet ACK+entropy 日志。⇒ 你定义的 per-path `q_i` 无法用现有 CLI flag 测到。
4. **但每个 PSN 的发送记录 `sendRecord` 已存 `path_id`**(uec.h:251-252),与 `send_time` 并列;在 `raw_rtt = now − send_time` 处(uec.cpp:~1047)`i->second.path_id` 在作用域内。⇒ 加一个只读日志钩子即可忠实记录 `(time, flow_id, path_id, raw_rtt)`。`path_id` 即发送端所选 entropy/路径(OBLIVIOUS 下还编码物理两跳,uec.cpp:2639)。

---

## 1. 测量改动(只读日志钩子,relax 了"不改 C++"约束 — 仅日志,不改仿真行为)

在 `uec.cpp` ACK 处理、`raw_rtt` 算出且时间戳有效的分支(~1047-1055,`if (raw_rtt >= _base_rtt)` 上下文),追加:若 env var `PRISM_PATHRTT` 已设,向一个 `static std::ofstream`(首次惰性打开 `getenv("PRISM_PATHRTT")` 指向的文件)写一行 CSV:
```
now_ns,flow_id,path_id,raw_rtt_ns
```
- 字段: `timeAsNs(eventlist().now())`、`_flow.flow_id()`、`i->second.path_id`、`timeAsNs(raw_rtt)`。
- **未设 env var 时此分支完全不执行** → 对其它实验/二进制零影响;不碰 `logfile` 二进制格式;无需 `parse_output`。
- 仅在"timestamp 有效"分支记录(避免重传/probe 的不可靠 RTT);probe-ack 不记。
- 需 `cmake --build build --target htsim_uec`(增量,几分钟)。

实现要点:静态成员或文件作用域 ofstream + 一次性 `getenv`;线程无关(htsim 单线程事件循环)。改动局限在 uec.cpp 一处(+ 必要的头),不动 uec.h 接口。

---

## 2. 指标(忠实于用户 Q2 定义)

- **path i = `path_id`**(发送端所选 entropy/路径,正是"flow 的 n 条可选路径")。
- 对每条流的每个 `path_id`:
  - `rtt_min_i` = 该 (flow, path_id) 历史最小 `raw_rtt`;
  - `q_i(t)` = 该路径在 t 时刻(或时间 bin 内)最近一次 `raw_rtt` − `rtt_min_i`。
- 每条流、每个时间 bin(建议 10µs):在该流已用过的路径集合上
  - **`C_cc = min_i q_i`**(所有路径共有的延迟下界 → 换路消不掉 → CC 职责);
  - **`C_spray = max_i q_i − min_i q_i`**(路径间不均衡 → 换路可压平 → LB 职责)。
- 主分析对象:incast 的一条**代表流**(如 sender 0);再给所有 incast 流的中位数/分布作稳健性佐证。
- 备注:O(N) 全表测量在本实验无所谓(我们是全知观察者);PRISM 实现阶段的 O(1) 近似(端侧如何免维护 per-path 表)是后续问题,**不在本实验范围**。

---

## 3. 场景(incast 进入部分降速的目的 pod)

- 拓扑:`topologies/fat_tree_128_1os.topo`(128 host / 8 pod / 4 agg per pod;不变)。
- **Incast**:N=32 个发送端(从其它 pod 选取,确保跨 pod、上行到 core 再下到 pod0)→ pod0 的**单一目的 host0**。每流 size 取大(如 20MB)以在测量窗内持续(实际被瓶颈限速)。`LS0→host0` 最后一跳在 incast 下成为**所有路径共享瓶颈** → **C_cc floor**。
- **非对称**:`-failed 8` → pod0 入口 US0、US1 的 core→agg 下行降到 25%,US2、US3 正常 → 进入 pod0 的路径快慢分化 → **C_spray**。
- **LB**:`-load_balancing_algo reps`(决定性 / 对照),`oblivious`(消融)。
- **CC**:`-sender_cc_algo nscc`(默认)。
- 时间线 `-end 2`(2ms),稳态窗 [500,1500]µs。path-rtt CSV 经 env var 输出(不需 `-logtime`)。

---

## 4. 实验矩阵

| tag | LB | incast | failed | 作用 |
|---|---|---|---|---|
| `reps_a8`(决定性) | reps | 32→host0 | 8 | C_spray & C_cc 都应非零、动态不同 |
| `obl_a8`(LB 消融) | oblivious | 32→host0 | 8 | C_spray 应 > reps(OBL 不避坏路);C_cc 应 ≈ reps(floor 不可消除) |
| `reps_a0`(对称对照) | reps | 32→host0 | 0 | C_spray≈0(无非对称);C_cc 仍 >0(incast floor)→ C_cc 由负载驱动 |
| 非对称扫描 | reps | 32→host0 | {0,4,8,12} | C_spray 随 failed 单调增 |
| 负载扫描(可选) | reps | {16,32,64}→host0 | 8 | C_cc 随 incast 度单调增 |

---

## 5. 分析与图(`mvp_runs3/pathrtt_analyze.py`)

流水线:读 path-rtt CSV → 按 (flow, path_id) 累计 `rtt_min`、按 10µs bin 取该路径最近 raw_rtt → 每流每 bin 算 `C_cc`、`C_spray` → 代表流时序 + 跨流中位数。

图:
1. **决定性 run**:`C_spray(t)`、`C_cc(t)` 时序(代表流)——两者非零、动态不同。
2. **LB 对比柱状**:REPS vs OBL 的稳态 C_spray(REPS≪OBL)与 C_cc(≈相等)——**核心论证图**。
3. **对称 vs 非对称**:C_spray 随非对称"点亮";C_cc 两者都在(incast 驱动)。
4. **扫描**:C_spray~failed(LB 领域);C_cc~incast 度(CC 领域)。

---

## 6. 判定(分解成立 ⇔ 全满足)

- 决定性 run:C_spray、C_cc 都持续非零,且两条曲线动态明显不同;
- **C_spray 可被 LB 消除**:REPS 的 C_spray ≪ OBLIVIOUS;
- **C_cc 不可被 LB 消除**:REPS ≈ OBLIVIOUS;
- **归因正交**:C_cc 随 incast 度(负载)单调增、对 failed 不敏感;C_spray 随 failed(非对称)单调增。

满足 ⇒ 数据支持 PRISM 的 motivation(分解干净、各归 LB/CC)。仍按框架汇报,最终判断交用户。

---

## 7. 约束 / 风险 / 预算

- C++ 改动**仅日志、env 触发、不改仿真动态**;改动集中在 uec.cpp 一处。其余沿用现有 flag。
- 产物放 `mvp_runs3/`,不污染仓库根目录;工具:`gen_incast.py`、`pathrtt_analyze.py`(+单测)、`run_one.sh`、图。
- **风险:每路径 RTT 样本稀疏**。incast 到单 host 总交付 ~100Gbps,2ms 窗内全体 ACK ~数千条,代表流 / 路径数 n 若过大则每路径样本少 → q_i 噪声。**冒烟阶段先验证样本充足**;不足则收窄 entropy 池(减小 n)、或 incast 到少数几个 host、或聚合多流。先冒烟、再矩阵(沿用上轮纪律)。
- 预算:重编几分钟;每 run ~30s;分析 ~30 分钟。任一阶段超 3× 停下报告。

---

## 8. 不做的事(范围收窄)

- 不实现 PRISM 机制本身(O(1) per-path 估计、协同控制算法)。
- 不改 NSCC/REPS 参数(除必要时的 entropy 池大小,会记录)。
- 不改仿真行为的 C++(只加只读日志)。
- 不做 STrack 对比(本 fork 无 main)。
