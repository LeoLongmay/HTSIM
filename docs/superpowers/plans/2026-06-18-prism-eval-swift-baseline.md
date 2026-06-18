# Swift CC Baseline Implementation Plan (phase A of Swift/LSwift/MSwift)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port Swift (Kumar et al. SIGCOMM 2020, Algorithm 1 + §3.5 flow-scaled target) into the `UecSrc` CC framework as `-sender_cc_algo swift`, and wire it as a baseline arm in `prism_eval/expA_delaydriven/`.

**Architecture:** Swift is a new additive `UecSrc` CC (pure-delay AIMD with a flow-scaled target), reusing the shared REPS spray + metrics, exactly as STrack/MNSCC were added. Pure logic (target formula + MD factor) in a unit-tested header `swift_cc.h`; the per-ACK controller calls into it. No existing CC path changes. **LSwift + MSwift are phase B — out of scope.**

**Tech Stack:** C++ (htsim_uec / `uec.cpp`, cmake build), bash harness, Python 3 + matplotlib. Under `/home/leo/htsim/htsim/sim/`.

## Global Constraints

- **Working dirs:** sim root `/home/leo/htsim/htsim/sim`; datacenter `…/sim/datacenter` (DC); eval group `DC/prism_eval/expA_delaydriven`.
- **Commit policy:** per-task **local commit** on branch `prism-motivation-redesign`; **NEVER push**.
- **Additive only — do NOT change NSCC/PRISM/STrack/MNSCC behavior.** Enum value APPENDED (no renumber), new functions, new default-initialized member, new flags (defaults reproduce the intended Swift). PRISM stays O(1).
- **Swift = Algorithm 1 + §3.5, queuing-delay domain.** On ACK: `delay < target` → AI `_cwnd += mtu·ai·newly_acked_bytes/_cwnd` (cumulative +ai pkts/RTT); else if `can_decrease` (once/RTT, `now−_swift_last_dec ≥ _base_rtt`) → MD `_cwnd *= md_factor`. ECN `skip` **ignored** (Swift is pure-delay). Loss (NACK) → flat `(1−max_mdf)` cut once/RTT.
- **Target (queuing domain):** `target = base_q + clamp(a/√cwnd_pkts + b, 0, fs_range)`, `a,b` from `fs_coeffs(fs_range, fs_min_cwnd, fs_max_cwnd)` (paper §3.5). Defaults: `base_q = _target_Qdelay` (≈14 µs), `fs_range = _target_Qdelay/2`, `fs_min_cwnd=0.1`, `fs_max_cwnd=100`, `ai=1.0`, `beta=0.8`, `max_mdf=0.5`. All flag-overridable (`-swift_*`).
- **Arm = `CC=swift LB=reps`**; color `plot_style.COLORS["swift"]="tab:pink"`; 7 arms total.
- **Renderer backward-compat:** Swift cwnd-panel/cut-count additions guarded by `os.path.exists` → expB/C/D and Swift-less expA mech figures byte-identical. No signature change to `render_main_perf*`/`render_fairness`.
- **YAGNI:** no sub-1-packet pacing; no `#hops·ℏ` separate term (folded into base_q); no fcwnd/ecwnd split.
- **Build:** `cd /home/leo/htsim/htsim/sim/build && make htsim_uec`. **Reproducibility:** seeds {13–17}; figures `git add -f`; `data/` gitignored; selftests gate the run.

---

### Task 1: Pure-logic `swift_cc.h` + unit test

**Files:**
- Create: `htsim/sim/swift_cc.h`
- Create: `htsim/sim/datacenter/prism_eval/common/tests/test_swift_cc.cpp`

**Interfaces:**
- Produces: `swift::fs_coeffs(double fs_range, double fs_min_cwnd, double fs_max_cwnd, double& a, double& b)`; `swift::target_delay_q(double cwnd_pkts, uint64_t base_q, double a, double b, double fs_range) -> uint64_t`; `swift::md_factor(uint64_t delay, uint64_t target, double beta, double max_mdf) -> double`. Task 2 includes this header (`simtime_picosec` == `uint64_t`).

- [ ] **Step 1: Write the unit test**

Create `htsim/sim/datacenter/prism_eval/common/tests/test_swift_cc.cpp`:

