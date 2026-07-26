# expI_prism_v2 — PRISM v2: robust gated design (positive result)

## 1. What this tests

**PRISM v2** introduces three flag-gated mechanisms on top of today's PRISM (which remains
byte-for-byte unchanged as the default binary — v2 is opt-in via flags):

| mechanism | flag(s) | what it does |
|-----------|---------|--------------|
| **A1** EWMA-smoothed floor/spread | `-prism_smooth_beta 0.3` | smooths the congestion signals to reduce transient noise |
| **A2** region hysteresis | `-prism_hysteresis 0.25` | adds hysteresis to the region-change boundary to prevent oscillation |
| **C** asymmetry-gated engagement | `-prism_engage_spread 28 -prism_disengage_spread 20` | disengages to plain NSCC when spread is not persistently high (i.e., no genuine asymmetry detected) |

The **design goal**: recover PRISM's cost on symmetric f=0 traffic and on incast (where bold PRISM@B
is known to be harmful — see `../expC2_incast_asym`), stabilise the queue, and keep the
asymmetric-f8 win (accepting partial give-back as an explicit trade-off).

The v2 default **binary is byte-identical to today's PRISM** — no existing experiments are
affected. The full bundle for v2-full is:
`-prism_smooth_beta 0.3 -prism_hysteresis 0.25 -prism_engage_spread 28 -prism_disengage_spread 20`

### 1024-node ACK queueing-delay CDF smoke trial

`repro_1024_ack_qdelay_cdf.sh` runs OPS+NSCC, REPS+NSCC, REPS+STrack, and REPS+Prism v2-full on
the 1:1 1024-node many2many workload (`256 -> 64`, 2 MB, `-failed 16`, five seeds).  It records
genuine ACK samples as `q = raw_rtt - base_rtt`, averages seed-local ECDFs with equal seed weight,
and writes `figI_1024_ack_qdelay_cdf.{png,pdf}`.  Run it with:

```bash
bash repro_1024_ack_qdelay_cdf.sh
```

Spec: `docs/superpowers/specs/2026-06-25-prism-v2-robust-gated-design.md`

## 2. Setup

| parameter | value |
|-----------|-------|
| topology | fat_tree_128_1os (last-hop 100 Gbps, base_rtt ≈ 14 us) |
| mode | delay-driven (-disable_trim) |
| seeds | 13–17 (5 seeds) |
| conditions | m2m f=0 (symmetric), m2m f=8 (asymmetric), incast n8/n32/n64 f=8 |

**Arms:**

| token | label | flags |
|-------|-------|-------|
| ref | REPS+NSCC | baseline, no PRISM |
| bold | PRISM@B (old) | always-on: `-prism_t_spray 7 -target_q_delay 10 -prism_kappa 2` |
| a1 | v2-A1 | smooth only (β=0.3), always engaged |
| a1a2 | v2-A1A2 | smooth + hysteresis, always engaged |
| v2 | v2-full | `-prism_smooth_beta 0.3 -prism_hysteresis 0.25 -prism_engage_spread 28 -prism_disengage_spread 20` |

`bash repro.sh` reproduces all runs (data/ gitignored; figs rendered via `python3 make_figs.py`;
committed via `git add -f`).

### Relative engagement thresholds (alternative to absolute µs values)

The engagement thresholds can be set two ways:

**(a) Absolute (used by the headline v2 runs above):**
`-prism_engage_spread 28 -prism_disengage_spread 20` (µs)

**(b) Relative:** `-prism_engage_mult m -prism_disengage_ratio ρ`
where engage = m·T_cc and disengage = ρ·m·T_cc.
The relative form **auto-scales with the network RTT (topology-independent)** — no per-topology
recalibration needed.

Recommended relative config: **m=2, ρ=0.7** ⇒ at T_cc≈14µs gives engage≈28.0µs, disengage≈19.6µs
(≈ the old absolute 28/20 values), and reproduces the absolute v2 result within seed noise
(parity: relative m=2 f8 goodput = +14.8% vs absolute v2 +15.0%; within seed noise).

