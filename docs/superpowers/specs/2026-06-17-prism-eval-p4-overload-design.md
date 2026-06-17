# PRISM eval P4 — overload (oversubscription + incast): fallback-correctness pillar (design)

**Date:** 2026-06-17
**Phase:** P4 of the PRISM Section-IV roadmap (oversubscription + incast), per `Exper_design.md` §6.2 (Exp B) and §6.3 (Exp C).
**Status:** design, pending user review → writing-plans → subagent-driven execution.

## 1. Goal and framing

The PRISM thesis has converged to: *characterize when delay-signal conflation costs performance
(reroutable AND delay-driven), and show PRISM recovers it there* — not "PRISM is universally
faster." `expA_delaydriven/` + `expA_tspray_tuning/` proved the **win side** (regime-internal:
+25–33% under asymmetry). Both attempts to broaden past the target cell were honest negatives
(`expA_lossdecomp/`, the f0 persistence fix).

**P4 closes the argument from the other side.** It is the **fallback-correctness / do-no-harm**
pillar (Exper_design §13 claim 2: "PRISM reacts when overload is irreducible"). It must show that
when PRISM *leaves* its target regime and meets **non-reroutable, path-wide overload**, it
**correctly falls back to floor-driven CC** — `C_cc` rises above `T_cc`, PRISM cuts the window
promptly, and it does **not** misuse spraying — achieving **do-no-harm vs REPS+NSCC**. This is the
user-chosen success criterion (2026-06-17): fallback correctness / do-no-harm, **not** a second
win-hunt.

This framing is mandated by the design menu itself and by what we already know:
- Exper_design §6.2: Exp B's goal is "PRISM still reduces the sending window when congestion is
  path-wide." §6.3: Exp C "is not necessarily expected to show the largest gain. Its purpose is to
  demonstrate that PRISM does not mistake shared bottleneck overload for reroutable imbalance."
- The f0 diagnosis (`expA_f0_diagnosis/`) already established that on a **symmetric shared
  bottleneck**, PRISM pays a *small cost* (it under-grows by HOLDing on a self-resolving transient
  spread). So on the incast side, the **honest expected outcome is "small cost + correct fallback,"
  not a win.** A win-hunt here would be both dishonest and doomed.

## 2. Deliverables

### 2.1 `htsim/sim/datacenter/prism_eval/expB_oversub/` (new group)
Oversubscription as a **graded** stressor: as the core (aggregation→spine uplinks) is narrowed,
congestion shifts from "still reroutable across the reduced core" toward "the core is a genuine
shared bottleneck." Tests that PRISM **cuts when the floor is high** while preserving whatever
reroutability remains.
- `repro.sh` — one-command reproduction (self-test → workload gen → main sweep → mechanism run →
  figs), modeled on `expA_delaydriven/repro.sh`.
- `make_figs.py` — thin wrapper over `common/perf_figs.py` (+ `--selftest`).
- `README.md` — setup, honest results, mechanism, caveats.
- `figs/` — `figB1_main_perf.{png,pdf}` (goodput/FCT vs oversub ratio), `figB2_mechanism.{png,pdf}`
  (C_cc/C_spray/cwnd/region time series at the most-oversubscribed point).

### 2.2 `htsim/sim/datacenter/prism_eval/expC_incast/` (new group)
Pure shared downstream bottleneck (symmetric fabric, many senders → one receiver): the fallback
extreme point. Tests that PRISM behaves like floor-driven CC and does **not** misuse spray;
characterizes the small cost honestly.
- `repro.sh`, `make_figs.py`, `README.md`, `figs/` (`figC1_main_perf` = goodput/FCT vs fan-in;
  `figC2_mechanism` = time series at fan-in 64), same structure as 2.1.

### 2.3 Shared-harness touch — `common/perf_figs.py`
`render_main_perf` currently labels its x-axis by `failed` (number of degraded links). P4's x-axis
is **oversub ratio** (B) / **fan-in** (C). Parameterize the x-axis label + tick values (a generic
`xlabel`/`xvalues` argument, default preserving the existing `failed` behavior) so the existing
expA wrappers stay **byte-identical**. This is the *only* shared-code change. Add/extend a selftest
covering the new x-axis path. No controller code changes anywhere in P4.

