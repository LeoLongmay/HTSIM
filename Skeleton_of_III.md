# Revised Skeleton of Section III: Overview of PRISM

This document records the revised skeleton and writing plan for Section III of the PRISM paper. The design section should present PRISM as a lightweight sender-side coordination layer between adaptive packet spraying and congestion control. The key message is that PRISM is small by design but non-trivial in structure: it decomposes multipath congestion into a reroutable path spread and an irreducible congestion floor, then assigns these two components to the appropriate control loops.

------

## Proposed Section Title

```text
3 Overview of PRISM
3.1 Congestion Decomposition
3.2 Epoch-based O(1) Estimation
3.3 Floor-driven Congestion Control
3.4 Practical Considerations
```

The section should emphasize four points throughout:

1.  PRISM is a sender-side coordination layer, not a new transport protocol.
2.  PRISM’s novelty lies in congestion decomposition, not in introducing a new AIMD law.
3.  PRISM estimates floor and spread with O(1) per-flow state.
4.  PRISM keeps the network and receiver largely unchanged, while all coordination logic stays at the sender side.

A reasonable target length is **15--20 paragraphs**, roughly **1500--2200 English words**, plus one compact architecture figure and one short algorithm.

------

# 3 Overview of PRISM

Before entering Section 3.1, the chapter should start with **three short overview paragraphs**. These paragraphs should be compact and should not repeat the motivation section in detail.

## Paragraph 1: Design Goals

**Main point:** State PRISM’s three design goals.

Suggested paragraph:

```text
PRISM is designed with three goals: (i) high utilization, preserving available path capacity by avoiding rate cuts when congestion is still reroutable; (ii) timely overload reaction, reducing the sending window once the least-congested path also exceeds the target queueing delay; and (iii) O(1) overhead, requiring only constant per-flow state without maintaining per-path queue tables or source-routed paths.
```

This paragraph should not explain the mechanism. It only states what PRISM aims to achieve.

## Paragraph 2: System Modules

**Main point:** Introduce PRISM’s three sender-side modules and their roles.

Suggested paragraph:

```text
PRISM consists of three sender-side modules: (i) entropy selector, which reuses the spraying cache to choose an entropy value for each outgoing packet; (ii) epoch-based estimator, which tracks the minimum and maximum queueing samples within each control epoch to derive C_cc and C_spray; and (iii) floor-driven congestion control, which adjusts the sending window based on the congestion floor while using the path spread only to gate rate increase.
```

This paragraph should make the module responsibilities clear:

-   Entropy selector: where to send.
-   Epoch-based estimator: what congestion components are observed.
-   Floor-driven CC: how fast to send.

## Paragraph 3: Design Insight

**Main point:** State the core insight in one sentence.

Recommended paragraph:

```text
PRISM’s key insight is to replace signal-level coordination with congestion decomposition, assigning the path spread to spraying and the congestion floor to rate control.
```

This sentence should directly distinguish PRISM from STrack-style signal splitting. The goal is not to say “ECN drives spraying and RTT drives CC,” but to say “spread belongs to spraying and floor belongs to CC.”

------

## Suggested Figure: Sender-centric PRISM Architecture

The architecture figure should be compact and sender-centric. Since PRISM’s design modules are all located at the sender side, the figure should not allocate equal space to sender, network, and receiver. Instead, the sender RNIC should occupy most of the figure, while the network and receiver should be compressed into a small “Unmodified ECMP Fabric and Receiver” region.

Recommended layout:

```text
┌──────────────────────────── Sender RNIC ────────────────────────────┐
│ RDMA packets                                                         │
│      ↓                                                               │
│ Entropy Selector  ←──── ACK feedback: EV/path_id, ECN, RTT ───┐     │
│      ↓ data + EV                                             │     │
│ Epoch-based Estimator → C_cc, C_spray → Floor-driven CC ──────┘     │
│                                           ↓                         │
│                                      cwnd update                     │
└──────────────────────────────────────────────────────────────────────┘
                   │
                   │ data packet + EV
                   ↓
┌──────────────────── Unmodified ECMP Fabric and Receiver ─────────────┐
│ ECMP fabric maps EV to an entropy-induced path                       │
│ Receiver ACK echoes EV/path_id, ECN, and RTT sample                  │
└──────────────────────────────────────────────────────────────────────┘
```