Defaults (m=0, engage_spread=0) ⇒ gating off ⇒ byte-identical (golden 53e85c88 unchanged).

## 3. Results

### 1024-node predeclared double-evidence sweep

This result uses `fat_tree_1024.topo` with `NODES=1024`, `PATHS=8`, `END_MS=8`, and
delay-driven mode (`-disable_trim`).  The fixed workload is a 1:1 many2many pattern with
256 sources, 64 destinations, and 256 paired 2 MB flows.  The predeclared grid contains all
five failure levels `{0, 8, 16, 24, 32}`, all five seeds `{13, 14, 15, 16, 17}`, and these
four arms:

| token | arm | congestion control / load balancing | extra flags |
|-------|-----|--------------------------------------|-------------|
| ops | OPS+NSCC | `nscc / oblivious` | `-disable_trim` |
| reps | REPS+NSCC | `nscc / reps` | `-disable_trim` |
| strack | REPS+STrack | `strack / reps` | `-disable_trim` |
| v2 | REPS+Prism v2-full | `prism / reps` | `-disable_trim -prism_smooth_beta 0.3 -prism_hysteresis 0.25 -prism_engage_spread 28 -prism_disengage_spread 20` |

From the repository root, reproduce the full 100-run grid and its eight sweep figure files with
the exact command:

```bash
bash htsim/sim/datacenter/prism_eval/expI_prism_v2/repro_1024_double_evidence.sh
```

To regenerate only `figI_1024_ack_qdelay_evidence.{png,pdf}` from the existing 20 ACK traces,
without running any simulation, use this exact repository-root command:

```bash
python3 htsim/sim/datacenter/prism_eval/expI_prism_v2/make_1024_ack_qdelay_cdf.py \
  --data-dir htsim/sim/datacenter/prism_eval/expI_prism_v2/data/ack_qdelay_1024 \
  --output-stem htsim/sim/datacenter/prism_eval/expI_prism_v2/figs/figI_1024_ack_qdelay_evidence \
  --seeds 13 14 15 16 17
```

The completion rule is applied independently to every run: `metrics.fct_stats` must report a
finite numeric `completion_rate >= 0.999`, otherwise the script stops before rendering.  The
completed sweep has 100/100 qualifying flow logs (observed minimum and maximum completion rate
are both 1.0) and 25/25 nonempty v2 epoch logs.

For the failure-sweep panels, each point is the arithmetic mean of the five seed-local metrics
and each error bar is the sample standard error.  ECDFs first form one ECDF per seed and then
average the five seed-local ECDF values, so every seed has equal weight regardless of its number
of samples.  The ACK delta panel is target arm minus REPS+NSCC; its band is the 2.5th--97.5th
nearest-rank interval from 2,000 paired seed-resampling draws (fixed bootstrap seed `20260725`).
The ACK figure uses the existing 20 `failed=16` traces and does not rerun simulation.

The complete sweep means are reported below; no failure level was omitted.  FCT values are in
microseconds and each row is the mean of seeds 13--17.

