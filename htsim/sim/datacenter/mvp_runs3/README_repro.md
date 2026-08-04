# 可复现的 paper motivation 图(figA–figI)

本目录下进论文的图**全部按可复现标准产出**。任何人从干净 checkout 出发,跑一条命令即可复现。

## 一键复现

```bash
# 0. Build the simulator (from the repository root)
cd htsim/sim
cmake -S . -B build && cmake --build build -j      # 产物 build/datacenter/htsim_uec(./htsim_uec 软链)

# 1. 跑出全部数据 + 生成九张图(figA–figI)
cd datacenter
bash mvp_runs3/repro.sh
```

产物:`figA`–`figI`(共九张,见下表)。每张图都**同时输出 `.png`(预览)与 `.pdf`(矢量,放论文/LaTeX 用)**。

## 九张图说明(及诚实作用域)

论点:**CC 与 spraying 两种机制都必要,且必须协同**。三条腿:
**figA–figF** 证明"**仅靠 spraying 不够,必须 CC**";**figG–figH** 证明"**仅靠 CC 不够,必须 spraying**";**figI** 证明"**即便两者都开,但独立调优(各自为战)仍次优,必须协同**"。

- **figA**:对称 incast,`C_cc`(真实传播基线)随 incast 度 N 上升,且 **REPS 与 OBL 几乎重合** → floor 是 LB 消不掉、随负载增长的不可约拥塞 → **必须 CC**。
- **figB**:whole-pod overload(多目的 host,有路径多样性),`C_spray` 在每个非对称档 **REPS < OBL** → 好 LB 能消除可重路由的不均衡 → **必须 spraying/LB**。
- **figC**:同为对称负载,**单主机 incast(共享末跳、无路径多样性)REPS≈OBL,LB 帮不上**;**whole-pod(路径多样)REPS<OBL,LB 有效** → 机制是否有效取决于瓶颈条件 → **需要按条件协同两种机制**。
- **figD**(时序,2 联面板):**REPS + 非对称(failed=12)**,左=低负载(4 发送端)、右=高负载(32 发送端),画 C_spray(t) 与 C_cc(const, t) 跨流中位数。**低负载 C_cc≈0(REPS 绕开降速路径,LB 独力够用);高负载 C_cc 持续 >0(换路到极限,floor 留存)** → 仅靠 spraying 有上限,**必须配合 CC 降速**。
- **figE**:同场景的负载扫描,`C_cc(const)` 随发送端数从 ~1.2µs(低负载)升到 ~5.3µs(高负载,误差棒收紧)→ **超过好路径容量后,只有 CC 能压低 floor**。量化 figD 的转变。
  - 容量算账:`failed=12` 降 US0–US2(各剩 100G)、US3 健康(400G)→ 好路径容量 ≈400G;8 接收端 =800G。需求 <400G 时 REPS 全走 US3(C_cc≈0),>400G 时被迫外溢/好路径饱和(C_cc>0)。**单流到单 host 永远逼不出(被接收端 100G 封顶),必须多流聚合需求超过好路径容量。**
- **figF**:固定 figD 高负载场景(REPS,failed=12,32 发送端),扫 **NSCC `target_q_delay`(CC 激进程度)**。`C_cc(const)` 随 target 单调升(2µs→**0.33µs**,16µs→**5.49µs**)、`C_spray` 基本不随之降 → **floor 由 CC 直接控制,收紧 CC 把 floor 压向 0;C_spray 不是 CC 的活(是 LB 的)**。这把"只能 CC 消 C_cc"从推理变成**实测**。

**——下面两张证明反方向:仅靠 CC 不够,必须 spraying——**(`make_cc_figs.py`,whole-pod overload 64→16,NSCC,failed 扫描,REPS vs **OBLIVIOUS=CC alone:不换路**,5 种子)