The figure should visually emphasize:

-   PRISM is sender-side.
-   The network uses standard ECMP.
-   The receiver only echoes feedback.
-   No switch-side PRISM logic is required.
-   No receiver-side control module is introduced.

Avoid drawing a large network cloud or a large receiver box, since they create empty space and suggest nonexistent design modules.

------

# 3.1 Congestion Decomposition

This subsection should contain **3--4 paragraphs**. It is the conceptual core of PRISM.

## Paragraph 1: Why Aggregate Signals Are Insufficient

**Main point:** Aggregate RTT or average queueing delay cannot distinguish path imbalance from path-wide overload.

This paragraph should explain that the same aggregate delay may arise from two different regimes:

1.  A subset of paths is congested while other paths remain lightly loaded.
2.  All available paths have non-negligible queueing.

The first regime should be handled by spraying because traffic can still be moved to less congested paths. The second regime should be handled by congestion control because no clean path remains. An aggregate signal mixes these regimes and can therefore trigger the wrong action.

Suggested emphasis:

-   High average delay does not necessarily mean all paths are congested.
-   Low average delay does not necessarily mean the congestion floor is safe.
-   The design must separate reroutable imbalance from irreducible overload.

## Paragraph 2: Entropy-induced Paths

**Main point:** Clarify what PRISM means by “path.”

PRISM does not require the sender to know the physical forwarding path. The sender selects an entropy value, or EV, and existing ECMP maps that EV to a forwarding trajectory. Therefore, a “path” in PRISM should be understood as an **entropy-induced path**, not necessarily a physical path explicitly known to the sender.

Key points to include:

-   EV is a sender-controlled header value, such as a UDP source port or path_id field.
-   The switch computes ECMP hash over packet headers.
-   The sender does not directly choose a physical path.
-   The sender only selects the EV, while the fabric maps the EV to a forwarding trajectory.
-   ACKs echo the EV or path_id so that the sender can associate feedback with the entropy choice.

Suggested sentence:

```text
PRISM does not require source routing. The sender selects an entropy value rather than an explicit physical path, and existing ECMP maps this value to an entropy-induced path.
```

## Paragraph 3: Formal Definition of the Decomposition

**Main point:** Define C_cc and C_spray within a control epoch.

Let (e) denote a control epoch. Let (q) denote a queueing sample returned by an ACK during this epoch. PRISM tracks the minimum and maximum queueing samples:

```text
q_min^(e) = min queueing sample observed in epoch e
q_max^(e) = max queueing sample observed in epoch e
```

Then PRISM defines:

```text
C_cc = q_min^(e)
C_spray = q_max^(e) - q_min^(e)
```

Interpretation:

-   (C_{\text{cc}}) is the **congestion floor**. It captures queueing that remains even on the least-congested observed entropy-induced path.
-   (C_{\text{spray}}) is the **path spread**. It captures how uneven the observed queueing distribution is across entropy-induced paths.

## Paragraph 4: Responsibility Assignment

**Main point:** Bind each component to a control loop.

If (C_{\text{spray}}) is high but (C_{\text{cc}}) is low, the problem is mainly path imbalance. The sender should not reduce the congestion window. Instead, the spraying layer should continue avoiding congested entropies and reusing better ones.

If (C_{\text{cc}}) is high, even the least-congested observed entropy-induced path has queueing. In this case, rerouting alone cannot remove congestion, and the congestion controller must reduce the sending window.

Important sentence:

```text
C_spray is not a rate-reduction signal. It only indicates that the spraying loop still has work to do.
```

## Paragraph 5: Difference from STrack-style Signal Splitting

**Main point:** Distinguish PRISM from signal-type decomposition.

STrack-style co-design divides responsibilities by signal type: ECN guides path selection, while RTT guides congestion window adjustment. PRISM divides responsibilities by congestion component: spread is assigned to spraying, and floor is assigned to congestion control.