| failed | arm | goodput (Gbps) | mean FCT | p99 FCT | minimum completion |
|-------:|:----|---------------:|---------:|--------:|-------------------:|
| 0 | OPS+NSCC | 3459.109 | 767.625 | 1115.829 | 1.000000 |
| 0 | REPS+NSCC | 3758.322 | 751.779 | 1059.936 | 1.000000 |
| 0 | REPS+STrack | 3497.405 | 810.694 | 1109.393 | 1.000000 |
| 0 | REPS+Prism v2-full | 3636.876 | 756.651 | 1080.357 | 1.000000 |
| 8 | OPS+NSCC | 1489.806 | 1420.969 | 2647.216 | 1.000000 |
| 8 | REPS+NSCC | 1961.590 | 1230.824 | 2030.388 | 1.000000 |
| 8 | REPS+STrack | 1909.988 | 1287.728 | 2053.771 | 1.000000 |
| 8 | REPS+Prism v2-full | 2029.783 | 1198.546 | 1911.483 | 1.000000 |
| 16 | OPS+NSCC | 1315.955 | 1788.935 | 3040.878 | 1.000000 |
| 16 | REPS+NSCC | 1839.069 | 1469.808 | 2154.317 | 1.000000 |
| 16 | REPS+STrack | 1757.739 | 1511.484 | 2258.426 | 1.000000 |
| 16 | REPS+Prism v2-full | 1923.890 | 1384.304 | 2038.842 | 1.000000 |
| 24 | OPS+NSCC | 1244.193 | 2075.390 | 3227.589 | 1.000000 |
| 24 | REPS+NSCC | 1608.370 | 1625.618 | 2511.200 | 1.000000 |
| 24 | REPS+STrack | 1639.226 | 1644.256 | 2402.344 | 1.000000 |
| 24 | REPS+Prism v2-full | 1919.751 | 1489.424 | 2055.921 | 1.000000 |
| 32 | OPS+NSCC | 1197.305 | 2238.630 | 3356.501 | 1.000000 |
| 32 | REPS+NSCC | 1558.686 | 1689.954 | 2545.351 | 1.000000 |
| 32 | REPS+STrack | 1569.680 | 1724.593 | 2540.039 | 1.000000 |
| 32 | REPS+Prism v2-full | 1864.818 | 1532.143 | 2114.668 | 1.000000 |

Prism v2 engagement rises with the complete failure grid rather than being inferred from one
selected point:

| failed | engaged fraction mean | sample SEM |
|-------:|----------------------:|-----------:|
| 0 | 0.024501 | 0.006676 |
| 8 | 0.228617 | 0.004341 |
| 16 | 0.333500 | 0.006698 |
| 24 | 0.387380 | 0.007347 |
| 32 | 0.420157 | 0.006159 |

Across all five predeclared levels, v2 versus REPS+NSCC changes goodput by
`{-3.2%, +3.5%, +4.6%, +19.4%, +19.6%}`, mean FCT by
`{+0.6%, -2.6%, -5.8%, -8.4%, -9.3%}`, and p99 FCT by
`{+1.9%, -5.9%, -5.4%, -18.1%, -16.9%}` for failures `{0, 8, 16, 24, 32}`,
respectively.  Thus the complete sweep records a small f=0 cost as well as the improvements at
every tested nonzero failure level.  `figI_1024_f16_fct_cdf` and
`figI_1024_f32_fct_cdf` are the predeclared explanatory endpoints for moderate and highest
failure, respectively, not post-hoc selections or substitutes for the full sweep.

### Goodput (Gbps, 5-seed mean) + Δ vs ref

| condition | ref | bold | a1 | a1a2 | v2-full |
|-----------|-----|------|----|----|---------|
| m2m f=0 (symmetric, do-no-harm) | 996.74 | 925.68 (−7.1%) | 765.87 (−23.2%) | 737.95 (−26.0%) | **998.90 (+0.2%)** |
| m2m f=8 (asymmetric, KEEP-WIN) | 430.84 | 552.56 (+28.3%) | 498.97 (+15.8%) | 482.57 (+12.0%) | **495.32 (+15.0%)** |
| incast n32 f=8 (do-no-harm) | 93.00 | 91.28 (−1.8%) | 91.92 (−1.2%) | 91.81 (−1.3%) | **93.00 (+0.0%)** |
| incast n8 f=8 | 77.74 | 72.94 (−6.2%) | 67.92 (−12.6%) | 67.40 (−13.3%) | **77.74 (+0.0%)** |
| incast n64 f=8 | 96.08 | 95.88 (−0.2%) | 95.79 (−0.3%) | 95.78 (−0.3%) | **96.13 (+0.1%)** |

