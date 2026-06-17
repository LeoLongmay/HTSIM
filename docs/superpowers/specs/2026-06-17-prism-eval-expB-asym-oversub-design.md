# PRISM eval — expB asymmetric oversubscription (design)

**Date:** 2026-06-17
**Phase:** continuation of P4 — does PRISM's delay-driven asymmetric *win* extend to an
oversubscribed core? A read-only experiment (no controller change), orthogonal-axis extension of the
committed symmetric `expB_oversub/`.
**Status:** design, pending user review → writing-plans → subagent-driven execution.

## 1. Goal and framing

`expA_delaydriven/` showed PRISM's headline win on a **non-blocking (1:1)** fabric: under asymmetry
(failed ≥ 4) PRISM beats both the decoupled REPS+NSCC and the coupled-SOTA STrack by +19–22% goodput
(and lower FCT), in the delay-driven regime. The committed `expB_oversub/` showed the *symmetric*
oversub case (failed=0): goodput do-no-harm + an FCT cost (the fallback side).

**This experiment asks the open empirical question:** does the asymmetric win **extend to an
oversubscribed core** — i.e. when the fabric is *both* capacity-constrained (oversub) *and* reroutably
asymmetric (failed links)? This is genuinely uncertain: at 4:1/8:1 the core is already constrained, so
the reroutable headroom a clean path offers may be smaller than at 1:1. The result may be a win
(extends), a tie (no headroom), or 1:1-specific. **Reported straight either way** — this is a
win-hunt with an honest, pre-registered bar, not a guaranteed positive.

## 2. Deliverables

### 2.1 `htsim/sim/datacenter/prism_eval/expB_oversub_asym/` (new group)
The orthogonal asymmetry axis on top of oversubscription. Keeps the committed `expB_oversub/`
(symmetric, x=oversub ratio) intact; this group fixes the oversub ratio and sweeps **#failed links**.
- `repro.sh` — build check, selftest, workload gen, sweep, mechanism run, render.
- `make_figs.py` — thin wrapper over `common/perf_figs.py` (render_main_perf per oversub ratio +
  render_mechanism), with `--selftest`.
- `README.md` — setup, the per-ratio results, the honest win/tie verdict.
- `figs/` — `figBa_4os_main.{png,pdf}`, `figBa_8os_main.{png,pdf}` (goodput/avg-FCT/P99-FCT vs
  #failed, 4 arms), `figBa_mech.{png,pdf}` (mechanism at 4:1, failed=8).

No controller change; no shared-code change (reuses the existing `render_main_perf` / `render_mechanism`).

## 3. Experimental design

- **Two oversub ratios** (both, user-confirmed): `fat_tree_128_4os.topo` (4:1) and
  `fat_tree_128_8os.topo` (8:1) — verified drop-ins; `-failed` degrades core-tier links to 25% speed
  (fat_tree_topology.cpp ~line 1013), confirmed to run on these topos.
- **x-axis = #failed links** (the asymmetry axis), swept `{0, 2, 4, 8}` per ratio. **failed=8 is a cap
  candidate:** oversub reduces the agg→core link count (4× fewer at 4:1, 8× at 8:1), so a requested
  failed count can exceed the available links. The plan **verifies** the actual degraded-link count per
  topo (count the binary's `Failure: ...` stdout lines == requested failed); if a value over-saturates
  (degrades fewer links than requested, i.e. clamped), it is dropped and the README records the cap.
- **Arms (4):** OPS+NSCC (`nscc oblivious`), REPS+NSCC (`nscc reps`), STrack (`strack reps`), PRISM
  (`prism reps`) — identical to `expA_delaydriven`, so the CC decision is the only variable.
- **Common:** delay-driven (`EXTRA_ARGS="-disable_trim"`), 2 MB many2many 64→16 pod0 (same workload as
  expA/expB), `PATHS=8`, seeds {13–17}, `END_MS=8` (verify cr≈1.0; bump via `EXP_END` if a heavily
  degraded cell is short, recording it).
- **failed=0 column** = the committed symmetric-oversub point (do-no-harm goodput + FCT cost) — the
  baseline the asymmetric columns are read against.
- **Mechanism condition:** 4:1, failed=8, seed 13, all 4 arms with `PRISM_PATHRTT` (PRISM also
  `PRISM_EPOCH`) — render the C_cc/C_spray/cwnd + floor-MD fraction, like expA.

## 4. Metrics, figures, and the pre-registered read

- **Metrics:** aggregate goodput (Gbps), avg-FCT, P99-FCT, completion ratio — via `common/metrics.py`,
  mean ± across seeds, per (oversub, failed, arm). Internal: floor-MD fraction + per-ACK cut counts at
  the mechanism point.
- **Figures:** one `render_main_perf` per oversub ratio (x=#failed, xlabel e.g. "# failed core links
  @ 4:1 oversub, delay-driven"), tag-prefixed `expBa4os` / `expBa8os`; one `render_mechanism` at 4:1
  failed=8 (tag prefix `expBa4os`, mech label "4:1 oversub, failed=8").
- **Pre-registered verdict (mirrors expA's bar):** a **win** at a given oversub ratio = PRISM goodput
  exceeds **both** REPS+NSCC and STrack by **≥ 5%** at failed ≥ 4. Report per ratio:
  - **Win** → the asymmetric advantage extends to oversubscription (strengthens the thesis; note the
    floor-MD evidence and any FCT cost).
  - **Tie / no-win** → state plainly that the advantage does not extend to a constrained core (the win
    is non-blocking-specific); report the numbers and the likely reason (reduced reroutable headroom).
  - The FCT cost (if goodput ties but FCT is worse, as in symmetric oversub) is reported as such.

## 5. Grounding & honesty rules (binding)
- No controller change (read-only on PRISM; O(1) intact). No shared-code change (reuse existing
  `perf_figs` renderers).
- Every number reproducible from `repro.sh` (pinned commit, deterministic `-seed`); raw data
  gitignored; figures `git add -f`. Selftests in `repro.sh`.
- The committed `expB_oversub/` (symmetric) is NOT modified.
- Win-hunt with an honest pre-registered bar: a tie/no-win is reported as plainly as a win; no forced
  positive. Consistent with the project's standing honest-reporting rule.

## 6. Non-goals
- No controller modification; no new flags.
- No modification of the committed `expB_oversub/` / `expC_incast/`.
- No trimming-regime variant (delay-driven only); no 1024-scale (deferred to scale work).
- No offered-load sweep (the asymmetry axis is the variable here).

## 7. Execution & honesty
- Subagent-driven: harness (make_figs + repro) as one task with two-stage review; the sweep+render as
  a following task; README from actual numbers; a final holistic review.
- The failed-cap verification (per topo) happens in the harness/sweep task before trusting figures.
- Commit batched to a milestone **only on explicit user approval** (standing rule). Communicate in
  Chinese.
- Next step after approval: invoke writing-plans.