- **figG(链路利用率不足)**:聚合 goodput vs 不对称度。failed=0 两者接近,随不对称增大 **OBLIVIOUS 越落越多**(failed=12:REPS 86.8 vs OBL 68.2 Gbps,差 **27%**)→ CC-alone 不能把流挪离降速路,只能对整条流降速,**把健康路径的容量闲置**。同一对 CC 完全相同,差距纯粹来自"没有自适应 LB"。
- **figH(拥塞/重传风暴)**:同一批 run 的**重传比例**(Rtx/New,= trim 风暴代理)vs 不对称度。**OBLIVIOUS 远高于 REPS**(failed=12:OBL **32%** vs REPS **21%**,差随不对称扩大)→ CC 对它无法换路缓解的降速路持续反应不过来,这些路不断溢出 → 被 trim/重传。这是 CC-alone 的**第二个、与利用率不同的代价**:不仅丢吞吐,还制造拥塞风暴;自适应 LB 通过换路消除它。

**诚实记录(figH 的设计经过 + 一个被证伪的直觉)**:最初设想的 fig2 是"机灵的 LB(REPS)把'真·全路径拥塞'误判成不均衡 → 让 NSCC 反应滞后 → 大规模拥塞"。**实测不成立**:(1) 单接收端 incast(最干净的"真·全路径拥塞")下,NSCC 把瓶颈队列稳稳压在 target,且 **REPS 与 OBLIVIOUS 三位有效数字完全一致**(N=16/64/112 的 peakQ/steadyQ/Rtx% 都相等)——末跳被所有路共享时**没有路径多样性**,REPS 无事可做,也就无从"误判不均衡";(2) NSCC 是 **delay+trim** 控制,对"聚合信号误判"这一失效本就大体免疫——该失效是 **STrack 式聚合-ECN-标记**控制器的问题(见 `prompt2.md`),不是 delay-based NSCC 的。因此 figH 改为诚实可测的版本:**CC-alone(OBLIVIOUS)在有路径多样性的不对称过载下产生重传风暴,自适应 LB 消除之**。

**——第三条腿:即便都开,各自为战(独立调优)仍次优——**(`make_coupling_fig.py`,REPS 固定 ON,扫 NSCC `target_q_delay`,5 种子)

- **figI(调优耦合)**:两面板,横轴 = `target_q_delay`(左激进/右宽松)。上=**Regime A(可换路消除,实测 C_spray=10.8≫C_cc=1.6µs)**的 goodput:随宽松上升、**最优在宽松端**(过激进 CC 无谓降速→利用率不足,默认 6µs 比最优少 ~10%);下=**Regime B(真·全路径,实测 C_cc=10.4≫C_spray=3.2µs)**的 **mean 队列时延**:随宽松上升、**最优在激进端**(过宽松 CC 让 floor 膨胀;默认 6µs 比最优高 ~17%)。**最优 CC 在两 regime 翻到相反两端,单一固定的默认值在两边都偏离最优** → CC 的最优激进程度与 LB 产生的 regime(C_spray vs C_cc 谁主导)耦合,独立调 CC(不知 spraying 处理了什么)无法两头都赢 → **必须协同**。(度量:Regime B 用 **mean** 而非 p99——NSCC 靠 trim 封住队列,p99/p90 被钉在缓冲上限、对 CC 不敏感;mean 反映被宽松 CC 抬高的持续 floor,正是 C_cc 所指。)

**作用域(必须在论文里写清)**:以上论证"**两种机制各自必要**"(figA–F:floor 需 CC;figG/H:不对称下需 LB)**以及"独立调优次优、最优设置与 regime 耦合"**(figI);**未**证明"**联合 co-design 优于最佳固定独立设置**"——figI 证的是"没有单一固定 CC 设置能跨 regime 最优"(实测),"协同自适应更优"仍是**推断**,本实验没有实现/测量协同控制器,不对 PRISM 机制性能做任何声称。figG/H 用 OBLIVIOUS 代表"CC alone"(关掉自适应换路);figI 中 REPS 始终 ON,变的只是 CC 激进程度。

