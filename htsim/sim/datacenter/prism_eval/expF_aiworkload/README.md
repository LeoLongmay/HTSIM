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
| Regime | delay-driven (`-disable_trim`), PATHS=8, END probed for cr≈1 |
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

*(filled after `bash repro.sh`; figures: `figs/figF1_cct_bars`, `figs/figF2_fct_cdf_f{0,8}`,
`figs/figF4_ai_decomp`.)*

## 6. Caveat

The failed links must lie on paths the (spatially uniform) ring traffic traverses; if a degraded
point shows CCT indistinguishable from f0 across **all** arms, the failures are off-path and the
failure model/location must be revisited (see the smoke check in §Verify of the plan).
