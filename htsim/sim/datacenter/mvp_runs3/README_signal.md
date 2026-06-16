# figS1 / figS2 — Mean-vs-floor signal conflation (PRISM Motivation, Section 2)

**Claim (grounded in the STrack paper).** A decoupled spraying+CC design decides whether
to *slow down* (cut the window) from an **aggregate/mean** queuing signal, not from the
per-path floor. STrack is explicit: ECN is kept as a *per-path bitmap used only for path
selection* (avoid ECN-marked entropies), while the **window-cut decision uses the average
RTT** — *"STrack's congestion control uses an average RTT … only when the average RTT is
above a threshold (target queuing delay), STrack cuts the congestion window"* (STrack §2.2.2;
Algorithm 4 cuts when `avg_delay > target_Qdelay`; Fig. 5 quadrant 3). NSCC behaves the same
way (it reacts to `get_avg_delay()`).

Because **avg_delay = floor + (traffic-weighted spread)**, the mean a decoupled controller
reacts to is inflated by the **reroutable** spread whenever path diversity exists — which is
intrinsic to multipath packet spray. PRISM instead reads the **floor = min_i q_i** (an order
statistic): the quantity that actually determines whether *even the best path* is congested,
i.e. whether slowing is unavoidable. A single average cannot represent that floor.

## The two figures

- **`figS1_path_distribution`** — the per-path queuing-delay distribution at one
  representative condition (load 16, `failed=12`, pooled over 5 seeds, 5089 path samples).
  The distribution is **bimodal**: a low cluster ≈1–4 µs (healthy paths via the one
  non-degraded aggregation switch, US3) and a high cluster ≈8–12 µs (paths through the three
  degraded aggregation switches). **The avg queuing delay (the decoupled slow-down signal)
  lands at 6.4 µs — in the empty valley between the two modes, where almost no path actually
  sits.** The floor (1.3 µs) correctly identifies the clean cluster, below the 6 µs slow-down
  target. The mean of a bimodal per-path reality represents neither mode.

  Note on the markers: the x-axis, the floor, the avg, and the target are all *queuing
  delays* (RTT − base RTT). STrack's prose calls its signal "average RTT", but Algorithm 4
  compares `measured_Qdelay = rtt − base_rtt` (averaged) to `target_Qdelay`, i.e. the average
  *queuing delay* — exactly the blue marker. The avg is **traffic-weighted** (mean over ACKs,
  as STrack computes it from received ACKs), whereas the histogram bars are **per-path**
  (unweighted); adaptive spray sends more traffic to low-delay paths, so the traffic-weighted
  avg (6.4 µs) sits left of the histogram's center of mass (~8 µs) — down in the valley.

- **`figS2_load_sweep`** — floor and avg_delay vs offered load (`failed=12`, 5 seeds). The
  avg RTT stays **above the 6 µs target across the whole light-to-moderate range** while the
  floor stays **below** it until the heaviest load (n=64, where the floor finally reaches
  ~5.9 µs). The shaded band is the conflated spread. A controller keyed on the mean would
  signal "slow down" while spare capacity remains (floor well below target); only at heavy
  load do the two signals converge (genuine fabric congestion, where slowing is warranted).

## Setup

| | |
|---|---|
| Topology | `fat_tree_128_1os.topo` (128 hosts, 100 Gbps, 1:1, 8 pods × 16), base RTT ≈ 13.945 µs |
| CC / LB | unmodified NSCC + REPS, `-paths 64` |
| Asymmetry | `-failed 12` (aggs US0/US1/US2 degraded to 25%, US3 healthy → a clean-path minority) |
| Load (figS2) | senders ∈ {4, 8, 16, 32, 64} → 16 pod0 receivers (`gen_overload`) |
| Seeds | {13, 14, 15, 16, 17}; per-seed cross-flow median, then mean ± std across seeds |
| Window | steady 500–1500 µs, 14 µs decision windows |