```cpp
#include "swift_cc.h"
#include <cassert>
#include <cstdio>
#include <cmath>
#include <cstdint>
using namespace swift;
int main() {
    double a, b;
    const double R = 7000.0;                 // fs_range (ps); fs_min=0.1, fs_max=100 packets
    fs_coeffs(R, 0.1, 100.0, a, b);
    // at cwnd == fs_max_cwnd (100) the scaling term is ~0 -> target == base
    assert(target_delay_q(100.0, 14000, a, b, R) == 14000);
    // at cwnd == fs_min_cwnd (0.1) the scaling term saturates at fs_range -> target == base + R
    assert(target_delay_q(0.1, 14000, a, b, R) == 14000 + (uint64_t)R);
    // monotonic: a smaller cwnd yields a larger target
    assert(target_delay_q(4.0, 14000, a, b, R) > target_delay_q(64.0, 14000, a, b, R));
    // cwnd <= 0 -> base (no scaling)
    assert(target_delay_q(0.0, 14000, a, b, R) == 14000);
    // md_factor: delay == target -> factor 1.0 (no decrease)
    assert(std::fabs(md_factor(14000, 14000, 0.8, 0.5) - 1.0) < 1e-9);
    // delay slightly above target -> just below 1, above the 1-max_mdf floor
    { double f = md_factor(15000, 14000, 0.8, 0.5); assert(f < 1.0 && f > 0.5); }
    // delay >> target -> clamped at 1 - max_mdf = 0.5
    assert(std::fabs(md_factor(1000000, 14000, 0.8, 0.5) - 0.5) < 1e-9);
    printf("ok swift target_delay_q + md_factor\n");
    printf("ALL PASS\n");
    return 0;
}
```

- [ ] **Step 2: Run the test to verify it fails (no header yet)**

Run: `cd /home/leo/htsim/htsim/sim && g++ -I. datacenter/prism_eval/common/tests/test_swift_cc.cpp -o /tmp/test_swift_cc`
Expected: FAIL — `fatal error: swift_cc.h: No such file or directory`.

- [ ] **Step 3: Write the header**

Create `htsim/sim/swift_cc.h`:

```cpp
#ifndef SWIFT_CC_H
#define SWIFT_CC_H
// Pure logic for the Swift CC (Kumar et al., SIGCOMM 2020): Algorithm 1's MD factor and the §3.5
// flow-scaled target delay, ported into the UecSrc framework. Header-only, no side effects;
// unit-tested in datacenter/prism_eval/common/tests/test_swift_cc.cpp. We work in the QUEUING-delay
// domain (delay = raw_rtt - base_rtt), so §3.5's base_target + #hops*h terms fold into base_q.
// Times are picoseconds (== simtime_picosec == uint64_t); kept as uint64_t so the header is
// standalone-compilable for the unit test.
#include <algorithm>
#include <cmath>
#include <cstdint>

namespace swift {

// §3.5 flow-scaling coefficients: a = fs_range / (1/sqrt(fs_min) - 1/sqrt(fs_max)), b = -a/sqrt(fs_max).
inline void fs_coeffs(double fs_range, double fs_min_cwnd, double fs_max_cwnd, double& a, double& b) {
    a = fs_range / (1.0 / std::sqrt(fs_min_cwnd) - 1.0 / std::sqrt(fs_max_cwnd));
    b = -a / std::sqrt(fs_max_cwnd);
}

// §3.5 target in the queuing-delay domain: base_q + clamp(a/sqrt(cwnd_pkts) + b, 0, fs_range).
// cwnd_pkts <= 0 -> base_q (no scaling). Larger cwnd -> smaller scaling term (target -> base_q).
inline uint64_t target_delay_q(double cwnd_pkts, uint64_t base_q, double a, double b, double fs_range) {
    if (cwnd_pkts <= 0.0) return base_q;
    double fs = a / std::sqrt(cwnd_pkts) + b;
    if (fs > fs_range) fs = fs_range;
    if (fs < 0.0) fs = 0.0;
    return base_q + (uint64_t)fs;
}

// Algorithm 1 MD factor: max(1 - beta*(delay-target)/delay, 1 - max_mdf).
// Caller guarantees delay >= target and delay > 0 (only the MD branch calls this).
inline double md_factor(uint64_t delay, uint64_t target, double beta, double max_mdf) {
    double f = 1.0 - beta * (double)(delay - target) / (double)delay;
    double lo = 1.0 - max_mdf;
    return f > lo ? f : lo;
}

} // namespace swift
#endif
```

