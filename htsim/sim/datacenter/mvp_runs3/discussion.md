# PRISM 拥塞分解 — 讨论与结论汇总

> 记录到 2026-06-07 的全部讨论与实验。目标:判定 PRISM(通过"拥塞分解"做 CC/LB 协同设计)是否有真实 motivation,即瓶颈拥塞能否干净地分成
> - **C_spray**(路径间不均衡,**LB 可重路由消除**)
> - **C_cc**(所有路径共有的下界,**LB 消不掉,只能靠 CC 降速**)。
>
> 本工作**只测量,不实现 PRISM**。所有产物在 `htsim/sim/datacenter/mvp_runs3/`(及历史 `mvp_runs/`、`mvp_runs2/`),分支 `prism-motivation-redesign`。

---

## 0. 一句话现状

**核心命题被支持,但"驱动归因"没做干净。** 在 per-path RTT 指标 + incast 场景下:分解的两个分量同时非零(判据 i),且 **REPS 的 C_spray ≪ Oblivious(LB 能压平 spread,判据 ii)**、**C_cc 对 LB 不敏感(floor 只能靠 CC,判据 iii)** —— 这就是 PRISM 要的 LB/CC 职责分离。**未**做干净的是"C_spray 由非对称驱动、C_cc 由负载驱动"这条因果链(判据 iv),原因见 §6、§7。

> **Round 4 更新(2026-06-08,见 §9):** 加了公共基线(`global`)和真实传播基线(`const`)两种指标 + 两个隔离场景后,结论被**细化但未改变**:
> - **LB 职责分离更干净了** —— **REPS C_spray < Oblivious 在每个非对称档都成立**(fig5),`C_spray` 确实可由 LB 消除;`C_cc` 只有用**真实传播基线**才测得出,且**随真实负载上升**(fig8)。
> - **判据 (iv) 仍不成立** —— `C_spray` 被**逐包喷洒 + NSCC 动态主导**(对称 f0 时就有 ~9µs),非对称只弱、非单调地叠加;且**非对称会节流负载**(NSCC 降速 → 最快路径变空 → C_cc 反而降,fig7),非对称与负载**纠缠**,无法正交归因。
> - **新发现(基线污染):** per-flow 的 min 基线(`own`/`global`)在**持续拥塞**下会被污染(流根本观测不到空网),`C_cc` 被错误地算成**随负载下降**;只有固定的真实传播基线 `const` 才显出 floor 随负载上升。

---

## 1. 三轮实验的演进

| 轮次 | 设置 | 指标 | 结论 | 致命问题 |
|---|---|---|---|---|
| **Round 1** | 单流 4MB,`tor_upqueue` | 对**全网所有队列**取 max/min | 退化(C_cc≡0) | 单流→多数队列空闲→min≡0;且测错层 |
| **Round 2** | 128 流 permutation | **队列占用**,按 agg 上行束 max/min | 先判"退化",**后被推翻** | 见下 |
| **Round 3** | 32→1 incast | **per-path RTT** `q_i=rtt_i−rtt_min_i` | **部分成立** | 见 §6 |

### Round 2 的推翻(关键转折)
- 队列型 C_cc≈0,一度判"退化"。但用户指出:**非对称 + 高负载下换路换不动了,本就该 CC 降速**——直觉对。
- 改测**吞吐空间**后发现:`failed=16` 时**目的地在 pod0 的 16 条流被砍到 ~24 Gbps**(求和 386 ≈ pod0 入口容量 16×25=400 Gbps),且 **REPS 24.1 ≈ Oblivious 23.8 → LB 无法消除**。这就是不可消除的 CC 份额,**真实存在**。
- **队列型 C_cc 看不见它的两个原因**:
  1. **测错层**:`-failed` 降的是 **core→agg 下行(pod 入口)**,而 round-2 在 **agg→core 上行**测;
  2. **测错空间**:NSCC 是**延迟/trim 型 CC**,设计上就把瓶颈队列**压短**(靠降速),所以不可消除拥塞表现为**速率赤字 + trim**,而非站立队列。队列 floor 只在"填缓冲型 CC"下才出现。

---

## 2. 关于仿真器的已核实事实(踩坑记录)