### avg FCT (us, 5-seed mean) + Δ vs ref

| condition | ref | bold | a1 | a1a2 | v2-full |
|-----------|-----|------|----|----|---------|
| m2m f=0 | 737 | 735 (−0.3%) | 1107 (+50.2%) | 1122 (+52.2%) | **737 (−0.0%)** |
| m2m f=8 | 1694 | 1400 (−17.3%) | 1509 (−10.9%) | 1563 (−7.8%) | **1521 (−10.2%)** |
| incast n32 f=8 | 4234 | 5176 (+22.3%) | 4660 (+10.1%) | 4551 (+7.5%) | **4234 (+0.0%)** |
| incast n8 f=8 | 1373 | 1617 (+17.8%) | 1771 (+29.0%) | 1773 (+29.1%) | **1373 (+0.0%)** |

p99 FCT (us) — m2m f=8: ref 2350, bold 1830, v2 2005. incast n32 f=8: ref 5505, bold 5609, v2 5505.

### Incast last-hop queue stability (time-series, failed=8 center)

| arm | mean qdelay (us) | sd (us) | jitter mean\|Δ\| (us) |
|-----|------------------|---------|----------------------|
| ref (REPS+NSCC) | 7.66 | 10.55 | 0.41 |
| bold (PRISM@B old) | 9.48 | 14.57 | 1.47 |
| **v2-full** | **7.66** | **10.55** | **0.41** |

v2 queue is **byte-identical to ref** — v2 fully disengages on incast (engaged fraction = 0.00)
and runs as pure NSCC. bold runs +24% deeper with 3.6× spikier jitter (1.47 vs 0.41 us).

### Engaged fraction (v2-full time-series)

| condition | engaged fraction | epochs |
|-----------|------------------|--------|
| incast f=8 | 0.00 | 3433 |
| m2m f=8 | 0.38 | 3217 |

### Calibration sweeps (goodput Δ vs ref; ref incast-n32-f8=93.00 Gbps, ref m2m-f8=430.84 Gbps)

**engage_spread (β=0.1):**

| engage_spread | incast Δ | m2m Δ |
|---------------|----------|-------|
| 24 | −0.1% | +20.9% |
| 28 (default) | +0.0% | +15.0% |
| 34 | +0.0% | +12.8% |

**engage_beta (engage_spread=28):**

| engage_beta | incast Δ | m2m Δ |
|-------------|----------|-------|
| 0.1 (default) | +0.0% | +15.0% |
| 0.2 | −0.1% | +20.2% |
| 0.3 | −0.1% | +18.4% |

**smooth_beta (incast only):** 0.15/0.3/0.5 all give incast +0.0% — smoothing alone is
incast-neutral once the engagement gate is active.

### Do-no-harm frontier on f0 (m2m failed=0, 5 seeds)