- [ ] **Step 4: Compile and run the test to verify it passes**

Run: `cd /home/leo/htsim/htsim/sim && g++ -I. datacenter/prism_eval/common/tests/test_swift_cc.cpp -o /tmp/test_swift_cc && /tmp/test_swift_cc`
Expected: `ok swift target_delay_q + md_factor` then `ALL PASS`.

- [ ] **Step 5: Commit (local; never push)**

```bash
cd /home/leo/htsim && git add htsim/sim/swift_cc.h htsim/sim/datacenter/prism_eval/common/tests/test_swift_cc.cpp && git commit -m "swift: pure-logic flow-scaled target + MD-factor header with unit test"
```

---

### Task 2: Swift controller (`-sender_cc_algo swift` + `-swift_*` flags)

**Files:**
- Modify: `htsim/sim/uec.h` (enum, decls, member, statics)
- Modify: `htsim/sim/uec.cpp` (include, static defs, dispatch, two functions)
- Modify: `htsim/sim/datacenter/main_uec.cpp` (parse `swift` + `-swift_*` flags)

**Interfaces:**
- Consumes: `swift::fs_coeffs`, `swift::target_delay_q`, `swift::md_factor` (Task 1).
- Produces: `UecSrc::SWIFT` enum; `-sender_cc_algo swift`; flags `-swift_ai/-swift_beta/-swift_max_mdf/-swift_base_q/-swift_fs_range/-swift_fs_min_cwnd/-swift_fs_max_cwnd`. Task 3 uses the arm.

- [ ] **Step 1: `uec.h` — enum, declarations, member, statics**

Append `SWIFT` to the enum (`uec.h:219`, currently ends `…, MNSCC};`):
```cpp
    enum Sender_CC { DCTCP, NSCC, CONSTANT, PRISM, STRACK, MNSCC, SWIFT};
```
Declare the two update functions next to `updateCwndOnAck_MNSCC` (~line 312):
```cpp
    void updateCwndOnAck_SWIFT(bool skip, simtime_picosec delay, mem_b newly_acked_bytes);
    void updateCwndOnNack_SWIFT(uint32_t ev, mem_b nacked_bytes, bool last_hop);
```
Add the per-flow member next to the MNSCC window members (the `_mnscc_*` block):
```cpp
    simtime_picosec _swift_last_dec = 0;   // Swift: time of last MD (MD allowed once per RTT)
```
Add the statics next to `_mnscc_h` (~line 374):
```cpp
    static double _swift_ai;          // Swift additive increment (default 1.0)
    static double _swift_beta;        // Swift MD constant (default 0.8)
    static double _swift_max_mdf;     // Swift max multiplicative decrease factor (default 0.5)
    static simtime_picosec _swift_base_q;   // queuing-domain base target; 0 = use _target_Qdelay
    static simtime_picosec _swift_fs_range;  // flow-scaling range; 0 = use _target_Qdelay/2
    static double _swift_fs_min_cwnd; // packets (default 0.1)
    static double _swift_fs_max_cwnd; // packets (default 100)
```

- [ ] **Step 2: `uec.cpp` — include, static definitions, dispatch**

Add the include next to `#include "mnscc_median.h"` (~line 14):
```cpp
#include "swift_cc.h"                // Swift CC pure logic (used by updateCwndOnAck_SWIFT)
```
Add static definitions next to `uint32_t UecSrc::_mnscc_h = 0;` (grep `UecSrc::_mnscc_h =`):
```cpp
double          UecSrc::_swift_ai = 1.0;
double          UecSrc::_swift_beta = 0.8;
double          UecSrc::_swift_max_mdf = 0.5;
simtime_picosec UecSrc::_swift_base_q = 0;
simtime_picosec UecSrc::_swift_fs_range = 0;
double          UecSrc::_swift_fs_min_cwnd = 0.1;
double          UecSrc::_swift_fs_max_cwnd = 100.0;
```
Add the dispatch case after the `MNSCC` case (~line 612):
```cpp
            case SWIFT:
                updateCwndOnAck = &UecSrc::updateCwndOnAck_SWIFT;
                updateCwndOnNack = &UecSrc::updateCwndOnNack_SWIFT;
                break;
```

- [ ] **Step 3: `uec.cpp` — the two Swift functions**

