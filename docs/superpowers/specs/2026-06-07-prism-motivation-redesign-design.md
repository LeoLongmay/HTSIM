# PRISM Motivation 实验重设计 — 设计文档

- 日期: 2026-06-07
- 状态: 已获用户批准(brainstorming 阶段)
- 前置: 第一轮最小验证实验(单流)结论为「退化」,见
  `htsim/sim/datacenter/mvp_runs/assessment.txt`
- 范围: **只测量,不实现 PRISM**;不修改 htsim C++ 源码;全部产物放
  `htsim/sim/datacenter/mvp_runs2/`

---

## 1. 目标(为什么要重做)

第一轮实验在「单流 + tor_upqueue + 全队列 min/max」最小设置下,得到
`C_cc ≈ 0`、对 `-failed` 零响应的退化结果。复盘出三条根因,本设计逐条修复:

| 第一轮根因 | 本轮修复 |
|---|---|
| 单流 → 瓶颈层多数队列空闲 → `min` 恒 0 | 改 **128 条 permutation 长流**,持续加载瓶颈层 |
| 分析层与 `-failed` 作用层错位(测 tor→agg,故障在 agg→core) | **在 agg→core(`US->CS`)层测量**,用 `idmap.txt` 精确定位 |
| `min` 取在「全网所有队列」上 → 混入无关空闲队列 | `max/min` 只取在 **单个 agg 交换机的 4 条上行束**内(可互换路径集) |

### 关键探索结论(决定可行性,均在 commit d42b157 上核实)

1. **所有层的队列都挂了采样 logger**。`QueueLoggerFactory` 在每一层
   (host→tor / tor→agg / agg→tor / **agg→core** / core→agg / tor→host)创建
   logger;一条队列只在第一个包经过后才开始输出(`loggers.cpp:194`
   `if (_queue==NULL) return`)。→ 只要有流经过,agg→core 数据就在。
2. **队列 ID→层 映射可无源码改动恢复**。`main_uec.cpp:1103` 调用
   `dump_idmap()`,在运行目录写出 `idmap.txt`(`loggers.cpp:18`),把每个 ID 映射到
   带层级语义的名字。已确认含 128 条 `US{agg}->CS{core}` 队列(agg→core 上行,
   即 `-failed` 作用层)。
3. **流量只能靠手写 `.cm`**(main_uec 未把 permutation/incast 生成器暴露成 flag),
   因此多流场景完全可控、可复现。
4. **NSCC 是延迟型 CC**,稳态把瓶颈队列维持在 `_target_Qdelay`(本配置实测
   ≈10.5µs)附近 → 一旦某链路成为瓶颈,其稳态队列天然非零,即 C_cc floor 的来源。

---

## 2. 核心设计决策(brainstorming 已敲定)

| 维度 | 决策 |
|---|---|
| 流量模式 | **Permutation 置换流**(标准 DC-LB benchmark,持续均匀负载,瓶颈在 agg↔core) |
| 瓶颈/自变量 | **保留 `-failed` 链路非对称**(agg→core 降速到 25%),在 agg→core 层测量 |
| per-path q_i 集合 | **按 agg 交换机上行束**:对每个 agg 的 4 条上行,`C_spray=max−min`、`C_cc=min` |
| 判定标准 | **因果对比 + 单调性**(见 §6) |
| 执行策略 | **方案 B:先冒烟找拐点,再跑自适应强度矩阵** |

---

## 3. 已知设计张力(必须诚实暴露)

**好的 LB 可能「绕开」非对称 → C_cc 重新退化。**

folded-Clos 路径极丰富(pod0 流量有 4 agg × 4 上行 = 16 条上行可选)。轻度分散故障
(如 `-failed 2`,仅降 128 条 agg→core 中的 2 条)对**聚合容量**几乎无影响,REPS 很可能
直接把流量绕开降速链 → 降速链空闲、瓶颈消失 → C_cc ≈ 0。

