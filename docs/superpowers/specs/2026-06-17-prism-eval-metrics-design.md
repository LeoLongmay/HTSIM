# PRISM eval — richer metrics infrastructure (fairness + slowdown + rate-reduction count) (design)

**Date:** 2026-06-17
**Phase:** evaluation-metrics infrastructure (direction 1 of 4: "zero-cost richer metrics"). Builds
reusable metric helpers in `common/` so every present and future experiment group gets them, and
renders the one metric that adds information on today's uniform workloads (Jain fairness) plus
elevates the rate-reduction count from a console print to a reported figure metric.
**Status:** design, pending user review → writing-plans → subagent-driven execution.

## 1. Goal and framing

Beyond goodput / avg-FCT / P99-FCT, what else can show PRISM's behaviour? Checked on real data
(expA f8/PRISM, 64 uniform 2 MB flows):
- **FCT slowdown** (FCT / ideal) is **redundant** at uniform flow size (slowdown ∝ FCT) — it only
  adds value once flow sizes vary (future flow-size-distribution / collective work).
- **Tail / max-FCT** ≈ the **P99-FCT we already plot** at 64 flows (p99 1950 µs ≈ max 1963 µs) — no
  new info now (meaningful only with more flows / collectives).
- **Jain fairness** = 0.9838 — genuinely **new** (not recoverable from avg/p99); informative now.
- **# rate reductions** (per-ACK cwnd cuts) — on-thesis (PRISM 3.7× fewer) but needs the
  `PRISM_PATHRTT` log, which only the **mechanism** run has → a mechanism-point number, not a swept
  curve.

So: build the metric **infrastructure** in `common/` (so future varied-workload groups get
slowdown/tail for free), but render now only what adds information — **Jain fairness** (swept) and
the **rate-reduction count** (mechanism point, elevated to the figure). Honest positioning: fairness
is a do-no-harm / characterization metric (all arms share the REPS spray, so it may be neutral);
the rate-reduction count is the on-thesis advantage.

## 2. Deliverables

### 2.1 `htsim/sim/datacenter/prism_eval/common/metrics.py` (new functions; unit-tested)
- `jain_fairness(flow_path)` → Jain's fairness index over per-flow throughput (`bytes / FCT`) of the
  completed flows; returns a float in (0, 1] (1.0 = perfectly fair). NaN/empty-safe (returns nan if
  < 2 completed flows).
- `fct_slowdown(flow_path, link_gbps, base_rtt_s)` → per-flow slowdown `FCT / (base_rtt_s +
  bytes*8 / (link_gbps*1e9))`; returns `{"mean": .., "p99": ..}`. **Built but not rendered now**
  (dormant until varied-size workloads); included so the infra is ready.
- (Tail/max already provided by `fct_stats` `max_s`/`p95_s` — no new function; just not rendered now.)

### 2.2 `htsim/sim/datacenter/prism_eval/common/tests/test_metrics.py` (extend)
Add a synthetic-fixture unit test for `jain_fairness` (equal-throughput flows → 1.0; skewed → <1)
and for `fct_slowdown` (known size/rate → known slowdown).

### 2.3 `htsim/sim/datacenter/prism_eval/common/perf_figs.py`
- New `render_fairness(data_dir, figs_dir, tag_prefix, baselines, failed, seeds, fig_stem, xlabel)`
  — one standalone figure: Jain fairness vs `failed`, one line per arm + error bars across seeds.
  **Self-aggregating** (computes fairness via `metrics.jain_fairness` in its own loop) — it does NOT
  touch the shared `aggregate()` / `render_main_perf*`, so existing figures are unaffected (zero
  regression risk). Skips cells with < 2 completed flows.
- **Rate-reduction annotation:** in `render_mechanism` and `render_mechanism_split`, add a text
  annotation on the cwnd panel reporting the per-ACK cwnd-cut counts already computed
  (`count_cwnd_cuts_from_pathrtt`): e.g. "rate reductions: Prism N, REPS+NSCC M, STrack K". This
  elevates the existing console number onto the figure. (Additive text only; the line plots are
  unchanged. expA_asymmetric's committed figA2 is not regenerated here, so it is unaffected until
  someone reruns its make_figs.)

### 2.4 Group wrappers (render fairness for the two committed headline groups)
- `expA_delaydriven/make_figs.py`: add a `render_fairness(... "figA1dd_fairness" ...)` call (x=#failed
  {0,2,4,6,8,10,12}).
- `expB_oversub_asym/make_figs.py`: add a `render_fairness(... "figBa_4os_fairness" ...)` call for the
  **4:1** win regime only (x=#failed {0,4,8,12}); 8:1 is saturated (cr≈0) so fairness is not
  meaningful there and is not rendered.

## 3. What is measured vs rendered

| Metric | Built in common | Rendered now | Why |
|---|---|---|---|
| Jain fairness | ✅ `jain_fairness` | ✅ `figA1dd_fairness`, `figBa_4os_fairness` | new info on uniform workloads |
| Rate-reduction count | ✅ (existing `count_cwnd_cuts_from_pathrtt`) | ✅ annotation on mechanism cwnd fig | on-thesis advantage (PRISM ~3.7× fewer) |
| FCT slowdown | ✅ `fct_slowdown` | ❌ dormant | redundant at uniform size; activates with varied-size workloads |
| Tail / max-FCT | ✅ (existing `fct_stats`) | ❌ | ≈ P99-FCT at 64 flows |

## 4. Grounding & honesty rules (binding)
- Zero-cost: all new metrics computed from the existing committed `flow.txt` (fairness/slowdown) and
  `PRISM_PATHRTT` mechanism logs (cut count). No new simulations, no controller change.
- `render_fairness` is purely additive; it must not change `aggregate()` / `render_main_perf` output
  (existing committed figures unaffected). New analysis code is unit-tested (`--selftest`).
- Fairness reported honestly as do-no-harm / characterization (may be neutral); the rate-reduction
  count as the on-thesis advantage. No forced positive.
- Figures committed with `git add -f`; raw data gitignored.

## 5. Non-goals
- No slowdown/tail RENDERING now (built-but-dormant; they activate with varied-size / collective
  workloads — a later direction).
- No controller change; no new workloads/topologies/scale (those are the other three directions).
- No re-render of `expA_asymmetric` (its committed figA2 is left as-is).
- No change to the goodput/FCT panels already shown.

## 6. Execution & honesty
- Subagent-driven: (T1) metrics.py functions + unit tests; (T2) perf_figs render_fairness +
  mechanism cut-count annotation; (T3) wire expA_delaydriven + expB_oversub_asym make_figs, render,
  capture the fairness numbers + cut counts; (T4) brief README notes in both groups + memory; each
  with two-stage review, plus a final holistic review.
- Commit batched to a milestone **only on explicit user approval** (standing rule). Communicate in
  Chinese.
- Next step after approval: invoke writing-plans.
