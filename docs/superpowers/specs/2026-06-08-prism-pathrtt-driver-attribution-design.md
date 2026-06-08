# PRISM Round 4 — 补齐判据 (iv)「驱动归因」设计

> 日期 2026-06-08。分支 `prism-motivation-redesign`。承接 Round 3
> (`mvp_runs3/discussion.md`、`mvp_runs3/assessment.txt`)。
> 目标:把 Round 3 留下的唯一缺口——判据 (iv)「C_spray 由非对称驱动、C_cc 由负载驱动」
> ——做干净,验证用户的核心直觉「对称小、不对称大」。
> **本工作只测量解耦 baseline,不实现 PRISM、不对其性能做任何声称。**

---

## 1. 背景:Round 3 为什么 (iv) 没成立

Round 3 用 per-path RTT 指标(`q_i = rtt_i − min_i`,`min_i` = 路径 i **自己**的历史最小
RTT)+ 32→1 incast 场景,得到:

- (i)(ii)(iii) 成立:两分量非零;REPS C_spray 3.37 ≪ OBL 8.44;C_cc 1.45 ≈ 1.54(LB 不变)。
- **(iv) 不成立**:C_spray 对 `-failed` **非单调**且对称时(failed=0)就有 7.17µs;C_cc 随 incast
  度只弱单调且 N=64 采样不足。

两个根因(见 `discussion.md` §3/§7/§8):

1. **指标根因 — per-path-own-min 吸收结构性慢。** 降速链路的"结构性慢"(更大的序列化延迟)被
   算进它**自己**的 `min_i`,不进 `q_i` → 非对称反而让 C_spray 变小(fig3 反转)。
2. **场景根因 — incast 最后一跳遮挡。** `LS0→host0` 的共享瓶颈主导了 spread,中间入口的非对称被
   淹没;且 C_spray 主要由 incast + 逐包喷洒本身驱动,不是链路非对称。

Round 4 同时修这两点:**换公共基线指标** + **拆成两个各自隔离驱动的场景**。

---

## 2. 指标层改动(纯 analysis,无新 C++)

C++ 钩子(`uec.cpp` 只读日志,env `PRISM_PATHRTT`)已记录 `time_ns,flow_id,path_id,raw_rtt_ns`,
**无需任何改动**。改动全在 `pathrtt_analyze.py`:加**第二个分解模式**,与现有 per-path-min
**并列**(不替换,以便并排对比展示指标选择如何翻转结论)。

| 模式 | `q_i` 定义 | `C_spray` | `C_cc` |
|---|---|---|---|
| `own`(现状) | `rtt_i − min_i(路径 i 自己历史 min)` | `max_i q_i − min_i q_i` | `min_i q_i` |
| `global`(新) | `rtt_i − B_flow` | `max_i rtt_i − min_i rtt_i`(B 抵消) | `min_i rtt_i − B_flow` |

- **`B_flow` 定义**:该流在**所有路径、所有时间**观测到的最小 raw RTT(= 该流最快路径的空载
  floor),per-flow。这是真实发送端能测到的量(NSCC 的 `base_rtt` 的全局版)。
- **已验证的代数性质**:`global` 模式下基线对所有路径相同,故
  `C_spray = max_i(rtt_i−B) − min_i(rtt_i−B) = max_i rtt_i − min_i rtt_i`,**B 抵消** →
  C_spray 退化成"各路径原始 RTT 的极差",与基线无关;基线只影响 `C_cc`。
- **为什么这修复 iv-a**:降速路径 `rtt_i` 高、基线是全局快速 floor,其差额留在 `max_i rtt_i`
  里 → C_spray 如实反映非对称(不再被自身 min 吸收)。
- **语义自洽**:结构性慢路径的高 `q_i` 计入 C_spray 是合理的——LB 可以把流量**绕离**慢路径,
  即这部分确实是"LB 可消除"的份额。

实现:`decompose(...)` 加参数 `baseline="own"|"global"`;`rtt_min_per_path`(own)旁加
`rtt_min_per_flow`(global)。`aggregate_tag` / `analyze_tag` 透传 `baseline`。

---

## 3. 场景 A — 整-pod 入口过载(验 iv-a「C_spray ~ 非对称」)

把**链路非对称**(而非 incast)做成区分路径的瓶颈,无单 host 最后一跳遮挡。

- **拓扑**:`fat_tree_128_1os.topo`(128 host / 8 pod / 4 agg per pod,100 Gbps)。
- **流量**:**whole-pod overload** —— 多个 pod 外发送端 → **pod0 的多个 host**(非单 host),
  让 pod0 入口层(core→agg 下行 `queues_nc_nup`,即 `-failed` 降速那层)成为饱和瓶颈。
  目的分散到 pod0 的多个 host(避免单 host 最后一跳成为新的共享 floor 淹没非对称)。
  offered load 调到让降速入口饱和(否则慢路径不排队,§8 条件4)。
- **非对称扫描**:`-failed ∈ {0, 4, 8, 12}`(0=对称;每 4 降一个 agg 的入口到 25%)。
- **LB**:
  - **Oblivious 为主**:非自适应 LB 才让"offered spread"显现(§8 条件2)。是 iv-a 的主线。
  - **REPS 对照**:展示自适应 LB 把 C_spray 压回(LB 在干正事,小 C_spray 是期望结果)。
