# expC2_incast_asym — PRISM under asymmetric (structured) incast

## 1. 这组测什么

与 `../expC_incast`(纯共享瓶颈 → PRISM 优雅退化/付代价)配对。

**预注册假设(本组设计动机):** 在 incast 上叠加 `-failed` 链路退化,或许能制造**可重路由的
fabric 结构**——若如此,PRISM 的 spread 信号将是**真实**的(而非 expC 的瞬态伪信号),拥塞
分解(floor 管真实末跳瓶颈、spread 把流量喷离坏路)有望避免 MSwift 描述的 Θ(1/√q) 吞吐崩塌
而取胜;并据此检验:为非对称 many2many 调出的均衡默认 **B=(T_spray 7, T_cc 10, kappa 2)**
是否在非对称 incast 上**也赢**(→ 排除逐实验过拟合)。

**结果(见 §3)反驳了这一假设。** 失败链路并未改变末跳瓶颈的本质——incast 仍由单条 100G 末跳
下行链路主导,无可重路由结构;PRISM 未取胜,B 在此场景反而最差。expC2 因此与 expC 共同界定
**PRISM 的适用边界**:单目的地 incast 不是 PRISM 的受益场景。

## 2. 设置

| 参数 | 值 |
|------|-----|
| 拓扑 | fat_tree_128_1os(末跳 100 Gbps,base_rtt≈14us)|
| 非对称 | -failed {0,2,4,8,12} 退化 core->agg 下行 |
| 制度 | delay-driven (-disable_trim) |
| 工作负载 | incast n→host0,2MB(消息大小扫 {128K,512K,2M,8M})|
| arms | OPS+NSCC, REPS+NSCC, REPS+MNSCC, STrack, PRISM@默认, PRISM@B |
| 切片 | ① failed 扫 @fan-in 32;② fan-in 扫 @failed 8 |
| seeds | 13–17(消息大小扫 13–15)|

一键复现:`bash repro.sh`(原始 data/ 不入库;figs 用 git add -f)。

## 3. 结果

### failed 扫(fan-in=32, 2MB, seeds 13–17 均值)

**Goodput (Gbps):**

| arm | failed=0 | failed=2 | failed=4 | failed=8 | failed=12 |
|-----|----------|----------|----------|----------|-----------|
| OPS+NSCC   | 93.00 | 92.93 | 92.96 | 92.82 | 92.79 |
| REPS+NSCC  | 92.86 | 93.14 | 92.83 | 93.00 | 92.82 |
| REPS+MNSCC | 92.69 | 92.85 | 92.69 | 92.71 | 92.49 |
| STrack     | 93.05 | 93.05 | 92.82 | 92.94 | 92.62 |
| PRISM@def  | 92.80 | 92.80 | 92.73 | 92.60 | 92.47 |
| PRISM@B    | 91.44 | 91.40 | 91.59 | 91.28 | 91.14 |

**avg FCT (us):**

| arm | failed=0 | failed=2 | failed=4 | failed=8 | failed=12 |
|-----|----------|----------|----------|----------|-----------|
| OPS+NSCC   | 4406 | 4254 | 4431 | 4317 | 4400 |
| REPS+NSCC  | 4253 | 4231 | 4328 | 4234 | 4364 |
| REPS+MNSCC | 4426 | 4217 | 4289 | 4299 | 4423 |
| STrack     | 4329 | 4259 | 4359 | 4249 | 4330 |
| PRISM@def  | 4798 | 4768 | 4746 | 4801 | 4835 |
| PRISM@B    | 5280 | 5195 | 5190 | 5176 | 5137 |

**p99 FCT (us):**

| arm | failed=0 | failed=2 | failed=4 | failed=8 | failed=12 |
|-----|----------|----------|----------|----------|-----------|
| OPS+NSCC   | 5506 | 5510 | 5508 | 5516 | 5518 |
| REPS+NSCC  | 5514 | 5497 | 5515 | 5505 | 5516 |
| REPS+MNSCC | 5524 | 5514 | 5524 | 5523 | 5536 |
| STrack     | 5503 | 5502 | 5516 | 5509 | 5528 |
| PRISM@def  | 5517 | 5518 | 5521 | 5529 | 5537 |
| PRISM@B    | 5599 | 5602 | 5590 | 5609 | 5618 |

### fan-in 扫(failed=8, 2MB, seeds 13–17 均值)

**Goodput (Gbps) / avg FCT (us):**

