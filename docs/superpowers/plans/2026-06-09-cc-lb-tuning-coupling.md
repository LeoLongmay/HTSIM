# figI — Uncoordinated CC+Spraying Tuning Is Suboptimal — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce figI proving that with spraying fixed ON (REPS), the optimal NSCC `target_q_delay` *flips* between a spray-removable regime (A) and a path-wide regime (B), so any single independently-tuned CC setting is off-optimum in one regime.

**Architecture:** Pure-logging htsim runs (no C++ change). Sweep `target_q_delay ∈ {2,4,6,8,12,16}µs` under REPS for two scenarios; Regime A measured by aggregate goodput (`-log sink`), Regime B by p99 bottleneck-queue latency (`-log tor_downqueue`). Each regime's (C_spray, C_cc) is measured once via the existing pathrtt machinery to prove its shape. A new `make_coupling_fig.py` renders the 2-panel figI. Front-loaded de-risk scout confirms the flip before 5-seed production.

**Tech Stack:** htsim_uec + parse_output (already built), bash wrappers (`run_meas.sh`, `run_one.sh`), python3 + matplotlib, existing `pathrtt_analyze.py`.

**Working directory for all commands:** `/home/leo/htsim/htsim/sim/datacenter`

---

### Task 1: Add optional `TQD` (target_q_delay) to `run_meas.sh`

`run_meas.sh` currently has no way to pass `target_q_delay`. Mirror the exact pattern already in `run_one.sh` so figG/figH calls stay byte-identical (TQD unset → flag absent → binary default 6µs).

**Files:**
- Modify: `mvp_runs3/run_meas.sh`

- [ ] **Step 1: Add the TQD_ARG variable**

In `mvp_runs3/run_meas.sh`, after the line `SEED="${SEED:-13}"; END="${END:-2}"; LOGTIME="${LOGTIME:-2}"`, add:

```bash
TQD_ARG=""           # NSCC target_q_delay (us); only passed when TQD env is set (default = binary's 6us)
[ -n "${TQD:-}" ] && TQD_ARG="-target_q_delay ${TQD}"
```

- [ ] **Step 2: Pass the flag to htsim**

In the `./htsim_uec ...` invocation, change the line containing `-paths "$PATHS" -seed "$SEED" $LOGARGS` to insert `$TQD_ARG` right after the seed:

```bash
    -paths 8 -seed "$SEED" $TQD_ARG $LOGARGS -logtime_us "$LOGTIME" -end "$END" \
```

(Note: `-paths` is hard-coded to 8 in `run_meas.sh`; keep it.)

- [ ] **Step 3: Echo TQD when set (for log traceability)**

Change the `echo "[meas] ...` line to append `${TQD:+ tqd=$TQD}`:

```bash
echo "[meas] lb=$LB failed=$FAILED tag=$TAG cm=$CM log=$LOGSPEC seed=$SEED end=$END logtime=${LOGTIME}us${TQD:+ tqd=$TQD}"
```

- [ ] **Step 4: Verify TQD actually reaches the binary**

Run (a 1ms smoke at the most aggressive setting, sink log):

```bash
cd /home/leo/htsim/htsim/sim/datacenter
python3 mvp_runs3/gen_incast.py mvp_runs3/_tqdcheck.cm 16 0 20000000 128 16
SEED=13 END=1 TQD=2 bash mvp_runs3/run_meas.sh reps 0 _tqdcheck mvp_runs3/_tqdcheck.cm sink
grep -i 'target_Qdelay\|target_q' mvp_runs3/_tqdcheck.stdout | head -2
```

Expected: the NSCC init line shows a `_target_Qdelay` consistent with 2µs (it prints in ps; 2µs ≈ 2.1e6 after scaling — the value must DIFFER from a TQD=16 run). Confirm by diffing:

```bash
SEED=13 END=1 TQD=16 bash mvp_runs3/run_meas.sh reps 0 _tqdcheck16 mvp_runs3/_tqdcheck.cm sink
grep -o '_target_Qdelay=[0-9]*' mvp_runs3/_tqdcheck.stdout mvp_runs3/_tqdcheck16.stdout
```

Expected: the two `_target_Qdelay=` values are DIFFERENT (proves TQD is wired). If identical → TQD not reaching binary; fix Step 2 before continuing.

- [ ] **Step 5: Clean smoke artifacts and commit**