Add after `updateCwndOnAck_MNSCC` ends:
```cpp
// Swift (Kumar et al. 2020): pure-delay AIMD with the §3.5 flow-scaled target, in the queuing-delay
// domain. ECN (skip) is ignored (Swift has no ECN term). MD is once per RTT. See swift_cc.h.
void UecSrc::updateCwndOnAck_SWIFT(bool skip, simtime_picosec delay, mem_b newly_acked_bytes) {
    if (quick_adapt(false, skip, delay))   // reuse NSCC loss/quick adaptation
        return;
    simtime_picosec base_q = _swift_base_q > 0 ? _swift_base_q : _target_Qdelay;
    double fs_range = _swift_fs_range > 0 ? (double)_swift_fs_range : (double)_target_Qdelay / 2.0;
    double a, b;
    swift::fs_coeffs(fs_range, _swift_fs_min_cwnd, _swift_fs_max_cwnd, a, b);
    double cwnd_pkts = (_mtu > 0) ? (double)_cwnd / _mtu : 0.0;
    simtime_picosec target = swift::target_delay_q(cwnd_pkts, base_q, a, b, fs_range);

    bool can_decrease = (eventlist().now() - _swift_last_dec) >= _base_rtt;
    if (delay < target) {
        if (_cwnd > 0)
            _cwnd += (mem_b)((double)_mtu * _swift_ai * (double)newly_acked_bytes / (double)_cwnd);
    } else if (can_decrease && delay > 0) {
        mem_b before = _cwnd;
        _cwnd = (mem_b)(_cwnd * swift::md_factor(delay, target, _swift_beta, _swift_max_mdf));
        if (_cwnd <= before)
            _swift_last_dec = eventlist().now();
    }
    set_cwnd_bounds();
}

// Swift loss reaction: flat (1 - max_mdf) multiplicative decrease, once per RTT.
void UecSrc::updateCwndOnNack_SWIFT(uint32_t ev, mem_b nacked_bytes, bool last_hop) {
    if ((eventlist().now() - _swift_last_dec) >= _base_rtt) {
        _cwnd = (mem_b)(_cwnd * (1.0 - _swift_max_mdf));
        _swift_last_dec = eventlist().now();
    }
    set_cwnd_bounds();
}
```

- [ ] **Step 4: `main_uec.cpp` — parse the algo name and the flags**

In the `-sender_cc_algo` block, after the `mnscc` clause (~line 236):
```cpp
            else if (!strcmp(argv[i+1],"swift"))
                UecSrc::_sender_cc_algo = UecSrc::SWIFT;
```
Add the flag clauses immediately after the `-mnscc_h` clause (mirror its `i++` convention):
```cpp
        } else if (!strcmp(argv[i],"-swift_ai")) {
            UecSrc::_swift_ai = atof(argv[i+1]);
            cout << "swift_ai " << UecSrc::_swift_ai << endl;
            i++;
        } else if (!strcmp(argv[i],"-swift_beta")) {
            UecSrc::_swift_beta = atof(argv[i+1]);
            cout << "swift_beta " << UecSrc::_swift_beta << endl;
            i++;
        } else if (!strcmp(argv[i],"-swift_max_mdf")) {
            UecSrc::_swift_max_mdf = atof(argv[i+1]);
            cout << "swift_max_mdf " << UecSrc::_swift_max_mdf << endl;
            i++;
        } else if (!strcmp(argv[i],"-swift_base_q")) {
            UecSrc::_swift_base_q = timeFromUs(atof(argv[i+1]));
            cout << "swift_base_q(us) " << atof(argv[i+1]) << endl;
            i++;
        } else if (!strcmp(argv[i],"-swift_fs_range")) {
            UecSrc::_swift_fs_range = timeFromUs(atof(argv[i+1]));
            cout << "swift_fs_range(us) " << atof(argv[i+1]) << endl;
            i++;
        } else if (!strcmp(argv[i],"-swift_fs_min_cwnd")) {
            UecSrc::_swift_fs_min_cwnd = atof(argv[i+1]);
            cout << "swift_fs_min_cwnd " << UecSrc::_swift_fs_min_cwnd << endl;
            i++;
        } else if (!strcmp(argv[i],"-swift_fs_max_cwnd")) {
            UecSrc::_swift_fs_max_cwnd = atof(argv[i+1]);
            cout << "swift_fs_max_cwnd " << UecSrc::_swift_fs_max_cwnd << endl;
            i++;
```

