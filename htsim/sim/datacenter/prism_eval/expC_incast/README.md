# expC_incast — PRISM under pure shared-bottleneck incast

## 1. What this group tests

This group asks whether PRISM **falls back to floor-driven CC** when the topology
provides no reroutable structure — and whether it avoids misusing spray in that
setting. The scenario is pure shared-bottleneck incast: N senders outside the
destination pod all converge on the same last-hop queue to host0. By construction
there is no persistently cleaner path to reroute traffic onto; any cross-path delay
spread is a transient artifact of entropy spraying, not a signal of reroutable
imbalance.

**Pre-registered expectation (from the f0 diagnosis):** tie-or-small-cost. The
contribution is not a win; it is showing that PRISM correctly falls back to
floor-driven CC under a pure shared bottleneck and does not misuse spray, with the
residual cost honestly characterized.

Cross-link: `../NARRATIVE.md`, `../TARGET_REGIME.md`, `../expA_f0_diagnosis/`.

---

## 2. Setup

| Parameter         | Value |
|-------------------|-------|
| Topology          | `fat_tree_128_1os.topo` — symmetric, 128 nodes, podsize 16 |
| Failed links      | `-failed 0` (no failures; no reroutable structure) |
| Regime            | Delay-driven: `EXTRA_ARGS=-disable_trim`, 5×BDP |
| Workload          | `incast.py {8,32,64} 0 1000000 128 16` — fan-in {8,32,64} senders → host0, 1 MB messages, senders forced across core into pod0's ingress |
| Arms              | OPS+NSCC, REPS+NSCC, PRISM (all-reps spray), STrack |
| Seeds             | 13–17 (5 seeds) |
| PATHS             | 8 |
| Simulation end    | `EXP_END=8` ms (cr=1.00 achieved at all cells including fan-in 64) |
| x-axis            | Fan-in {8, 32, 64} |

**One-command repro:**

```bash
bash repro.sh
```

Raw output is gitignored; figures are committed with `git add -f`.

---

## 3. Results — cost shrinks as fan-in grows

### Goodput (Gbps)

| Arm         | Fan-in 8 | Fan-in 32 | Fan-in 64 |
|-------------|----------|-----------|-----------|
| OPS+NSCC    | 66.5     | 88.2      | 94.0      |
| REPS+NSCC   | 66.7     | 88.2      | 94.0      |
| STrack      | 63.9     | 88.1      | 93.9      |
| PRISM       | 59.0     | 87.2      | 93.6      |

### Average FCT (µs)

| Arm         | Fan-in 8 | Fan-in 32 | Fan-in 64 |
|-------------|----------|-----------|-----------|
| OPS+NSCC    | 851      | 2427      | 4650      |
| REPS+NSCC   | 853      | 2337      | 4676      |
| STrack      | 937      | 2421      | 4789      |
| PRISM       | 1025     | 2560      | 4848      |

All cells: cr=1.00 at EXP_END=8 ms.

### PRISM vs REPS+NSCC deltas

| Fan-in | Goodput delta | Avg-FCT delta |
|--------|---------------|---------------|
| 8      | −11.5%        | +20.2%        |
| 32     | −1.1%         | +9.5%         |
| 64     | −0.4%         | +3.7%         |

**The cost shrinks monotonically as fan-in grows.** At fan-in 8 it is real (−11.5%
goodput, +20.2% FCT). By fan-in 64 it is essentially do-no-harm on goodput (−0.4%)
with a small FCT residual (+3.7%). The more extreme the fan-in — the more irreducible
the shared bottleneck — the closer PRISM converges to its floor-driven baseline. This
is consistent with the fallback-correctness thesis.

---

## 4. Mechanism (figC2, fan-in 64, seed 13)

Two facts must be held together; neither cancels the other.

### Fact A — PRISM falls back to floor-driven CC

At fan-in 64:

- Per-ACK cwnd-decrease events: PRISM=1849, REPS+NSCC=3037, STrack=1066.
  PRISM cuts **fewer** times than REPS+NSCC — it does not sit and spray endlessly.
- Floor-MD fraction = 1633/1849 = **0.883** (trimming baseline ≈0.05). Fully 88.3%
  of PRISM's cwnd-decreases are floor-MDs, not trim-driven cuts.
- Mean C_cc ≈ 17.2 µs (above the ~14 µs target in most epochs), so the floor
  signal itself frequently exceeds the slow-down threshold → the floor-MD path fires.

Together these show PRISM correctly diagnoses the shared-bottleneck overload through
the floor signal and cuts on it — it does not mistake the shared-bottleneck load for
a reroutable imbalance.

### Fact B — the symmetric incast still presents a substantial measured spread

Across 3225 epochs: mean C_spray ≈ 12.3 µs (~0.72× C_cc), with C_spray > 0 in ~98%
of epochs. Roughly 50% of epochs carry a cut.

**C_spray is not small here.** A symmetric shared bottleneck still produces a real
cross-path delay spread — a startup/transient artifact of entropy spraying over a
shared last-hop queue, not a persistent reroutable path difference. This is the same
phenomenon as the f0 case (see `../expA_f0_diagnosis/`): PRISM partly HOLDs on this
spread, which under-grows the window and is the direct source of the residual cost.

The nuance is that both facts are true simultaneously: PRISM correctly fires the
floor-MD (Fact A) and is also partially held back by a non-trivial transient C_spray
(Fact B). The residual cost is the price of Fact B.

Reference: `figs/figC2_mechanism.*`

---

## 5. Honest verdict

**Fallback-correctness pillar.** PRISM does not misuse spray under a pure shared
bottleneck:

- It cuts on the floor (88.3% floor-MD fraction at fan-in 64), not on trim alone.
- It makes fewer total cuts than REPS+NSCC (1849 vs 3037), showing it is not
  spiraling into spurious slow-downs.
- The residual cost is the characterized O(1) f0 cost: the transient symmetric
  cross-path spread (C_spray ≈ 0.72× C_cc) that entropy spraying itself induces.
  This cost was pre-registered (see `../expA_f0_diagnosis/`) and is not a surprise.

The cost converges to do-no-harm as fan-in grows (−0.4% goodput at fan-in 64), which
is the expected direction: larger, more irreducible fan-ins leave PRISM less
opportunity to be fooled by transient spread and more fully dominated by the floor
signal.

**This group does not claim a win under incast.** The claim is narrower and more
useful: PRISM falls back gracefully, does not amplify the problem, and the residual
cost is bounded and understood.

Cross-links: `../NARRATIVE.md` (Section 4, fallback-correctness),
`../TARGET_REGIME.md` (Axis-2 out-of-regime: shared bottleneck),
`../expA_f0_diagnosis/` (the f0 transient-spread diagnosis).

---

## 6. Caveats

- **Completion:** cr=1.00 at EXP_END=8 ms for all fan-in levels including fan-in 64;
  the 8 ms window is sufficient.
- **Scale:** 128-node development-scale fat tree. Behavior at production scale
  (larger radix, deeper trees) is not evaluated here.
- **Message size:** 1 MB (`INCAST_SIZE=1000000`). A 2 MB variant is available via
  `INCAST_SIZE=2000000` in `repro.sh` if desired.
- **Regime:** Delay-driven only (`-disable_trim`). Trim-enabled (loss-driven) incast
  is not covered by this group.
