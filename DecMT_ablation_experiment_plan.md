# DecMT 消融实验设计方案

## 1. 实验目标

当前论文已经通过多组仿真实验展示了 DecMT 在路径不对称、链路降速和 AI 集合通信场景下的性能优势，但现有结果仍难以回答一个关键问题：

> DecMT 的性能收益究竟来自本文提出的 congestion decomposition，还是主要来自更大的拥塞阈值、epoch minimum、EWMA 平滑或 Hold 状态等单独因素？

因此，需要增加一组规模较小但针对性强的消融实验，对 DecMT 的关键机制进行拆分。该实验不要求重新运行全文所有场景，而应选取一个最能体现路径不均衡与共享拥塞共存的代表性场景，用尽可能少的实验回答以下问题：

1. DecMT 的收益是否只是由更宽松的拥塞阈值带来？
2. 使用 epoch minimum 作为 congestion floor 是否优于原始聚合反馈？
3. residual spread 驱动的 Hold 状态是否能够在 floor-only 的基础上进一步改善性能？
4. DecMT 在对称拓扑或不可重路由拥塞下是否会引入明显副作用？

---

## 2. 推荐实验场景

### 2.1 主消融场景

建议优先选择论文中已有实验配置中的一个典型路径不对称场景，以减少新增代码和实验成本。

推荐配置如下：

- 拓扑：128-node fat tree
- 工作负载：Many-to-many
- 网络负载：50%
- Throttled links：8
- 正常链路速率：100 Gbps
- 降速链路速率：25 Gbps
- Buffer：875 KB
- ECN：沿用论文默认配置
- Packet spraying：REPS
- Congestion control 基础算法：NSCC
- 随机种子：沿用正文使用的 10 个 seeds
- 统计方式：报告均值和标准差

该场景已经在正文中表现出较明显的路径不均衡，并且 DecMT 在该场景下相较 REPS+NSCC 具有较大收益，因此适合作为机制归因实验。

若 128-node 场景的趋势不够稳定，也可以使用：

- 1024-node fat tree
- Many-to-many
- 16 或 32 个 throttled links

但从实验时间和图表复杂度考虑，优先推荐 128-node 场景。

---

## 3. 消融版本设计

建议至少比较以下四个版本。

### 3.1 REPS + Original NSCC

这是论文中的原始解耦基线。

其特点是：

- REPS 根据原有反馈更新 entropy cache；
- NSCC 使用原始聚合 queueing-delay 信号；
- 使用 NSCC 推荐的默认 target queueing delay；
- 不包含 epoch-bounded minimum；
- 不包含 floor–spread decomposition；
- 不包含 spread-based Hold。

该版本用于表示现有解耦 spraying 与 CC 设计的基础性能。

---

### 3.2 REPS + Matched-Target NSCC

该版本与 Original NSCC 保持相同算法，只修改其 target queueing delay，使其与 DecMT 使用相同或可比的拥塞阈值。

其目的不是提出新机制，而是排除参数不公平带来的影响。

例如，如果 DecMT 使用：

\[
T_{cc}=14\,\mu s
\]

则 Matched-Target NSCC 也应使用：

\[
T_{\mathrm{NSCC}}=14\,\mu s
\]

其他配置保持不变。

该版本能够回答：

> DecMT 的 goodput 提升是否仅仅来自允许网络维持更高的 queueing delay？

如果 Matched-Target NSCC 的 goodput有所提高，但其 FCT 或 P99 FCT明显恶化，而 DecMT仍能同时维持较高 goodput 和较低 tail latency，则可以说明 DecMT 的优势并非简单的参数放宽。

---

### 3.3 Floor-Only

Floor-Only 保留 DecMT 的 epoch-bounded estimator，但仅使用 congestion floor 驱动 CC，不使用 residual spread 触发 Hold。

建议实现方式为：

- 每个 epoch 统计 \(q_{\min}^{(e)}\) 和 \(q_{\max}^{(e)}\)；
- 令 congestion floor 为：

\[
\hat{C}_{cc}^{(e)}
\]

- CC 的 Decrease 和 Increase 仅由 \(\hat{C}_{cc}^{(e)}\) 与 \(T_{cc}\) 的关系决定；
- 不判断：

