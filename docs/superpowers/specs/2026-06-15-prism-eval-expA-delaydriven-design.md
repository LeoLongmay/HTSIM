# PRISM Eval — Experiment A, Delay-Driven Regime (decisive probe) Design Spec

**Date:** 2026-06-15
**Status:** Approved (design confirmed by user)
**Parent:** `docs/superpowers/specs/2026-06-15-prism-eval-roadmap-design.md` (a follow-on probe within P2/Experiment A)
**Depends on:** P0 harness, P1 PRISM controller, P2 Experiment A (`expA_asymmetric/`, committed `ba647e8`/`9b18932`).

## Why this probe

P2 (Experiment A, trimming/default) found PRISM **tied** REPS+NSCC on goodput, FCT, FCT
dispersion, and cwnd jitter. Data-mining diagnosed the decomposition being masked **twice**:
(1) adaptive spraying keeps NSCC utilized so its cuts cost no throughput, and (2) the fabric is
loss/trim-driven — NACK/quick_adapt machinery produces ~95% of PRISM's cwnd decreases (only
~5%, 141/2687, are the floor-driven epoch-MD the decomposition governs). PRISM's distinctive
action ("hold instead of cut when floor low + spread high") only matters when the **delay-based
MD is the dominant rate-control lever**. This probe creates that condition and re-tests.

## Recipe: make the regime delay-driven

Add **`-disable_trim`** to every run. Effect (verified in `main_uec.cpp`): trimming off →
no trim-NACKs; default buffer becomes **5×BDP** (`DEFAULT_NONTRIMMING_QUEUESIZE_FACTOR`, vs 1×
for trimming); ECN auto-set to 0.2/0.8×BDP. Queues build → ECN + delay drive NSCC's MD (the
lever PRISM's floor decomposition controls); drops occur only on true buffer overflow.

## Experiment (= Exp A + `-disable_trim`)

Identical to `expA_asymmetric` except for the flag and the output location:
- Workload `many2many` pairs, 64 senders outside pod0 → 16 pod0 receivers, 2 MB; `fat_tree_128_1os`, `-paths 8`, `-end 2` (ms).
- Baselines: OPS+NSCC (`nscc`,`oblivious`), REPS+NSCC (`nscc`,`reps`), PRISM (`prism`,`reps`).
- `-failed {0,2,4,8,12}`; seeds {13–17}; mechanism trace at failed=8, seed=13.
- **Every run sets `EXTRA_ARGS="-disable_trim"`.**
- New self-contained folder `prism_eval/expA_delaydriven/` (repro.sh + make_figs.py + README + figs/).

## Harness changes (both small, reusable)

1. **`common/run_lib.sh`: add an `EXTRA_ARGS` env knob** — appended verbatim to the `htsim_uec`
   command line (default empty; behaviour unchanged when unset). Enables passing extra flags
   (here `-disable_trim`) without per-experiment runner forks.
2. **Refactor the figure logic into `common/perf_figs.py`** — the generic aggregation + Fig1
   (goodput/avg-FCT/P99-FCT vs #failed, 3 baselines, error bars, completion annotation) + Fig2
   (mechanism: floor-vs-avg signal + cwnd; fair per-ACK cut counts; floor-MD fraction) currently
   in `expA_asymmetric/make_figs.py`, parameterized by `(data_dir, figs_dir, baselines, failed,
   seeds, title_suffix, fig_prefix)`. Both `expA_asymmetric/make_figs.py` and the new
   `expA_delaydriven/make_figs.py` become thin wrappers calling it. The refactor MUST leave
   `expA_asymmetric`'s rendered figures functionally unchanged (re-verify).

## Key validation metric (decisive check)

`perf_figs` (Fig2 path) prints the **floor-MD fraction** =
`PRISM epoch-MD count / PRISM total per-ACK cwnd-decreases` at failed=8. Trimming baseline:
~0.05 (141/2687). **If `-disable_trim` worked, this fraction should rise substantially** (NACK
drops fell; the floor decision now governs cwnd). Report it for this regime; if it does NOT rise
meaningfully, the recipe did not achieve delay-driven control — note it and consider a larger
buffer (`-queue_size_bdp_factor`) before interpreting the perf result.

## Honest pre-registration (decide the thesis from the outcome)

- **Floor-MD fraction rises AND PRISM beats REPS+NSCC on goodput/FCT** → thesis sharpens to
  "PRISM helps when congestion is reroutable AND delay-driven"; design the next experiment around it.
- **PRISM still ties REPS+NSCC (even delay-driven)** → accept the negative: the decomposition does
  not change outcomes; pivot to a scoping/measurement framing.
- Report the actual numbers either way; no parameter tuning to manufacture a win. FCT over
  completed flows with `completion_rate` surfaced; goodput is window-free aggregate.

## Reproducibility & testing
- `repro.sh` (from datacenter dir): gen `many2many.cm`; triple loop with `EXTRA_ARGS="-disable_trim"`;
  mechanism runs with PRISM_PATHRTT (+ PRISM_EPOCH for prism); `make_figs.py`. One command;
  deterministic `-seed`; raw data gitignored; figs `git add -f`.
- `perf_figs` keeps a `--selftest`-able aggregation path (reuse the synthetic-log self-check);
  `repro.sh` runs the common selftests first.
- Done criteria: repro reproduces Fig1 + Fig2; selftests pass; `expA_asymmetric` figs unchanged
  by the refactor; floor-MD fraction reported; README states the honest outcome + which
  pre-registered branch it lands in.

## Out of scope
- 1024-node scale, permutation workload, STrack baseline, oversubscribed/incast (later phases).
- Larger-buffer / lossless variants unless the floor-MD fraction shows `-disable_trim` alone didn't bite.

## Next step
After user review: writing-plans for the implementation (run_lib EXTRA_ARGS + perf_figs refactor + the new folder + run), then subagent-driven execution; the run + honest write-up are controller-owned (as in P2).