Suggested phrasing:

```text
STrack asks which signal should drive which control loop. PRISM asks which part of congestion each loop should control.
```

This paragraph should be concise but important. It anchors the novelty of PRISM.

------

# 3.2 Epoch-based O(1) Estimation

This subsection should contain **3--4 paragraphs plus one short algorithm**. It establishes the deployability of PRISM.

## Paragraph 1: Avoiding Per-path State

**Main point:** A direct implementation would require per-path queue state, which is too expensive for RNIC-friendly deployment.

Computing exact max and min queueing delay over all entropy-induced paths may appear to require a queueing table for every active entropy. PRISM avoids this by observing that the controller does not need to know which path is physically best or worst. It only needs the shape of the queueing distribution within a recent epoch.

Suggested key sentence:

```text
The entropy selector keeps path identity, while PRISM keeps distribution shape.
```

This sentence should appear in this subsection.

## Paragraph 2: Queueing Sample and Base RTT

**Main point:** Define the queueing sample used by the estimator.

For RTT-based feedback, each ACK provides an RTT sample. PRISM computes queueing delay as:

```text
q = max(RTT_sample - RTT_base, 0)
```

The base RTT is defined as the minimum RTT recently observed by the connection over its active entropy set. It approximates propagation and fixed processing delay without queueing.

Important clarification:

-   (RTT_{\text{base}}) is not the minimum RTT over all possible physical paths.
-   It is the minimum observed RTT for the current connection.
-   In regular fat-tree topologies, equal-cost paths usually have similar propagation delay, so this estimate is stable.
-   If path lengths vary, a low percentile RTT can be used instead of a strict minimum.

## Paragraph 3: Epoch Length

**Main point:** Define the control epoch and treat it as a timing parameter.

PRISM uses an epoch length:

```text
Delta_e = kappa * RTT_base
```

The default is (\kappa=1), i.e., one base RTT. This aligns control decisions with the feedback freshness of the connection. A shorter epoch may not collect enough samples, while a longer epoch may delay rate reaction. Therefore, (\kappa) should be included in parameter sensitivity analysis.

Key point:

```text
The epoch is not a hidden constant. It is a timing parameter tied to the connection’s RTT scale.
```

## Paragraph 4: Epoch-based Min/Max Estimator

**Main point:** Maintain only two scalar values per epoch.

For each connection, PRISM maintains:

```text
q_min^(e), q_max^(e)
```

Upon receiving an ACK, PRISM updates:

```text
q_min^(e) = min(q_min^(e), q)
q_max^(e) = max(q_max^(e), q)
```

At the epoch boundary, PRISM computes:

```text
C_cc = q_min^(e)
C_spray = max(q_max^(e) - q_min^(e), 0)
```

Then it resets the epoch statistics.

## Paragraph 5: Why Epoch-based Estimation Is Preferable

**Main point:** Epoch-based estimation avoids extra tuning parameters and stale minima.

Earlier EWMA-style estimators would require multiple smoothing constants, such as up/down gains for floor and high trackers. This would make the system harder to tune and harder to explain. Epoch-based min/max estimation avoids these parameters.

It also naturally limits stale samples. A low queueing sample observed in one epoch does not persist forever. At the next epoch, the estimator must observe a fresh low sample again.

Suggested emphasis:

-   No EWMA gain parameters.
-   No per-path queue table.
-   No stale-floor aging parameter.
-   Only the epoch length needs sensitivity analysis.

## Suggested Algorithm: Epoch-based Decomposition

```text
On ACK(ack):
    q = max(ack.rtt_sample - RTT_base, 0)
    epoch_min = min(epoch_min, q)
    epoch_max = max(epoch_max, q)

At epoch boundary:
    C_cc = epoch_min
    C_spray = max(epoch_max - epoch_min, 0)
    epoch_min = INF
    epoch_max = 0
    return C_cc, C_spray
```

The algorithm should remain short. Avoid introducing smoothing coefficients unless experiments later prove that the raw epoch estimator is too noisy.

------

# 3.3 Floor-driven Congestion Control

