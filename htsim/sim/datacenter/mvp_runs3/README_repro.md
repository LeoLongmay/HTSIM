# 可复现的 paper motivation 图(figA / figB / figC)

本目录下进论文的图**全部按可复现标准产出**。任何人从干净 checkout 出发,跑一条命令即可复现。

## 一键复现

```bash
# 0. 编译带钩子的模拟器(从 sim/ 目录)
cd /home/leo/htsim/htsim/sim
cmake -S . -B build && cmake --build build -j      # 产物 build/datacenter/htsim_uec(./htsim_uec 软链)

# 1. 跑出全部数据 + 生成三张图
cd datacenter
bash mvp_runs3/repro.sh
```

产物:`figA_floor_vs_load.png`、`figB_spray_lb_removable.png`、`figC_lb_depends_on_bottleneck.png`。

## 五张图说明(及诚实作用域)

论点:**CC 与 spraying 两种机制都必要**(因此值得协同设计)。

- **figA**:对称 incast,`C_cc`(真实传播基线)随 incast 度 N 上升,且 **REPS 与 OBL 几乎重合** → floor 是 LB 消不掉、随负载增长的不可约拥塞 → **必须 CC**。
- **figB**:whole-pod overload(多目的 host,有路径多样性),`C_spray` 在每个非对称档 **REPS < OBL** → 好 LB 能消除可重路由的不均衡 → **必须 spraying/LB**。
- **figC**:同为对称负载,**单主机 incast(共享末跳、无路径多样性)REPS≈OBL,LB 帮不上**;**whole-pod(路径多样)REPS<OBL,LB 有效** → 机制是否有效取决于瓶颈条件 → **需要按条件协同两种机制**。
- **figD**(时序,2 联面板):**REPS + 非对称(failed=12)**,左=低负载(4 发送端)、右=高负载(32 发送端),画 C_spray(t) 与 C_cc(const, t) 跨流中位数。**低负载 C_cc≈0(REPS 绕开降速路径,LB 独力够用);高负载 C_cc 持续 >0(换路到极限,floor 留存)** → 仅靠 spraying 有上限,**必须配合 CC 降速**。
- **figE**:同场景的负载扫描,`C_cc(const)` 随发送端数从 ~1.2µs(低负载)升到 ~5.3µs(高负载,误差棒收紧)→ **超过好路径容量后,只有 CC 能压低 floor**。量化 figD 的转变。
  - 容量算账:`failed=12` 降 US0–US2(各剩 100G)、US3 健康(400G)→ 好路径容量 ≈400G;8 接收端 =800G。需求 <400G 时 REPS 全走 US3(C_cc≈0),>400G 时被迫外溢/好路径饱和(C_cc>0)。**单流到单 host 永远逼不出(被接收端 100G 封顶),必须多流聚合需求超过好路径容量。**

**作用域(必须在论文里写清)**:以上仅论证"**两种机制各自必要**";**未**证明"**联合 co-design 优于各自独立运行**"——本实验没有测量联合方案的性能,不对 PRISM 机制性能做任何声称。

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

真实传播 floor `B_prop` = `mp_inc_reps_n1.s13` 的 min raw RTT(空载单流;拓扑决定、与种子无关)。

## 今后所有进论文的图的可复现标准(模板)

1. **固定模拟器 commit**(含任何只读钩子),README 写明 SHA 与构建命令。
2. **显式随机种子**,多种子(≥5)+ 误差棒;严禁依赖隐式默认种子或单种子下结论。
3. **确定性输入生成**(流量矩阵脚本无 RNG)。
4. **一条命令复现**(`repro.sh`):构建检查 → 生成输入 → 跑全部 (config × seed) → 生成图。
5. **原始数据可弃**(`.cm/.csv/.stdout` 进 `.gitignore`),**图入库**(`git add -f`)。
6. **度量/窗口/采样门在脚本里写死并在 README 列出**,避免口口相传。
7. **结论与图一一对应、诚实标注作用域**(不夸大、不声称未测量的东西)。

## 复现注意

- 原始 `*.cm / *.csv / *.stdout` 被 `.gitignore` 忽略(可由本流程完全再生);仓库只跟踪脚本、README 与最终 png。
- `figA/B/C` 的底层结论已多种子、稳态复核;**已废弃**的 `fig2_lb_contrast`(incast LB 对比,仅 END=2 暂态成立)、`fig3_sym_vs_asym`(`own`-min 伪信号)**不要**用于论文,原因见上级 `discussion.md` 与 `assessment.txt`。