**评估已补上这个口子(motivation→eval 闭合)**:上面"协同更优仍是**推断**、本实验未实现协同控制器"这一处,Evaluation 已用 **PRISM**(协同控制器,分解 floor/spread)**实测**兑现,且边界与本动机一致 —— 因为 figS/figI 是**延迟信号**故事,只在**延迟驱动 regime** 成立:
- **延迟驱动 / 大缓冲 / 不裁包**(figI 的 Regime A 类条件):PRISM 在非对称下击败最佳固定独立设置 REPS+NSCC **与**耦合-SOTA STrack(`../prism_eval/expA_delaydriven/`、`../prism_eval/expA_tspray_tuning/`:goodput **+25–33%**),正是 figI/figS 的预测;对称档(failed=0)有小幅代价。
- **trimming 默认 regime**:队列被裁浅、控制转为丢包驱动,figS/figI 所讲的延迟信号基本消失,PRISM **打平**(`../prism_eval/expA_asymmetric/`、`../prism_eval/expA_lossdecomp/`,即便把分解延伸到丢包信号亦然)。

**故 PRISM 的优势是 regime-specific 的:它赢的边界条件正是本动机的前提(可重路由且延迟驱动);trimming-打平是该作用域的推论,而非反例。** 完整叙事见 `../prism_eval/NARRATIVE.md`。

## 度量定义

每条流第 i 条路径 `q_i = rtt_i − 基线`;**C_spray = max_i q_i − min_i q_i**(可被 LB 消除的不均衡)、**C_cc = min_i q_i**(LB 消不掉的共有下界)。基线:`global`=该流所有路径/时刻 min(C_spray 用,基线在 max−min 抵消);`const`=固定真实传播 floor(C_cc 用,取自下文 N=1 空载 run 的 min raw RTT)。统计量:每个种子先取**跨流中位数**,再在**5 个种子上取均值 ± 标准差**(误差棒)。

## 可复现关键点

| 项 | 值 |
|---|---|
| 模拟器钩子 | `htsim/sim/uec.cpp` 的**只读** per-path RTT 日志(env `PRISM_PATHRTT`,提交 `32fde90`)。不改仿真行为。 |
| 随机种子 | **显式 `-seed`**,种子集 `{13,14,15,16,17}`。htsim 给定 (seed, 输入) **确定性**(实测同配置重跑逐字节相同)。 |
| 拓扑 | `topologies/fat_tree_128_1os.topo`(128 host / 8 pod,100 Gbps) |
| CC / LB | `-sender_cc_algo nscc`;`-load_balancing_algo {reps,oblivious}` |
| 路径池 | `-paths 8`(密集 per-path 采样;floor 才可观测) |
| 采样门 | 稳态窗内每条流 ≥200 个 ACK 样本 |
| 流量 | `gen_incast.py`(N→单 host)、`gen_overload.py`(32→pod0 的 8 host),**无随机性,确定性** |

### 各图对应的 run 配置

