# PRISM: one thread from motivation to evaluation

This note ties the motivation figures (`../mvp_runs3/`) to the evaluation results
(`expA_*/` here) so the whole story reads as one argument with a precisely characterized
boundary. Every number below is traceable to a committed result; the regime where PRISM does
**not** help is stated as plainly as where it does.

## 1. Premise — the motivation (delay-signal conflation + CC/LB coupling)

- **figS (`../mvp_runs3/README_signal.md`).** A *decoupled* spraying+CC controller decides
  whether to slow down from the **average** queuing delay, and `avg = floor + reroutable
  spread`. Whenever multipath spray creates path diversity, the mean is inflated by spread the
  load balancer could remove. figS1 shows the per-path delay is bimodal with the mean sitting
  in the empty valley; figS2 shows the mean stays above the slow-down target while the floor
  (`min_i q_i`) stays below it across light-to-moderate load. A single average cannot represent
  the floor — the quantity that says whether *even the best path* is congested.
- **figI (`../mvp_runs3/README_repro.md`).** The optimal static CC aggressiveness **flips**
  between two regimes: Regime A (reroutable, `C_spray ≫ C_cc`) prefers a loose target; Regime B
  (true all-path congestion, `C_cc ≫ C_spray`) prefers a tight one. No single fixed target is
  best in both → CC's optimum is **coupled** to the regime the LB produces.

Both are **delay-signal** statements: they are defined on queuing delay (`rtt − base`).

**The motivation deliberately stopped short of a cost/co-design claim.** README_signal: *"a
signal-representation result, not a cost claim … establishing a cost requires running both
controllers head-to-head, which is Evaluation."* README_repro: *"co-design > best fixed
independent remains an inference; this experiment implements no coordinated controller."* The
evaluation closes exactly these two open ends.

## 2. Mechanism — PRISM

PRISM decomposes the delay signal per epoch into **`C_cc = floor = min_i q_i`** (does even the
best path need slowing? → drives CC) and **`C_spray = max−min`** (is the congestion reroutable?
→ let spraying rebalance, hold the window). It is the coordinated controller the motivation
only inferred. (`../../uec.cpp` `updateCwndOnAck_PRISM`; pure logic `../../prism_decompose.h`.)

## 3. Evaluation — the cost, measured, and its boundary

- **Reroutable AND delay-driven → PRISM wins.** `expA_delaydriven/` (no-trim, 5×BDP buffers,
  delay-MD): under asymmetry (failed ≥ 4) PRISM beats the *decoupled* REPS+NSCC **and** the
  *coupled-SOTA* STrack on both goodput (+19–22%) and FCT (7–12% lower). Crucially STrack
  (coupled, but averaging) does **not** beat REPS+NSCC — so the win is from *decomposing the
  signal*, not from coupling per se. The same experiment adds **MNSCC** (median@NSCC, H ≤ 4
  Nyquist window), the concurrent design that asks whether robust-statistics smoothing on the
  shared NSCC base already captures what the floor does: MNSCC only modestly improves REPS+NSCC
  (+0.7–3.4% goodput at failed ≥ 4), while PRISM's floor beats MNSCC's median by +11–18%
  goodput under asymmetry and +17–25% / ~2.8× lower avg-FCT under load — the median of
  spread-inflated samples remains spread-inflated; the one place the median wins is at f0
  (symmetric), where it ties REPS with no penalty while PRISM pays its known floor over-permit
  cost (`figA2dd_signal`, `figA1dd`). `expA_tspray_tuning/` sharpens it: tightening `T_spray`
  (the spread tolerance) below the ~14 µs default widens the lead to **+25–33%** over both, at
  no symmetric cost. This is the head-to-head cost the motivation said it had not yet run.
  The advantage is also load-dependent: swept over offered load at fixed asymmetry (`figA3dd_load`),
  PRISM ~ties near-idle (no reroutable spread yet) and its FCT lead over REPS+NSCC and STrack widens as
  load approaches saturation — the floor-vs-spread structure of figS only becomes actionable once queues build.
  The same experiment adds **Swift** (Google SIGCOMM 2020; Algorithm 1 + §3.5 flow-scaled-target
  delay-AIMD, same ~14 µs operating point) as a fourth independent delay-CC reference: Swift lands
  in the same cluster as REPS+NSCC / STrack / MNSCC under asymmetry and load (f8 goodput 445 vs
  REPS 431, STrack 415, MNSCC 444 Gbps; load ρ = 0.5 FCT 4.1 ms vs REPS 3.2 ms), while PRISM's
  floor beats it by +9–22% goodput at failed ≥ 4 and +19–36% / ~4× lower avg-FCT under load — the
  floor-decomposition win is robust across the CC design space (AIMD, per-flow average, coupled
  average, median), because all four designs act on a spread-inflated delay signal that can only be
  corrected at the signal-decomposition level, not per-ACK.