1. **`-failed N` = 降速,不是断链。** 把链路带宽降到线速 × `failed_link_ratio`(默认 **0.25**,即 100→**25 Gbps**),队列容量、ECN 阈值同样 ×0.25(`fat_tree_topology.cpp:1174-1191`)。**带宽不是 0**,链路仍通、仍是合法候选路径,只是慢 4×。模拟的是"链路降级",不是"link down"。
2. **`-failed` 作用层 = core→agg 下行(`queues_nc_nup`,CS→US)**,即**目标 pod 的入口**;受影响的是**目的地在该 pod 的流**(`fat_tree_topology.cpp:1013-1018`)。`-failed N` 从 agg_sw0 起顺序填充;pod0 的 agg = US0–US3。
3. **LB 算法用 `-load_balancing_algo {reps|oblivious|...}`,不是 `-strat`**(后者是路由策略;给非法值会**静默回退默认 MIXED**——round-2 初跑因此把 reps/oblivious 跑成了同一个 MIXED,被"两组比特级相同"抓到)。
4. **`-end` 单位是毫秒**(`setEndtime(timeFromMs(...))`),`-end 2` = 2 ms(不是 2 µs)。
5. **NSCC 只维护 flow 级 `_base_rtt`,无 per-path RTT 表;无 per-packet ACK+entropy 日志** → 用户定义的 per-path `q_i` **无法用现成 CLI flag 测到**。
6. **但每个 PSN 的发送记录存了 `path_id`**(`uec.h:251`),在 `raw_rtt=now−send_time`(`uec.cpp:1047`)处可直接取到 → 加只读日志钩子即可。
7. **`-paths N`**(默认 64)= 发送端喷洒的 entropy/路径池大小;`-o /dev/null` 会触发 `transposeLog` 断言,需给真实文件。

---

## 3. per-path RTT 指标(用户 Q2 定义,本轮采用)

对**一条流**、它喷洒用的**第 i 条路径**(path i = 发送端所选 `path_id`):
```
q_i      = rtt_i − rtt_min_i        # 该路径最近 RTT − 该路径历史最小 RTT
C_cc     = min_i q_i                # n 条路径里最小的排队延迟(共有下界)
C_spray  = max_i q_i − min_i q_i    # 最堵 − 最空(路径间不均衡)
```
**为什么比 round-2 的队列型更合适**:
- **路径级,不是节点级**:`q_i` 是整条路径的排队延迟,正是 PRISM 命题里的 `q_i`;round-2 在单跳的链路束上取 min,任一链路瞬时空就把 C_cc 归零。
- **就是真实发送端能测到的信号**:`rtt_i − rtt_min_i` 正是 NSCC 自己用的 `delay = raw_rtt − base_rtt`(`uec.cpp:1055`)的 per-path 推广。
- **O(N)→O(1)**:全表 per-path 是测量期的全知视角;真实发送端免维护 per-path 表是 PRISM **实现期**的事,不在本实验。**但"发送端跟踪几条路径"既是可测性条件也是实现问题**(见 §6 发现 3)。

---

## 4. Round 3 实验设置

- **改动**:`uec.cpp` 加只读钩子,env `PRISM_PATHRTT` 触发,每条有效 ACK 写 `time_ns,flow_id,path_id,raw_rtt_ns`。**不改仿真行为**(未设 env 则完全不执行)。
- **场景**:32 发送端(均在 pod0 之外)→ 目的 host0(pod0);`-failed 8` 降 pod0 入口的 US0/US1(US2/US3 正常)。最后一跳 `LS0→host0` 是 incast 共享瓶颈。
- **参数**:`-load_balancing_algo reps|oblivious`,`-sender_cc_algo nscc`,`-paths 8`,`-end 2`(2ms),稳态窗 [500,1500]µs。
- **主统计量**:**跨流中位数**(每条流稳态均值 → 跨流取中位数);比单"代表流"稳健。

---

## 5. Round 3 结果(跨流中位数,单位 µs)

| tag | 角色 | C_spray | C_cc |
|---|---|---|---|
| reps_a0 | REPS 对称 (failed 0) | 7.17 | 1.36 |
| reps_a4 | REPS failed 4 | 7.93 | 1.36 |
| **reps_a8** | **REPS failed 8(决定性)** | **3.37** | **1.45** |
| reps_a12 | REPS failed 12 | 4.21 | 1.33 |
| **obl_a8** | **Oblivious failed 8(LB 消融)** | **8.44** | **1.54** |
| reps_n16 | REPS incast 16 | 7.86 | 1.33 |
| reps_n64 | REPS incast 64 | 样本不足无法聚合 | — |