- [ ] **Step 5: Build htsim_uec**

Run: `cd /home/leo/htsim/htsim/sim/build && make htsim_uec 2>&1 | tail -5`
Expected: builds with no errors (`Built target htsim_uec`).

- [ ] **Step 6: Swift sanity + f0 target calibration check**

```bash
cd /home/leo/htsim/htsim/sim/datacenter
python3 prism_eval/common/gen/many2many.py /tmp/m.cm 64 16 pairs 2000000 128 16
PATHS=8 END_MS=8 EXTRA_ARGS="-disable_trim" PRISM_PATHRTT=/tmp/sw/swift_f0.pathrtt.csv \
  bash prism_eval/common/run_lib.sh swift reps 0 fat_tree_128_1os.topo 13 /tmp/m.cm flow,sink swift_f0 /tmp/sw
PATHS=8 END_MS=8 EXTRA_ARGS="-disable_trim" \
  bash prism_eval/common/run_lib.sh swift reps 8 fat_tree_128_1os.topo 13 /tmp/m.cm flow,sink swift_f8 /tmp/sw
python3 - <<'PY'
import sys; sys.path.insert(0,'prism_eval/common'); import metrics
for tag in ("swift_f0","swift_f8"):
    fp=f"/tmp/sw/{tag}.flow.txt"
    g=metrics.aggregate_goodput_gbps(fp); cr=metrics.fct_stats(fp)["completion_rate"]
    print(f"{tag}: goodput={g:.1f} Gbps cr={cr:.3f}")
    assert cr > 0.99, f"{tag} cr<1 ({cr})"
    assert 300 < g < 1000, f"{tag} goodput out of sane band ({g})"
# f0 mean queuing delay should track the ~14us target (gross-miscalibration guard)
b=metrics.qdelay_bins("/tmp/sw/swift_f0.pathrtt.csv", base_ns=13945, bin_us=20)
mean_q=sum(x[2] for x in b)/len(b) if b else float("nan")
print(f"swift_f0 mean queuing delay = {mean_q:.1f} us  (target ~14us)")
assert 3.0 < mean_q < 35.0, f"f0 queuing delay {mean_q}us far from ~14us target -- tune -swift_base_q/-swift_fs_range"
print("SWIFT SANITY OK")
PY
```
Expected: `SWIFT SANITY OK` — both runs cr≈1 with sane goodput, and f0 mean queuing delay near the ~14 µs target. If goodput is degenerate (≈0 or line-rate-cheating) or the queuing delay is far off, STOP and report (the calibration / port is wrong).

- [ ] **Step 7: Regression — existing arms unaffected**

```bash
cd /home/leo/htsim/htsim/sim/datacenter
for cc in nscc prism; do
  PATHS=8 END_MS=8 EXTRA_ARGS="-disable_trim" bash prism_eval/common/run_lib.sh $cc reps 8 fat_tree_128_1os.topo 13 /tmp/m.cm flow A_$cc /tmp/sw
done
python3 -c "import sys; sys.path.insert(0,'prism_eval/common'); import metrics; print('nscc f8', metrics.aggregate_goodput_gbps('/tmp/sw/A_nscc.flow.txt')); print('prism f8', metrics.aggregate_goodput_gbps('/tmp/sw/A_prism.flow.txt'))"
```
Expected: nscc/prism f8 goodput in line with the committed figA1dd values (REPS≈431, Prism≈504 at 5-seed mean; single-seed will be close) — Swift is additive-only so existing CCs cannot regress. If either is degenerate, STOP.

- [ ] **Step 8: Commit (local; never push)**

```bash
cd /home/leo/htsim && git add htsim/sim/uec.h htsim/sim/uec.cpp htsim/sim/datacenter/main_uec.cpp && git commit -m "swift: -sender_cc_algo swift (Algorithm 1 + flow-scaled target) + -swift_* flags"
```

---

### Task 3: Eval wiring — color, BASELINES, repro runs

**Files:**
- Modify: `prism_eval/common/plot_style.py`
- Modify: `prism_eval/expA_delaydriven/make_figs.py`
- Modify: `prism_eval/expA_delaydriven/repro.sh`

