# expF_aiworkload — MSwift AI-training collective (Llama-70B HSDP ring) × failed-links

## 1. What this group tests

Whether PRISM's delay-driven **asymmetric-fabric advantage** carries to a realistic **AI training
collective**. We reproduce MSwift's AI workload (Gerstein et al., 2026, *Congestion Control for
Spraying with Congested Paths*, Fig. 7): **one inter-server ring step of the Llama-3 70B HSDP
(FSDP2 2D) backward pass** on a 128-GPU cluster — and add a **failed-links sweep**, PRISM's thesis
axis, as our extension.

### Faithful to MSwift vs. our extension

| Aspect | Faithful | Our extension / deviation |
|---|---|---|
| Workload | HSDP ring single step (stride-8, 13 MB/flow, 128 GPU, random placement) | — |
| Metric | CCT = worst-case FCT; CCT slowdown over a zero-queue lower bound | — |
| Figure | grouped bar chart, log-y, value labels, SEM error bars | — |
| Fabric | 3-tier non-blocking 128-node fat-tree, ECN, no trimming | **100 G / 1 µs-hop / COMPOSITE** (ours), not MSwift's 800 G / 0.5 µs / 4 KB / droptail |
| Asymmetry | MSwift fails 1 % of links on its *baseline* (Fig. 11), not on the AI workload | We sweep **failed-links {0,4,8,12}** on the AI workload |
| CCA × LB grid | each CCA × {OPS, AR, REPS} | our arm convention (CC fixed per arm on REPS + the oblivious/OPS arm); no AR; PRISM is REPS-only |

## 2. Setup

| Parameter | Value |
|---|---|
| Topology | `fat_tree_128_1os.topo` (3-tier, 100 G, 1:1) |
| Nodes | 128 (= 16 servers × 8 GPUs) |
| Workload | HSDP ring single step, GPU `i → (i+8) mod 128`, 13,697,024 B/flow, random server placement per seed |
| Failed-link sweep | `{0, 4, 8, 12}` |
| Regime | delay-driven (`-disable_trim`), PATHS=8, END=8 ms (gives cr≈1; override via `EXP_END`) |
| Arms | OPS+NSCC, REPS+NSCC, REPS+Swift, REPS+MSwift, REPS+MNSCC, STrack, **Prism** (7) |
| Seeds | 13–17 (5) → 7×4×5 = **140 runs** |

**One-command repro:** `bash repro.sh`. Raw data gitignored; figures committed with `git add -f`.

## 3. Metric

CCT = worst-case FCT across the 128 ring flows. **CCT slowdown** = CCT / LB, where the zero-queue
lower bound LB = base_rtt + size×8/100 Gbps ≈ 1.11 ms (slowdown 1.0 = ideal/no queueing; 2.0 = twice
the ideal). Error bars = SEM across seeds. (Equivalently, "CCT increase %" = (slowdown − 1)×100.)

## 4. Honest pre-registration

- **f0 (healthy):** PRISM's advantage needs path asymmetry; on a healthy ring C_spray ≈ 0 ⇒ PRISM ≈
  NSCC (**do-no-harm**, possibly the small transient-spread cost of `../expA_f0_diagnosis`). Reported
  straight, expecting roughly neutral — not a win.
- **f>0 (asymmetric):** PRISM's decomposition should avoid degraded paths ⇒ modest win or
  do-no-harm, growing with failures. A tie everywhere is an acceptable, publishable outcome.

## 5. Results

All 140 cells completed; **137/140 at cr = 1.00** (the 3 exceptions are the OPS+NSCC arm only — see
§6). Figures: `figs/figF1_cct_bars` (headline), `figs/figF2_fct_cdf_f{0,8}`, `figs/figF4_ai_decomp`.

**PRISM gives the lowest collective completion time on the AI ring at every failure level, and the
margin grows with failures.** It is the single best arm at f0, f4, f8, and f12.

### CCT slowdown (CCT / ideal) — mean ± SEM, 5 seeds (lower is better; 1.0 = ideal)

