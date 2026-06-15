# PRISM Section IV (Evaluation) — Incremental Implementation Roadmap

**Date:** 2026-06-15
**Status:** Approved umbrella spec (sections 1–3 confirmed by user)
**Scope:** This is the *umbrella* roadmap for building and running the PRISM evaluation
(Section IV). It sequences every artifact from the current simulator state to the full
experiment matrix. Two large source-code efforts — the **PRISM controller (P1)** and the
**STrack port (P3)** — each get their own brainstorm → spec → plan cycle; this document is
their parent.

**Source documents:**
- `Skeleton_of_III.md` — PRISM design (Section III writing plan).
- `Exper_design.md` — PRISM evaluation design (the experiment menu this roadmap implements).

---

## 1. Context & current state

The simulator today has: NSCC + REPS, and a read-only env-gated `PRISM_PATHRTT` per-ACK
log (`time,flow,path_id,raw_rtt,ecn_echo,cwnd`). It does **not** have: a PRISM controller, a
wired STrack baseline (only a separate, unwired `strack.cpp` transport exists), most workload
generators (only `gen_overload`/`gen_incast` for motivation), or FCT/utilization/internal-metric
extraction.

The motivation work (Section II, in `mvp_runs3/`) deliberately measured only the decoupled
baseline's *signal representation* and made no cost claim. Section IV is **Evaluation**:
implementing PRISM and measuring performance/cost is now in scope.

## 2. Resolved decisions (the forks)

| Decision | Choice | Rationale |
|---|---|---|
| Plan scope | **Everything, phased** | One end-to-end roadmap: controller + baseline + generators + metrics + runs/figures. |
| Sequencing | **Approach 1: vertical slice first** (borrow claim-grouping for P4–P6) | The core thesis was disproved once before; get one credible asymmetric result early to de-risk before building all baselines/workloads. |
| STrack baseline | **Port CC core into `UecSrc`** (`-sender_cc_algo strack`) | Identical topology/buffer/packet infra as PRISM → cleanest apples-to-apples; reuse REPS for ECN path selection. |
| Main-result seeds | `{13–22}` (10) for A/B/C/D/E; `{13–17}` (5) for dev / sensitivity / ablation | Tighter error bars on headline results; cheap iteration elsewhere. |
| Scale | 128-node for dev / sensitivity / ablation; 1024-node for main results (A/B/D/E) | Topology is a `.topo`-file swap; 1024 and 8192 files already exist. |

## 3. Directory structure

A new evaluation root, parallel to (and not polluting) the motivation's `mvp_runs3/`:

```
htsim/sim/datacenter/prism_eval/
├── common/                  # shared infra, single copy
│   ├── gen/                 # permutation / many2many / incast / collective / flowsize
│   ├── metrics.py           # FCT(avg/P95/P99/max), utilization, cwnd-cuts, region occupancy
│   ├── run_lib.sh           # thin htsim_uec wrapper (cc/lb/topo/seed/log)
│   ├── plot_style.py        # shared fonts/colors/legend (reuse figS/figI conventions)
│   └── tests/               # selftests for generators + parsers
├── expA_asymmetric/         # one folder per experiment group; each self-contained:
│   ├── repro.sh             #   one-command: run sims + render figures
│   ├── make_figs.py
│   ├── README.md            #   claim / setup / repro / honest scope
│   ├── .gitignore           #   ignore raw data
│   └── figs/                #   committed with `git add -f`
├── expB_oversub/
├── expC_incast/
├── expD_flowsize/
├── expE_collective/
├── sensitivity/
├── ablation/
└── overhead/
```

**Principles:**
- **Algorithm code is NOT here.** PRISM controller + STrack port live in `uec.cpp`/`uec.h`,
  compiled into the shared `htsim_uec`; each group's `repro.sh` only invokes the binary.
- **Each group is self-contained**: one folder = one group = `repro.sh` + `make_figs.py` +
  `README.md` + `figs/`. Anyone can open one folder and reproduce it independently.
- **Shared logic converges in `common/`** — no copy-paste across groups.