**Interfaces:**
- Consumes: `-sender_cc_algo swift` (Task 2).
- Produces: data `expA_swift_f{F}_s{S}.flow.txt`, `expAload_swift_L{rho}_s{S}.flow.txt`, `expA_swift_mech.pathrtt.csv`.

- [ ] **Step 1: Add the swift color**

In `prism_eval/common/plot_style.py`, in `COLORS`, after the `"mnscc"` line add:
```python
    "swift": "tab:pink",  # Swift (Kumar et al. 2020) delay-AIMD baseline
```

- [ ] **Step 2: Add swift to BASELINES**

In `prism_eval/expA_delaydriven/make_figs.py`, change `BASELINES` to append swift:
```python
BASELINES = [("ops", "OPS+NSCC", "ops"), ("reps", "REPS+NSCC", "reps"),
             ("strack", "STrack", "strack"), ("prism", "Prism", "prism"),
             ("ecmp", "ECMP+NSCC", "ecmp"), ("mnscc", "MNSCC", "mnscc"),
             ("swift", "Swift", "swift")]
```

- [ ] **Step 3: Add the swift run to the `-failed` sweep**

In `prism_eval/expA_delaydriven/repro.sh`, inside the `for f in $FAILEDS; do for s in $SEEDS; do` loop, after the `expA_mnscc_...` line add:
```bash
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" swift reps "$f" "$TOPO" "$s" "$CM" flow,sink "expA_swift_f${f}_s${s}" "$OUT"
```

- [ ] **Step 4: Add the swift run to the offered-load sweep**

In the offered-load `for rho ... for s ...` loop, after the `expAload_mnscc_...` line add:
```bash
    PATHS=8 END_MS="$LOAD_END" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" swift reps 8 "$TOPO" "$s" "$LCM" flow,sink "expAload_swift_L${rho}_s${s}" "$OUT"
```

- [ ] **Step 5: Add the swift mechanism run**

In the mechanism block, after the `expA_mnscc_mech` run, add:
```bash
PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_PATHRTT="$OUT/expA_swift_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" swift reps 8 "$TOPO" 13 "$CM_MECH" flow,sink expA_swift_mech "$OUT"
```

- [ ] **Step 6: Smoke — one swift failed run aggregates under the 7-arm pipeline**

```bash
cd /home/leo/htsim/htsim/sim/datacenter
D=prism_eval/expA_delaydriven/data; mkdir -p "$D"
python3 prism_eval/common/gen/many2many.py "$D/m2m.cm" 64 16 pairs 2000000 128 16
PATHS=8 END_MS=8 EXTRA_ARGS="-disable_trim" bash prism_eval/common/run_lib.sh swift reps 8 fat_tree_128_1os.topo 13 "$D/m2m.cm" flow,sink expA_swift_f8_s13 "$D"
python3 -c "import sys; sys.path.insert(0,'prism_eval/common'); import perf_figs; print(perf_figs.aggregate('$D','expA','swift',[8],[13]))"
```
Expected: dict with `8: {...}` and a finite goodput → Swift slots into the `expA_*` aggregation under the `swift` label.

- [ ] **Step 7: Verify make_figs --selftest still passes**

Run: `cd /home/leo/htsim/htsim/sim/datacenter && python3 prism_eval/expA_delaydriven/make_figs.py --selftest`
Expected: `ok perf_figs aggregation selftest`.

- [ ] **Step 8: Commit (local; never push; no data/)**

```bash
cd /home/leo/htsim && git add htsim/sim/datacenter/prism_eval/common/plot_style.py htsim/sim/datacenter/prism_eval/expA_delaydriven/make_figs.py htsim/sim/datacenter/prism_eval/expA_delaydriven/repro.sh && git commit -m "prism_eval: wire Swift arm into expA_delaydriven failed/load/mech runs"
```

---

### Task 4: Mechanism cwnd panel — add Swift (backward-compatible)

**Files:**
- Modify: `prism_eval/common/perf_figs.py` (`render_mechanism_split`)

**Interfaces:**
- Consumes: `expA_swift_mech.pathrtt.csv` (Task 3).
- Produces: Swift on the cwnd panel + its rate-reduction count. Renders only if the file exists (other experiments unaffected).

- [ ] **Step 1: Add Swift to the cwnd-panel arms list**