| 图 | 场景 | `-end` | 稳态窗 (µs) | 配置 | 基线 |
|---|---|---|---|---|---|
| figA | 对称 incast N∈{16,32,64} | 8 ms | [1000,7000] | `mp_inc_{reps,obl}_n{N}` | `const`(C_cc) |
| figB | whole-pod overload f∈{0,4,8,12} | 2 ms | [500,1500] | `mp_wp_{reps,obl}_f{F}` | `global`(C_spray) |
| figC | incast N=32 vs whole-pod f=0(均对称) | 8/2 ms | 同上 | `mp_inc_*_n32` / `mp_wp_*_f0` | `global`(C_spray) |
| figD | REPS whole-pod failed=12,低/高负载(4 vs 32 发送端) | 2 ms | [500,1500] | `mp_load_reps_n{4,32}`(时序用 seed 13) | `const`(C_cc)/`global`(C_spray) |
| figE | REPS whole-pod failed=12,负载扫描 N∈{2,4,8,16,32} 发送端 | 2 ms | [500,1500] | `mp_load_reps_n{N}` | `const`(C_cc) |
| figF | REPS whole-pod failed=12,32 发送端,扫 CC `target_q_delay`∈{2,4,6,8,12,16}µs | 2 ms | [500,1500] | `mp_cc_tqd{Q}`(env `TQD`) | `const`(C_cc)/`global`(C_spray) |
| figG | whole-pod overload 64→16,failed∈{0,4,8,12},REPS vs **OBLIVIOUS** | 2 ms | [500,1500] | `cc_{reps,obl}_f{F}.s{S}`(`run_meas.sh … sink`) | — (聚合 goodput Gbps) |
| figH | 与 figG **同一批 run** | 2 ms | 全程累计 | 同上;读 stdout 的 `New`/`Rtx` | — (重传% = Rtx/New) |
| figI | REPS 固定;Regime A=overload 8→16(failed12)取 goodput、Regime B=incast 32→1(failed0)取 mean 队列时延;各扫 `target_q_delay`∈{2,4,6,8,12,16}µs。**一图两面板**(上=Regime A goodput、下=Regime B latency,共用横轴) | 2 ms | [500,1500] | `cp{A,B}_tqd{Q}.s{S}`;分解 `cp{A,B}_decomp`(END=8) | A:goodput / B:mean lat;分解用 `const` |

真实传播 floor `B_prop` = `mp_inc_reps_n1.s13` 的 min raw RTT(空载单流;拓扑决定、与种子无关)。

figG/figH 的度量来自**纯日志、零 C++ 改动**:`-log sink`(UEC_SINK RATE 记录,接收端 goodput,bits/s)给 figG;每个 run 的 stdout 末行 `New:/Rtx:` 给 figH。封装在 `run_meas.sh`(与 figA–F 的 `run_one.sh` 分开,后者保持逐字节不变);出图在 `make_cc_figs.py`。

## 今后所有进论文的图的可复现标准(模板)

1. **固定模拟器 commit**(含任何只读钩子),README 写明 SHA 与构建命令。
2. **显式随机种子**,多种子(≥5)+ 误差棒;严禁依赖隐式默认种子或单种子下结论。
3. **确定性输入生成**(流量矩阵脚本无 RNG)。
4. **一条命令复现**(`repro.sh`):构建检查 → 生成输入 → 跑全部 (config × seed) → 生成图。
5. **原始数据可弃**(`.cm/.csv/.stdout` 进 `.gitignore`),**图入库**(`git add -f`)。
6. **度量/窗口/采样门在脚本里写死并在 README 列出**,避免口口相传。
7. **结论与图一一对应、诚实标注作用域**(不夸大、不声称未测量的东西)。

## 复现注意

- 所有原始/中间数据(`*.cm *.dat *.csv *.stdout *.idmap *.sink.txt *.q.txt` 等)都被 `.gitignore` 忽略,且**已从磁盘删除以节省空间**——它们由 `repro.sh` 完全再生。本目录只保留:**运行脚本**(`repro.sh`、`run_one.sh`、`run_meas.sh`、`gen_incast.py`、`gen_overload.py`)、**绘图脚本**(`make_paper_figs.py`→figA–F、`make_cc_figs.py`→figG/H、`make_coupling_fig.py`→figI,依赖 `pathrtt_analyze.py`;自检 `test_pathrtt_analyze.py`、`test_gen_overload.py`)、`README_repro.md`,以及 **figA–figI 的 png+pdf**。
- 复现方法:`bash mvp_runs3/repro.sh`(从干净状态重新生成全部数据并产出 figA–figI)。
- 更早的探索版图与脚本(fig1–fig8、`make_figures*.py`、各 round 的 `*.txt`/`discussion.md` 记录)已删除以保持目录整洁,如需可从 git 历史取回。