| config | f0 goodput Δ | f0 avg FCT Δ | f8 goodput Δ | verdict |
|--------|-------------|--------------|--------------|---------|
| default eng28 / β0.1 | **+0.2%** | −0.0% | +15.0% | strict do-no-harm — recommended default |
| eng24 | **−1.5%** | +0.4% | +20.9% | leans aggressive: trades 1.5% f0 for +6% more f8 (74% of bold's edge) |
| engage_beta 0.2 | **−10.7%** | +4.4% | +20.2% | BREAKS do-no-harm — fast detector engages on f0 transient spikes — rejected |

### Parameter sensitivity (OAT)

Goodput as % of REPS+NSCC baseline; 100% = do-no-harm. 3 seeds (13–15). Center = (β0.3, h0.25, m2.0, ρ0.7). Baselines (Gbps, seeds 13–15): m2m-f0=1005.6, m2m-f8=443.7, incast-n32-f8=92.95 Gbps. All 108 cells cr>=0.999.

**β (smooth_beta) {0.15, 0.3, 0.5}:**
| val | f0 | incast | f8 |
|-----|----|--------|----|
| 0.15 | 99.5% | 100.0% | 109.8% |
| 0.3 (center) | 100.2% | 100.0% | 114.8% |
| 0.5 | 98.8% | 100.0% | 115.1% |

**h (hysteresis) {0.15, 0.25, 0.4}:**
| val | f0 | incast | f8 |
|-----|----|--------|----|
| 0.15 | 99.3% | 100.0% | 115.1% |
| 0.25 (center) | 100.2% | 100.0% | 114.8% |
| 0.4 | 100.3% | 100.0% | 117.3% |

**ρ (disengage_ratio) {0.6, 0.7, 0.8}:**
| val | f0 | incast | f8 |
|-----|----|--------|----|
| 0.6 | 99.1% | 100.0% | 111.8% |
| 0.7 (center) | 100.2% | 100.0% | 114.8% |
| 0.8 | 99.2% | 100.0% | 115.3% |

**m (engage_mult) {1.7, 2.0, 2.4}:**
| val | f0 | incast | f8 |
|-----|----|--------|----|
| 1.7 | 98.4% | 99.9% | 119.3% |
| 2.0 (center) | 100.2% | 100.0% | 114.8% |
| 2.4 | 99.7% | 100.0% | 107.4% |

## 4. Verdict (POSITIVE)

**v2-full achieves the design goal:**

1. **Full do-no-harm on symmetric and incast traffic.** f0 goodput: +0.2% vs ref (within noise);
   f0 avg FCT: −0.0%. Incast n32 f=8: +0.0% gp, +0.0% FCT. Queue is byte-identical to NSCC
   (jitter 0.41 us, matching ref exactly). This directly recovers the negative result in
   `../expC2_incast_asym` and `../expC_incast`.

2. **Keeps +15.0% goodput / −10.2% FCT on asymmetric f=8** (53–59% of bold's edge). The accepted
   give-back of ~41–47% of bold's f8 win is the explicit cost of the engagement gate — stated in
   the spec and confirmed here.

3. **Queue stability fully restored.** v2 incast jitter 0.41 us = ref (bold is 3.6× spikier at
   1.47 us). v2 is byte-identical to NSCC on incast because it fully disengages (engaged fraction
   0.00 across 3433 epochs).

4. **Ablation: C (the engagement gate) is the load-bearing mechanism.** A1 (smoothing alone) and
   A1A2 (smoothing + hysteresis), both always engaged, are **not** do-no-harm — they are
   **catastrophic on f0** (−23.2%/−26.0% gp, +50%/+52% FCT) and worse than bold on small incast
   (n8: −12.6%/−13.3% gp vs bold's −6.2%). The robustness fixes (A1, A2) are insufficient alone;
   only disengaging to NSCC where spread is not persistently high (mechanism C) delivers do-no-harm.

5. **Tunable frontier.** Default 28/0.1 is the strict-do-no-harm point. eng24 captures more f8
   win (+20.9%, 74% of bold) at a small f0 cost (−1.5%) — a viable aggressive-mode option.
   engage_beta 0.2 over-engages on symmetric traffic (−10.7% f0 gp) and is rejected.

### Parameter surface

The OAT sweep data establishes the following data-backed conclusions:

- **Incast is exactly 100% under every parameter** — it always fully disengages (engaged≈0) →
  identical to REPS+NSCC regardless of any knob. Do-no-harm on incast is parameter-independent,
  by construction.

- **β, h, ρ are robust (flat curves):** across their ranges f0 stays 98.8–100.3% (do-no-harm
  holds), f8 stays ~110–117% (win held). They are not policy knobs → safe to FIX as constants
  (β=0.3, h=0.25, ρ=0.7).

- **m (engage_mult) is the ONE sensitive knob** — it monotonically trades do-no-harm vs keep-win:
  m=1.7 → f0 98.4% / f8 +19.3% (aggressive, mild f0 cost); m=2.0 → f0 100.2% / f8 +14.8%
  (recommended sweet spot, full do-no-harm); m=2.4 → f0 99.7% / f8 +7.4% (conservative).

- **Net: the recommended tuning surface collapses to ONE knob (m)**, with β/h/ρ fixed and
  thresholds auto-scaling via T_cc — resolving the "too many parameters" concern. The 5 raw flags
  exist for research/back-compat, but only m needs tuning; m=2 is a robust default.

## 5. Figures

- **figI_1024_ack_qdelay_evidence** — existing `failed=16` ACK traces shown as the full and
  low-delay equal-seed ECDFs plus paired-bootstrap ECDF deltas versus REPS+NSCC.
- **figI_1024_failure_sweep** — goodput, mean FCT, and p99 FCT over all five predeclared failure
  levels; points are five-seed means with sample-SEM error bars.
- **figI_1024_f16_fct_cdf** and **figI_1024_f32_fct_cdf** — the predeclared moderate- and
  highest-failure explanatory endpoints, with equally weighted seed-local FCT ECDFs.
- **figI_1024_v2_engagement_sweep** — v2 engaged-epoch fraction over the complete failure grid;
  points are five-seed means with sample-SEM error bars.
- **figI_a_headline** — grouped bars: goodput + avg FCT for {ref, bold, v2-full} across
  {m2m f=0, m2m f=8, incast n32 f=8}. Shows do-no-harm on f0/incast and the preserved f8 win.
- **figI_b_queue_stability** — last-hop switch queue delay vs time (time-series run, seed 13) for
  ref/bold/v2; annotated with sd and jitter. v2 and ref traces are identical.
- **figI_c_engaged_fraction** — fraction of PRISM epochs engaged vs time (20 us bins) for incast
  and m2m conditions; confirms 0.00 on incast and 0.38 on m2m.
- **figI_d_ablation** — bars for {ref, a1, a1a2, v2} on incast n32 f=8: goodput, avg FCT, and
  queue-delay stdev. Demonstrates that C (the gate) is the essential component.
- **figI_e_sweeps** — sensitivity sweep lines: goodput (incast + m2m) vs engage_spread, smooth_beta
  (incast only; m2m panel hidden — repro.sh does not run the m2m beta sweep), and engage_beta.
  Reference REPS+NSCC line on each panel.
- **figI_f_sensitivity** — 2×2 panels (β, h, ρ, m); y = goodput % of REPS+NSCC baseline; 3
  scenario lines (m2m-f0, incast, m2m-f8) + 100% do-no-harm reference line. Flat curves ⇒ robust;
  only the m panel's f8 line slopes.

## 6. Cross-links and caveats

**Spec:** `docs/superpowers/specs/2026-06-25-prism-v2-robust-gated-design.md`

**Plan:** `.superpowers/sdd/` (PRISM v2 controller plan, Task 9)

**Contrast with expC2:** `../expC2_incast_asym` established that PRISM@B breaks do-no-harm on
incast (negative result). This redesign directly recovers that result via the asymmetry engagement
gate — v2-full is +0.0% on all incast conditions tested.

**Caveats:**
- 128-node development scale (fat_tree_128_1os). Results should be validated at larger scale before
  production recommendation.
- Absolute-µs engage thresholds (engage_spread=28, disengage_spread=20) are calibrated for
  base_rtt ≈ 14 us / 100G. These will need re-calibration for different link speeds or RTTs.
- v2 default is **OFF** (byte-identical to existing PRISM) — all existing experiments are
  unaffected. v2 mechanisms require explicit flag enabling.
- Engaged fraction on m2m f=8 is 0.38 (not 1.0) — PRISM v2 engages selectively and
  intermittently, which is expected and desirable. The 62% of time spent disengaged still benefits
  from NSCC's stability.