| arm | N=8 gp | N=8 avgFCT | N=32 gp | N=32 avgFCT | N=64 gp | N=64 avgFCT |
|-----|--------|------------|---------|-------------|---------|-------------|
| OPS+NSCC   | 78.34 | 1363 | 92.82 | 4317  | 96.13 | 9515  |
| REPS+NSCC  | 77.74 | 1373 | 93.00 | 4234  | 96.08 | 9530  |
| REPS+MNSCC | 77.51 | 1380 | 92.71 | 4299  | 96.00 | 9540  |
| STrack     | 76.83 | 1444 | 92.94 | 4249  | 96.08 | 9533  |
| PRISM@def  | 74.24 | 1642 | 92.60 | 4801  | 95.81 | 9907  |
| PRISM@B    | 72.94 | 1617 | 91.28 | 5176  | 95.88 | 10230 |

### T_spray 微扫(PRISM, fan-in=32, failed=8)

| T_spray | goodput (Gbps) | avg FCT (us) |
|---------|----------------|--------------|
| 5       | 92.23 | 4937 |
| 7 (B)   | 92.39 | 4849 |
| 10      | 92.33 | 4837 |
| 14 (def)| 92.60 | 4801 |
| 20      | 92.63 | 4795 |
| 28      | 92.63 | 4843 |
| REPS+NSCC (ref) | 93.00 | 4234 |

Note: larger T_spray (20–28) achieves the best PRISM goodput and lowest FCT. T_spray=7 (config B)
is near the bottom — the opposite of the asymmetric many2many result (expA), where smaller T_spray
was better. This is consistent with the incast topology: in a shared-bottleneck incast, aggressive
spray (small T_spray) wastes bandwidth across paths rather than concentrating load at the bottleneck.

### 判定(诚实)

**@default>@B,且 REPS+NSCC 优于所有 PRISM 配置 — do-no-harm 不成立。**

在非对称 incast 场景下,PRISM@B 表现是最差的:

- **goodput**:PRISM@B(91.1–91.6 Gbps)低于 REPS+NSCC(92.8–93.1 Gbps),差距约
  **1.2–1.7 Gbps(−1.3% ~ −1.9%)**,在所有 failed 值下持续。PRISM@def(92.5–92.8 Gbps)
  同样弱于 REPS+NSCC,但差距约 0.1–0.4 Gbps。
- **avg FCT**:PRISM@B(5137–5280 us)比 REPS+NSCC(4231–4364 us)慢 **+18%~+24%**;
  PRISM@def(4746–4835 us)也比 REPS+NSCC 慢 **约 +10%~+13%**。
- **T_spray 微扫**:incast 场景最优 T_spray 为 20–28(对应低频重路由、稳定收敛),
  与 expA 推荐的 T_spray=7 方向**相反**。B=(7,10,2)在此场景确属过拟合到多对多流量。
- **fan-in 扫**:N=8 时 PRISM@B(72.94 Gbps)甚至落后 REPS+NSCC(77.74 Gbps)约 6.2%;
  N=64 时差距收窄至 ~0.2 Gbps,但 avg FCT 仍差 700 us(+7%)。

**原因**:纯 incast 是单目的地共享瓶颈,所有流量天然汇聚在末跳链路,没有"可迁移的
不平衡"。PRISM 的 spray 机制在此反而引入跨路径乱序与重排开销,floor 信号也因目的地固定
而无法通过分流改善队列——与 expC(对称 incast)结论一致。结构性失败链路(-failed)并未
改变末跳瓶颈的本质,故 PRISM spread 信号依然无法转化为吞吐收益。

**叙事**:expC2 与 expC 共同构成"PRISM 的边界":在单目的地 incast 中,无论是否
有链路失败,PRISM 均付出约 1–2% 吞吐 + 10–25% FCT 代价;只在多目的地非对称流量(expA)
中才真正受益。B=(T_spray 7, T_cc 10, kappa 2)的参数来源于 expA 的多对多场景,迁移至
incast 后不仅无益反而更差。

## 4. STrack/MSwift 风格图

- figC2a/b:goodput+avg/p99 FCT vs failed / fan-in(6 arms,PRISM 两条线)
- figC2c:末跳交换机队列时延 ‖ 端到端排队时延 vs 时间(PRISM@B vs REPS+NSCC)
- figC2d:PRISM@B 排队时延 vs 时间,跨 fan-in {8,32,64}(是否稳定在 target)
- figC2e:逐流 goodput vs 时间(PRISM@B 公平收敛 vs REPS+NSCC)
- figC2f:max-FCT(CCT)vs 消息大小
- figC2g:PRISM goodput/FCT vs T_spray 微扫

## 5. 交叉链接 / caveats

- 对照:`../expC_incast`(无结构→退化);参数来源:`../expA_sensitivity`(B 的由来)。
- caveats:128 节点开发规模;-failed 随机退化(跨 arms 同拓扑/seed 对比);仅 delay-driven。
- END_MS 公式:`v=d*1.6+2`(未调整,所有 cells cr>=0.999 通过)。