**判定(设计 §6):**
- (i) 决定性 run 两分量都非零、动态不同 → ✅(reps_a8: 3.37 / 1.45)
- (ii) REPS C_spray ≪ Oblivious → ✅(**3.37 vs 8.44,~2.5×**)
- (iii) C_cc 对 LB 不敏感 → ✅(**1.45 ≈ 1.54**)
- (iv) C_spray~非对称、C_cc~负载(正交驱动)→ ❌/混杂(见 §6、§7)

**结论:部分成立。** LB/CC 职责分离(i,ii,iii)干净;驱动归因(iv)不成立。

---

## 6. 四张图说明了什么(逐图)

四张图在 `mvp_runs3/fig1_decisive.png`…`fig4_sweeps.png`。

**fig1(决定性 run 时序)**:纵轴是**一条代表流**在每个 10µs 格上的两个统计量——`C_spray(t)=max−min`、`C_cc(t)=min`,取在该流的 **8 条路径**上。**不是单条路径、也不是平均**,而是"8 条里最空那条的延迟(C_cc)"和"最堵减最空(C_spray)"。t≈100µs 的尖峰是 incast 启动暂态;稳态窗内两线都>0、形状不同。

**fig2(LB 对比,核心图)**:纵轴 = 跨流中位数。**C_cc 两算法几乎相等(1.45 vs 1.54)= floor 换 LB 消不掉**(因为它来自所有路径共享的 incast 最后一跳)→ 只能靠 CC。**C_spray REPS≪OBL(3.37 vs 8.44)= 不均衡能被好 LB 压平** → LB 的活。两根柱合起来 = "LB 管 spread,CC 管 floor"。

**fig3(对称 vs 不对称,反直觉)**:REPS 下 C_spray 从 7.17(对称)降到 3.37(非对称)。**为什么不对称反而更小?** 三个机制:① `q_i` 相对各路径**自己**的 min,而降速链基线本就高 → 走它的路径"结构性慢"被算进基线、不进 `q_i`;② REPS **自适应绕开**慢路径 → 慢路径不载流量、不排队 → `q_i≈0`;③ 对称时 8 条路径都活跃、incast 暂态把某些路径瞬时冲高 → max−min 反而大。**C_cc 两者差不多(1.36 vs 1.45)= floor 由 incast 负载设定,几乎不受链路非对称影响**(非对称在中间入口,floor 在最后一跳)。

**fig4(两个扫描)**:左 `C_spray vs -failed` **非单调**(7.17→7.93→3.37→4.21)→ 非对称不是 C_spray 的干净驱动。右 `C_cc vs incast 度`(16→1.33,32→1.45;64 样本不足缺失)→ 负载越大 floor 越高,**方向符合预期但只有两点、不足以下定论**。

---

## 7. 关键发现 / 教训

1. **测错层 + 测错空间会得出假"退化"。** round-1/2 的负面结论都源于此:`-failed` 在 core→agg 下行(pod 入口),且 trimming+延迟 CC 把拥塞转成速率赤字/trim 而非队列。**先搞清"故障作用在哪一层、拥塞表现在哪个空间",再选指标。**
2. **单"代表流"会误导,要用跨流中位数。** 单代表流在不同 run 里是不同 sender,曾把 LB 对比方向**搞反**(让 Oblivious 看着 spread 更小);跨流中位数修正后才对(fig2)。
3. **per-path-min 的 C_cc 只在"发送端跟踪少量路径"时可观测。** 默认 `-paths 64` 时,per-path 采样太稀疏 → 总有某路径停在自身最小值 → `C_cc=min` 塌成 0。`-paths 8`(密集采样)才测得出 floor。**这同时是可测性条件,也正好回应 O(N)→O(1):现实里发送端跟踪少量路径,既省状态又让分解可测。**
4. **C_spray 在 incast 场景里主要由 incast + 逐包喷洒本身驱动,不是链路非对称。** 对称时(failed=0)就有 7.17µs。所以"非对称→C_spray"在本场景不成立(详见 §8)。
5. **`-failed` 是降速(25%)不是断链**——慢路径仍是合法候选路径,REPS 能绕但不能弃,这影响 C_spray 的解读(§3 机制①、②)。

---

## 8. 关于"非对称 → C_spray 变大"这个直觉

**直觉在原理上正确**(它就是 C_spray 存在的理由),但**有条件成立**;Round 3 恰好踩中了让它反转的条件。