This subsection should contain **4--5 paragraphs**, plus either a small table or a short control algorithm. It is the mechanism core of PRISM.

## Paragraph 1: PRISM Does Not Redesign AIMD

**Main point:** PRISM does not propose a new increase/decrease law.

This paragraph should explicitly state that PRISM inherits the increase and decrease functions from the underlying congestion controller. It only changes when those functions are invoked.

Suggested sentence:

```text
PRISM does not introduce a new AIMD law. It changes the congestion component that selects among increase, hold, and decrease.
```

This is important for experiment attribution. If performance improves, it should be because the controller reads the right congestion component, not because a new gain was tuned.

## Paragraph 2: Four-quadrant Control Rule

**Main point:** Define the complete control logic.

PRISM uses two semantic thresholds:

-   (T_{\text{cc}}): target congestion floor.
-   (T_{\text{spray}}): tolerated path spread.

The four control regions are:

| Region               | Condition                                                    | Interpretation                                            | Action           |
| -------------------- | ------------------------------------------------------------ | --------------------------------------------------------- | ---------------- |
| Balanced free        | (C_{\text{cc}} < T_{\text{cc}}), (C_{\text{spray}} < T_{\text{spray}}) | The floor is safe and paths are balanced                  | Increase         |
| Reroutable imbalance | (C_{\text{cc}} < T_{\text{cc}}), (C_{\text{spray}} \ge T_{\text{spray}}) | A clean path exists, but paths are imbalanced             | Hold + Spray     |
| Uniform overload     | (C_{\text{cc}} \ge T_{\text{cc}}), (C_{\text{spray}} < T_{\text{spray}}) | All paths are similarly queued                            | Decrease         |
| Mixed overload       | (C_{\text{cc}} \ge T_{\text{cc}}), (C_{\text{spray}} \ge T_{\text{spray}}) | Even the best path is queued, and paths remain imbalanced | Decrease + Spray |

This table is worth including in the paper because it makes the control logic complete and easy to understand.

## Paragraph 3: Decrease Is Triggered Only by the Floor

**Main point:** Explain the most important rule.

PRISM reduces the sending window only when (C_{\text{cc}}) exceeds (T_{\text{cc}}). A high spread alone is not enough to reduce the window. This rule follows directly from the decomposition: spread represents congestion that should be handled by spraying, while floor represents congestion that cannot be removed by rerouting.

Important sentence:

```text
The floor decides whether the rate loop may decrease, while the spread decides whether the spraying loop still has work to do.
```

## Paragraph 4: Spread Gates Increase but Does Not Cause Decrease

**Main point:** Explain the hold state.

When (C_{\text{spray}}) is high but (C_{\text{cc}}) is low, PRISM holds the congestion window. It does not decrease, because a clean path still exists. It also does not increase, because increasing the window before spraying has rebalanced traffic may amplify the imbalance.

Suggested sentence:

```text
Spread is a brake on increase, not a trigger for decrease.
```

This sentence prevents readers from interpreting (C_{\text{spray}}) as another rate-reduction signal.

## Paragraph 5: Mixed Overload

**Main point:** Explain the fourth region.

When both (C_{\text{cc}}) and (C_{\text{spray}}) exceed their targets, PRISM treats the state as mixed overload. The rate loop decreases the window because the floor is high, while the spraying loop remains active because the spread is also high. The decrease aggressiveness is determined by the underlying CC and the magnitude of the floor, not by the spread itself.

This avoids introducing a new aggressive-decrease parameter while still acknowledging that this region is more severe than uniform overload.

## Paragraph 6: Timescale Separation

**Main point:** Explain how the fast spraying loop and slower CC loop interact.

Spraying reacts at packet or ACK granularity because it updates entropy decisions whenever feedback arrives. CC reacts at epoch granularity, after min/max statistics have been collected. This timescale separation gives spraying time to reshape the path distribution before CC decides whether the congestion floor is truly high.

This paragraph should stay intuitive. It does not need a formal stability analysis.

## Suggested Algorithm: Floor-driven Control