这恰是实验要回答的问题,两种结局都是有效结论:
- REPS 能完全绕开非对称 ⇒ **不存在不可消除的 floor** ⇒ LB 单独够用,**PRISM 无 motivation**(负面结论);
- 非对称集中到削减聚合容量(某 pod 出口被卡死,绕无可绕)⇒ C_cc 持续非零 ⇒ **PRISM 有 motivation**。

因此 floor 出现与否取决于**故障集中度**,不能假设 `failed 2` 就够 → 必须先冒烟扫描集中度
(方案 B 的核心理由)。

`-failed` 选链顺序(实测):failed=2 → agg_sw0 链 0,1;failed=8 → agg_sw0 链 0-3 + agg_sw1 链 0-3。
即 failed=2 时 agg_sw0 是「2 降速 + 2 正常」的混合束(spread 最大);failed=4 时 agg_sw0 整束降速
(spread 消失、floor 抬高)。

---

## 4. 实验设置(含路径)

工作目录: `/home/leo/htsim/htsim/sim/datacenter`(下称 datacenter/);二进制:
`htsim_uec` → `build/datacenter/htsim_uec`。

### 4.1 拓扑(不变)
`datacenter/topologies/fat_tree_128_1os.topo`:128 host / 8 pod;NCORE=16, NAGG=32,
NTOR=32;每 pod 16 host、4 ToR、4 Agg;100Gbps;每跳 1µs(直径 6µs);自动 1×BDP 队列
(178450 字节);ECN 开;trimming 丢包。agg 上行 radix=4(每 agg 4 条 agg→core)。

### 4.2 流量
`datacenter/mvp_runs2/perm.cm`:手写 128 条 permutation。
- 每 host i → 固定目的 π(i)(固定置换,保证可复现;π 取「跨 pod」映射,如 i→(i+64) mod 128,
  使流量真正上到 core 层)。
- 每流 size ≈ **25–30 MB**,start 0,使其在 [500,1500]µs 稳态窗内不结束
  (100Gbps 满速 25MB ≈ 2ms;受竞争后更长)。

### 4.3 仿真命令(每个 run)
```
htsim_uec -topo topologies/fat_tree_128_1os.topo -tm mvp_runs2/perm.cm \
          -nodes 128 -sender_cc_algo nscc -strat <reps|oblivious> \
          -failed <N> -mtu 4150 -log tor_upqueue -logtime_us 2 -end 2
```
- `-log tor_upqueue` 触发全层采样 logger(见 §1.1);`-logtime_us 2` = 2µs 采样
  (够看 floor,省一半数据);`-end 2` = 2ms 时间线。
- **每个 run 结束立刻 `cp idmap.txt mvp_runs2/<tag>.idmap`**(否则被下个 run 覆盖)。
- stdout → `<tag>.stdout`;解码 → `parse_output <log> -ascii`,过滤 QUEUE_APPROX → `<tag>.q.txt`。

### 4.4 产物布局
`datacenter/mvp_runs2/`:`perm.cm`、`<tag>.{stdout,q.txt,idmap}`、`analyze2.py`、
`<tag>.png`、`summary.txt`、`assessment.txt`。**不污染仓库根目录**。

---

## 5. 分析流水线(`mvp_runs2/analyze2.py`)

1. 读 `<tag>.idmap`,建 `id → name`;筛出名字匹配 `^US(\d+)->CS(\d+)` 的队列,
   解析出 `(agg, core)`,得到 **agg→core 层** 的 id 集合,并按 agg 分组(每 agg 4 条上行)。
2. 读 `<tag>.q.txt`,取 `QUEUE_APPROX … RANGE LastQ <bytes>`(`LastQ` 数值在 **p[8]**,
   不是字面量 p[7]);字节→µs 用 `bytes × 8 / 100e9 = bytes × 8e-5 µs`。