## 3. Experimental design

### 3.1 Common settings (both groups)
- **Regime:** delay-driven, `EXTRA_ARGS="-disable_trim"` (5×BDP buffer, queues build, delay-MD is
  the operative signal) — matches the `expA_delaydriven/` headline so results are comparable and the
  floor signal `C_cc` is actually exercised. (Under trimming the decomposition is dormant,
  floor-MD ~0.05, so everyone would just tie — uninformative for testing fallback. Trimming-regime
  sanity is deferred to P5.)
- **Scale / nodes:** 128 (`NODES=128`), dev tier.
- **Arms:** REPS+NSCC (`nscc reps`), STrack (`strack reps`), PRISM (`prism reps`). OPS+NSCC
  (`nscc oblivious`) included as a lower-bound reference arm (cheap; consistent with expA's 4-arm
  layout). PRISM and STrack share the REPS spray so the CC decision is the only variable.
- **Seeds:** {13,14,15,16,17} (dev tier).
- **`END_MS`:** parameterized via an `EXP_END` env override (as in expA). Default chosen large
  enough that the no-trim deep-queue workload drains (completion ratio → ~1.0); README carries the
  expA completion-stress caveat (FCT is only clean once completion ≈ 1.0). Default starting point
  `END_MS=8`; the plan verifies completion and bumps if needed (incast, see 3.3).