**Metrics (per flow, per decision window, then aggregated):**
- `floor`   = min over the flow's paths of the per-path mean q  (PRISM's signal).
- `avg_delay` = mean over the window's ACKs of q  (traffic-weighted = STrack's `avg_delay`).
- `q` = `raw_rtt − BPROP`, `BPROP = 13.945 µs` (const uncontended baseline).

## Key numbers

```
figS1 (load 16, failed=12):  floor 1.28 µs | avg_delay 6.42 µs | target 6.0 µs
figS2 load:        4      8     16     32     64
  floor (min):    2.30   1.13   1.28   3.91   5.92
  avg_delay:      8.41   6.82   6.42   7.90   8.74
```
avg_delay exceeds the floor at every load (gap 0.5–7.3 µs) and exceeds the 6 µs target at
every load; the floor reaches the target only at n=64.

## Honest scope and caveats

- **This is a signal-representation result, not a cost claim.** It shows the two control
  *signals* diverge and what the mean conflates. It does **not** claim a controller is "wrong"
  or measure a throughput/latency cost — establishing a cost requires running both controllers
  head-to-head, which is Evaluation, not Motivation.
- **Threshold dependence (stated, not hidden).** Whether the divergence flips a *decision*
  depends on the target. With the tight target used here (6 µs, NSCC's default) the mean
  crosses while the floor does not. STrack's recommended `target_Qdelay` is ~1 base RTT
  (≈14 µs); at that looser target avg_delay (6–9 µs) would not trigger a cut in these
  regimes — but the looser target buys that at the cost of tolerating more queuing. The
  point is structural: a *single* average must trade a tight latency target against
  over-reacting to reroutable spread; PRISM's decomposition (floor sets slow-down, spread
  sets rerouting) is not forced to make that trade.
- **The conflation is intrinsic to spray, not to failures.** The gap is large even on a
  symmetric network; `failed=12` is used only to make the bimodal structure legible in figS1.
- **Regime scope (where this leads).** This conflation is a **delay-driven-regime** phenomenon —
  it is defined on queuing delay, so it can only bite when the controller's slow-down decision is
  delay-driven (large-buffer / no-trim fabrics). The evaluation confirms exactly this boundary:
  in the delay-driven regime PRISM's floor/spread decomposition recovers the lost performance
  (`../prism_eval/expA_delaydriven/`, `../prism_eval/expA_tspray_tuning/`: +25–33% over REPS+NSCC
  and the coupled-SOTA STrack under asymmetry); under the **trimming** UEC-default regime queues
  are capped shallow and this delay signal is largely absent, so the conflation does not bite and
  PRISM ties (`../prism_eval/expA_lossdecomp/`). The trimming-tie is thus a corollary of this
  scope, not a counterexample. Full thread: `../prism_eval/NARRATIVE.md`.

## Reproduce

```
bash mvp_runs3/repro_signal.sh          # 25 sims (load×seed) + renders figS1, figS2
python3 mvp_runs3/make_signal_fig.py --selftest   # parser/metric self-checks
```
Pinned commit; deterministic (explicit `-seed`); raw `sigL_*.pathrtt.csv` gitignored and
regenerable; figures committed with `git add -f`. Requires `htsim_uec` built with the
read-only 6-column `PRISM_PATHRTT` log (`time,flow,path,raw_rtt,ecn_echo,cwnd_bytes`).

## Design history (why this, not an ECN-based test)

An earlier design tried to show the aggregate *ECN mark-rate* cannot separate two congestion
regimes; the data disproved it (on this simulator the aggregate ECN mark-rate tracks the
regime, and "low-spread + high-floor" requires a shared bottleneck, incompatible with path
independence). Reading the STrack paper then established that STrack's *slow-down* decision is
driven by the **average RTT**, not an ECN mark-rate (ECN is per-path, for path selection only).
figS1/figS2 test that average-RTT signal — the one a decoupled controller actually uses.
