# PRISM target-regime argument (design)

**Date:** 2026-06-16
**Phase:** agenda item (a) — the target-regime positioning argument, now load-bearing (both attempted
broadenings — loss-decomposition under trimming, and the f0 persistence fix — were honest negatives,
so PRISM's contribution rests on its target regime being real and important).
**Status:** design, pending user review → controller-direct execution (pure narrative, no new sims; the
implementation is writing the doc directly, as with the prior `NARRATIVE.md` consolidation).

## 1. Goal
Write a focused, evidence-grounded argument for **which real fabrics PRISM targets and why that class
is real and important** — so the evaluation's characterized boundary reads as "PRISM recovers lost
performance in a large, important class of fabrics," not "PRISM is niche." Text-only.

## 2. Deliverables

### 2.1 `htsim/sim/datacenter/prism_eval/TARGET_REGIME.md` (new)
A ~1.5-page reasoned argument. Structure:
1. **Claim (one sentence).** PRISM's decomposition helps iff congestion is **delay-driven AND
   reroutable**; that conjunction defines its target regime.
2. **Axis 1 — delay-driven vs loss/trim-driven.** The conflation is a *delay-signal* phenomenon, so it
   bites only when the controller's slow-down decision is driven by queuing delay — i.e. large-buffer
   fabrics where queues build, or **lossless** fabrics where dropping is not an option so CC must react
   to delay/queue. Contrast: shallow-buffer **trimming** (UEC-default) is loss/trim-driven, the delay
   signal is largely absent, and PRISM ties (cite `expA_lossdecomp/`, `expA_asymmetric/`).
3. **Axis 2 — reroutable vs shared-bottleneck.** The decomposition needs congestion localized to some
   entropy-paths while a *persistent* clean path exists (fabric imbalance across alternative paths).
   Contrast: a shared downstream bottleneck (receiver-side incast, symmetric fabric) has no persistent
   clean path, so PRISM falls back to floor-driven CC at a small cost (cite `expA_f0_diagnosis/`: the
   f0 spread is a self-resolving startup transient, not persistent structure).
4. **The target cell = real fabrics (named, honestly layered).** delay-driven + reroutable =
   large-buffer / lossless multipath Clos with link asymmetry. Name the real classes that instantiate
   these properties: **lossless RoCE/PFC and InfiniBand** (dominant AI/HPC and storage fabrics — cannot
   drop, hence delay-driven by construction), **deep-buffer datacenter switches** (queues build),
   carrying the most performance-critical traffic (collectives, RDMA); multipath packet spray is
   standard in Clos/fat-tree, and link/switch heterogeneity + failures at scale create persistent path
   asymmetry. Where PRISM wins: +25–33% over REPS+NSCC and coupled-SOTA STrack under asymmetry (cite
   `expA_delaydriven/`, `expA_tspray_tuning/`).
5. **The boundary, stated plainly.** Non-targets: shallow-buffer trimming (ties — delay signal absent;
   loss-decomposition found no headroom), and symmetric/shared-bottleneck incast (small cost). **Both
   attempts to extend PRISM past this cell were tried and honestly failed** — loss-decomposition under
   trimming (`expA_lossdecomp/`) and the f0 persistence fix (refuted, removed, O(1) kept,
   `expA_f0_diagnosis/`). This is *why* the target-regime argument is load-bearing, and why the framing
   is "characterize when conflation matters and recover it there," not "universally better."
6. **Honest layering + cross-links.** Explicit note: the regime's *defining properties* (delay-driven,
   large-buffer, lossless, multipath, asymmetric) are what the evaluation *measured*; the claim that
   the named real classes *have* those properties is a *positioning assertion* from their design, not
   something this work measured. Cross-link `NARRATIVE.md`, the cited eval-group READMEs, and the
   Section III skeleton scope paragraph.

### 2.2 Skeleton edit — `Skeleton_of_III.md` 3.4 Paragraph 5 (Scope and Boundary Conditions)
The skeleton's scope paragraph already covers the reroutable-vs-shared-bottleneck (incast) axis and the
O(1) overhead (Para 6). Tighten its "Main point" with **one line** adding the delay-driven-vs-trimming
axis and a forward-reference to `prism_eval/TARGET_REGIME.md` as the full argument. Do not rewrite the
paragraph or the rest of the skeleton.

### 2.3 NARRATIVE cross-link
Add a one-line pointer from `prism_eval/NARRATIVE.md` (its closure/boundary section) to
`TARGET_REGIME.md` as the fuller "which real fabrics" argument. (NARRATIVE already states the boundary;
this just links the positioning piece.)

## 3. Grounding & honesty rules (binding)
- Every **regime-property** claim is traceable to a committed eval group (cite it inline).
- Every **real-system** claim (RoCE/PFC, InfiniBand, deep-buffer DC, AI/HPC collectives) is framed as a
  positioning assertion about that class's *design properties*, explicitly NOT as something measured
  here. No fabricated numbers; no citations invented (property-level assertions, named classes, honest
  "asserted vs measured" layering — per the chosen grounding level).
- The boundary (trimming tie, symmetric cost) and the two refuted extensions are stated as plainly as
  the win — consistent with the project's standing honest-reporting rule.

## 4. Non-goals
- No new simulations, no figures, no new numbers beyond what the cited eval groups already report.
- No rewrite of the Section III skeleton beyond the one-line scope pointer (2.2).
- No literature/related-work section, no invented citations (grounding level B/C explicitly not chosen).
- Does not re-open the f0 or trimming questions; it positions the already-characterized boundary.

## 5. Execution & honesty
- Controller-direct (pure narrative; user-approved), as with the prior `NARRATIVE.md` consolidation — no
  subagent/writing-plans ceremony for a single prose doc. Write `TARGET_REGIME.md`, the one-line skeleton
  pointer, and the NARRATIVE cross-link; verify all cross-link paths resolve.
- Commit batched to a milestone **only on explicit user approval** (standing rule).