```bash
rm -f mvp_runs3/_tqdcheck*.cm mvp_runs3/_tqdcheck*.sink.txt mvp_runs3/_tqdcheck*.stdout mvp_runs3/_tqdcheck*.idmap mvp_runs3/_tqdcheck*.q.txt
git -C /home/leo/htsim add htsim/sim/datacenter/mvp_runs3/run_meas.sh
git -C /home/leo/htsim commit -m "run_meas.sh: add optional TQD (target_q_delay) env, mirroring run_one.sh"
```

---

### Task 2: De-risk scout — pick Regime A load and CONFIRM the optimum flips (GATE)

This is the critical gate from spec §7. Do NOT proceed to production until the flip is confirmed. 1 seed (13) only.

**Files:**
- Create (data, gitignored): `mvp_runs3/overload_cpA.cm`, `mvp_runs3/incast_cpB.cm`, scout outputs.

- [ ] **Step 1: Generate candidate traffic matrices**

Regime B is a strong single-receiver incast (high floor). Regime A candidates are asymmetric whole-pod overloads at 3 load levels (8/16/24 senders → 16 dests).

```bash
cd /home/leo/htsim/htsim/sim/datacenter
python3 mvp_runs3/gen_incast.py   mvp_runs3/incast_cpB.cm  64 0 20000000 128 16
for na in 8 16 24; do python3 mvp_runs3/gen_overload.py mvp_runs3/overload_cpA_$na.cm $na 0 16; done
```

- [ ] **Step 2: Measure C_spray/C_cc for each Regime A candidate (default CC) and Regime B**

Use `run_one.sh` (it logs pathrtt). Regime A = failed 12; Regime B = failed 0.

```bash
for na in 8 16 24; do SEED=13 END=2 bash mvp_runs3/run_one.sh reps 12 scpA_$na mvp_runs3/overload_cpA_$na.cm; done
SEED=13 END=2 bash mvp_runs3/run_one.sh reps 0 scpB mvp_runs3/incast_cpB.cm
```

- [ ] **Step 3: Print the decomposition; pick NA where C_cc is smallest relative to C_spray**

```bash
python3 - <<'PY'
import sys; sys.path.insert(0,"mvp_runs3")
import pathrtt_analyze as A
BPROP=13945.0   # uncontended propagation floor (ns), topology constant (= min raw RTT of N=1 run)
def decomp(tag):
    rows=A.parse_csv(f"mvp_runs3/{tag}.pathrtt.csv")
    g=A.aggregate_rows(rows, min_samples=200, baseline="const", const_base=BPROP)
    return g
for na in [8,16,24]:
    g=decomp(f"scpA_{na}")
    if g: print(f"RegimeA na={na}: C_spray={g['cspray_med']:.2f}us C_cc={g['ccc_med']:.2f}us nflows={g['nflows']}")
g=decomp("scpB")
if g: print(f"RegimeB incast64: C_spray={g['cspray_med']:.2f}us C_cc={g['ccc_med']:.2f}us nflows={g['nflows']}")
PY
```

Expected/decision: pick the Regime-A `na` with **C_spray clearly > C_cc and C_cc small** (the cleanest "spray-removable, low floor"). Record it as **NA**. Regime B must show **C_cc clearly > C_spray**. If no `na` gives C_spray>C_cc, widen candidates (4, 32) or report to the user — do not force.

- [ ] **Step 4: Scout the CC sweep in BOTH regimes (1 seed), check the flip**

Use the chosen NA (example assumes NA=16; substitute the value picked in Step 3). Regime A → goodput (sink); Regime B → queue.

```bash
cp mvp_runs3/overload_cpA_16.cm mvp_runs3/overload_cpA.cm   # substitute NA
for q in 2 4 6 8 12 16; do
  SEED=13 END=2 TQD=$q bash mvp_runs3/run_meas.sh reps 12 scA_tqd$q mvp_runs3/overload_cpA.cm sink
  SEED=13 END=2 TQD=$q LOGTIME=1 bash mvp_runs3/run_meas.sh reps 0 scB_tqd$q mvp_runs3/incast_cpB.cm queue
done
```

- [ ] **Step 5: Compute the two curves and verify opposite-end optima**