In `prism_eval/common/perf_figs.py`, in `render_mechanism_split`, the cwnd-panel loop currently iterates a list ending with the `("mnscc", "MNSCC", …)` entry (added previously). Append a Swift entry to that list:
```python
                           ("swift", "Swift", os.path.join(data_dir, f"{tag_prefix}_swift_mech.pathrtt.csv"))]
```
(The loop already does `if not os.path.exists(path): continue`, so Swift renders only when its file exists.)

- [ ] **Step 2: Add Swift to the rate-reduction annotation (guarded)**

After the `mnscc_dec = …` line, add:
```python
    swift_pr = os.path.join(data_dir, f"{tag_prefix}_swift_mech.pathrtt.csv")
    swift_dec = metrics.count_cwnd_cuts_from_pathrtt(swift_pr) if os.path.exists(swift_pr) else -1
```
And next to the existing `mnscc_part = …` guard, add:
```python
    swift_part = f", Swift {swift_dec}" if swift_dec != -1 else ""
```
Append `{swift_part}` to the `axc.text(...)` f-string (right after `{mnscc_part}`).

- [ ] **Step 3: Run the perf_figs selftest**

Run: `cd /home/leo/htsim/htsim/sim/datacenter && python3 prism_eval/common/perf_figs.py`
Expected: `ok perf_figs aggregation selftest` (no behavior change to the selftest path).

- [ ] **Step 4: Regression — expD mechanism (no Swift files) unchanged**

Run: `cd /home/leo/htsim/htsim/sim/datacenter && python3 prism_eval/expD_scale1024/make_figs.py --selftest`
Expected: `ok perf_figs aggregation selftest` (Swift additions guarded by `os.path.exists` → byte-identical where Swift files absent).

- [ ] **Step 5: Commit (local; never push)**

```bash
cd /home/leo/htsim && git add htsim/sim/datacenter/prism_eval/common/perf_figs.py && git commit -m "perf_figs: add Swift to the mechanism cwnd panel + cut count (backward-compatible)"
```

---

### Task 5: Full reproduction + figures + docs

**Files:**
- Run: `prism_eval/expA_delaydriven/repro.sh`
- Modify: `prism_eval/expA_delaydriven/README.md`, `prism_eval/NARRATIVE.md`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces: regenerated `figA1dd_*`/`figA3dd_load_*` (7 arms) + `figA2dd_cwnd` (with Swift), and docs with real numbers.

- [ ] **Step 1: Add the swift unit test to repro.sh's self-test block**

In `prism_eval/expA_delaydriven/repro.sh`, after the `test_mnscc_median` compile/run line in the self-test block, add:
```bash
( cd "$DC/.." && g++ -I. datacenter/prism_eval/common/tests/test_swift_cc.cpp -o /tmp/test_swift_cc && /tmp/test_swift_cc )
```
Also update the main-sweep echo `6 baselines` → `7 baselines`.

- [ ] **Step 2: Run the full repro (background)**

```bash
cd /home/leo/htsim/htsim/sim/datacenter
mkdir -p prism_eval/expA_delaydriven/data
( bash prism_eval/expA_delaydriven/repro.sh > prism_eval/expA_delaydriven/data/repro.log 2>&1 ) &
echo "launched pid $!"
```

- [ ] **Step 3: Confirm completion + capture the 7-arm summaries**

```bash
cd /home/leo/htsim/htsim/sim/datacenter
tail -30 prism_eval/expA_delaydriven/data/repro.log
grep -E "\[figA1dd\]|\[figA3dd_load\]" prism_eval/expA_delaydriven/data/repro.log
ls prism_eval/expA_delaydriven/figs/figA2dd_cwnd.pdf prism_eval/expA_delaydriven/figs/figA1dd_goodput.pdf
```
Expected: the `[figA1dd]`/`[figA3dd_load]` lines now include a `Swift:` row; figures present; no tracebacks.

- [ ] **Step 4: Sanity-check the Swift result honestly**

From the summaries confirm: (a) Swift completes (cr≈1 where REPS/PRISM do); (b) record where Swift's goodput/FCT land vs PRISM/REPS/STrack/MNSCC under asymmetry and load — **as measured** (PRISM wins / Swift competitive / Swift worse). If Swift fails to run or is degenerate (NaN/zero) everywhere, STOP — wiring/calibration bug, not a result.

- [ ] **Step 5: Write the README subsection + NARRATIVE with real numbers**

