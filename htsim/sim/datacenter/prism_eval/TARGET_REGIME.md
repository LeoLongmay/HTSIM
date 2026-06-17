# PRISM's target regime: where the decomposition matters, and why that class is real

This note states, plainly and with the evidence cited, **which fabrics PRISM is for**. The evaluation
characterizes a precise boundary; the purpose here is to argue that the region *inside* that boundary
is a large and important class of real networks — so the result reads as "PRISM recovers performance
that a decoupled averaging controller loses, across an important class of fabrics," not as a niche
win. Where PRISM does **not** help is stated as plainly as where it does, and the line between what we
*measured* and what we *assert* about real deployments is kept explicit (§6).

## 1. The claim

PRISM's congestion decomposition — floor `C_cc = min_i q_i` drives the window, spread
`C_spray = max−min` gates rerouting — helps **if and only if congestion is both delay-driven and
reroutable**. That conjunction is the target regime:

- **delay-driven** — the controller's slow-down decision is governed by *queuing delay*, not by loss
  or trimming; and
- **reroutable** — the congestion is unevenly distributed across the entropy-induced paths, with a
  *persistent* less-congested path the load balancer can shift onto, rather than a single shared
  bottleneck every path must cross.

Both conditions are necessary because the phenomenon PRISM corrects is a *delay-signal* phenomenon
(an average over paths conflates the floor with reroutable spread — the motivation, `../mvp_runs3/`
figS/figI), and the correction (hold the window, let spraying rebalance) only pays off when there is
something stable to rebalance onto. The two axes below make each condition concrete, name where real
fabrics fall, and cite where the evaluation measured the consequence of leaving the regime.

## 2. Axis 1 — delay-driven, not loss/trim-driven

The conflation PRISM corrects is defined on queuing delay (`rtt − base`), so it can only bite when the
controller actually *decides from* delay. That requires queues to build and be observed: either a
**large-buffer** fabric, or a **lossless** fabric where dropping is not an option and congestion
control must therefore react to rising delay/queue occupancy rather than to loss.

- **Inside the regime (delay-driven):** queues build, the floor-vs-spread structure of figS is real
  and acted upon, and PRISM's decomposition recovers the performance a decoupled averaging controller
  gives up. Measured: in the no-trim, 5×BDP-buffer, delay-MD regime under asymmetry (`failed ≥ 4`),
  PRISM beats both the decoupled REPS+NSCC and the coupled-SOTA STrack by **+19–22%** goodput (and
  +25–33% once `T_spray` is tightened), with the floor-MD fraction at **0.374** (≈7× the ~0.05
  trimming baseline) — i.e. the delay decomposition is operative (`expA_delaydriven/`,
  `expA_tspray_tuning/`).
- **Outside the regime (loss/trim-driven):** under the shallow-buffer **trimming** UEC default, queues
  are capped, the controller is driven by trim-NACKs, and the delay signal is largely absent (floor-MD
  fraction ~**0.05**). The conflation does not bite, and PRISM ties REPS+NSCC. Extending the
  decomposition to the *loss* signal activates (it holds ~18% of fabric trim-NACKs) but still finds no
  headroom, because the load balancer already reroutes on every trim-NACK (`expA_asymmetric/`,
  `expA_lossdecomp/`).

**Which real fabrics are delay-driven.** Lossless RoCE/PFC and InfiniBand — the dominant fabrics for
AI/HPC training, collective communication, and disaggregated storage — *cannot* drop packets, so their
congestion control is delay/queue-driven by construction. Deep-buffer datacenter switches likewise let
queues build rather than trim. These fabrics carry the most performance-critical traffic in modern
datacenters, and they sit squarely on the delay-driven side of this axis.

## 3. Axis 2 — reroutable, not a shared bottleneck

The decomposition assumes the per-path delay *differences* reflect **fabric imbalance** across
alternative entropy-paths — congestion concentrated on some paths while a *persistent* clean path
remains. When instead every path funnels through one shared downstream queue, there is nothing to
reroute to: the spread carries no durable signal, and holding the window only forfeits throughput.

- **Inside the regime (reroutable):** structural asymmetry — degraded vs. healthy aggregation switches
  — produces persistent per-path differences (measured rank-stability ~0.8, the clean paths stay clean
  across the flow). Holding and letting REPS shift traffic onto the durable clean path is the right
  move, and it is the source of the asymmetric win above (`expA_delaydriven/`, `expA_f0_diagnosis/`).
- **Outside the regime (shared bottleneck):** a receiver-side incast on a *symmetric* fabric has all
  paths converging on one last-hop queue. There is no persistent clean path; the cross-path spread that
  appears is a self-resolving *startup transient* (it drains from ~31 µs to ~8 µs over the flow), not
  structure. PRISM then falls back toward floor-driven CC at a small cost (at `failed=0`, goodput 869
  vs REPS+NSCC 997), diagnosed as under-growth from holding on that transient spread
  (`expA_f0_diagnosis/`). **P4 measured this fallback at graded scale:** under oversubscription
  (`expB_oversub/`, 1:1→4:1→8:1) PRISM is do-no-harm on goodput (−1.3%, −1.0%) while becoming
  decisively floor-driven (floor-MD fraction **0.957** at 8:1, cutting fewer times than REPS+NSCC),
  and under pure incast (`expC_incast/`, fan-in 8→64) it falls back to floor-driven CC (floor-MD
  **0.883** at fan-in 64) and converges to do-no-harm as the bottleneck becomes more irreducible
  (goodput −11.5% at f8 → −0.4% at f64); the residual cost is the same transient spread
  (`C_spray ≈ 0.72·C_cc`, present in ~98% of epochs). So PRISM cuts on the floor under irreducible
  overload rather than misusing spray — fallback correctness, measured.