成立条件:
1. **公共基线**:`q_i` 相对"全局最快路径的空载 RTT"算,而非各路径自己的 min。否则慢链路的结构性慢被自身基线吸收,不进 C_spray。
2. **非自适应 LB(Oblivious/ECMP)**,或测"LB 补偿之前的 offered spread"。自适应 LB(REPS)会主动绕开慢路径、压低 C_spray——**这是 LB 在干正事,小 C_spray 是期望结果**,不矛盾。(印证:fig2 同一 failed=8 下 Oblivious C_spray 8.44 ≫ REPS 3.37。)
3. **非对称链路就是区分路径的瓶颈,且没有更大的共享瓶颈淹没差异**(Round 3 被 incast 最后一跳淹没了)。
4. **慢路径要有足够负载**才会真排队。

| 条件组合 | "非对称→C_spray↑" |
|---|---|
| 公共基线 + Oblivious + 非对称在瓶颈处 | ✅ 成立(= 你的直觉) |
| 自适应 LB(REPS) | ❌ 反而降(LB 把 spray 消掉了) |
| per-path 自身 min 作基线 | ❌ 结构性慢被吸收 |
| incast 共享瓶颈主导 | ❌ 中间非对称被淹没 |

**准确表述**:你的直觉描述的是 **offered/未被均衡的 spread**(LB 的输入);Round 3 测的是 **REPS 均衡后、相对自身基线的残余 spread**(LB 的输出)。两者的差值正是 LB 的价值,并不矛盾。

---

## 9. Round 4 执行结果(2026-06-08,补齐 (iv) 的尝试)

按 §9 原计划执行了:① 公共基线 `global` + 真实传播基线 `const`;② 场景 A = 整-pod 过载(32 发送端→pod0 的 8 host)验 iv-a;③ 场景 B = incast 度扫描(对称,N=16/32/64,`-end 8`)验 iv-b;④ 窗内 ≥200 样本门。设计/计划见 `docs/superpowers/specs|plans/2026-06-08-prism-pathrtt-driver-attribution*`。完整数据见 `assessment.txt` 的 ROUND 4 段,图见 fig5–fig8。

**指标(新增两种基线,与 `own` 并列):**
```
own    : q_i = rtt_i − 路径i自身历史min            (Round 3 默认)
global : q_i = rtt_i − B_flow(该流所有路径/时刻min);C_spray = max−min 原始RTT(基线抵消)
const  : q_i = rtt_i − B_prop(固定真实传播floor);B_prop=13945ns(N=1 空载run实测)
```

**结果与判定:**

| 子判据 | 结果 | 证据 |
|---|---|---|
| **iv-a**(C_spray~非对称) | ❌ 不成立(指标伪信号已修,但 C_spray 由喷洒主导) | 预验证:incast 上 `own` C_spray 随 failed **非单调** [7.33,6.49,6.21,7.51] → `global` **单调升** [2.58,2.74,3.33,3.96](修掉 Round-3 反转)。但场景 A:`global` C_spray = OBL [9.07,8.86,9.87,12.44](非单调、f0 就 ~9µs)、REPS [7.36,6.36,7.43,7.31](近平);8 发送端中等负载更平 [12.58,13.34,12.60,12.40]。fig5/fig6 |
| **LB 职责分离**(C_spray 可被 LB 消除) | ✅ **干净成立** | REPS C_spray < OBL 在**每个** failed 档(f0:9.07>7.36;f4:8.86>6.36;f8:9.87>7.43;f12:12.44>7.31)。fig5 |
| **iv-b**(C_cc~负载) | △ 弱成立,**仅在真实传播基线下** | 场景 B:`C_cc(const)` 随 N **单调升** [10.22,10.35,11.38];`C_cc(global)` 反而**降** [7.61,4.97,1.41](污染);`C_cc(own)` 也降 [2.10,1.16,0.78]。最后一跳全程饱和 → 升幅小。fig8 |

**为什么 (iv) 还是没补齐(三条根因):**
1. **C_spray 由逐包喷洒 + NSCC 动态主导,不是非对称。** 对称 f0 时 C_spray 就 ~9µs;非对称只弱、非单调叠加(OBL f12 比 f0 高 37%)。用户"对称→小"的直觉只在"对称且无拥塞且 LB 已均衡"时成立 —— Oblivious 过载下两个前提都不满足。
2. **非对称与负载纠缠。** 场景 A 里 `-failed` 越大,NSCC 越降速 → 总负载下降、那条健康路径变空 → `C_cc(const)` 反而**降** [OBL 6.10,4.39,3.45,0.46](fig7)。非对称不是一个能独立于负载的旋钮,正交归因结构上就难。
3. **per-flow 基线污染(新发现)。** 持续拥塞下流观测不到空网,其 `B_flow` 随负载抬高(中位 16.5→19.4→23.9µs),把要测的 floor 抵消掉,使 `C_cc(global/own)` 看着随负载**下降**。只有固定的真实传播基线 `const` 才显出 floor 随负载上升 —— 这对"真实发送端如何估 base_rtt"是个有意义的提示。