```bash
python3 - <<'PY'
import collections, statistics as st
TQD=[2,4,6,8,12,16]; WIN=(0.5e-3,1.5e-3)
def goodput(tag):
    bt=collections.defaultdict(float)
    for ln in open(f"mvp_runs3/{tag}.sink.txt"):
        p=ln.split()
        if len(p)>=13: bt[float(p[0])]+=float(p[12])
    tail=[v/1e9 for t,v in bt.items() if WIN[0]<=t<=WIN[1]]
    return st.mean(tail) if tail else 0
def qid_LS0DST0(tag):
    for ln in open(f"mvp_runs3/{tag}.idmap"):
        ps=ln.split(None,1)
        if len(ps)==2 and ps[1].strip().startswith("LS0->DST0"): return int(ps[0])
def p99lat(tag):
    q=qid_LS0DST0(tag); v=[]
    for ln in open(f"mvp_runs3/{tag}.q.txt"):
        p=ln.split()
        if len(p)>=9 and int(p[4])==q:
            t=float(p[0])*1e6
            if 500<=t<=1500: v.append(int(p[8])*8e-5)
    v.sort(); return v[min(len(v)-1,int(0.99*len(v)))] if v else 0
gA=[goodput(f"scA_tqd{q}") for q in TQD]
lB=[p99lat(f"scB_tqd{q}") for q in TQD]
print("RegimeA goodput(Gbps) vs tqd:", [f"{q}:{g:.1f}" for q,g in zip(TQD,gA)])
print("RegimeB p99 lat(us)  vs tqd:", [f"{q}:{l:.1f}" for q,l in zip(TQD,lB)])
print("A argmax tqd =", TQD[gA.index(max(gA))], "(want LENIENT end, >=8)")
print("B argmin tqd =", TQD[lB.index(min(lB))], "(want AGGRESSIVE end, <=4)")
PY
```

**GATE — proceed only if:** Regime A goodput is maximized at a *lenient* setting (argmax `target_q_delay` ≥ 8) AND Regime B p99 latency is minimized at an *aggressive* setting (argmin ≤ 4), i.e. the optima sit at opposite ends. If not:
- If A's goodput is flat/insensitive → load NA too low; bump NA and re-scout Step 3–5.
- If B's latency is flat → incast not stressing floor; raise incast senders (96/112).
- If still no flip after these adjustments → STOP and report honestly to the user (per spec §7); do not fabricate.

- [ ] **Step 6: Record the chosen NA and incast size, commit nothing yet (scout data is gitignored)**

Write the chosen values into a short note for later tasks:

```bash
echo "NA=<chosen> incastB=64  # figI regime params, from Task 2 scout" > mvp_runs3/_figI_params.txt
cat mvp_runs3/_figI_params.txt
```

(`_figI_params.txt` matches no gitignore pattern but is a scratch note; it will be removed in Task 7. The authoritative values live in `repro.sh` once Task 7 wires them in.)

---

### Task 3: `make_coupling_fig.py` — parsing functions with self-checks

Build the two metric parsers with inline assert-based self-checks (same no-pytest style as `test_pathrtt_analyze.py`), so the figure is built on verified parsing.

**Files:**
- Create: `mvp_runs3/make_coupling_fig.py`

- [ ] **Step 1: Create the file with parsers + a `__selftest__` block**