- **The win extends to an oversubscribed core, and holds at 1024-node scale.**
  `expB_oversub_asym/`: the same asymmetric advantage generalizes from the 1:1 non-blocking fabric
  to a moderately-oversubscribed **4:1** core — **+14–32%** goodput over both REPS+NSCC and STrack
  once any core link is degraded — bounded by **8:1**, where the 128-node fabric saturates regardless
  of controller. `expD_scale1024/`: at **1024 nodes (8× scale)** both headline wins reproduce
  *undiluted* — D1 (1:1) **+14–25%** goodput at failed ≥ 8 (peak ≥ the 128-node result), and the 4:1
  win **+3.7–30.8%** — and, with more reroutable headroom at scale, the 8:1 case flips from the
  128-node hard-saturation into a PRISM **graceful-degradation** win: at the heaviest failure REPS and
  STrack complete only ~36% of flows (cr 0.36) while PRISM completes 84% (cr 0.84, +133% goodput).
- **Symmetric fabric → small penalty (diagnosed, and a fix tried + refuted).** At failed=0 PRISM is
  slightly worse: it under-grows because it HOLDs on a cross-path spread that is real but a
  self-resolving *startup transient* (the incast drains to uniformly-low queue), whereas at f8 the
  spread is structural and persistent so the same HOLD pays off (`expA_f0_diagnosis/`). The natural
  fix — a persistence-aware spread signal — was prototyped (flag-gated, not shipped) and **backfired**
  (smoothing also lagged the floor `C_cc` → more cutting; f0 −18%, f4 −15%), so it was removed and
  **PRISM kept O(1)**. The symmetric penalty therefore stands as a *characterized cost* of the O(1)
  decomposition, not a defect — the advantage is asymmetry-specific (`expA_delaydriven/`,
  `expA_tspray_tuning/`).
- **Trimming default → PRISM ties.** `expA_asymmetric/` (P2) and `expA_lossdecomp/`: in the
  UEC-default trimming regime PRISM ties REPS+NSCC. Extending the decomposition to the
  **loss/NACK** signal (`-prism_loss_decomp`) *activates* — PRISM holds ~18% of fabric
  trim-NACKs (loss-HOLD fraction 0.177, vs the delay floor-MD fraction ~0.05) — but still does
  not produce a win.
- **Path-wide overload → PRISM falls back correctly (the other side of the boundary, measured).**
  P4 tested what PRISM does when it *leaves* its target regime and meets non-reroutable overload.
  Under graded oversubscription (`expB_oversub/`, delay-driven, 1:1→4:1→8:1) PRISM is **do-no-harm
  on goodput** at oversub (4:1 −1.3%, 8:1 −1.0% vs REPS+NSCC) and at 8:1 is decisively floor-driven
  — **floor-MD fraction 0.957**, cutting *fewer* times than REPS+NSCC (2693 vs 4586) — so it reacts
  to the genuine core bottleneck through `C_cc` rather than waiting on spray; the cost shows up on
  FCT (+12–14%). Under pure shared-bottleneck incast (`expC_incast/`, symmetric, fan-in 8→64) PRISM
  again falls back to floor-driven CC (floor-MD 0.883 at fan-in 64) and **converges to do-no-harm as
  the fan-in grows** (goodput −11.5% at f8 → −0.4% at f64). Its residual cost is the *same* f0
  phenomenon: a symmetric shared bottleneck still presents a non-trivial transient cross-path spread
  (`C_spray ≈ 0.72·C_cc`) that PRISM partly HOLDs on. (The 1:1 oversub column reproduces the f0
  symmetric penalty exactly.) So PRISM does not mistake irreducible overload for reroutable
  imbalance — it cuts on the floor — which is the fallback-correctness claim, now measured.