**结论(细化 Round-3 的"部分成立",未改变方向):**
- **核心分解 + LB/CC 职责分离:成立,且比 Round 3 更干净** —— C_spray 可被 LB 消除(fig5 干净);C_cc 是 LB 消不掉的下界,用真实基线测得出且随真实负载上升(fig8)。
- **干净的因果归因(判据 iv):不成立** —— C_spray 喷洒主导、两个驱动纠缠、floor 仅对真实基线可见。
- 按约束 §11:结论**不是**"分解成立 + 驱动可归因",故**不建议进入 PRISM 实现阶段**;不对 PRISM 机制性能做任何声称;最终 go/no-go 由用户裁定。

**若要继续(下一步候选,未执行):** ① 用**非贪婪/受控速率**流量,使对称 f0 真正无拥塞,把"非对称→C_spray"从喷洒噪声里分离;② 让非对称与负载**解耦**(如固定总负载、只改单条链路速率),单独验 iv-a/iv-b;③ 在**速率空间**(goodput 赤字 / trim 率)而非延迟空间测 C_cc(Round 2 已显示不可消除拥塞在速率空间最干净)。

---

## 10. 产物索引

**Round 3(`mvp_runs3/`)**
- `gen_incast.py` — incast `.cm` 生成器(N 个 pod 外发送端 → 单目的)
- `pathrtt_analyze.py`(+`test_pathrtt_analyze.py`)— per-path RTT 分解 + 跨流中位数聚合;6 个单测
- `run_one.sh` — 跑一个配置(env `PRISM_PATHRTT`,`-paths 8`,真实 `-o` 文件)
- `make_figures.py` — 4 张演示图
- `summary.txt` / `assessment.txt` / `smoke.txt` — 数据表 / 结构化评估 / 冒烟记录
- `fig1_decisive.png` … `fig4_sweeps.png` — 演示图
- C++ 钩子:`htsim/sim/uec.cpp`(只读、env 触发)

**Round 4(`mvp_runs3/`)**
- `pathrtt_analyze.py` — 加 `global`/`const` 基线模式 + 窗内采样门(`test_pathrtt_analyze.py` 现 11 测)
- `gen_overload.py`(+`test_gen_overload.py`)— whole-pod overload 生成器(N 发送端→pod 多 host)
- `run_one.sh` — `-end` 由 `END` 环境变量控制(默认 2)
- `make_figures_r4.py` — fig5–fig8(与 Round-3 `make_figures.py` 分开:窗内门使旧 `-end 2` CSV 不再合格)
- `prevalidation.txt` — `global` 重算旧 incast CSV(`own` 反转 → `global` 单调)
- `fig5_lb_ablation.png`(LB 消融,REPS<OBL 每档)、`fig6_baseline_compare.png`(own vs global)、`fig7_ccc_vs_asymmetry.png`(非对称节流负载→C_cc 降)、`fig8_ccc_vs_load.png`(C_cc vs 负载,三基线)
- `assessment.txt` 的 ROUND 4 段 — 完整数据表与判定
- 原始 `*.cm/*.csv/*.stdout` 被 `.gitignore` 忽略(可由 `gen_incast.py`/`gen_overload.py` + `run_one.sh` 复现)

**设计/计划文档(`docs/superpowers/`)**
- `specs/2026-06-08-prism-pathrtt-driver-attribution-design.md`、`plans/2026-06-08-prism-pathrtt-driver-attribution.md`(Round 4)
- `specs/2026-06-07-prism-pathrtt-incast-demo-design.md`(本轮设计)
- `plans/2026-06-07-prism-pathrtt-incast-demo.md`(本轮实现计划)
- Round 2:`specs/2026-06-07-prism-motivation-redesign-design.md`、`plans/2026-06-07-prism-motivation-redesign.md`

**历史**
- `mvp_runs/` — Round 1(单流,退化)
- `mvp_runs2/` — Round 2(permutation;`assessment.txt` 含队列型退化 + 吞吐空间推翻的更正)

---

## 11. 约束(始终生效)
- 不对 PRISM 机制性能做任何声称;只测量解耦 baseline。
- C++ 改动仅限只读日志(env 触发,不改仿真动态)。
- 最终 go/no-go 由用户裁定。
- 中间文件放 `mvp_runs*/`,不污染仓库根目录。
