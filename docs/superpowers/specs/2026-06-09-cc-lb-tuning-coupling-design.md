# 设计:figI —— 即使 CC 与 spraying 同时启用,二者“各自为战”仍导致次优

日期:2026-06-09
分支:prism-motivation-redesign
状态:已通过 brainstorming 评审,待写实现计划(writing-plans)

## 1. 目标与可证伪论点

motivation 章节已有两半:
- **figA–F**:floor 高时 spraying 消不掉 → 必须 CC。
- **figG–H**:不对称下仅靠 CC(关掉自适应换路)→ 利用率不足 + 拥塞风暴 → 必须 spraying。

本实验补第三条腿:**即使 CC 与 spraying 同时启用,但两者独立调优(“各自为战”、互不知道对方处理了什么),性能也会次优。**

**可证伪论点:** 固定 spraying 开启(REPS),CC 的最优激进程度(NSCC `target_q_delay`)在两种由 LB 产生的拥塞 regime 之间**翻转**;因此任何单一固定的、独立选定的 CC 设置都会在至少一种 regime 下偏离最优。这就证明“CC 不与 LB/regime 协同 → 次优”。

**核心机理(对应 C_spray/C_cc 分解):** 正确的 CC 激进程度取决于 spraying 能否消除当前拥塞,即取决于 C_spray vs C_cc 谁占主导——而独立调优的 CC 看不到这个分解。

## 2. 关键边界(沿用全项目约束)

- **不实现、不测量 PRISM。** 本图证明“没有单一固定 CC 设置能在两 regime 都最优”,**不**测量协同自适应 CC 的性能。“协同设计能解决它”只作为**有依据的推断**,不作实测声称。
- **零 C++ 改动。** `target_q_delay`、`-failed`、`-log sink`、`-log tor_downqueue` 均为现有 CLI/纯日志。
- **所有中间文件放 `mvp_runs3/`,不污染仓库根目录。**
- **不下最终 go/no-go 结论;诚实标注作用域;不硬凑正结果。**

## 3. 两种 regime(都 REPS + NSCC,5 种子 {13–17}),并实测分解以自证

| regime | 物理含义 | 构造 | 预期分解 | 正确的 CC |
|---|---|---|---|---|
| **A:可换路消除型** | spread 大、floor≈0 | 不对称 `failed=12` + **中等**负载(REPS 能完全绕到健康 US3,floor 不抬起;即 figE 低负载端) | C_spray ≫ C_cc(C_cc≈0) | **宽松**(别降速,REPS 已解决) |
| **B:真·全路径型** | spread≈0、floor 高 | **单接收端 incast**(末跳被所有路共享;figF/fig2 侦察:REPS≡OBL,spraying 无用) | C_cc ≫ C_spray | **激进**(必须降速,换路无用) |

每个 regime 用现有 `pathrtt_analyze.py` 机制实测一组 (C_spray, C_cc),作为图上标注,**证明 regime 确实是所声称的形状**(把“regime 选择”从断言变成实测)。

负载点(Regime A 的发送端数)在侦察阶段定:取 figE 上 C_cc 仍≈0 的最大负载(让 spread 明显但 floor 未抬起)。

## 4. 自变量与度量

- **自变量(CC 激进程度):** `target_q_delay ∈ {2,4,6,8,12,16} µs`(与 figF 同集合;值越小越激进)。spraying 固定 REPS。
- **Regime A 度量:** 聚合 goodput(`-log sink`,稳态窗 [500,1500]µs 求和均值,Gbps)。**预期随 target 上升**(宽松更好);过激进 CC 无谓降速 → 利用率不足。
- **Regime B 度量:** 瓶颈尾部排队时延(`-log tor_downqueue`,接收端 `LS0->DST0` 队列占用换算 µs,取窗内 **p99**)。**预期随 target 上升**(激进更好);过宽松 CC 让 floor 膨胀,而 goodput 已被封顶、不增。

→ 对 A 最优(宽松端)= 对 B 最差(高时延),反之亦然 = **最优翻转**。

## 5. 交付图(figI,一张图、两个子面板)