```text
At epoch boundary:
    C_cc, C_spray = decomposition()

    if C_cc < T_cc and C_spray < T_spray:
        cwnd = baseline_increase(cwnd, C_cc)
    else if C_cc < T_cc and C_spray >= T_spray:
        cwnd = cwnd
        keep_spraying_active()
    else if C_cc >= T_cc and C_spray < T_spray:
        cwnd = baseline_decrease(cwnd, C_cc)
    else:
        cwnd = baseline_decrease(cwnd, C_cc)
        keep_spraying_active()
```

Keep the algorithm short and symbolic. Do not expose additional gain parameters in the main design.

------

# 3.4 Practical Considerations

This subsection should contain **4--5 paragraphs**. It prevents the design from looking idealized or underspecified.

## Paragraph 1: Parameter Setting

**Main point:** PRISM has two semantic thresholds and one timing parameter.

PRISM exposes:

-   (T_{\text{cc}}): target congestion floor.
-   (T_{\text{spray}}): tolerated path spread.
-   (\Delta_e = \kappa RTT_{\text{base}}): control epoch length.

(T_{\text{cc}}) should be inherited from the underlying CC’s target queueing delay. (T_{\text{spray}}) can default to (T_{\text{cc}}) or a fixed ratio of it. The default epoch uses (\kappa=1), while (\kappa) should be varied in sensitivity analysis.

Suggested sentence:

```text
PRISM adds two semantic thresholds and one RTT-scaled timing parameter, not a new set of control gains.
```

## Paragraph 2: Signal Source

**Main point:** Define where the queueing sample comes from.

The default signal is RTT-derived queueing delay:

```text
q = max(RTT_sample - RTT_base, 0)
```

If INT is available, PRISM can use bottleneck queue depth directly, which should improve decomposition accuracy. ECN-only feedback can support a coarse variant, but it is not the primary design because a single ECN bit does not provide enough information to estimate floor and spread precisely.

This paragraph should present RTT as the default and INT as a stronger optional signal.

## Paragraph 3: EV, ECMP, and Receiver Feedback

**Main point:** Clarify what is required from the fabric and receiver.

PRISM does not require source routing or switch modifications. The sender selects an EV, existing ECMP maps the EV to an entropy-induced path, and the receiver echoes the EV or path_id in ACKs. The ACK also carries ECN and RTT information used by the entropy selector and the estimator.

Key points:

-   The sender selects EV, not a physical path.
-   The switch selects next hop using ECMP hash.
-   The receiver does not compute path identity.
-   The receiver only echoes the EV/path_id carried in the packet.

## Paragraph 4: RNIC-friendly Implementation

**Main point:** Be precise about deployability.

PRISM should be described as RNIC-friendly, not immediately deployable on all commodity RNICs. Ordinary RNICs may not expose enough programmability to implement PRISM as software. However, PRISM’s logic is suitable for programmable NICs, DPUs, or incremental RNIC transport extensions because it requires only constant per-flow state and simple fast-path operations.

Suggested sentence:

```text
PRISM is RNIC-friendly, but not necessarily deployable on today’s closed RNICs without firmware or hardware support.
```

Avoid writing:

```text
PRISM can be directly deployed on existing RNICs.
```

## Paragraph 5: Scope and Boundary Conditions

**Main point:** State where the decomposition is most accurate and where it may degrade — along *two* axes: reroutable-vs-shared-bottleneck (below) and delay-driven-vs-loss/trim-driven (the conflation is a delay-signal phenomenon, so it bites only on large-buffer/lossless fabrics; under shallow-buffer trimming PRISM ties). The full target-regime argument, with the evaluation evidence and the named real fabric classes (lossless RoCE/PFC, InfiniBand, deep-buffer DC), is in `htsim/sim/datacenter/prism_eval/TARGET_REGIME.md`.

PRISM’s decomposition is most meaningful when path delay differences reflect fabric imbalance across alternative entropy-induced paths. In shared downstream bottlenecks, such as receiver-side incast, multiple paths may share the same queue. In this case, spread can be small while the floor is high, so PRISM naturally behaves more like a floor-driven CC scheme.