## 4. Reproducibility convention (uniform across groups)

Carries over the standard already validated in `mvp_runs3/`:
1. **Pinned commit** recorded in each group's README.
2. **Fixed seeds** (§2): explicit `-seed`, deterministic — no wall-clock/RNG dependence.
3. **One-command repro**: `bash prism_eval/<group>/repro.sh` regenerates data + renders figs.
4. **Raw data gitignored, figures `git add -f`** (data regenerable; figures committed).
5. **Selftests** for generators + parsers (`common/tests/`); `repro.sh` runs them first.
6. **Honest README** per group: claim, setup, result, and explicit scope/caveats.

## 5. Shared infrastructure (`common/`)

| Component | Responsibility | Notes |
|---|---|---|
| `gen/permutation.py` | sender↔receiver random permutation | active frac 25/50/75/100%, msg size, load |
| `gen/many2many.py` | sender group → receiver group | group 8/16/32; random pairs or all-to-all |
| `gen/incast.py` | many→one (generalized from `gen_incast`) | fan-in 8/32/64, msg size, start stagger |
| `gen/collective.py` | AlltoAll (primary), AllReduce (optional) | parallel degree 16/32/64 |
| `gen/flowsize.py` | WebSearch/DataMining sizes + Poisson arrivals | distribution, offered load |
| `metrics.py` | external (FCT, goodput, util, retx/drop) + internal (`C_cc`/`C_spray`/cwnd series, region occupancy, cwnd-cuts, recovery time) | **FCT log source must be located in P0** |
| `run_lib.sh` | `(cc, lb, topo/failed, seed, cm, logspec, tag)` → htsim_uec → decode `.dat` → text logs → delete `.dat` | generalizes `run_one.sh`/`run_meas.sh` |
| `plot_style.py` | shared matplotlib style + legend helpers | consistent figure look across the paper |
| `tests/` | generator selftests (counts/placement) + parser selftests (synthetic logs → known FCT/util) | |

Existing `mvp_runs3/gen_overload.py` and `gen_incast.py` stay **frozen** for motivation
reproducibility; `common/gen/` re-implements/generalizes so `prism_eval` is self-contained.

**Data flow (every group):**
```
gen/*.py → *.cm → run_lib.sh → htsim_uec → *.dat → decoded logs (sink/queue/pathrtt/prism-epoch)
                                                          └→ metrics.py → numbers → make_figs.py → figs/
```

## 6. Phase plan (P0–P6)

