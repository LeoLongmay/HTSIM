# PRISM Eval — 1024-Node Scale Verification (`expD_scale1024`) — Design

**Date:** 2026-06-17
**Branch:** prism-motivation-redesign
**Status:** design (approved in brainstorm; spec for review)

## 1. Question

The two PRISM headline wins were established at **128-node development scale**:

- **expA_delaydriven** (1:1 non-blocking, 100G, delay-driven `-disable_trim`): under asymmetry
  (`-failed ≥ 4`, ≥25% of pod0 core-ingress degraded) PRISM beats **both** decoupled REPS+NSCC
  **and** coupled-SOTA STrack by **+19–22% goodput** and **7–12% lower avg-FCT**, with a modest
  fairness advantage; at the symmetric point (failed=0) it pays a small penalty.
- **expB_oversub_asym** (oversubscribed core): the same asymmetric win extends to a moderately
  oversubscribed **4:1** core (+14–32% goodput), bounded by **8:1** saturation.

**The scale question:** do these wins survive on an **8× larger fabric (1024 nodes)**, holding
the 100G / 14µs calibration fixed? A reviewer's natural skepticism is that a larger fabric
offers far more path diversity and spare core capacity, which could *dilute* a hotspot-plus-
asymmetry advantage. This experiment answers that directly by reproducing both headlines at
1024 nodes with a proportionally scaled workload.

This is **verification, not a new mechanism**: the PRISM controller is byte-identical to the
committed O(1) decomposition. Only topology scale, workload scale, and the `-failed`
calibration change.

## 2. Feasibility (probed 2026-06-17, this machine)

Empirically de-risked before committing to a sweep (machine has only ~3 GB RAM):

| Run (1024 fabric, `-disable_trim`, END=8ms, failed=8) | Wall | Peak RSS | `.dat` | Notes |
|---|---|---|---|---|
| REPS 64→16 2MB (= expA workload) | 0.75 s | 54 MB | 8 KB | all flows complete |
| REPS 256→64 2MB (D1 workload) | ~4–6 s (est.) | <90 MB | — | between the two below |
| REPS 512→64 2MB (8× flows) | 12.8 s | 86 MB | 66 KB | 250k pkts, all complete |
| PRISM 512→64 2MB | 14.1 s | 87 MB | 66 KB + 1.3 MB epoch | all complete |

**RAM is not a constraint:** htsim_uec logs FLOW_EVENT + sink rates only (not per-packet), so
peak RSS stays <90 MB even at 512 flows. A single heavy run is ~14 s; the full study
(~120 D1 + ~180 D2 runs, sequential — `run_lib.sh` writes a shared `idmap.txt` so runs must
not be parallelized) completes well under 1–2 hours.

**Calibration confirmed:** `fat_tree_1024.topo` reports runtime `_network_linkspeed=100 Gbps`,
`_target_Qdelay=14022720 ps` (14 µs), `_network_rtt=14022720 ps` — **identical to the 128-node
experiments**. This is the apples-to-apples scaling topology.

## 3. Scope — two parts mirroring the committed 128 experiments

### D1 — 1:1 delay-driven (scales `expA_delaydriven`)