- **`PATHS`:** 8 (as expA).
- **`T_cc` / `T_spray`:** PRISM defaults (`_target_Qdelay ≈ 14µs`, `T_spray` follows target). No
  per-experiment tuning (do-no-harm framing; tuning is P5's job).

### 3.2 Exp B — oversubscription (`expB_oversub/`)
- **Independent variable = oversubscription ratio**, swept as the topology file:
  `{fat_tree_128_1os.topo, fat_tree_128_4os.topo, fat_tree_128_8os.topo}` (verified drop-ins: same
  128 nodes / podsize 16; only Tier-1 `Oversubscribed`/`Radix_Up` differ → graded core-uplink
  capacity). x-axis = {1:1, 4:1, 8:1}. `failed=0` throughout (oversub is the *only* stressor;
  orthogonal to expA's link-asymmetry axis).
- **Workload:** the **same** `many2many.py 64 16 pairs 2000000 128 16` as `expA_delaydriven/` (64
  senders outside pod0 → 16 pod0 receivers, 2MB), held fixed across the ratio sweep for direct
  comparability with the asymmetric headline.
- **What it tests:** as the ratio rises 1→4→8, does PRISM correctly shift from "hold/spray" toward
  "cut" — `C_cc` crossing `T_cc`, DECREASE / floor-MD fraction rising — while remaining do-no-harm
  on goodput/FCT vs REPS+NSCC (and not worse than STrack)?
- **Optional extension (NOT in the main sweep):** at fixed 4:1, an offered-load sweep (via
  `n_send` or message size). Deferred to keep scope tight; noted in README as future work.

### 3.3 Exp C — incast (`expC_incast/`)
- **Independent variable = fan-in**, swept via `incast.py`: `{8, 32, 64}` senders → one dest host,
  on the **symmetric** `fat_tree_128_1os.topo`, `failed=0` (pure shared downstream bottleneck; no
  reroutable structure by construction).
- **Message size:** secondary knob. Primary axis fixes size for comparability (start at 1MB to keep
  the 64:1 case tractable in the deep-buffer regime; the plan confirms completion and may also report
  a 2MB point to align with expA). Senders are placed outside the dest pod by `incast.py` (forces
  traffic across the core into the ingress).
- **Completion-stress note:** 64:1 incast of even 1MB flows = 64MB into one 100Gbps receiver
  (~5ms drain at line rate, plus deep queue). The plan **verifies completion ratio** at the largest
  fan-in and bumps `END_MS` (or trims message size) until cr ≈ 1.0 before trusting FCT; goodput +
  completion are the clean headline if FCT stays confounded (same discipline as expA).
- **What it tests:** with `C_cc` high and `C_spray` small/transient, does PRISM behave like
  floor-driven CC (prompt window reduction, low HOLD fraction) and **not** misuse spray? Do-no-harm
  vs REPS+NSCC; the small cost (if present) is reported and explained via the f0 mechanism.

### 3.4 Mechanism condition (both groups)
At the most-overloaded column (B: 8os; C: fan-in 64), seed 13, run all arms with
`PRISM_PATHRTT=` set, and PRISM additionally with `PRISM_EPOCH=`, to log per-path RTT and the PRISM
epoch decomposition. Render the C_cc / C_spray / cwnd / region-occupancy time series (`figB2`,
`figC2`), exactly as `expA_delaydriven/` does for its mechanism figure.

## 4. Metrics and figures

- **End-to-end (do-no-harm headline):** aggregate goodput (Gbps), avg-FCT, P99-FCT, completion
  ratio — all via `common/metrics.py` (`aggregate_goodput_gbps`, `fct_stats`), per arm per x-value,
  mean ± across seeds.
- **Internal (mechanism / correctness):** `C_cc` & `C_spray` time series, cwnd time series,
  four-region occupancy, floor-MD fraction, per-ACK cwnd-cut count — via `metrics.py`
  (`count_cwnd_cuts_from_pathrtt`, `parse_prism_epoch`) and the epoch CSV.
- **Figures:** `figB1`/`figC1` main-perf (goodput + FCT vs x), `figB2`/`figC2` mechanism, rendered
  through the parameterized `perf_figs.render_main_perf`. Color/style from `common/plot_style.py`.

## 5. Expected results (honest, pre-registered direction)

- **Exp B (oversub):** PRISM should track the floor — DECREASE / floor-MD fraction rising with the
  ratio — and stay do-no-harm (tie, or a small edge from preserving residual reroutability) vs
  REPS+NSCC; not worse than STrack. The *interesting* evidence is the region-occupancy shift, not a
  headline speedup.
- **Exp C (incast):** the f0 finding predicts **PRISM ≈ baseline or slightly worse** (small cost
  from HOLDing on transient spread), with PRISM clearly in the floor-driven (DECREASE/low-HOLD)
  regime. **A win is not expected and will not be manufactured.** If PRISM is worse, it is reported
  straight and explained by the f0 mechanism; the contribution is *correct fallback*, not a speedup.
- Either way, OPS+NSCC is expected to be the weakest (no path feedback). The pillar succeeds if
  PRISM is **do-no-harm vs REPS+NSCC** and the mechanism logs show **correct floor-driven reaction**
  under genuine overload.

## 6. Grounding & honesty rules (binding)
- No controller code changes in P4 (read-only on PRISM; only the figure x-axis is parameterized).
- Reuse `expA_delaydriven/` infrastructure verbatim where possible (run_lib.sh, generators,
  metrics.py, perf_figs.py); the expA wrappers must remain byte-identical after the perf_figs touch.
- Every reported number is reproducible from the committed `repro.sh` (pinned commit, deterministic
  `-seed`); raw data (`*.csv/*.txt/*.dat/*.stdout/*.idmap`) gitignored; figures `git add -f`.
- Each group self-contained in its own folder. Selftests for analysis code (`--selftest`) and the
  reused common code must pass in `repro.sh` before the sweep.
- Results reported straight — do-no-harm ties and the incast cost stated as plainly as any edge. No
  forced positives, no final go/no-go.
- PRISM stays O(1) (no per-path state introduced).

## 7. Non-goals
- No win-hunt; no tuning of `T_cc`/`T_spray`/`kappa` per experiment (that is P5 sensitivity).
- No offered-load sweep in the main B sweep (optional/deferred); no 1024-node scale (deferred).
- No trimming-regime variant (deferred to P5 sanity).
- No new workloads beyond oversub-topology m2m (B) and incast (C); no flow-size/collective workloads
  (those are Exp D/E).
- No controller modification of any kind.

## 8. Execution & honesty
- Subagent-driven development (per the standing rule): one subagent per task, each with a two-stage
  review (spec compliance THEN code quality), plus a final holistic review. The two groups can be
  built sequentially (B first, then C); the shared perf_figs touch lands first so both wrappers reuse
  it.
- Commit batched to a milestone **only on explicit user approval** (standing rule). Communicate in
  Chinese.
- Next step after this spec is approved: invoke writing-plans to produce the implementation plan.
