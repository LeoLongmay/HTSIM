# probe_avgdisc — read-only test of proposal (b): can avg-delay discriminate f0 vs f8 HOLD?

**Question.** PRISM under-grows at f0 because it HOLDs on a *transient* cross-path spread, while the
*same* HOLD wins at f8 (structural spread). Proposal (b) asks: can the **average** per-epoch queuing
delay tell the two apart cheaply (O(1))? Rule under test: when `C_cc < T_cc` and `C_spray ≥ T_spray`
(the HOLD quadrant), additionally require **avg ≥ T_cc** to HOLD; if **avg < T_cc**, treat the spread
as jitter and INCREASE instead. (b) is viable only if that rule **flips many f0 HOLD epochs** to
INCREASE (fixing under-growth) while **flipping few f8 HOLD epochs** (preserving the win).

**Method (no controller change).** PRISM runs at failed∈{0,8}, 2 MB many2many (the f0-cost
condition), seeds {13,14,15}, delay-driven, with `PRISM_PATHRTT`+`PRISM_EPOCH`. Per flow, bin per-ACK
`q = max(raw_rtt − base, 0)` into base_rtt-wide epochs; per epoch compute `avg`, `C_cc=min`,
`C_spray=max−min`; classify with `prism::decide_region` (`T_cc=T_spray=14.02 µs`). Report the **flip
fraction `P(avg < T_cc | HOLD)`** at f0 vs f8. (`discriminator.py`, with `--selftest`; reconstruction
cross-checked against the epoch log's own region column: recon HOLD f0 0.33 / f8 0.54 vs epoch-log
0.36 / 0.61 — faithful.)

**Result — proposal (b) REFUTED.**

| failed | HOLD epochs | avg(HOLD) mean / median | flip `P(avg<T_cc | HOLD)` | early / late |
|---|---|---|---|---|
| 0 (transient) | 2578 | 15.8 / 15.8 µs | **0.37** | 0.05 / 0.37 |
| 8 (structural) | 6397 | 17.9 / 16.0 µs | **0.40** | 0.30 / 0.42 |

Separation = 0.37 − 0.40 = **−0.03** (essentially zero, marginally backwards). The two avg-in-HOLD
CDFs nearly coincide and cross at `T_cc` (`figs/figP_avg_discriminator`). No avg threshold separates
them (the CDFs overlap everywhere).

**Why (b) fails.** The f0 transient is **broad startup congestion**, not a few sparse spikes: during
the startup epochs where PRISM wrongly HOLDs, *enough* paths are simultaneously elevated that the avg
is **above** target — just like f8. The early-half flip fraction at f0 is only **0.05**: avg is high
*exactly when* the harmful holding happens. So "avg high ⇒ real imbalance" misfires — both transient
and structural spread present a high avg. avg-vs-floor measures *congestion breadth*, but f0's
transient is broad too, so breadth does not distinguish transient from structural.

**Conclusion.** No instantaneous O(1) aggregate (floor `C_cc`, spread `C_spray`, or avg) separates the
f0-transient from the f8-structural HOLD: the only distinguishing feature is **which paths stay
congested over time** (rank persistence), which is inherently O(paths). This re-confirms — now via a
direct measurement of the proposed signal — that the symmetric cost is intrinsic to the O(1) design.
Proposal (a) (timer-reset on the spread) is already realized by the per-epoch reset (kappa was swept,
minor). The only remaining O(1) lever is a **blunt** one (a "HOLD-leak" growth-during-HOLD), which
trades the f0 recovery against a proportional erosion of the f8 win — it does not discriminate.

**Repro:** `bash probe.sh` (from `sim/datacenter`). Raw data gitignored; figure `git add -f`.