\[
\hat{C}_{spray}^{(e)} \ge T_{spray}
\]

- 当 floor 未超过阈值时，直接进入 Increase；
- 仍然保留与 DecMT 相同的 EWMA、epoch length、\(N_{\min}\) 和 NSCC window update function。

该版本用于隔离 epoch minimum 或 congestion floor 本身的贡献。

它能够回答：

> 仅用最低观测排队时延替代聚合反馈，是否已经足以获得大部分性能收益？

---

### 3.4 Full DecMT

Full DecMT 使用论文中的完整设计：

- epoch-bounded minimum and maximum estimator；
- EWMA-smoothed congestion floor；
- EWMA-smoothed residual spread；
- floor 触发 Decrease；
- spread 触发 Hold；
- floor 和 spread 均低于阈值时进入 Increase；
- spraying 继续由 REPS 处理 entropy selection。

Full DecMT 与 Floor-Only 的差异应仅保留在 spread-based Hold 状态上，避免同时修改其他参数。

该对比能够直接回答：

> residual spread 是否提供了超出 minimum-based rate control 的额外收益？

---

## 4. 可选的第五个版本

若实验时间允许，可以加入一个额外版本：

### Raw-Extrema DecMT

该版本保留 floor–spread decomposition 和 Hold 状态，但取消跨 epoch 的 EWMA，直接使用当前 epoch 的原始 extrema：

\[
\tilde{C}_{cc}^{(e)}=q_{\min}^{(e)}
\]

\[
\tilde{C}_{spray}^{(e)}=q_{\max}^{(e)}-q_{\min}^{(e)}
\]

该版本用于评估 EWMA 的作用。

它能够回答：

- EWMA 是否减少了控制状态抖动？
- 原始 extrema 是否容易受到瞬态样本影响？
- DecMT 的收益是否主要来自平滑而非 decomposition？

如果版面或实验时间有限，该版本可以不加入主图，而只在正文中报告一组数值或状态切换次数。

---

## 5. 实验指标

建议至少报告以下三个指标：

1. **Goodput**
2. **Average FCT**
3. **P99 FCT**

其中，Goodput 用于观察不同机制是否因过度降速而损失吞吐，Average FCT 用于反映整体完成效率，P99 FCT 用于检验尾部性能。

若实验代码容易支持，还可以增加以下辅助指标：

- Average queueing delay
- P99 queueing delay
- Increase/Hold/Decrease 状态占比
- 单位时间内状态切换次数
- congestion-window time series

其中，状态占比和状态切换次数对于解释 Hold 的作用尤其有价值，但不是必须项。

---

## 6. 参数公平性要求

所有消融版本应尽量使用相同的实验参数。

需要统一的参数包括：

- topology；
- workload；
- traffic load；
- throttled-link placement；
- random seeds；
- buffer size；
- ECN threshold；
- epoch length \(\tau\)；
- EWMA coefficient \(\beta\)；
- minimum sample count \(N_{\min}\)；
- NSCC increase/decrease functions；
- spraying algorithm and cache size。

特别需要注意 target queueing delay 的公平性。

建议同时报告：

- Original NSCC 使用推荐默认 target；
- Matched-Target NSCC 使用与 DecMT 相同的 \(T_{cc}\)；
- Floor-Only 和 Full DecMT 使用完全相同的 \(T_{cc}\)。

这样可以避免审稿人认为 DecMT 的吞吐提升仅来自更宽松的 target。

---

## 7. 推荐图表形式

### 7.1 主图

推荐使用一张包含三个子图的柱状图或点图：

- Fig. Xa：Goodput
- Fig. Xb：Average FCT
- Fig. Xc：P99 FCT

横轴包含：

- Original NSCC
- Matched-Target NSCC
- Floor-Only
- DecMT

每个柱或点显示 10 个 seeds 的均值，并附标准差误差棒。

如果版面紧张，可以只保留：

- Goodput
- P99 FCT

Average FCT 的结果可在正文中给出。

---

### 7.2 对称场景补充结果

为证明 DecMT 不会在无明显路径不均衡时产生严重副作用，建议再运行一个对称场景：

