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
| Metric | CCT = worst-case FCT; CCT inflation over a zero-queue lower bound | — |
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

CCT = worst-case FCT across the 128 ring flows. **CCT Increase (%)** = (CCT − LB)/LB×100, where the
zero-queue lower bound LB = base_rtt + size×8/100 Gbps ≈ 1.11 ms. Error bars = SEM across seeds.

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

### CCT Increase (%) — mean ± SEM, 5 seeds (lower is better)

| Arm | f0 | f4 | f8 | f12 |
|---|---|---|---|---|
| OPS+NSCC | 146 ± 15 | 379 ± 62 | 448 ± 77 | 477 ± 58 |
| REPS+NSCC | 95 ± 8 | 260 ± 46 | 285 ± 26 | 328 ± 42 |
| REPS+Swift | 114 ± 7 | 292 ± 47 | 307 ± 31 | 339 ± 36 |
| REPS+MSwift | 111 ± 7 | 226 ± 34 | 258 ± 16 | 304 ± 33 |
| REPS+MNSCC | 97 ± 8 | 249 ± 43 | 278 ± 28 | 316 ± 38 |
| STrack | 94 ± 9 | 258 ± 45 | 302 ± 27 | 348 ± 47 |
| **Prism** | **78 ± 4** | **157 ± 19** | **170 ± 11** | **213 ± 23** |

### Prism vs REPS+NSCC (the UEC reference arm) — CCT-inflation reduction

| failed | Prism | REPS+NSCC | Δ |
|---|---|---|---|
| f0 | 78% | 95% | **−17 pts** |
| f4 | 157% | 260% | **−103 pts** |
| f8 | 170% | 285% | **−115 pts** |
| f12 | 213% | 328% | **−114 pts** |

At f8, PRISM's CCT inflation (170%) is **1.7× smaller** than REPS+NSCC's (285%) and **2.6× smaller**
than OPS+NSCC's (448%).

### f0 exceeds the pre-registration — and the mechanism explains why

§4 pre-registered f0 as "do-no-harm / roughly neutral, not a win," on the assumption that a healthy
ring has `C_spray ≈ 0`. **That premise was wrong, and the result beats it: PRISM is the best arm at
f0 (−17 pts vs REPS+NSCC).** `figF4_ai_decomp` shows why — even on the *symmetric* ring the
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
with fabric degradation** — best arm at every level, 1.7× lower CCT inflation than the UEC reference
at f8. The win is driven by spread-dominated ring congestion (`figF4`), and it shows up even on the
healthy fabric, exceeding the do-no-harm bar we pre-registered.

## 6. Caveats (honest)

1. **Failure on-path check (passed).** The failed links must lie on paths the spatially-uniform ring
   traverses, else the sweep would be meaningless. They do: CCT rises monotonically f0→f12 across all
   arms (e.g. REPS+NSCC 95%→328%, PRISM 78%→213%), confirming the `-failed K` choke bites the ring
   traffic.
2. **OPS+NSCC does not fully drain under failures.** 3 of 140 cells have cr < 1.00 — all **OPS+NSCC**,
   all seed 16 (f4/f8/f12, cr ≈ 0.94, ~7–8 of 128 flows unfinished at END = 8 ms). Oblivious spraying
   has no way to avoid degraded links, so on a choked fabric some flows starve. CCT there is computed
   over completed flows only and is therefore a **lower bound** (OPS's true CCT is worse than tabled);
   even so OPS is the worst arm by a wide margin. Every other arm — including PRISM — is cr = 1.00 at
   all 140 cells.
3. **Fabric is our 100 G / COMPOSITE, not MSwift's 800 G / droptail** (see §1) — we replicate the
   workload and metric, not the link layer.