- **关键对照**:`obl_a0`(对称,期望 C_spray 小) vs `obl_a8`(非对称,期望 C_spray 大)
  —— 直接验用户直觉。
- **参数**:`-load_balancing_algo {oblivious|reps}`,`-sender_cc_algo nscc`,`-paths 8`,
  `-failed N`,真实 `-o` 文件,`-end` 取够稳态窗 [500,1500]µs 且每流 ≥200 样本。
- **指标**:主用 `global`;同时出 `own` 做对比(展示翻转)。
- **统计量**:跨流中位数(沿用 Round 3,稳健)。

tag 命名:`A_obl_f{0,4,8,12}`、`A_reps_f8`(REPS 对照)。

---

## 4. 场景 B — incast 度扫描(验 iv-b「C_cc ~ 负载」)

把**负载**(而非非对称)做成唯一变量。

- **流量**:沿用 Round-3 incast(N 发送端 → 单 host0),`gen_incast.py`。
- **拓扑非对称**:**关掉**(`-failed 0`,对称)——把负载从非对称里隔离出来。
- **负载旋钮**:incast 度 `N ∈ {16, 32, 64}`。
- **修采样**:延长 `-end`,使 **N=64 每条流稳态窗 ≥200 样本**(Round 3 在 `-end 2`/N=64 下
  样本不足无法聚合)。`-paths 8` 保持(密集 per-path 采样,floor 才可观测,§7 发现3)。
- **LB**:REPS(单一即可;iv-b 不依赖 LB 对比)。
- **指标**:两基线都看 `C_cc` 随 N 是否单调升。

tag 命名:`B_reps_n{16,32,64}`。

---

## 5. 图 / 判据

四张新图(`mvp_runs3/` 下,接 Round 3 的 fig1–4):

| 图 | 内容 | 期望 = 判据 |
|---|---|---|
| **fig5** | 场景A,Oblivious `C_spray vs -failed`,`own` vs `global` 两条线 | `global` 单调升、`own` 反转 → 复现并修正 fig3 |
| **fig6** | 场景A,`A_obl_f0` vs `A_obl_f8` 柱状(`global`) | 对称小、非对称大 = 用户直觉 |
| **fig7** | 场景A,REPS vs OBL @ failed=8(`global`) | REPS C_spray ≪ OBL → LB 压回(印证 §8 条件2) |
| **fig8** | 场景B,`C_cc vs N`(每流 ≥200 样本) | 单调升 = iv-b |

**判据 (iv) 补齐的定义**:
- **iv-a 成立** ⟺ fig5 的 `global` 线单调升 **且** fig6 中 `A_obl_f0` C_spray < `A_obl_f8` C_spray。
- **iv-b 成立** ⟺ fig8 中 C_cc(N=16) < C_cc(N=32) < C_cc(N=64),且每点每流 ≥200 样本。
- (iv) 补齐 ⟺ iv-a 与 iv-b 同时成立。

若不成立:如实报告,**不**强行宣称分解成立,**不**建议进入 PRISM 实现阶段(约束 §11)。

---

## 6. 执行顺序

1. **先 0 成本预验证(无新仿真)**:实现 `global` 模式 + 单测;用它**重算已有** Round-3 CSV
   (`reps_a0/a4/a8/a12`、`obl_a8`)。若 C_spray(global) 已转为对 `-failed` 单调升,先报这个
   ——它在**最不利**(incast 遮挡)场景下都成立,是强信号。
2. **场景 B**(改动最小,沿用 incast,只延长 `-end` + 对称):跑 N=16/32/64,出 fig8。
3. **场景 A**(需新 whole-pod overload 流量生成器):跑 `A_obl_f{0,4,8,12}` + `A_reps_f8`,
   出 fig5/6/7。
4. 汇总更新 `assessment.txt`(追加 Round 4 段)、`discussion.md`(更新 §0/§5/§9)。

---

## 7. 约束(始终生效,逐字保留)

- 不对 PRISM 机制性能做任何声称;只测量解耦 baseline。
- C++ 改动仅限只读日志(env 触发,不改仿真动态)——本轮**无新 C++ 改动**。
- 所有中间文件放 `mvp_runs*/`,不污染仓库根目录。
- 只按上述框架向用户汇报,不自下最终 go/no-go 结论。
- 结论不是「分解成立 + 驱动可归因」时,不建议进入 PRISM 实现阶段。

---

## 8. 作用域 / 警告

- 即便 (iv) 补齐,结论仍是「分解 + LB/CC 职责分离成立、且驱动可归因」,**不**等于 PRISM 机制有效。
- 单 seed / 单拓扑;新增 whole-pod overload 流量形态的 offered-load 标定需在计划中明确。
- `-failed` = 降速 25% 非断链;慢路径仍是合法候选(REPS 能绕不能弃)。

---

## 9. 产物(Round 4 预期)

- `pathrtt_analyze.py`(+`test_pathrtt_analyze.py`)— 加 `global` 基线模式 + 单测
- `gen_overload.py` — whole-pod overload `.cm` 生成器(多发送端 → pod0 多 host)
- `run_one.sh` — 复用/扩展(传 `-failed`、tag)
- `make_figures.py` — 加 fig5–fig8
- `fig5_baseline_compare.png`、`fig6_sym_vs_asym_global.png`、`fig7_lb_contrast_global.png`、
  `fig8_ccc_vs_load.png`
- `assessment.txt` / `discussion.md` — 追加/更新 Round 4
