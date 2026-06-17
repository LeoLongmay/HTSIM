# expB_oversub — Graded Oversubscription / Fallback Correctness

## 1. What this group tests

This experiment tests PRISM under **graded oversubscription** of a fat-tree core in the
**delay-driven regime** (`-disable_trim`, 5x BDP buffers). Oversubscription is the sole
stressor (`-failed 0`); it is induced by swapping the topology file so that the
aggregation-to-core uplink capacity narrows at three ratios: 1:1, 4:1, and 8:1.

As the ratio rises, congestion shifts from "still reroutable across a reduced core" toward
"the core is a genuine shared bottleneck." The central question is a **fallback-correctness
/ do-no-harm** question, not a win-hunt:

> As the core saturates, does PRISM correctly shift to cutting the window on the floor
> (`C_cc`) rather than holding or spraying — and does it stay do-no-harm on goodput
> versus the REPS+NSCC baseline?

This is **Axis-2 / oversub** in the PRISM evaluation. See `../NARRATIVE.md` and
`../TARGET_REGIME.md`.

---

## 2. Setup

| Parameter | Value |
|---|---|
| Topologies | `fat_tree_128_{1,4,8}os.topo` — 128 nodes, podsize 16; only Tier-1 oversub differs (verified drop-ins) |
| x-axis | Oversubscription ratio {1:1, 4:1, 8:1} |
| Workload | `many2many.py 64 16 pairs 2000000 128 16` — 64 senders outside pod0 → 16 pod0 receivers, 2 MB each (identical to `expA_delaydriven/` for comparability) |
| Arms | OPS+NSCC, REPS+NSCC, PRISM (all-reps spray), STrack |
| Seeds | {13, 14, 15, 16, 17} |
| `PATHS` | 8 |
| `EXTRA_ARGS` | `-disable_trim` |
| `EXP_END` | 8 ms (completion ratio reached 1.00 at all cells; no bump needed) |

**One-command repro** (from this directory):

```
bash repro.sh
```

Raw simulation data is gitignored. Figures are committed with `git add -f`.

---

## 3. Results — do-no-harm and cost

### Goodput (Gbps) and avg-FCT (us), all cr = 1.00

| Arm | ratio 1:1 goodput | ratio 1:1 avg-FCT | ratio 4:1 goodput | ratio 4:1 avg-FCT | ratio 8:1 goodput | ratio 8:1 avg-FCT |
|---|---|---|---|---|---|---|
| OPS+NSCC | 906.4 Gbps | 788 us | 326.2 Gbps | 2430 us | 178.6 Gbps | 4570 us |
| REPS+NSCC | 996.7 Gbps | 737 us | 343.5 Gbps | 2334 us | 185.4 Gbps | 4344 us |
| STrack | 912.4 Gbps | 789 us | 341.3 Gbps | 2288 us | 184.9 Gbps | 4229 us |
| PRISM | 868.6 Gbps | 945 us | 339.2 Gbps | 2625 us | 183.5 Gbps | 4971 us |

### PRISM vs REPS+NSCC deltas

| Ratio | Goodput delta | Avg-FCT delta |
|---|---|---|
| 1:1 | −12.9% | +28.2% |
| 4:1 | −1.3% | +12.5% |
| 8:1 | −1.0% | +14.4% |

**Goodput under oversubscription (4:1, 8:1):** PRISM is within ~1% of REPS+NSCC at both
oversubscribed ratios (−1.3% and −1.0%). These are ties within noise. PRISM does not
forfeit throughput by holding spray when the core is the actual bottleneck.

**FCT under oversubscription:** PRISM's avg-FCT is worse than REPS+NSCC at both
oversubscribed ratios (+12.5% at 4:1, +14.4% at 8:1). This is a real cost and is
reported plainly. Goodput is do-no-harm; latency is not. This is consistent with PRISM's
known under-growth tendency under shared-bottleneck-like congestion.

**The 1:1 column is the f0 symmetric case.** Ratio 1:1 — `fat_tree_128_1os`, failed=0,
64→16 many2many — is exactly the f0 condition from `expA_delaydriven` /
`../expA_f0_diagnosis/`. PRISM's −12.9% goodput and +28.2% FCT at 1:1 are the
already-characterized symmetric penalty (under-growth from HOLDing on a transient spread),
re-surfacing here. This is not a new finding; cross-reference `../expA_f0_diagnosis/`.

---

## 4. Mechanism — floor-driven reaction at 8:1

See `figs/figB2_mechanism`.

At oversub = 8:1, seed 13:

| Arm | Per-ACK cwnd-decrease events |
|---|---|
| REPS+NSCC | 4586 |
| STrack | 4002 |
| PRISM | 2693 |

**Floor-MD fraction (PRISM):** epoch-MDs / cwnd-decreases = 2577 / 2693 = **0.957**.

The trimming baseline floor-MD fraction in the delay-driven regime was ~0.05. At 8:1, 96%
of PRISM's window cuts are triggered by the epoch floor `C_cc` crossing the target —
decisively floor-driven.

What this shows: under genuine path-wide overload PRISM reacts to the real bottleneck and
does **not** mistake core saturation for reroutable spread. It cuts fewer times overall
than REPS+NSCC (2693 vs 4586) yet keeps goodput within ~1%. This is the "reacts correctly
when overload is irreducible" claim, measured.

The floor-MD fraction near 1.0 is the direct mechanical evidence for the fallback-correctness
pillar: PRISM shifts to `C_cc`-driven cutting exactly as the core saturates.

---

## 5. Honest verdict

This experiment group is a **fallback-correctness / do-no-harm** study, not a win-hunt.

The contribution is:

1. **Correct floor-driven reaction (measured).** At 8:1 the floor-MD fraction is 0.957.
   PRISM is decisively driven by `C_cc` under genuine path-wide overload. It does not
   misuse spray or mistake an irreducible bottleneck for reroutable spread.

2. **Goodput do-no-harm.** At 4:1 and 8:1 PRISM's goodput is within ~1% of REPS+NSCC.
   PRISM does not forfeit throughput under oversub.

3. **FCT cost, stated honestly.** PRISM's avg-FCT is +12–15% worse than REPS+NSCC under
   oversubscription. This is a real cost.

4. **The 1:1 symmetric penalty is the known f0 cost.** It is not a new finding here; see
   `../expA_f0_diagnosis/` for the full diagnosis.

Cross-links: `../NARRATIVE.md` | `../TARGET_REGIME.md` (Axis-2 / oversub).

---

## 6. Caveats

- **Completion:** All cells reached cr = 1.00 at EXP_END = 8 ms. Deep no-trim queues
  (5x BDP, `-disable_trim`) produce longer absolute FCTs than trimming runs.
- **Scale:** 128-node development-scale topology. Relative trends are the focus.
- **Regime:** Delay-driven only (`-disable_trim`). Trimming-regime oversub behavior is
  deferred to P5.
- **FCT cost:** The +12–15% FCT penalty relative to REPS+NSCC at high oversub is noted
  throughout and is not minimized.