| Arm | f0 | f4 | f8 | f12 |
|---|---|---|---|---|
| OPS+NSCC | 2.46 ± 0.15 | 4.79 ± 0.62 | 5.48 ± 0.77 | 5.77 ± 0.58 |
| REPS+NSCC | 1.95 ± 0.08 | 3.60 ± 0.46 | 3.85 ± 0.26 | 4.28 ± 0.42 |
| REPS+Swift | 2.14 ± 0.07 | 3.92 ± 0.47 | 4.07 ± 0.31 | 4.39 ± 0.36 |
| REPS+MSwift | 2.11 ± 0.07 | 3.26 ± 0.34 | 3.58 ± 0.16 | 4.04 ± 0.33 |
| REPS+MNSCC | 1.97 ± 0.08 | 3.49 ± 0.43 | 3.78 ± 0.28 | 4.16 ± 0.38 |
| STrack | 1.94 ± 0.09 | 3.58 ± 0.45 | 4.02 ± 0.27 | 4.48 ± 0.47 |
| **Prism** | **1.78 ± 0.04** | **2.57 ± 0.19** | **2.70 ± 0.11** | **3.13 ± 0.23** |

### Prism vs REPS+NSCC (the UEC reference arm)

| failed | Prism | REPS+NSCC |
|---|---|---|
| f0 | **1.78×** | 1.95× |
| f4 | **2.57×** | 3.60× |
| f8 | **2.70×** | 3.85× |
| f12 | **3.13×** | 4.28× |

At f8, PRISM's **excess time over ideal** (slowdown − 1 = 1.70) is **1.7× smaller** than REPS+NSCC's
(2.85) and **2.9× smaller** than OPS+NSCC's (4.48).

### f0 exceeds the pre-registration — and the mechanism explains why

§4 pre-registered f0 as "do-no-harm / roughly neutral, not a win," on the assumption that a healthy
ring has `C_spray ≈ 0`. **That premise was wrong, and the result beats it: PRISM is the best arm at
f0 (slowdown 1.78× vs REPS+NSCC's 1.95×).** `figF4_ai_decomp` shows why — even on the *symmetric* ring the
congestion is **spread-dominated**: `C_spray ≈ 34 µs` (rising to ≈ 38 µs at f8) while the floor
`C_cc` stays pinned near zero, well below the ~14 µs target, throughout. The HSDP ring's bursty
all-lanes-at-once traffic produces large per-path spread but almost no persistent floor. A CC that
reacts to that spread (NSCC/Swift reacting to max/avg delay) over-throttles; PRISM routes the spread
to spraying and holds CC on the near-zero floor, so it backs off less and drains the collective
faster. This is the same decomposition advantage shown on incast/permutation — now on a faithful AI
collective, and present even without injected failures because the ring itself creates transient
asymmetry.

### FCT distribution (figF2)

Median FCT is similar across arms (all reach CDF ≈ 0.8 by ~2 ms); the story is the **tail**. PRISM's
CDF closes earliest (its worst-case FCT — i.e. the CCT — is the smallest), while REPS+Swift and
OPS+NSCC stretch to 5–8 ms. CCT is a worst-case metric, so the tail is what the headline measures.

### Verdict

On MSwift's own AI-training collective, PRISM's congestion-decomposition advantage **holds and grows
with fabric degradation** — best arm at every level (CCT slowdown 1.78×/2.57×/2.70×/3.13× at
f0/f4/f8/f12), with 1.7× lower excess-over-ideal than the UEC reference at f8. The win is driven by
spread-dominated ring congestion (`figF4`), and it shows up even on the
healthy fabric, exceeding the do-no-harm bar we pre-registered.

## 6. Caveats (honest)

1. **Failure on-path check (passed).** The failed links must lie on paths the spatially-uniform ring
   traverses, else the sweep would be meaningless. They do: CCT slowdown rises monotonically f0→f12
   across all arms (e.g. REPS+NSCC 1.95×→4.28×, PRISM 1.78×→3.13×), confirming the `-failed K` choke
   bites the ring traffic.
2. **OPS+NSCC does not fully drain under failures.** 3 of 140 cells have cr < 1.00 — all **OPS+NSCC**,
   all seed 16 (f4/f8/f12, cr ≈ 0.94, ~7–8 of 128 flows unfinished at END = 8 ms). Oblivious spraying
   has no way to avoid degraded links, so on a choked fabric some flows starve. CCT there is computed
   over completed flows only and is therefore a **lower bound** (OPS's true CCT is worse than tabled);
   even so OPS is the worst arm by a wide margin. Every other arm — including PRISM — is cr = 1.00 at
   all 140 cells.
3. **Fabric is our 100 G / COMPOSITE, not MSwift's 800 G / droptail** (see §1) — we replicate the
   workload and metric, not the link layer.