```python
#!/usr/bin/env python3
"""figI -- uncoordinated CC+spraying tuning is suboptimal (optimum-flip).

Spraying fixed ON (REPS). Sweep NSCC target_q_delay; the optimal setting flips between:
  Regime A (spray-removable, high C_spray / ~0 C_cc): metric = aggregate goodput (Gbps);
            lenient CC wins (aggressive CC needlessly throttles -> underutilization).
  Regime B (path-wide, high C_cc / ~0 C_spray):        metric = MEAN bottleneck-queue latency (us);
            aggressive CC wins (lenient CC lets the floor balloon; goodput is capped).
            (MEAN not p99: NSCC trims to bound the queue, so the tail is pinned at the buffer
             ceiling regardless of CC; the mean tracks the sustained floor = what C_cc measures.)
No single fixed target_q_delay is optimal in both -> CC must coordinate with the regime
the LB produces. Reads mvp_runs3/cp{A,B}_tqd{Q}.s{S}.{sink.txt,q.txt,idmap}. Run:
  python3 make_coupling_fig.py            # render figI
  python3 make_coupling_fig.py --selftest # run parser self-checks
"""
import os, sys, collections, statistics as st
HERE = os.path.dirname(os.path.abspath(__file__))
TQD = [2, 4, 6, 8, 12, 16]
SEEDS = [13, 14, 15, 16, 17]
WIN_S = (0.5e-3, 1.5e-3)      # steady window, seconds (sink timestamps)
WIN_US = (500.0, 1500.0)      # steady window, microseconds (queue timestamps)
BYTES_TO_US = 8e-5            # 1 byte @100Gbps queueing delay
DEFAULT_TQD = 6              # the "independently chosen" default

def goodput_gbps(tag):
    """Steady-window aggregate goodput (Gbps) = sum of UEC_SINK Rate (bits/s)."""
    bt = collections.defaultdict(float)
    with open(os.path.join(HERE, f"{tag}.sink.txt")) as fh:
        for ln in fh:
            p = ln.split()
            if len(p) >= 13:
                bt[float(p[0])] += float(p[12])
    tail = [v / 1e9 for t, v in bt.items() if WIN_S[0] <= t <= WIN_S[1]]
    return st.mean(tail) if tail else 0.0

def _qid_ls0dst0(tag):
    """Resolve the receiver bottleneck downqueue (LS0->DST0) id from the run's idmap."""
    with open(os.path.join(HERE, f"{tag}.idmap")) as fh:
        for ln in fh:
            ps = ln.split(None, 1)
            if len(ps) == 2 and ps[1].strip().startswith("LS0->DST0"):
                return int(ps[0])
    return None

def mean_latency_us(tag):
    """Steady-window MEAN queueing latency (us) at the receiver bottleneck.

    MEAN, not p99: NSCC trims to bound the queue, so the tail (p99/p90) is pinned at the
    buffer ceiling regardless of CC aggressiveness; the MEAN tracks the sustained floor,
    which is exactly what C_cc represents and what a lenient CC inflates.
    """
    qid = _qid_ls0dst0(tag)
    vals = []
    with open(os.path.join(HERE, f"{tag}.q.txt")) as fh:
        for ln in fh:
            p = ln.split()
            if len(p) >= 9 and int(p[4]) == qid:
                t_us = float(p[0]) * 1e6
                if WIN_US[0] <= t_us <= WIN_US[1]:
                    vals.append(int(p[8]) * BYTES_TO_US)
    return st.mean(vals) if vals else 0.0

def _selftest():
    import tempfile
    # goodput: two receivers, steady within window -> sum/mean
    d = tempfile.mkdtemp()
    global HERE; HERE = d
    with open(os.path.join(d, "_g.sink.txt"), "w") as f:
        # t Type UEC_SINK ID id Ev RATE CAck n ReorderBuffer n Rate bits ; t in window 0.6/1.0 ms
        for t in ("0.000600000", "0.001000000"):
            f.write(f"{t} Type UEC_SINK ID 10 Ev RATE CAck 1 ReorderBuffer 0 Rate 40000000000\n")
            f.write(f"{t} Type UEC_SINK ID 11 Ev RATE CAck 1 ReorderBuffer 0 Rate 10000000000\n")
    assert abs(goodput_gbps("_g") - 50.0) < 1e-9, goodput_gbps("_g")
    # mean latency: idmap maps qid 164 -> LS0->DST0; q.txt LastQ bytes in window
    with open(os.path.join(d, "_p.idmap"), "w") as f:
        f.write("164 LS0->DST0(0)\n165 LS0->DST1(0)\n")
    with open(os.path.join(d, "_p.q.txt"), "w") as f:
        # 3 in-window samples on qid 164: 1000,2000,3000 bytes -> 0.08,0.16,0.24 us -> mean 0.16
        f.write("0.000600000 Type QUEUE_APPROX ID 164 Ev RANGE LastQ 1000 MinQ 0 MaxQ 0\n")
        f.write("0.000700000 Type QUEUE_APPROX ID 164 Ev RANGE LastQ 2000 MinQ 0 MaxQ 0\n")
        f.write("0.000800000 Type QUEUE_APPROX ID 164 Ev RANGE LastQ 3000 MinQ 0 MaxQ 0\n")
        f.write("0.000650000 Type QUEUE_APPROX ID 165 Ev RANGE LastQ 999999 MinQ 0 MaxQ 0\n")  # other queue ignored
    got = mean_latency_us("_p")
    assert abs(got - 0.16) < 1e-9, got
    print("ok goodput_gbps + mean_latency_us")

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
```

- [ ] **Step 2: Run the self-test, expect PASS**

```bash
cd /home/leo/htsim/htsim/sim/datacenter
python3 mvp_runs3/make_coupling_fig.py --selftest
```