- **上面板(Regime A):** goodput vs `target_q_delay`,误差棒(5 种子 mean±std)。最优点标在宽松端;阴影标“过激进 CC 浪费的容量”。面板内标注实测 (C_spray≫C_cc)。
- **下面板(Regime B):** p99 排队时延 vs `target_q_delay`,误差棒。最优点标在激进端;阴影标“过宽松 CC 导致的时延膨胀”。面板内标注实测 (C_cc≫C_spray)。
- 两面板都画竖线标默认 `6µs`,显示它在**两 regime 都偏离最优**。
- 标题/脚注一句话点题:独立调 CC(不知道 spraying 产生的 regime)无法两头都赢 → 需要协同。

文件名:`figI_cc_lb_tuning_coupled.png`。生成脚本:`make_coupling_fig.py`(独立于 `make_paper_figs.py`/`make_cc_figs.py`)。

(可选第 2 张:若你更想把 C_spray/C_cc 分解单独成图而非标注,再加 `figJ`;默认只出 figI。)

## 6. 运行矩阵与脚本

- 复用 `run_meas.sh`(已有,纯日志,不动 `run_one.sh`)。需要它支持 `TQD` 环境变量传 `target_q_delay`——`run_one.sh` 已有该模式,把同样的 `TQD_ARG` 逻辑加进 `run_meas.sh`(可选环境变量,不设则用二进制默认 6µs,保持既有 figG/H 调用逐字节不变)。
- 流量:Regime A 复用 `gen_overload.py`(中等发送端数,16 dests);Regime B 复用 `gen_incast.py`(单接收端,发送端数在侦察定,够压出高 floor 即可)。
- 运行数:6 个 `target_q_delay` × 2 regime × 5 种子 = **60 次**(Regime A 取 sink + pathrtt 用于 C_spray/C_cc;Regime B 取 tor_downqueue + pathrtt)。pathrtt 仅各 regime 跑 1 种子用于标注分解即可,减少体量。
- 分解标注:对每 regime 各跑 1 次带 `PRISM_PATHRTT` 的 run,用 `pathrtt_analyze.aggregate_tag` 取 (C_spray, C_cc)。

## 7. 风险与先行侦察(实现计划第一步)

1. **最优是否真翻转(主风险)。** 方向上近乎定义性(A:floor≈0→宽松不伤时延、激进伤吞吐;B:floor 高→宽松伤时延、吞吐封顶),但**幅度未知**。实现第一步先各 regime 跑 1 种子全 `target_q_delay` 扫描,确认两条曲线单调方向相反、最优在两端。**若不翻转**:如实报告,并考虑(i)调 Regime A 负载点使 floor 更干净地≈0,或(ii)改 Regime B 为对称均匀过载以抬高 floor;仍不成立则回报用户,不硬凑。
2. **Regime A 负载点。** 太低→无拥塞、CC 无所谓;太高→floor 抬起、退化成 B。侦察用 figE 曲线定在 C_cc≈0 的最大负载。
3. **p99 时延的瓶颈队列识别。** Regime B 单接收端 incast 的瓶颈是 `LS0->DST0`(qid 由 idmap 按名解析,已在 fig2 侦察验证)。
4. **度量单位。** sink Rate 为 bits/s(figG 已验证);队列 LastQ 为 bytes,×8e-5 = µs@100G(analyze.py 已用)。

## 8. 可复现性与作用域

- 标准同 figA–H:固定 commit、显式 5 种子 + 误差棒、确定性流量、一条命令 `repro.sh`(新增第 9 步)、原始数据 gitignore、图 `git add -f`、度量/窗口写死并在 `README_repro.md` 列出。
- `README_repro.md` 增 figI 段落:论点、两 regime 配置表行、诚实作用域(独立调优次优 = 实测;协同更优 = 推断)。
- **作用域(写进论文与图注):** 仅证明“独立调优 CC 在跨 regime 时次优、最优设置与 LB 产生的 regime 耦合”;**未**证明“协同 co-design 优于最佳固定独立设置”。不对 PRISM 性能做任何声称。

## 9. 成功标准

- figI 两面板的最优点分别落在 `target_q_delay` 轴的相反两端,且默认 6µs 在两面板都可见地低于该 regime 最优(误差棒不重叠或差距明确)。
- 两 regime 的实测 (C_spray, C_cc) 确实落在所声称的象限。
- 一条命令从干净 checkout 重生成 figI;原始数据不入库,仅 figI png 入库。
- 若上述任一不成立,产出的是**诚实的否定/调整报告**,而非硬凑的图。
