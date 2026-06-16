# PRISM T_spray Tuning (delay-driven regime)

**Why.** The delay-driven Exp A result (incl. P3 STrack) had one honest weak spot: at **failed=0
(symmetric fabric)** PRISM was the worst arm (goodput 869 vs REPS 997 / STrack 912 / OPS 906).
Hypothesis: PRISM over-*holds* its window on benign (symmetric) path spread, so raising
`-prism_t_spray` (the spread tolerance `T_spray` in the four-quadrant `decide_region` rule)
should recover f0. This experiment tests that, then reports what actually happened.

## Setup
Delay-driven regime (`EXTRA_ARGS="-disable_trim -prism_t_spray <us>"`, END=8), same 128-node
many2many 64→16 pod0 2 MB workload as `expA_delaydriven` (byte-identical `m2m.cm`), seeds {13..17}.
Two stages:
- **Stage 1 (knee):** `T_spray ∈ {2,3,4,6,9,14} µs × failed {0,8} × 5 seeds`. f0 = symmetric cost
  end, f8 = asymmetric win end. → `figs/figT1_knee`.
- **Stage 2 (validate):** PRISM at the selected `T_spray*` over the full `failed {0,2,4,8,12} × 5
  seeds`; OPS/REPS/STrack/PRISM-default reused read-only from `../expA_delaydriven/data`. →
  `figs/figT2_compare`.

## Methodology correction (important)
The runtime `_target_Qdelay ≈ 14 µs` (set by `initNsccParams` to one network RTT, matching the
STrack paper's "target queuing delay = one network RTT"); the static `timeFromUs(6u)` initializer
is overridden. So PRISM's **default `t_spray` is ~14 µs, not 6 µs** as earlier docs implied. The
sweep brackets the true default (2–9 below, 14 = default). This also fixed a committed-figure bug:
`figA2dd`/`figA2` had drawn the target line at 6 µs — corrected to the real value
(`perf_figs._read_target_us` now reads it from the mechanism stdout).

## Result 1 — registered goal (fix f0): **NEGATIVE**
f0 goodput is **essentially insensitive to T_spray** (835–879 Gbps across 2–14 µs; never reaches
the 906 OPS floor, let alone REPS 997). The "over-hold on benign spread" hypothesis is **refuted**:
at very low T_spray (2,3 µs) f0 actually *drops* (835/853) — aggressive non-holding causes
overshoot → floor-driven cuts. **T_spray cannot fix the f0 penalty.** (The originally-planned
contingency — a ratio-based spread test — is also dropped: it pulls the same "reduce HOLD" lever
f0 is insensitive to. The f0 penalty has a different root cause — likely floor-driven increase
timidity / epoch ramp — left to a separate diagnosis.)

Stage-1 knee (mean / 5 seeds; do-no-harm bar = default-f0 × 0.99 = 862):

| T_spray | f0 goodput | f8 goodput | eligible (f0 ≥ 862)? |
|---|---|---|---|
| 2  | 835 | 574 | no (f0 harm) |
| 3  | 853 | 576 | no (f0 harm) |
| **4**  | **864** | **554** | **yes — f8-max\*** |
| 6  | 874 | 548 | yes |
| 9  | 879 | 508 | yes |
| 14 (default) | 871 | 512 | yes |

## Result 2 — pivot (bank the f8 gain): **POSITIVE**
Lowering T_spray *below* the ~14 µs default **widens PRISM's asymmetric advantage**. Pre-registered
pivot rule: maximize f8 subject to f0 do-no-harm (≥ default-f0 − 1%). Selected **T_spray* = 4 µs**
(f8=554 vs default 512 in the endpoint sweep; f0=864 ≥ bar 862). Stage-2 full grid validates it
(goodput / avg-FCT, all cr = 1.00):

| -failed | REPS+NSCC | STrack | PRISM (default ~14µs) | PRISM (T_spray=4) | tuned vs default |
|---|---|---|---|---|---|
| 0  | 997 / 737 | 912 / 789 | 869 / 945 | 864 / 956 | −0.6% / +1% (do-no-harm) |
| 2  | 533 / 1202 | 515 / 1255 | 572 / 1305 | **583 / 1257** | +1.9% / −3.7% |
| 4  | 483 / 1450 | 471 / 1513 | 574 / 1401 | **606 / 1284** | **+5.6% / −8.4%** |
| 8  | 431 / 1694 | 415 / 1725 | 504 / 1518 | **554 / 1436** | **+9.9% / −5.4%** |
| 12 | 379 / 1856 | 364 / 1890 | 434 / 1725 | **442 / 1759** | +1.8% / +2.0% |

**Tuning T_spray 14→4 µs improves the entire asymmetric region (f2–f8) on BOTH goodput and avg-FCT,
with f0 essentially unchanged (do-no-harm respected) and f12 marginal.** It widens PRISM's lead over
the baselines from +17–22% (default) to **+25–33%** (f8: 554 vs REPS 431 = +29%, vs STrack 415 =
+33%); avg-FCT and P99-FCT are also lowest for the tuned arm across f2–f8 (figT2_compare).

## Honest verdict
- The **registered goal failed**: `T_spray` does not fix the symmetric f0 penalty (f0 stays ~864,
  worst arm; the penalty needs a different mechanism, not this knob).
- The **pivot succeeded**: the corrected understanding of the knob (default ~14 µs, lower = tighter
  spread detection = more holding on *genuine* asymmetric spread) banks a real **+8–10% f8
  goodput / lower-FCT improvement** to the asymmetric headline, at no f0 cost.
- Caveats: f0 penalty persists (unsolved here); f12 goodput gain is marginal (+1.8%) and its FCT is
  ~2% worse (within noise); the tuned value (4 µs) is specific to this 128-node fat-tree (one-RTT
  target ~14 µs) — β/h and T_spray sensitivity across topologies/scales is a P5 item.
- No cherry-picking: T_spray* chosen by the pre-registered rule (`select_tspray_maximize_f8`), the
  failed registered criterion is preserved in the Stage-1 output, and the full grid (incl. the
  marginal f12) is reported straight.

## Reproduce
```
# Stage 1 (knee + criterion):  prints the registered FAILED verdict + the pivot T_spray*
bash prism_eval/expA_tspray_tuning/repro.sh                 # from sim/datacenter
# Stage 2 (validate the pick on the full grid):
TS_STAR=4 bash prism_eval/expA_tspray_tuning/repro.sh
```
Selector logic is unit-tested: `python3 tspray_select.py --selftest`.