3. 对每个 agg、每个采样时刻 t:`C_spray(agg,t)=max−min`、`C_cc(agg,t)=min`(在该 agg 的 4 条上行上)。
4. 取 **稳态窗 [500,1500]µs** 的统计:mean / median / p95。重点输出 **agg_sw0、agg_sw1**
   (带故障链),并给「全体 32 个 agg 的均值」作参考。
5. 出图:agg_sw0 的 C_spray/C_cc 时序;跨配置的 C_spray、C_cc 柱状对比图。

---

## 6. 判定标准(因果对比 + 单调性)

**分解成立 ⇔ 四条同时满足:**
- (i) **floor 存在**:非对称下瓶颈 agg 的 C_cc 在稳态窗有持续非零值(明显高于对称基线);
- (ii) **LB 可消除 spray**:同 `-failed` 强度下,REPS 的 C_spray ≪ Oblivious 的 C_spray;
- (iii) **CC 才能消 floor**:C_cc 对 LB 选择不敏感(REPS ≈ Oblivious);
- (iv) **单调性**:C_cc 随 `-failed` 强度(0 → k → 2k)单调上升。

任一条不满足 → 报「退化 / 部分成立」,**不下最终 go/no-go,不建议进入 PRISM 实现**
(由用户裁定)。

---

## 7. 执行流程(方案 B)

### 阶段 0 — 冒烟(找拐点 k)
跑 1 个诊断 run:REPS + permutation + **重度集中故障**(如先试 `-failed 4` 让 agg_sw0 整束降速,
不够再 8、16…)。用流水线过滤到 agg→core 层、按 agg 束算 C_cc。
**目标:确认「在某故障强度下瓶颈 agg 出现持续非零 floor」并定出拐点 k。**
- 若直到很高强度仍无 floor(REPS 总能绕开)→ **立即停下报告**:此场景下非对称不诱发不可消除拥塞,
  分解退化(负面结论)。

### 阶段 1 — 自适应矩阵(冒烟通过后)
锚定 k,跑:**REPS × failed{0, k, 2k}** + **Oblivious × failed{k}**(约 4 个 run;
若要强化 (iii),Oblivious 补 {0, 2k})。

### 阶段 2 — 分析与汇报
出图 + `summary.txt` + 一段结构化评估(结论 / 依据 / 意外 / 下一步),按 §6 框架汇报,
不下最终结论。

---

## 8. 约束兜底(沿用 prompt.md)

- 不修改 htsim C++ 源码;全部测量经现有 CLI flag + 后处理完成。
- 不对 PRISM 机制性能做任何声称;本实验只测量解耦 baseline。
- 若发现仓库事实与本文档矛盾(flag 改名等),**停下报告**,不即兴改。
- 所有中间文件放 `mvp_runs2/`,不污染仓库根目录。
- 时间预算:冒烟 ~10 分钟,矩阵 4–6 run ~15 分钟,分析 ~30 分钟;任一阶段超 3× 停下报告。
- 只按框架汇报,不自下最终 go/no-go;结论非「成立」时不建议进入 PRISM 实现阶段。

---

## 9. 风险与回退

| 风险 | 应对 |
|---|---|
| REPS 绕开非对称,任何强度都无 floor | 这是有效负面结论,阶段 0 即报告;不强行造数据 |
| permutation 满载导致日志过大/超时 | 2µs 采样 + 仅过滤 agg→core 入 q.txt;必要时缩短 `-end` 或减小流 size,记录改动 |
| 稳态窗选取不当(流未收敛/已结束) | 先看 agg_sw0 时序图确认窗口落在稳态段,再算统计 |
| `idmap.txt` 被下个 run 覆盖 | 每 run 立刻另存 `<tag>.idmap` |
| oblivious 是无自适应的喷洒/散列(`-strat oblivious`,与 REPS 并列的独立选项;精确语义未深究) | 以 C_spray 实测为准,不预设其均衡度;(ii) 是观察不是假设 |