**Which real fabrics are reroutable.** Multipath packet spray over a Clos/fat-tree is standard in
datacenter fabrics, so path diversity is the norm rather than the exception; and at scale, link and
switch heterogeneity, partial failures, and degraded links create *persistent* path asymmetry — the
very imbalance the decomposition reads. Pure shared-bottleneck incast is the complementary case the
design explicitly does not try to solve by spraying.

## 4. The target cell is a real, important class of fabrics

The intersection of the two axes — **delay-driven *and* reroutable** — is not a contrived corner. It
is a **large-buffer or lossless, multipath Clos fabric with link asymmetry**: concretely, the modern
AI/HPC RoCE/PFC or InfiniBand cluster, which is lossless (hence delay-driven), packet-sprayed across a
fat-tree (hence multipath), and heterogeneous/partially-degraded at scale (hence reroutable). This is
where the most valuable and congestion-sensitive traffic in the datacenter runs, and it is exactly
where the evaluation measures PRISM recovering **+25–33%** goodput (and lower FCT) over both a
decoupled SOTA controller and a coupled averaging SOTA controller — and crucially, where the coupled
averaging controller (STrack) does *not* beat the decoupled one, isolating the win to *decomposing the
signal* rather than to coupling per se (`expA_delaydriven/`, `expA_tspray_tuning/`).

## 5. The boundary, stated plainly

PRISM is not universally better, and the evaluation says so:

- **Shallow-buffer trimming → ties.** The delay signal is absent; even decomposing the loss signal
  finds no headroom (`expA_lossdecomp/`).
- **Symmetric / shared-bottleneck incast → small cost.** No persistent reroutable spread; PRISM
  under-grows slightly while holding on a transient (`expA_f0_diagnosis/`). Measured at graded scale
  in P4 (`expB_oversub/`, `expC_incast/`): PRISM falls back to floor-driven CC (floor-MD 0.88–0.96),
  is do-no-harm on goodput under oversub, and the incast cost shrinks toward do-no-harm as fan-in
  grows — the cut side is correct; only the FCT/under-growth residual remains.

Both of these are not just conceded — they were *probed*. The two natural ways to extend PRISM past
its target cell were each built and **honestly refuted**: loss-signal decomposition under trimming
activated but won nothing (`expA_lossdecomp/`), and a persistence-aware spread signal meant to remove
the symmetric f0 cost *backfired* (it lagged the floor and cut more, f0 −18%) and was removed to keep
PRISM's O(1) overhead (`expA_f0_diagnosis/`). That both extensions failed is precisely *why* this
target-regime argument carries weight: PRISM's contribution is not "make everything faster" but
**characterize when signal conflation costs performance — reroutable and delay-driven fabrics — and
recover it there**, which the cell in §4 shows is a real and important class. The trimming tie and the
symmetric cost are corollaries of that scope, not counterexamples to it.

## 6. What is measured vs. what is asserted

Keeping the honest line explicit:

- **Measured (in simulation, this evaluation).** That a delay-driven (no-trim, 5×BDP), multipath,
  asymmetric fabric is where PRISM's floor/spread decomposition recovers performance (+25–33%), that
  the trimming default ties, and that symmetric incast costs a little — with the floor-MD fraction,
  loss-HOLD fraction, region split, and per-path stability as the mechanism evidence. The "delay-driven"
  and "reroutable" conditions are operationalized here as the no-trim/large-buffer setting and
  failed-link fabric asymmetry, respectively.
- **Asserted (positioning, not measured here).** That the named real fabric classes — lossless
  RoCE/PFC, InfiniBand, deep-buffer datacenter switches, AI/HPC collective traffic — *instantiate*
  those regime properties, by virtue of their design (losslessness ⇒ delay-driven; Clos multipath +
  scale heterogeneity ⇒ reroutable). We did **not** simulate RoCE/PFC or InfiniBand specifically; the
  claim is that these classes fall on the inside of both axes, which makes the measured regime the
  operative one for them.

## Map

| Stage | Artifact | Claim |
|---|---|---|
| Motivation | `../mvp_runs3/` (figS/figI) | average conflates floor + reroutable spread (a delay-signal phenomenon) |
| Axis 1 (in) | `expA_delaydriven/`, `expA_tspray_tuning/` | delay-driven + asymmetric → +25–33%; floor-MD fraction 0.374 |
| Axis 1 (out) | `expA_asymmetric/`, `expA_lossdecomp/` | trimming → delay signal absent (floor-MD ~0.05) → ties |
| Axis 2 (in) | `expA_delaydriven/`, `expA_f0_diagnosis/` | structural asymmetry persists (rank-stability ~0.8) → reroutable |
| Axis 2 (out) | `expA_f0_diagnosis/` | symmetric incast = shared bottleneck, transient spread → small cost |
| Fallback (P4) | `expB_oversub/`, `expC_incast/` | path-wide overload: floor-driven fallback (floor-MD 0.88–0.96), goodput do-no-harm under oversub, incast cost shrinks with fan-in |
| Boundary | `expA_lossdecomp/`, `expA_f0_diagnosis/` | both extensions past the cell tried and refuted |
| Thread | `NARRATIVE.md` | motivation → mechanism → boundary, one argument |