The paper should not claim that PRISM solves all incast cases through spraying. Instead, the evaluation should include incast to show how PRISM falls back when rerouting is less useful.

## Paragraph 6: State and Computation Overhead

**Main point:** Summarize why the design is lightweight.

Per connection, PRISM adds only a few scalar variables:

-   epoch minimum queueing delay,
-   epoch maximum queueing delay,
-   epoch timestamp or counter,
-   two thresholds shared across connections or configured per class.

Each ACK requires only two comparisons and two assignments. Each epoch requires one subtraction and one four-region control decision. No per-path queue table is maintained.

This paragraph should close the design section by returning to the main claim: PRISM is a lightweight structural correction, not a complex new transport.

------

# Recommended Total Length

| Part                                | Suggested Paragraphs | Function                                                     |
| ----------------------------------- | -------------------- | ------------------------------------------------------------ |
| 3 Overview of PRISM                 | 3                    | Design goals, modules, core insight                          |
| 3.1 Congestion Decomposition        | 4--5                 | Why decomposition, entropy-induced path, formal definition, responsibility assignment, difference from STrack |
| 3.2 Epoch-based O(1) Estimation     | 5 + algorithm        | Queueing sample, base RTT, epoch length, min/max estimator, no per-path state |
| 3.3 Floor-driven Congestion Control | 6 + table/algorithm  | Four-quadrant control logic and loop coordination            |
| 3.4 Practical Considerations        | 5--6                 | Parameters, signal source, EV/ECMP/ACK echo, RNIC-friendly implementation, scope, overhead |

Expected total:

-   **18--25 paragraphs**
-   **1800--2600 English words**
-   **3--4 double-column pages**, depending on figure and algorithm size

If space is tight, merge the following:

-   3.1 Paragraph 2 and 3.
-   3.2 Paragraph 2 and 3.
-   3.4 Paragraph 5 and 6.

------

# Recommended Visual Elements

## Figure: Sender-centric PRISM Architecture

The figure should focus on the sender RNIC and compress the network/receiver region.

It should show:

1.  Entropy selector choosing EVs using the existing spraying cache.
2.  Data packets carrying EVs into the ECMP fabric.
3.  Receiver ACK echoing EV/path_id, ECN, and RTT sample.
4.  ACK feedback updating both the entropy selector and the epoch estimator.
5.  Epoch estimator outputting (C_{\text{cc}}) and (C_{\text{spray}}).
6.  Floor-driven CC updating cwnd.
7.  The network and receiver marked as unmodified.

Recommended figure caption idea:

```text
Overview of PRISM. PRISM is implemented as a sender-side coordination layer. It reuses entropy-based spraying for path selection, estimates the congestion floor and path spread from ACK feedback, and drives congestion control using the floor while using the spread only to gate rate increase.
```

## Algorithm: PRISM Control Epoch

A single algorithm can combine ACK processing and epoch control:

```text
On ACK:
    update entropy selector
    q = max(RTT_sample - RTT_base, 0)
    epoch_min = min(epoch_min, q)
    epoch_max = max(epoch_max, q)

At epoch boundary:
    C_cc = epoch_min
    C_spray = max(epoch_max - epoch_min, 0)

    if C_cc < T_cc and C_spray < T_spray:
        increase
    else if C_cc < T_cc and C_spray >= T_spray:
        hold and spray
    else if C_cc >= T_cc and C_spray < T_spray:
        decrease
    else:
        decrease and spray

    reset epoch statistics
```

This algorithm should stay compact and avoid exposing unnecessary tuning parameters.

------

# Final Writing Strategy

The section should repeatedly reinforce three messages:

1.  **PRISM is small by design.** It is a thin sender-side decomposition layer, not a new transport.
2.  **Small does not mean trivial.** The key contribution is the structural separation of reroutable spread and irreducible floor.
3.  **Deployability matters.** PRISM avoids per-path queue tables, avoids extra smoothing gains, reuses entropy-based spraying, and keeps the network/receiver largely unchanged.

If these messages are maintained consistently, the current outline will read as a disciplined design rather than a thin heuristic.