## 4. Closure — the boundary IS the premise

The boundary condition where PRISM wins is the same condition the motivation requires. The
motivation is a **delay-signal** phenomenon, so it exists only when the controller is
**delay-driven**:

- In a **delay-driven / large-buffer / no-trim** fabric, queues build, the floor-vs-spread
  structure of figS is real and acted upon, and PRISM's decomposition recovers the performance a
  decoupled averaging controller loses — exactly figS/figI's prediction, now measured (+25–33%).
- Under **trimming**, queues are capped shallow and the controller is loss-driven, not
  delay-driven. The delay signal figS is about is largely absent (the floor-MD fraction stays
  ~0.05), so the conflation does not bite — and even decomposing the loss signal instead finds
  no headroom (REPS already reroutes on every trim-NACK). PRISM ties.

So **the trimming-tie is a corollary of the motivation's scope, not a counterexample.** This is
the honest framing: *characterize when signal conflation matters — reroutable and delay-driven —
and show PRISM recovers the lost performance there*, rather than claiming PRISM improves
performance universally. (Consistent detail: README_signal already flagged that STrack's target
is ~1 base RTT ≈ 14 µs; the eval confirms the runtime `_target_Qdelay` ≈ 14 µs — see
`expA_tspray_tuning/`.)

**Which real fabrics this regime is** — large-buffer/lossless multipath Clos with link asymmetry
(lossless RoCE/PFC, InfiniBand, deep-buffer DC), and why that class is real and important — is argued
in `TARGET_REGIME.md`.

## Map

| Stage | Artifact | Claim |
|---|---|---|
| Motivation | `../mvp_runs3/README_signal.md` (figS) | avg conflates floor + reroutable spread (delay signal) |
| Motivation | `../mvp_runs3/README_repro.md` (figA–figI) | both mechanisms necessary; CC optimum coupled to LB regime |
| Mechanism | `../../prism_decompose.h`, `../../uec.cpp` | PRISM decomposes floor (CC) vs spread (spraying) |
| Eval (win) | `expA_delaydriven/`, `expA_tspray_tuning/` | reroutable + delay-driven: +25–33% over REPS+NSCC & STrack |
| Eval (vs median CC) | `expA_delaydriven/` (MNSCC arm, figA2dd_signal) | PRISM floor beats MNSCC median under asymmetry/load (+11–25%); MNSCC only modestly > REPS+NSCC; median avoids PRISM's f0 cost |
| Eval (vs Swift) | `expA_delaydriven/` (Swift arm) | PRISM floor beats Swift delay-AIMD (+13% f8, +36% load); Swift ~ REPS/STrack/MNSCC cluster |
| Eval (win, load) | `expA_delaydriven/` (figA3dd_load) | open-loop offered-load sweep: PRISM's FCT lead widens with load under asymmetry |
| Eval (win, oversub) | `expB_oversub_asym/` | asymmetric win extends to a 4:1 oversubscribed core (+14–32%); 8:1 = saturation boundary |
| Eval (scale) | `expD_scale1024/` | both headline wins hold undiluted at 1024 nodes (8×); 8:1 becomes a graceful-degradation win |
| Eval (cost) | `expA_delaydriven/` (f0) | symmetric fabric: small penalty |
| Eval (boundary) | `expA_asymmetric/` (P2), `expA_lossdecomp/` | trimming default: ties (delay signal absent; loss-decomp no headroom) |
| Eval (fallback) | `expB_oversub/` | path-wide overload: goodput do-no-harm, floor-driven (floor-MD 0.957); FCT cost |
| Eval (fallback) | `expC_incast/` | shared-bottleneck incast: floor-driven fallback, cost shrinks with fan-in (−11.5%→−0.4%) |