- 128-node fat tree
- Many-to-many
- 0 throttled links

不一定需要单独绘图，可以在正文中增加一句话，例如：

> Under the symmetric fabric, DecMT changes goodput by only X% and P99 FCT by Y% relative to Floor-Only, indicating that the spread-based Hold state incurs limited overhead when persistent path imbalance is absent.

该结果的作用是提前回应审稿人关于 Hold 导致保守控制或利用率下降的质疑。

---

## 8. 结果应如何解释

理想情况下，实验可能呈现以下趋势。

### 8.1 Original NSCC 与 Matched-Target NSCC

Matched-Target NSCC 可能获得更高 goodput，但同时出现更高 Average/P99 FCT。

这说明简单提高 target 可以减少降速，但会积累更多排队，无法同时平衡吞吐与时延。

### 8.2 Matched-Target NSCC 与 Floor-Only

如果 Floor-Only 在相同阈值下获得更高 goodput或更低 P99 FCT，则说明 epoch floor 比聚合 queueing feedback 更能避免由少量拥塞路径引发的不必要 rate reduction。

### 8.3 Floor-Only 与 Full DecMT

如果 Full DecMT 在 goodput 和 P99 FCT 上继续优于 Floor-Only，则说明 residual spread 并非冗余信号。

合理解释是：

- Floor-Only 在 floor 较低时继续增加窗口；
- 但此时较大的 residual spread 表明路径分布尚未稳定；
- Full DecMT 通过 Hold 暂停窗口增长，为 REPS 的 entropy redistribution 留出时间；
- 因而减少了局部拥塞进一步扩散和随后触发的窗口下降。

即使 Full DecMT 的 goodput 与 Floor-Only 接近，只要其 P99 FCT 更低或状态切换更少，也能够证明 spread-based Hold 的价值。

---

## 9. 论文中可加入的实验描述草稿

### 9.1 Evaluation Setup

> **Component ablation.** We further isolate the contribution of each component in DecMT under the 128-node many-to-many workload with eight throttled links. We compare four variants. Original NSCC combines REPS with the default NSCC configuration. Matched-Target NSCC uses the same target queueing delay as DecMT to exclude gains caused by a more permissive threshold. Floor-Only replaces aggregate delay feedback with the epoch-bounded congestion floor but disables the spread-based Hold state. Full DecMT additionally uses the residual spread to gate window increase. All variants use the same traffic traces, spraying configuration, epoch length, and random seeds.

### 9.2 Result Analysis

> The matched-target baseline improves goodput over the default NSCC configuration, but increases queueing and tail FCT, showing that threshold relaxation alone cannot achieve balanced performance. Floor-Only improves both goodput and FCT under the same target, demonstrating the benefit of separating the observed congestion floor from higher-delay samples. Full DecMT further reduces tail FCT by holding window growth when the residual spread remains large, allowing adaptive spraying to rebalance traffic before additional load is injected. These results confirm that DecMT's gains arise from the joint use of the floor and residual spread rather than parameter tuning alone.

具体百分比需要在实验完成后替换。

---

## 10. 最低可行实验版本

若投稿时间极其紧张，至少完成以下内容：

- 一个 128-node many-to-many 非对称场景；
- 四个版本；
- Goodput 和 P99 FCT 两个指标；
- 10 个 seeds；
- 一张包含两个子图的消融图；
- 正文中明确说明 Matched-Target NSCC 与 DecMT 使用相同阈值。

该最小版本已经能够回应最关键的实验质疑：

> DecMT 的性能提升不是简单的阈值调大，也不是只来自 minimum delay，而是来自 floor-driven rate control 与 spread-based Hold 的组合。

---

## 11. 实验优先级

建议按照以下顺序执行：

1. 实现 Matched-Target NSCC；
2. 实现 Floor-Only；
3. 在主非对称场景运行四个版本；
4. 绘制 Goodput 和 P99 FCT；
5. 补充对称场景；
6. 有余力时增加 Raw-Extrema 或状态切换统计。

优先保证参数公平性和 Floor-Only 对比，不建议在时间不足时扩展大量新拓扑或新工作负载。