Expected: `ok goodput_gbps + p99_latency_us` (no AssertionError).

- [ ] **Step 3: Commit the parsers**

```bash
git -C /home/leo/htsim add htsim/sim/datacenter/mvp_runs3/make_coupling_fig.py
git -C /home/leo/htsim commit -m "make_coupling_fig.py: goodput + p99-latency parsers with self-checks"
```

---

### Task 4: `make_coupling_fig.py` — render the 2-panel figI

**Files:**
- Modify: `mvp_runs3/make_coupling_fig.py`

- [ ] **Step 1: Add the across-seeds aggregation + decomposition annotation helpers**

Insert before `if __name__ == "__main__":`:

```python
def across_seeds(fn, prefix):
    """(means, stds) over seeds for each target_q_delay; tags = {prefix}_tqd{Q}.s{S}."""
    means, stds = [], []
    for q in TQD:
        vals = [fn(f"{prefix}_tqd{q}.s{s}") for s in SEEDS]
        means.append(st.mean(vals))
        stds.append(st.stdev(vals) if len(vals) > 1 else 0.0)
    return means, stds

def decomp(tag):
    """(C_spray, C_cc) in us for a pathrtt run, const baseline. None if unavailable.

    Uses the WIDE (1000,7000)us window (decomp runs are END=8) so enough in-window ACKs
    pass the sample gate; falls back to a relaxed gate if the strict one yields nothing.
    """
    sys.path.insert(0, HERE)
    import pathrtt_analyze as A
    BPROP = 13945.0   # uncontended propagation floor (ns); topology constant (min raw RTT of N=1 run)
    csv = os.path.join(HERE, f"{tag}.pathrtt.csv")
    if not os.path.exists(csv):
        return None
    rows = A.parse_csv(csv)
    for ms in (200, 100, 50):
        g = A.aggregate_rows(rows, min_samples=ms, baseline="const", const_base=BPROP, win=(1000.0, 7000.0))
        if g:
            return (g["cspray_med"], g["ccc_med"])
    return None
```

- [ ] **Step 2: Add the figure renderer**

Insert the `render()` function before `if __name__ == "__main__":`:

```python
def render():
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    gm, gs = across_seeds(goodput_gbps, "cpA")        # Regime A goodput
    lm, ls = across_seeds(mean_latency_us, "cpB")     # Regime B mean queue latency
    dA, dB = decomp("cpA_decomp"), decomp("cpB_decomp")
    qA_best = TQD[gm.index(max(gm))]                  # lenient end expected
    qB_best = TQD[lm.index(min(lm))]                  # aggressive end expected

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7, 7.6), sharex=True)
    # Panel A
    ax1.errorbar(TQD, gm, yerr=gs, marker='o', lw=2, capsize=3, color='tab:green')
    ax1.axvline(DEFAULT_TQD, color='gray', ls='--', lw=1)
    ax1.scatter([qA_best], [max(gm)], s=130, facecolors='none', edgecolors='tab:green', zorder=5)
    ax1.annotate("optimum: LENIENT CC", xy=(qA_best, max(gm)), xytext=(qA_best-3.5, max(gm)),
                 fontsize=8.5, va='center', ha='right')
    ax1.annotate("default 6us", xy=(DEFAULT_TQD, min(gm)), fontsize=8, color='gray', rotation=90, va='bottom')
    annA = f"Regime A (spray-removable)\nmeasured C_spray={dA[0]:.1f} ≫ C_cc={dA[1]:.1f} us" if dA else "Regime A (spray-removable)"
    ax1.set_title(annA, fontsize=9)
    ax1.set_ylabel("aggregate goodput (Gbps)\n↑ better"); ax1.grid(alpha=0.3)
    ax1.fill_between(TQD, gm, max(gm), color='tab:red', alpha=0.10)
    # Panel B
    ax2.errorbar(TQD, lm, yerr=ls, marker='s', lw=2, capsize=3, color='tab:purple')
    ax2.axvline(DEFAULT_TQD, color='gray', ls='--', lw=1)
    ax2.scatter([qB_best], [min(lm)], s=130, facecolors='none', edgecolors='tab:purple', zorder=5)
    ax2.annotate("optimum: AGGRESSIVE CC", xy=(qB_best, min(lm)), xytext=(qB_best+0.5, min(lm)),
                 fontsize=8.5, va='center', ha='left')
    annB = f"Regime B (path-wide)\nmeasured C_cc={dB[1]:.1f} ≫ C_spray={dB[0]:.1f} us" if dB else "Regime B (path-wide)"
    ax2.set_title(annB, fontsize=9)
    ax2.set_ylabel("mean queue latency (us)\n↓ better"); ax2.grid(alpha=0.3)
    ax2.fill_between(TQD, lm, max(lm), color='tab:red', alpha=0.10)
    ax2.set_xlabel("CC aggressiveness  —  NSCC target_q_delay (us)   [left = aggressive, right = lenient]")
    ax2.set_xticks(TQD)
    fig.suptitle("figI: CC and spraying tuned independently can't win both regimes\n"
                 "REPS fixed ON; optimal CC flips ends -> the fixed default is off-optimum in BOTH",
                 fontsize=10.5)
    plt.tight_layout(rect=(0, 0, 1, 0.96))
    plt.savefig(os.path.join(HERE, "figI_cc_lb_tuning_coupled.png"), dpi=140); plt.close()
    print("figI: RegimeA goodput vs tqd =", [round(x,1) for x in gm], "argmax tqd", qA_best)
    print("figI: RegimeB mean-lat vs tqd =", [round(x,1) for x in lm], "argmin tqd", qB_best)
    print("figI: decomp A", dA, " B", dB)
```

