# PRISM motivation→eval narrative bridge (design)

**Date:** 2026-06-16
**Phase:** narrative consolidation (agenda item: connect motivation to the characterized boundary).
**Status:** design, pending user review → controller-direct execution (pure-narrative task; the user
approved writing it directly rather than via subagents).

## 1. Goal
Make the PRISM story one coherent thread: **motivation → mechanism → evaluation boundary**. The
motivation figures in `mvp_runs3/` (figS signal-conflation, figI optimum-flip) are already a
*delay-signal* story; the evaluation just characterized PRISM's advantage as **regime-specific**
(wins when reroutable AND delay-driven; ties under trimming; small symmetric cost). This task makes
that alignment explicit — so the trimming-tie reads as a *consequence of the motivation's scope*,
not a hidden failure — and tidies+commits the long-uncommitted `mvp_runs3/` motivation work.
**Text-only: no new simulations, no figure regeneration.**

## 2. Deliverables

### 2.1 Bridge document — `htsim/sim/datacenter/prism_eval/NARRATIVE.md` (new)
One page, ~4 short sections, honest and cross-linked:
- **Premise (motivation).** figS (`mvp_runs3/`): a decoupled spraying+CC controller cuts its
  window from the **average** queuing delay, and `avg = floor + reroutable spread`, so the mean is
  inflated by spread whenever path diversity exists (STrack/NSCC react to `avg_delay > target`).
  figI: the optimal static CC/LB operating point **flips** with the bottleneck (reroutable vs not)
  — CC and LB are coupled. Both say: *on the delay signal, a decoupled design mis-decides.*
- **Mechanism (PRISM).** Decompose the signal into `floor = min_i q_i` (does even the best path
  need slowing? → CC) and `spread = max−min` (is congestion reroutable? → let spraying rebalance).
- **Evaluation boundary.** Reroutable AND delay-driven → PRISM wins (`expA_delaydriven`: +19–22%
  over REPS+NSCC and the coupled-SOTA STrack; `expA_tspray_tuning`: tightening T_spray widens it to
  +25–33%). Symmetric fabric (failed=0) → small penalty. Trimming default (`expA_lossdecomp`,
  `expA_asymmetric`/P2) → **ties**, even after extending the decomposition to the loss signal.
- **Closure (the point).** The boundary condition *is* the motivation's premise. The motivation is
  a delay-signal phenomenon, so it exists only in the delay-driven regime; trimming caps queues and
  removes the delay signal the motivation is about, so the conflation does not bite and PRISM ties.
  **The trimming-tie is a direct corollary of the motivation's scope, not a counterexample.** This
  is the honest framing: *characterize WHEN signal conflation matters, and show PRISM recovers the
  lost performance there* — not a blanket "PRISM improves performance."

Cross-links (relative paths) to: `../mvp_runs3/README_signal.md`, `../mvp_runs3/README_repro.md`,
`expA_delaydriven/README.md`, `expA_tspray_tuning/README.md`, `expA_lossdecomp/README.md`.

### 2.2 Regime-scoping wording in the motivation READMEs (edits)
- `mvp_runs3/README_signal.md` (figS): add a short paragraph stating the conflation is a
  **delay-driven-regime** phenomenon (it is defined on queuing delay) and forward-referencing the
  eval boundary (`prism_eval/NARRATIVE.md`): delay-driven → PRISM wins; trimming → conflation absent
  → PRISM ties.
- `mvp_runs3/README_repro.md` (figI + the figA–figH mechanism set): add an equivalent one-paragraph
  scope note + the same forward reference. (Read the file first; match its structure; do not rewrite
  existing content.)

### 2.3 Tidy + commit the uncommitted `mvp_runs3/` motivation work
Currently uncommitted (by prior design): `figI_cc_lb_tuning_coupled.pdf` (M), `make_coupling_fig.py`
(M), `make_paper_figs.py` (M), `pathrtt_analyze.py` (M), `README_signal.md` (??), `make_signal_fig.py`
(??), `repro_signal.sh` (??), plus `figI2_cc_lb_tuning_coupled.pdf` and `figS1/figS2/figS_legend`
pdfs (figures). Before committing: scan for stray intermediate/temp data that should be gitignored
(raw `*.txt/*.csv/*.dat` are already ignored by `prism_eval/.gitignore`, but `mvp_runs3/` may have
its own ignore rules — verify; figures `git add -f` if globally ignored, matching the eval-group
convention). Commit the motivation work + the new bridge doc + the README edits + this spec as one
"narrative consolidation" milestone — **on the user's explicit approval** (standing rule).

## 3. Non-goals
- No new simulations, no figure regeneration/annotation (figures already carry the story; only text
  changes). No edits to the eval controllers or eval groups' results. No re-opening the f0/trim
  questions. No unrelated `mvp_runs3/` refactor beyond the scope notes + the commit.

## 4. Execution & honesty
- Controller-direct (pure narrative; user-approved). Write the bridge doc + README scope notes,
  verify cross-link paths resolve, stage, and commit on approval.
- Every claim in the bridge doc must be traceable to a committed result (cite the exact eval group);
  no new numbers invented; the trimming-tie and the f0 penalty are stated plainly as part of the
  boundary, not hidden.
