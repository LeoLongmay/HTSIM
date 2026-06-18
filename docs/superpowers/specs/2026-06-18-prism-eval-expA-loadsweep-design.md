# Design: expA_delaydriven — ECMP+NSCC baseline + open-loop offered-load figure

**Date:** 2026-06-18
**Scope:** Enrich the existing `prism_eval/expA_delaydriven/` experiment group (1:1 non-blocking,
delay-driven / `-disable_trim` / 5×BDP) with (1) an **ECMP+NSCC** single-path baseline added to the
existing `-failed` performance sweep, and (2) a **new offered-load figure** that sweeps an open-loop
**Poisson** arrival process at a fixed asymmetry (`-failed 8`), giving the canonical "FCT vs offered
load" curve. Pure-evaluation work: **no change to PRISM controller code; O(1) decomposition unchanged.**

This is a single coherent plan over one folder. Deliverable ① is trivial (one baseline tuple + one run
line, renderer untouched). Deliverable ② is the substance (new generator + a small token-generalization
of the shared renderer + a new repro section + empirical calibration + docs).

---

## Background / current state (verified)

- **Binary:** `htsim_uec` = `main_uec.cpp`. LB modes parsed: `bitmap / reps / reps_legacy / freezing /
  oblivious / mixed / ecmp` (`ecmp` → `UecMpEcmp`, one static path per flow). CC modes:
  `dctcp / nscc / constant / prism / strack`. So **ECMP+NSCC needs zero code** — it is `LB=ecmp CC=nscc`,
  exactly parallel to the existing `ops` arm (`LB=oblivious CC=nscc`).
- **Harness:** `common/run_lib.sh CC LB FAILED TOPO SEED CM LOGSPEC TAG OUTDIR` (env `PATHS END_MS
  EXTRA_ARGS PRISM_EPOCH PRISM_PATHRTT NODES MTU`). One sim → decode once → extract text logs.
- **Renderer:** `common/perf_figs.py`. Sweep variable is a list (`failed`); files are named
  `{tag_prefix}_{label}_f{value}_s{seed}.flow.txt`. `aggregate()` keys results by that value;
  `render_main_perf_split()` emits 3 standalone panels (goodput Gbps, avg FCT ms, P99 FCT ms) vs the
  sweep variable, and already annotates any cell with completion-rate < 0.999 (saturation flag).
- **Workload generator:** `common/gen/many2many.py`. Current `.cm` is a **synchronized burst**: all flows
  `start 1000`, each transfers a fixed `size`, run to completion. Senders = hosts outside pod0; receivers
  = first `n_recv` hosts of pod0; `pairs` = round-robin. expA uses `64 -> 16`, 2 MB, `fat_tree_128_1os.topo`.