In `prism_eval/expA_delaydriven/README.md`, add a subsection "Swift (delay-AIMD) baseline": Swift's `-failed` and load numbers vs PRISM/REPS/STrack/MNSCC; the faithful-port note (Algorithm 1 + §3.5 flow-scaled target, queuing-delay domain, base_q≈14µs; `ai/β/max_mdf` = htsim defaults since the paper's production values are unpublished); the honest verdict (where PRISM's floor beats Swift's instantaneous-delay AIMD, ties, or Swift is competitive). In `prism_eval/NARRATIVE.md` §3 add one sentence placing Swift as a delay-AIMD reference CC and the measured outcome, plus a Map row `| Eval (vs Swift) | expA_delaydriven/ (Swift arm) | <one-line measured verdict> |`. (Fill all `<...>` from Step 3.)

- [ ] **Step 6: Report + list commit commands (controller/user finalizes)**

Provide the commands to commit when ready (figs gitignored → forced):
```bash
cd /home/leo/htsim/htsim/sim/datacenter
git add prism_eval/expA_delaydriven/README.md prism_eval/NARRATIVE.md \
        ../../../docs/superpowers/specs/2026-06-18-prism-eval-swift-baseline-design.md \
        ../../../docs/superpowers/plans/2026-06-18-prism-eval-swift-baseline.md
git add -f prism_eval/expA_delaydriven/figs/figA1dd_goodput.* prism_eval/expA_delaydriven/figs/figA1dd_avg_fct.* \
           prism_eval/expA_delaydriven/figs/figA1dd_p99_fct.* prism_eval/expA_delaydriven/figs/figA1dd_fairness.* \
           prism_eval/expA_delaydriven/figs/figA3dd_load_goodput.* prism_eval/expA_delaydriven/figs/figA3dd_load_avg_fct.* \
           prism_eval/expA_delaydriven/figs/figA3dd_load_p99_fct.* prism_eval/expA_delaydriven/figs/figA2dd_cwnd.*
```

---

## Self-Review

**Spec coverage:**
- Pure logic `swift_cc.h` (target_delay_q + md_factor + fs_coeffs) + unit test → Task 1. ✓
- Controller `-sender_cc_algo swift` (AIMD, flow-scaled target, ECN ignored, max_mdf NACK) → Task 2. ✓
- Target calibration (base_q=_target_Qdelay, fs_range/2, fs params) + empirical f0 check → Task 2 Steps 3,6. ✓
- 7-arm eval wiring (color/BASELINES/repro failed+load+mech) → Task 3. ✓
- Mechanism cwnd panel + cut count, backward-compatible → Task 4. ✓
- Regression (NSCC/PRISM/STrack/MNSCC unchanged; expD mech byte-identical) → Task 2 Step 7 + Task 4 Step 4. ✓
- Docs + honest framing → Task 5 Steps 5. ✓
- Repro integrity (swift unit test in self-test; echo 6→7) → Task 5 Step 1. ✓
- YAGNI (no sub-1 pacing, no #hops·ℏ term, no fcwnd/ecwnd) → header/controller as written; out-of-scope noted. ✓

**Placeholder scan:** README/NARRATIVE `<...>` are data-fill markers correctly deferred to post-run (Task 5). No code step has TBD/placeholder.

**Type consistency:** `swift::target_delay_q(double, uint64_t, double, double, double) -> uint64_t`, `md_factor(uint64_t, uint64_t, double, double) -> double`, `fs_coeffs(double, double, double, double&, double&)` consistent between Task 1 (def + test) and Task 2 (calls; `simtime_picosec` == `uint64_t`). AI formula `_cwnd += mtu·ai·newly_acked_bytes/_cwnd` uses `newly_acked_bytes` (bytes) consistently with the swift.cpp byte-domain reference. Statics `_swift_ai/_swift_beta/_swift_max_mdf/_swift_base_q/_swift_fs_range/_swift_fs_min_cwnd/_swift_fs_max_cwnd` declared (Task 2 Step 1), defined (Step 2), parsed (Step 4) with matching names/types. Arm tag `expA_swift_f{F}_s{S}`/`expAload_swift_L{rho}_s{S}`/`expA_swift_mech` consistent between repro.sh (Task 3) and the `swift` BASELINES label + perf_figs `{tag_prefix}_swift_mech.pathrtt.csv` (Task 4).