- [ ] **Step 3: Wire `render()` into `__main__`**

Change the `if __name__ == "__main__":` block to:

```python
if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        render()
```

- [ ] **Step 4: Commit (cannot render yet — no production data; that's Task 5/6)**

```bash
git -C /home/leo/htsim add htsim/sim/datacenter/mvp_runs3/make_coupling_fig.py
git -C /home/leo/htsim commit -m "make_coupling_fig.py: 2-panel figI renderer + decomposition annotations"
```

---

### Task 5: Production runs (5 seeds) + decomposition runs

Uses the NA chosen in Task 2. Substitute the real NA value (this plan shows the commands; the `overload_cpA.cm` written in Task 2 Step 6 already encodes NA).

**Files:**
- Create (data, gitignored): `mvp_runs3/cpA_tqd{Q}.s{S}.sink.txt`, `mvp_runs3/cpB_tqd{Q}.s{S}.q.txt`, `mvp_runs3/cp{A,B}_decomp.pathrtt.csv`.

- [ ] **Step 0: Regenerate the locked traffic matrices (scout-chosen params: NA=8, Regime B = 32-sender incast)**

```bash
cd /home/leo/htsim/htsim/sim/datacenter
python3 mvp_runs3/gen_overload.py mvp_runs3/overload_cpA.cm 8  0 16                 # Regime A: NA=8 (spray-removable)
python3 mvp_runs3/gen_incast.py   mvp_runs3/incast_cpB.cm  32 0 20000000 128 16     # Regime B: 32-sender path-wide incast
```

- [ ] **Step 1: Regime A production — goodput, 6 tqd × 5 seeds (30 runs)**

```bash
for q in 2 4 6 8 12 16; do for s in 13 14 15 16 17; do
  SEED=$s END=2 TQD=$q bash mvp_runs3/run_meas.sh reps 12 cpA_tqd$q.s$s mvp_runs3/overload_cpA.cm sink
done; done
echo "RegimeA sink files: $(ls mvp_runs3/cpA_tqd*.sink.txt | wc -l)  (expect 30)"
```

- [ ] **Step 2: Regime B production — p99 latency, 6 tqd × 5 seeds (30 runs)**

```bash
for q in 2 4 6 8 12 16; do for s in 13 14 15 16 17; do
  SEED=$s END=2 TQD=$q LOGTIME=1 bash mvp_runs3/run_meas.sh reps 0 cpB_tqd$q.s$s mvp_runs3/incast_cpB.cm queue
done; done
echo "RegimeB q files: $(ls mvp_runs3/cpB_tqd*.q.txt | wc -l)  (expect 30)"
```

- [ ] **Step 3: Decomposition runs (default CC, 1 seed each, END=8 for enough in-window ACKs)**

These use `END=8` so the wide `(1000,7000)µs` decomposition window has ≥200 ACKs/flow (a 1ms window at END=2 fails the gate). The decomposition is a steady-state property, so the longer run is fine; flows stay backlogged (20MB ≫ delivered in 8ms).

```bash
SEED=13 END=8 bash mvp_runs3/run_one.sh reps 12 cpA_decomp mvp_runs3/overload_cpA.cm
SEED=13 END=8 bash mvp_runs3/run_one.sh reps 0  cpB_decomp mvp_runs3/incast_cpB.cm
ls mvp_runs3/cpA_decomp.pathrtt.csv mvp_runs3/cpB_decomp.pathrtt.csv
```

(No commit — all outputs are gitignored raw data.)

---

### Task 6: Render figI and validate success criteria

**Files:**
- Create: `mvp_runs3/figI_cc_lb_tuning_coupled.png`

- [ ] **Step 1: Render**

```bash
cd /home/leo/htsim/htsim/sim/datacenter
python3 mvp_runs3/make_coupling_fig.py
```

Expected stdout: RegimeA argmax tqd ≥ 8 (lenient), RegimeB argmin tqd ≤ 4 (aggressive), decomp A shows C_spray≫C_cc, decomp B shows C_cc≫C_spray.

- [ ] **Step 2: Visually inspect the figure**

Open `mvp_runs3/figI_cc_lb_tuning_coupled.png` (or Read it). Confirm: panel A goodput rises toward the lenient (right) end with the optimum circled there; panel B mean latency rises toward the lenient end with the minimum circled at the aggressive (left) end; the dashed 6µs line sits visibly off-optimum in both; regime annotations present.

- [ ] **Step 3: Validate the success criteria (spec §9)**

Confirm against the spec:
- Optima at opposite ends of the `target_q_delay` axis (argmax_A ≥ 8, argmin_B ≤ 4).
- Default 6µs is off-optimum in both panels (error bars do not straddle the optimum, or the gap is clearly visible).
- Decomp A has C_spray > C_cc; Decomp B has C_cc > C_spray.

If any criterion fails, STOP and report honestly (do not adjust the figure to hide it). Otherwise continue.

---

### Task 7: Wire into repro.sh + README, gitignore check, commit figI

**Files:**
- Modify: `mvp_runs3/repro.sh`
- Modify: `mvp_runs3/README_repro.md`
- Verify: `mvp_runs3/.gitignore` (should already cover `*.sink.txt`/`*.q.txt`/`*.idmap`/`*.csv`/`*.cm`/`*.dat`/`*.png`)

- [ ] **Step 1: Add step 9 to repro.sh**

In `mvp_runs3/repro.sh`, after the figures block (the `python3 mvp_runs3/make_cc_figs.py` line and its `echo`), insert (substitute NA with the value chosen in Task 2):

```bash
echo "== 9. CC/LB tuning-coupling (REPS fixed; sweep target_q_delay) for figI, seeds $SEEDS =="
python3 mvp_runs3/gen_overload.py mvp_runs3/overload_cpA.cm 8  0 16                 # Regime A: spray-removable, NA=8
python3 mvp_runs3/gen_incast.py   mvp_runs3/incast_cpB.cm   32 0 20000000 128 16    # Regime B: path-wide 32-sender incast
for q in 2 4 6 8 12 16; do for s in $SEEDS; do
  SEED=$s END=2 TQD=$q          bash mvp_runs3/run_meas.sh reps 12 cpA_tqd$q.s$s mvp_runs3/overload_cpA.cm sink
  SEED=$s END=2 TQD=$q LOGTIME=1 bash mvp_runs3/run_meas.sh reps 0  cpB_tqd$q.s$s mvp_runs3/incast_cpB.cm  queue
done; done
SEED=13 END=8 bash mvp_runs3/run_one.sh reps 12 cpA_decomp mvp_runs3/overload_cpA.cm
SEED=13 END=8 bash mvp_runs3/run_one.sh reps 0  cpB_decomp mvp_runs3/incast_cpB.cm
python3 mvp_runs3/make_coupling_fig.py
echo "==       figI_cc_lb_tuning_coupled.png =="
```

- [ ] **Step 2: Add the figI section to README_repro.md**

In `mvp_runs3/README_repro.md`, after the figG/figH bullets (before the scope paragraph beginning `**作用域(必须在论文里写清)**`), add:

```markdown
**——第三条腿:即使两者都开,但独立调优(各自为战)仍次优——**(`make_coupling_fig.py`,REPS 固定 ON,扫 NSCC `target_q_delay`)

- **figI(调优耦合)**:两面板,横轴 = `target_q_delay`(左激进/右宽松)。上=**Regime A(可换路消除,实测 C_spray≫C_cc)**的 goodput:**宽松端最优**(过激进 CC 无谓降速→利用率不足);下=**Regime B(真·全路径,实测 C_cc≫C_spray)**的 mean 队列时延:**激进端最优**(过宽松 CC 让 floor 膨胀,goodput 已封顶)。最优值在两端**翻转**,默认 6µs 在两 regime 都偏离最优 → **CC 的最优设置与 LB 产生的 regime 耦合**,独立调 CC(不知 spraying 处理了什么)无法两头都赢 → 必须协同。(度量说明:Regime B 用 **mean** 队列时延而非 p99——NSCC 靠 trim 封住队列,p99/p90 被钉在缓冲上限、对 CC 不敏感;mean 反映被宽松 CC 抬高的持续 floor,正是 C_cc 所指。)
```

Then add a config-table row after the figH row:

```markdown
| figI | REPS 固定;Regime A=overload 8→16(failed12)取 goodput、Regime B=incast 32→1(failed0)取 mean 队列时延;各扫 `target_q_delay`∈{2,4,6,8,12,16}µs | 2 ms | [500,1500] | `cp{A,B}_tqd{Q}.s{S}`;分解 `cp{A,B}_decomp` | A:goodput / B:mean lat;分解用 `const` |
```

(Also update the intro line "## 八张图说明" → "## 九张图说明" and the two-half framing sentence to mention the third leg: "figI:即便都开,各自为战仍次优".)

- [ ] **Step 3: Confirm raw data is gitignored, figure is not**

```bash
cd /home/leo/htsim
git check-ignore htsim/sim/datacenter/mvp_runs3/cpA_tqd2.s13.sink.txt htsim/sim/datacenter/mvp_runs3/cpB_tqd2.s13.q.txt htsim/sim/datacenter/mvp_runs3/figI_cc_lb_tuning_coupled.png
```

Expected: all three paths are printed (all ignored, including the png — so the png needs `-f`). If `cpA_*.sink.txt` is NOT printed, it's tracked; add `*.sink.txt`/`*.q.txt` to `mvp_runs3/.gitignore` (they should already be there from the figG/H work).

- [ ] **Step 4: Remove scratch note and stage**

```bash
rm -f htsim/sim/datacenter/mvp_runs3/_figI_params.txt htsim/sim/datacenter/mvp_runs3/overload_cpA_*.cm htsim/sim/datacenter/mvp_runs3/scpA_*.* htsim/sim/datacenter/mvp_runs3/scpB.* htsim/sim/datacenter/mvp_runs3/scA_tqd*.* htsim/sim/datacenter/mvp_runs3/scB_tqd*.*
git add htsim/sim/datacenter/mvp_runs3/repro.sh htsim/sim/datacenter/mvp_runs3/README_repro.md
git add -f htsim/sim/datacenter/mvp_runs3/figI_cc_lb_tuning_coupled.png
git status --short | grep -E '^[A-Z]'
```

Expected staged: `repro.sh`, `README_repro.md` (modified), `figI_*.png` (added). No `.sink.txt/.q.txt/.idmap/.csv/.dat` staged.

- [ ] **Step 5: Commit**

```bash
git commit -m "Add figI: uncoordinated CC+spraying tuning is suboptimal (optimum flips across regimes)

Third motivation leg. REPS fixed ON; NSCC target_q_delay swept. Optimal CC flips ends:
Regime A (spray-removable, C_spray>>C_cc) wants lenient CC (aggressive -> underutilization);
Regime B (path-wide, C_cc>>C_spray) wants aggressive CC (lenient -> p99 latency blowup).
Default 6us off-optimum in both -> CC optimum is coupled to the LB-produced regime; tuning
them independently is provably suboptimal. Measured; co-design benefit remains inference
(no PRISM perf claim). No C++ change; pure logging. Wired into repro.sh + README_repro.md.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Notes for the executor

- **Honesty gate (Task 2 Step 5 / Task 6 Step 3):** the flip is the whole result. If it doesn't appear after the documented adjustments, report it — a truthful null is acceptable; a forced figure is not. This matches the project's standing constraint.
- **No C++ changes** anywhere. Only CLI flags + existing parse_output.
- **All intermediate files under `mvp_runs3/`.** Never write to the repo root.
- **Scope language is fixed** (spec §8): figI proves *independent-tuning suboptimality* (measured); it does NOT claim a co-designed controller is better (inference only). Keep that wording in the figure/README.