- **`.cm` start-time unit (DE-RISKED 2026-06-18):** the `-tm` connection-matrix loader interprets `start`
  as **picoseconds** — verified by a 2-probe test (`start 1000` → START at 1 ns; `start 1000000000` →
  1 ms; `start 8000000000` → 8 ms, with **no uint32 overflow** at the 8 ms window scale). `many2many.py`'s
  "picoseconds" comment is correct; the `timeFromUs(...)` call grepped earlier is a *different* code path,
  not the `-tm` loader. → The generator emits `start` in **picoseconds**; its human-facing `window_us`
  arg is converted ×1e6 to ps internally. (This inverts the original µs assumption — exactly what the
  de-risk step is for; the experiment's scientific design is unchanged, only the emitted time unit.)
- **`plot_style.COLORS`** currently has no `ecmp` key (ops=tab:gray, reps=tab:blue, strack=tab:orange,
  prism=tab:green). Must add one.

---

## Deliverable ① — ECMP+NSCC baseline in the existing `-failed` sweep

**What:** add the single-path anchor to the headline 1:1 delay-driven performance sweep.

- `common/plot_style.py`: add `"ecmp": "tab:purple"` to `COLORS` (distinct from ops=gray).
- `expA_delaydriven/make_figs.py`: append `("ecmp", "ECMP+NSCC", "ecmp")` to `BASELINES`.
- `expA_delaydriven/repro.sh`: in the main `-failed` sweep loop add one run per `(f,s)`:
  `PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" bash run_lib.sh nscc ecmp "$f" "$TOPO" "$s" "$CM" flow,sink "expA_ecmp_f${f}_s${s}" "$OUT"`.
- Re-render `figA1dd_{goodput,avg_fct,p99_fct}` and `figA1dd_fairness` (now 5 lines).
- **Not** added to the mechanism figure (`figA2dd_*`): signal decomposition only concerns
  REPS / STrack / PRISM. ECMP is a perf-sweep anchor, framed in the README as **context** ("ECMP/OPS
  bracket the spraying contribution; REPS/STrack are PRISM's real competition"), never the headline.

**Renderer impact:** none — `render_main_perf_split` / `render_fairness` iterate over `BASELINES`.

---

## Deliverable ② — open-loop offered-load figure (Poisson, fixed 2 MB, `-failed 8`)

### Offered-load definition

- Offered load **ρ** is defined relative to **aggregate receiver-access capacity**
  `C = n_recv × link_rate = 16 × 100 Gbps = 1.6 Tbps`. This is the **demand-side** reference: it is
  **independent of `-failed`**, so the ρ axis is clean and comparable across asymmetry levels.
- The x-axis is **offered** load (standard practice — plot offered, not achieved). Under `-failed 8`,
  *achieved* utilization is below ρ because the degraded core makes delivering 1.6 Tbps into pod0 harder
  — which is precisely the regime PRISM helps. The saturation knee therefore appears at ρ < 1.
- ρ sweep points: **{0.1, 0.3, 0.5, 0.7, 0.9}**, encoded in filenames as integer percent
  `{10,30,50,70,90}`.

### New generator `common/gen/poisson_load.py`

- **Inputs:** `out.cm n_send n_recv size nodes hpp rho window_us ref_gbps seed` (size fixed at
  2_000_000; ref_gbps = 1600; window_us = the measurement window W).
- **Sender/receiver sets:** identical construction to `many2many.py` (senders outside pod0; receivers =
  first `n_recv` pod0 hosts; round-robin `pairs`).
- **Arrivals:** Poisson process with rate `λ = ρ · ref_gbps·1e9 / (size·8)` flows/sec. Draw inter-arrival
  gaps `~ Exponential(λ)` (seeded), accumulate until exceeding `W`. Each arrival is assigned a
  `(src,dst)` pair (round-robin over the sender list → its paired receiver, so the spatial pattern matches
  the burst workload; a given src may originate several sequential/overlapping flows — realistic open loop).
- **Output:** `Nodes`, `Connections N`, then `src->dst start <ps> size <bytes>` lines sorted by start
  time; `start` is an **integer picoseconds ≥ 1** (never 0 — the t=0 START-event gotcha). Inter-arrivals
  and the window are computed in ps (`window_ps = window_us × 1e6`).
- **Determinism:** seeded RNG; same seed → identical `.cm`.
- **Selftest (`poisson_load.py --selftest`):** for a fixed seed, assert (a) the `.cm` parses (header
  counts match line count), (b) flow count is within a tolerance band of `λ·W`, (c) start times are
  monotonic non-decreasing and all in `[1, W]`, (d) every src is outside pod0 and every dst in `[0,n_recv)`.

### Calibration / validation (empirical, in repro.sh + README)

- ρ is *offered*; we **report achieved** alongside (goodput panel makes this visible: below saturation
  goodput tracks offered, then plateaus). No closed-form calibration is asserted — the generator emits a
  known offered λ and the figure shows the resulting goodput/FCT.
- **Window/END sizing:** `W = 8 ms`, `END_MS = 20 ms` (window + drain). At the lowest ρ=0.1,
  λ ≈ 0.1·1.6e12/1.6e7 = 10 000 flows/s → ≈ 80 flows/seed; × 5 seeds ≈ 400 samples (adequate for P99).
  At ρ=0.9 ≈ 720 flows/seed. Validate `cr` per cell; the renderer flags cr<1.
- **Cost:** 5 arms × 5 ρ × 5 seeds = **125 runs**. Short flows + sparse flow/sink logging → well under the
  3 GB budget; serial wall-clock ≈ 1–2 h (a few may run concurrently on the 8-core box).

### Renderer change (minimal, zero regression)

- Thread an **optional `token="f"` kwarg** through `aggregate()`, `render_main_perf_split()`,
  `render_main_perf()`, and `render_fairness()` so the filename sweep token is configurable. **Default
  `"f"` keeps every existing expA/expD figure byte-identical.**
- Load runs are tagged `expAload_{arm}_L{rho100}_s{seed}` and rendered via
  `render_main_perf_split(..., token="L")` with sweep list `[10,30,50,70,90]` and
  `xlabel="offered load (% of receiver-access capacity)"`.
- Output: 3 standalone panels `figA3dd_load_{goodput,avg_fct,p99_fct}`:
  - **goodput vs ρ** — saturation knee + delivered-throughput ceiling (PRISM's plateau higher under f8).
  - **avg / P99 FCT vs ρ** — latency blow-up; PRISM's advantage widens with ρ (mechanism: high load →
    deeper queues → reroutable spread appears → PRISM holds-and-reroutes while baselines cut).
- Extend `perf_figs.selftest()` to cover `token="L"` (synthetic `expAload_*_L50_*` files aggregate correctly).

### repro.sh additions

- A new section after the mechanism block: build per-ρ `.cm` files via `poisson_load.py` (seeded per
  `(rho,seed)` so each seed is an independent arrival realization), then loop
  `for rho in 10 30 50 70 90; do for s in SEEDS; do` over the 5 arms with `-failed 8`,
  `END_MS=20`, `EXTRA_ARGS="-disable_trim"`, TAG `expAload_{arm}_L${rho}_s${s}`.
- **Step 0 (de-risk), runs first:** a 2-flow probe (`start 1` and `start 1000`) decoded to confirm the
  µs interpretation and FINISH spacing before the full sweep is trusted; abort with a clear message on
  mismatch.

---

## Documentation / reproducibility

- `expA_delaydriven/README.md`: new subsection "Offered-load sweep + ECMP anchor" — ρ definition and
  denominator, the de-risked start-unit fact, real result table (goodput/FCT/cr per ρ for all 5 arms),
  and honest flagging of any cr<1 saturation cells. ECMP framed as context anchor.
- `NARRATIVE.md` §3: one sentence — "the win emerges as offered load rises: near-idle the fabric has no
  reroutable spread to decompose, so PRISM ties; as ρ→saturation under asymmetry the spread appears and
  PRISM's lead widens" — plus one Map row (`Eval (win, load) → expA_delaydriven/ figA3dd_load`).
- figs committed with `git add -f` (figs are gitignored at a higher level); `data/` stays gitignored;
  `repro.sh` remains one-command; deterministic seeds {13–17}; selftests gate the run.
- **No PRISM code touched.** Execution via subagent-driven development with two-stage review.

---

## Out of scope (YAGNI)

- Flow-size *distributions* / per-size slowdown binning (decided: fixed 2 MB).
- Load sweeps at other asymmetries (decided: `-failed 8` only); failed=0 contrast deferred.
- Normalized-slowdown panel (the 3 reused panels suffice; can add later if wanted).
- Buffer-depth and PATHS sweeps (separate future work discussed but not chosen here).