| Phase | Deliverables | Location | Sub-spec? | Verification | Paper output |
|---|---|---|---|---|---|
| **P0 Harness** | `run_lib.sh`, `metrics.py`, `plot_style.py`, `gen/` (permutation+many2many+incast first); **locate + parse FCT log**; `tests/` | `common/` | No | selftests pass; N=1 smoke: FCT ≈ size/BW + RTT | serves all |
| **P1 PRISM controller** | `-sender_cc_algo prism`; epoch min/max of `q=max(rtt−base,0)`; four-quadrant rule; **inherit NSCC increase/decrease** (only change *when* invoked); spread gates increase, floor triggers decrease; env-gated **epoch log** (`C_cc,C_spray,region,cwnd,cut`); CLI `T_cc/T_spray/kappa` | `uec.cpp`/`uec.h` | **Yes** | epoch log vs offline recompute from pathrtt agree; region transitions sane | serves all |
| **P2 Exp A (cheap baselines)** | permutation+many2many; `-failed {0,2,4,8,12}`; baselines **OPS+NSCC / REPS+NSCC / PRISM**; `repro.sh` (10 seeds) + `make_figs.py` | `expA_asymmetric/` | No | one-command repro + error bars; **honest check**: does PRISM truly preserve utilization under asymmetry? | **Fig1 main perf + Fig2 mechanism** (core de-risk milestone) |
| **P3 STrack port** | `-sender_cc_algo strack` (port avg-RTT/achieved-BDP window control from `strack.cpp`; reuse REPS; target ≈ 1 base RTT); re-run A with STrack | `uec.cpp` + `expA_*` | **Yes** | STrack behaves sanely vs known behavior; fair config | completes Fig1 with SOTA baseline |
| **P4 Broaden** | **B**: 4:1/8:1 oversubscribed, load 50/70/90% → PRISM *does* cut window; **C**: incast 8/32/64:1, msg 1/16/64MB → fallback (`C_cc` high, `C_spray` small → floor-driven; honestly marked as not PRISM's main win) | `expB_oversub/`, `expC_incast/` | No | per-group repro + selftest | **Fig3 correct overload reaction** (claim 2) |
| **P5 Sensitivity + Ablation** | sensitivity: `T_cc`(0.5/1/2/4×), `T_spray/T_cc`(0.5/1/2), `kappa`(0.5/1/2/4), 128-node, 2 scenarios, 5 seeds; ablation: No-Decomposition, Average-as-Floor, No-Spread-Gate, Spread-as-Decrease, **Oracle-PRISM**, Long-Epoch (mostly PRISM compile/CLI variants; Oracle needs per-entropy queue table) | `sensitivity/`, `ablation/` | Small (Oracle + variant flags fold into P1 sub-spec extensions) | per-group repro | **Fig4 robustness + Fig5 component necessity** |
| **P6 Realistic + Overhead** | **D**: WebSearch/DataMining flow-size, full+asym, load 30–90% → avg/P95/P99 FCT slowdown; **E**: AlltoAll (primary)/AllReduce (optional), degree 16/32/64 → CCT; **overhead**: state O(1) vs O(entropies) table, per-ACK op count, runtime/memory vs #flows, estimator-vs-Oracle decision agreement | `expD_flowsize/`, `expE_collective/`, `overhead/` | No | repro + selftest | **Fig6 + Table2 lightweight** (claim 3) + realistic traffic |

**Minimal-6 set** (if time/space limited) = P0–P5 + overhead: asymmetric, oversubscribed,
incast, sensitivity, ablation (avg-vs-floor + spread-gate), O(1)-vs-Oracle. `expD`/`expE`
are stretch, sequenced last.

## 7. Sub-spec boundaries

- **P1 (PRISM controller)** and **P3 (STrack port)** are substantial source-code changes →
  each gets its own brainstorm → spec → plan. This roadmap is their parent.
- **P1 open decision deferred to its sub-spec:** floor definition — epoch-min *raw sample*
  (`C_cc = q_min`, per the design doc) vs a robust low-percentile (more stable, matches the
  motivation's "min of per-path means"). Must be settled in the P1 spec and kept consistent
  between motivation framing and mechanism so the Oracle-vs-O(1) error analysis is clean.
- **P5 ablation variants** (Oracle-PRISM, Average-as-Floor, No-Spread-Gate, Spread-as-Decrease,
  Long-Epoch) are extensions of the P1 controller (compile/CLI flags), specced as part of P1.

## 8. Testing strategy

- Generators + parsers: selftests in `common/tests/` (counts/placement; synthetic logs → known
  metrics), run at the top of every `repro.sh`.
- PRISM internal metrics: deterministic-sim cross-check — the controller's epoch log must match
  an offline recompute of `C_cc`/`C_spray` from the `PRISM_PATHRTT` log on the same run.
- Each experiment group: a one-command reproduction smoke (gen → 1 sim → metrics) before the
  full seed sweep.

## 9. Honesty, attribution, and scope

- PRISM **inherits NSCC's increase/decrease** functions; only the *trigger* (which congestion
  component selects increase/hold/decrease) changes. Any performance gain is therefore
  attributable to "reading the right component," not to new control gains.
- Report results as they are — including negative/mixed outcomes (as done in the motivation
  pivot). Do not force positive results; do not draw a final go/no-go from a single experiment.
- **Cost/performance claims are now in scope** (this is Evaluation, unlike the motivation phase).
- Incast is honestly framed as a fallback scenario, not PRISM's main-advantage case.

## 10. Next step

After user review of this spec: invoke **writing-plans** to produce the **P0 (harness
foundation)** implementation plan. P1 and P3 each enter their own brainstorm → spec → plan
cycle when reached.