| Parameter | Value |
|---|---|
| Topology | `fat_tree_1024.topo` (100G, 1:1, Nodes 1024, Podsize 64) |
| Workload | `many2many.py <out> 256 64 pairs 2000000 1024 64` — 256 senders (outside pod0) → 64 pod0 receivers, 2 MB, round-robin pairs (4:1 incast = expA's 64→16 scaled ×4) |
| Arms | OPS+NSCC, REPS+NSCC, STrack, Prism (same 4 as expA) |
| Asymmetry sweep | `-failed {0, 8, 16, 24, 32, 48}` |
| Seeds | {13, 14, 15, 16, 17} |
| `PATHS` | 8 |
| `EXTRA_ARGS` | `-disable_trim` |
| `END` | 8 ms (verify cr=1.0 at every cell; bump via `EXP_END` if any cell under-completes) |
| Mechanism | failed=32 (50% pod0-ingress choke = same fraction as expA's failed=8 mechanism), seed 13, 4 MB workload (`many2many ... 256 64 pairs 4000000 ...`) |

**`-failed` calibration (probed: linear on the 1:1 topo).** On `fat_tree_1024.topo`, `-failed N`
degrades **exactly N** core→agg uplinks, filling pod0's aggregation switches first (agg_sw 0
links 0–7, then agg_sw 1, …; 8 uplinks per agg switch). pod0 has 8 agg switches → 64 core
uplinks. So the sweep maps to pod0 core-ingress choke as:

| `-failed` | uplinks degraded | pod0 ingress choke | 128 analog (pod0=16 uplinks) |
|---|---|---|---|
| 0 | 0 | 0% | failed=0 |
| 8 | 8 (= 1 agg switch) | 12.5% | failed=2 |
| 16 | 16 (= 2 agg) | 25% | failed=4 (win onset) |
| 24 | 24 (= 3 agg) | 37.5% | failed=6 |
| 32 | 32 (= 4 agg) | 50% | failed=8 (mechanism) |
| 48 | 48 (= 6 agg) | 75% | failed=12 |

All 48 degraded uplinks stay within pod0 (needs 64 to exhaust pod0), so the asymmetry is
co-located with the workload hotspot — structurally identical to the 128 case. The win region
is expected to begin at **failed=16 (25% choke)**, matching expA's failed=4.

### D2 — oversubscribed asymmetric (scales `expB_oversub_asym`)

| Parameter | Value |
|---|---|
| 8:1 topology | `fat_tree_1024_8os.topo` (100G — matches calibration) |
| 4:1 topology | **`fat_tree_1024_4os_100g.topo` — generated** (see below) |
| Workload | same scaled `many2many ... 256 64 pairs 2000000 1024 64` |
| Arms | OPS+NSCC, REPS+NSCC, STrack, Prism |
| Seeds | {13, 14, 15, 16, 17} |
| `EXTRA_ARGS` | `-disable_trim` |
| Asymmetry sweep | **probe-and-calibrate** (see below) |
| Mechanism | at the 4:1 win point (chosen after the sweep), seed 13 |

**4:1 topology generation (decision A — 100G, approved).** The stock `fat_tree_1024_4os.topo`
uses **200 Gbps** links, which would change BDP and `_target_Qdelay` and break apples-to-apples
scaling. `repro.sh` therefore generates `topologies/fat_tree_1024_4os_100g.topo` (idempotent
heredoc, only if absent) as a byte-for-byte copy of `fat_tree_1024_4os.topo` with all three
`Downlink_speed_Gbps 200` lines changed to `100`. Structure unchanged: Tier0 Oversubscribed 4
(Radix_Down 8, Radix_Up 2), Tier1 Oversubscribed 1 (Radix_Down 8, Radix_Up 8), Tier2 Radix_Down
16. This keeps the 100G/14µs calibration identical to D1 and the 128 oversub experiments. The
8:1 topology (`fat_tree_1024_8os.topo`) is already 100G and is used as-is.

Writing the generated topo into `topologies/` (rather than touching the shared `run_lib.sh`,
which hardcodes the `topologies/$TOPO` prefix) keeps the change isolated to this experiment.

**`-failed` calibration on oversub topos (nonlinear — probe required).** As documented for the
128 expB-asym, `-failed N` does **not** degrade N links on oversubscribed topologies (the index
interacts with the reduced core radix). Task 1 runs a short probe on both 1024 oversub topos to
record the actual degraded-link counts, then the sweep values are chosen to (a) span a
comparable asymmetry fraction to the 128 case and (b) keep 4:1 in the reroutable-win regime
while 8:1 reaches its saturation boundary. Candidate starting points (to be confirmed by the
probe): 4:1 `-failed {0, 16, 32, 48}`, 8:1 `-failed {0, 8, 16, 32}`. The repro prints the
degraded-link report; the README documents requested-vs-actual (a table like expB-asym §2).

## 4. Figures (reuse `common/perf_figs.py` renderers — no new plotting code)

**D1** (`render_main_perf_split` + `render_fairness` + `render_mechanism_split`):
- `figs/figD1_goodput`, `figs/figD1_avg_fct`, `figs/figD1_p99_fct` (FCT in ms)
- `figs/figD1_fairness` (Jain index vs failed)
- `figs/figD1_mech_signal`, `figs/figD1_mech_cwnd` (failed=32, seed 13, [0,3] ms window;
  annotated with per-ACK cut counts + floor-MD fraction)

**D2** (`render_main_perf` + `render_fairness` + `render_mechanism`):
- `figs/figD2_4os_main`, `figs/figD2_8os_main`
- `figs/figD2_4os_fairness`
- `figs/figD2_mech` (4:1 win point)

`make_figs.py` is a thin wrapper (like the expA/expB `make_figs.py`); `--selftest` reuses
`perf_figs.selftest()`. Legends say **"Prism"** (not "PRISM"), per the established convention.

## 5. File structure

```
prism_eval/expD_scale1024/
  repro.sh        # generate 4:1-100G topo + 2 workloads (2MB sweep, 4MB mech);
                  # run D1 sweep+mech, D2 (4:1 + 8:1) sweep+mech; render figs
  make_figs.py    # thin wrapper over common/perf_figs (D1 + D2 figure sets) + --selftest
  README.md       # question, setup, requested-vs-actual failed table, results, verdict, caveats
  data/           # raw .cm/.flow/.sink/.epoch/.csv  (gitignored)
  figs/           # figD1_*, figD2_*  (git add -f)
```

Reuses `common/` unchanged: `run_lib.sh`, `perf_figs.py`, `metrics.py`, `gen/many2many.py`.
No change to the PRISM controller or any shared infra (the 4:1-100G topo is generated into
`topologies/` by `repro.sh`, not hardcoded into `run_lib.sh`).

## 6. Honest scope / pre-registration

- **Verification only.** PRISM controller byte-identical to the committed O(1) decomposition.
  No tuning to force a scale win. Same `_gamma`/`_eta`/`_target_Qdelay` and STrack β/h defaults.
- **Pre-registered expectation:** the asymmetric win (goodput + FCT + fairness) reproduces at
  1024 for D1 at failed ≥ 16, and for D2 at the 4:1 reroutable regime; 8:1 reaches saturation.
  If scale *dilutes* the win (the reviewer's skeptical hypothesis), that is recorded honestly
  as a scale boundary — not hidden. completion_rate must be 1.00 for every reported FCT cell
  (bump END otherwise); goodput is a window-free aggregate.
- **Single fabric per arm, controller isolated:** all arms share topology, sink, trimming-off
  setting, loss machinery; only sender CC (and ops' spray) differs.
- **Deferred:** trimming-regime scale behavior; STrack adaptive spray (Approach B); 8192-node
  scale; permutation/AI-collective workloads at 1024 (separate roadmap directions).

## 7. Cost

~120 D1 runs + ~180 D2 runs, sequential, ~4–14 s each → **well under 1–2 hours total**. Peak
RSS <90 MB. Raw `.dat` deleted by `run_lib.sh` after decode (only text logs kept).

## 8. Success criteria

1. `repro.sh` runs end-to-end from `sim/datacenter/` with one command, deterministic per seed.
2. All reported cells have cr=1.00 (FCT unconfounded).
3. Figures render (D1: 6, D2: 4) with "Prism" legends; `make_figs.py --selftest` passes.
4. README reports the requested-vs-actual `-failed` table for the oversub topos, the D1 and D2
   result tables (goodput/FCT/fairness), the mechanism cut-counts + floor-MD fraction, and an
   honest verdict on whether each headline survives at scale (including any dilution found).
