# PRISM Controller (P1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `-sender_cc_algo prism` to the htsim/UEC transport: an epoch-based controller that decomposes per-epoch multipath congestion into floor `C_cc` (epoch-min q) and spread `C_spray` (epoch max−min), and drives NSCC's existing increase/decrease *formulas* from that decomposition.

**Architecture:** Pure decomposition logic (four-quadrant region decision, floor-driven MD factor) lives in a new dependency-free header `htsim/sim/prism_decompose.h`, unit-tested standalone. `UecSrc::updateCwndOnAck_PRISM` (new method in `uec.cpp`) wires it in: it accumulates epoch min/max per ACK, decides the region at each `kappa*base_rtt` boundary, reuses NSCC's `proportional_increase`/`fulfill_adjustment`/`quick_adapt`/NACK, and cuts via NSCC's MD formula fed `C_cc`. Spraying (REPS) and NACK handling are untouched. An env-gated `PRISM_EPOCH` CSV log + a Python cross-check verify the wiring.

**Tech Stack:** C++17 (htsim), CMake build (`htsim/sim/build`), Python 3 (cross-check), the P0 harness (`prism_eval/common/run_lib.sh`, `metrics.py`).

**Spec:** `docs/superpowers/specs/2026-06-15-prism-controller-design.md`.

---

> **COMMIT POLICY (overrides the skill default):** The user has a standing instruction **not to `git commit`**. Each task ends with a "Stage & checkpoint" step: `git add` the listed files and **pause** — do NOT `git commit` until the user explicitly approves. The `git commit` lines are the message to use *when* approved.

> **Build command (used throughout):**
> `cmake --build /home/leo/htsim/htsim/sim/build --target htsim_uec -j 2>&1 | tail -8`
> Success = ends without error and prints a `Built target htsim_uec` (or relinks). The datacenter `./htsim_uec` is a symlink to `build/datacenter/htsim_uec`, so it updates automatically.

## File structure

```
htsim/sim/prism_decompose.h        (NEW) pure logic: prism::Region, decide_region(), md_factor()
htsim/sim/uec.h                    (MOD) PRISM enum value; static params; per-flow epoch state; method decl
htsim/sim/uec.cpp                  (MOD) #include header; static defs; dispatch case; updateCwndOnAck_PRISM + PRISM_EPOCH log
htsim/sim/datacenter/main_uec.cpp  (MOD) parse "prism"; parse -prism_t_spray / -prism_kappa
htsim/sim/datacenter/main_uec_sf.cpp (MOD) same parse additions (htsim_uec_sf parity)
htsim/sim/datacenter/prism_eval/common/tests/test_prism_decompose.cpp  (NEW) standalone unit test
htsim/sim/datacenter/prism_eval/common/prism_epoch_check.py            (NEW) offline cross-check tool
htsim/sim/datacenter/prism_eval/common/tests/test_prism_epoch_check.py (NEW) cross-check selftest
```

---

### Task 1: Pure decomposition logic + standalone unit test (TDD)

**Files:**
- Create: `htsim/sim/prism_decompose.h`
- Create/Test: `htsim/sim/datacenter/prism_eval/common/tests/test_prism_decompose.cpp`

- [ ] **Step 1: Write the failing test**

Create `htsim/sim/datacenter/prism_eval/common/tests/test_prism_decompose.cpp`:
```cpp
#include "prism_decompose.h"
#include <cassert>
#include <cstdio>
using namespace prism;

int main() {
    // Four quadrants: T_cc = 6, T_spray = 6 (arbitrary ps units). ">=" counts as "high".
    assert(decide_region(3, 3, 6, 6) == INCREASE);  // floor low, spread low
    assert(decide_region(3, 9, 6, 6) == HOLD);      // floor low, spread high
    assert(decide_region(9, 3, 6, 6) == DECREASE);  // floor high (uniform overload)
    assert(decide_region(9, 9, 6, 6) == DECREASE);  // floor high + spread high (mixed)
    assert(decide_region(6, 0, 6, 6) == DECREASE);  // C_cc == T_cc -> high -> decrease
    assert(decide_region(0, 6, 6, 6) == HOLD);      // C_spray == T_spray -> high -> hold
    printf("ok decide_region\n");

    // md_factor: NSCC's MD shape, driven by the floor. multiplier in [0.5, 1].
    assert(md_factor(3, 6, 0.8) == 1.0);            // C_cc <= T_cc -> no cut
    { double f = md_factor(12, 6, 0.8);             // 1 - 0.8*6/12 = 0.6
      assert(f > 0.5999 && f < 0.6001); }
    assert(md_factor(1000000, 1, 0.8) == 0.5);      // clamped to 0.5 floor
    printf("ok md_factor\n");

    printf("ALL PASS\n");
    return 0;
}
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
g++ -std=c++17 -I/home/leo/htsim/htsim/sim \
  /home/leo/htsim/htsim/sim/datacenter/prism_eval/common/tests/test_prism_decompose.cpp \
  -o /tmp/test_prism_decompose 2>&1 | head
```
Expected: FAIL — `fatal error: prism_decompose.h: No such file or directory`.

- [ ] **Step 3: Write minimal implementation**

Create `htsim/sim/prism_decompose.h`:
```cpp
#ifndef PRISM_DECOMPOSE_H
#define PRISM_DECOMPOSE_H
// PRISM congestion decomposition — pure logic, no htsim dependencies (uint64_t times).
// Used by UecSrc::updateCwndOnAck_PRISM and unit-tested standalone. Times in picoseconds.
#include <cstdint>
#include <algorithm>

namespace prism {

enum Region { INCREASE = 0, HOLD = 1, DECREASE = 2 };

// Four-quadrant rule. floor C_cc vs target T_cc; spread C_spray vs tolerance T_spray.
// ">=" counts as "high". P5 ablation variants will branch here (left as the single
// decision point); P1 implements the default rule only.
inline Region decide_region(uint64_t c_cc, uint64_t c_spray,
                            uint64_t t_cc, uint64_t t_spray) {
    bool floor_high  = c_cc    >= t_cc;
    bool spread_high = c_spray >= t_spray;
    if (!floor_high && !spread_high) return INCREASE;  // floor safe, paths balanced
    if (!floor_high &&  spread_high) return HOLD;       // clean path exists; let REPS rebalance
    return DECREASE;                                    // floor high: even the best path is queued
}

// Multiplicative-decrease multiplier (NSCC's formula, fed the floor): max(1 - g*(Ccc-Tcc)/Ccc, 0.5).
// Returns 1.0 (no cut) when C_cc <= T_cc.
inline double md_factor(uint64_t c_cc, uint64_t t_cc, double gamma) {
    if (c_cc <= t_cc) return 1.0;
    double f = 1.0 - gamma * (double)(c_cc - t_cc) / (double)c_cc;
    return std::max(f, 0.5);
}

}  // namespace prism
#endif  // PRISM_DECOMPOSE_H
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
g++ -std=c++17 -I/home/leo/htsim/htsim/sim \
  /home/leo/htsim/htsim/sim/datacenter/prism_eval/common/tests/test_prism_decompose.cpp \
  -o /tmp/test_prism_decompose && /tmp/test_prism_decompose
```
Expected: `ok decide_region` / `ok md_factor` / `ALL PASS`.

- [ ] **Step 5: Stage & checkpoint** (do NOT commit until approved)
```bash
cd /home/leo/htsim
git add -f htsim/sim/prism_decompose.h htsim/sim/datacenter/prism_eval/common/tests/test_prism_decompose.cpp
git commit -m "prism P1: pure decomposition logic (decide_region, md_factor) + unit test"
```

---

### Task 2: Enum, static params, dispatch, CLI parse (build-verified)

**Files:**
- Modify: `htsim/sim/uec.h` (enum + static param declarations)
- Modify: `htsim/sim/uec.cpp` (static param definitions + dispatch case + include)
- Modify: `htsim/sim/datacenter/main_uec.cpp` (parse "prism" + 2 flags)
- Modify: `htsim/sim/datacenter/main_uec_sf.cpp` (same parse additions)

- [ ] **Step 1: Add the enum value + static param declarations (uec.h)**

In `uec.h`, change the `Sender_CC` enum (currently `enum Sender_CC { DCTCP, NSCC, CONSTANT};`, ~line 219) to:
```cpp
    enum Sender_CC { DCTCP, NSCC, CONSTANT, PRISM};
```
Then, in the `public:` static-params block near `static simtime_picosec _target_Qdelay;` (~line 366), add:
```cpp
    // PRISM params. T_cc IS _target_Qdelay (reused, not a separate knob).
    static simtime_picosec _prism_T_spray;  // tolerated spread; 0 = follow _target_Qdelay
    static double          _prism_kappa;    // epoch length = kappa * base_rtt; default 1.0
```
Also add the method declaration in the `private:` methods area, next to the existing
`void updateCwndOnAck_NSCC(bool skip, simtime_picosec delay, mem_b newly_acked_bytes);`
(match that signature exactly):
```cpp
    void updateCwndOnAck_PRISM(bool skip, simtime_picosec delay, mem_b newly_acked_bytes);
```

- [ ] **Step 2: Add static definitions + include + dispatch case (uec.cpp)**

In `uec.cpp`, near the top with the other `#include` lines, add:
```cpp
#include "prism_decompose.h"
```
Near the other `UecSrc::` static definitions (~line 95, by `simtime_picosec UecSrc::_target_Qdelay = timeFromUs(6u);`), add:
```cpp
simtime_picosec UecSrc::_prism_T_spray = 0;   // 0 sentinel: follow _target_Qdelay
double UecSrc::_prism_kappa = 1.0;
```
In the CC dispatch switch (~line 583, the `switch (_sender_cc_algo)`), add a case after the `NSCC` case:
```cpp
        case PRISM:
            updateCwndOnAck = &UecSrc::updateCwndOnAck_PRISM;
            updateCwndOnNack = &UecSrc::updateCwndOnNack_NSCC;  // reuse NSCC NACK/loss handling
            break;
```
Add a **stub** definition of the method, immediately after the `updateCwndOnAck_NSCC`
definition (ends ~line 1457), so the binary links and runs as NSCC for now (Task 3 replaces
the body with the real controller):
```cpp
// PRISM stub (Task 2): delegates to NSCC so the binary links/runs; Task 3 replaces this body.
void UecSrc::updateCwndOnAck_PRISM(bool skip, simtime_picosec delay, mem_b newly_acked_bytes) {
    updateCwndOnAck_NSCC(skip, delay, newly_acked_bytes);
}
```

- [ ] **Step 3: Parse "prism" + the two flags (main_uec.cpp)**

In `main_uec.cpp`, inside the existing `-sender_cc_algo` if-chain (between the `constant` case at ~line 205-206 and the `else { UNKNOWN }` at ~line 207), add:
```cpp
            else if (!strcmp(argv[i+1],"prism"))
                UecSrc::_sender_cc_algo = UecSrc::PRISM;
```
Then add two new flag branches next to the `-target_q_delay` branch (~line 189-192), following the same `i++` convention:
```cpp
        } else if (!strcmp(argv[i],"-prism_t_spray")) {
            UecSrc::_prism_T_spray = timeFromUs(atof(argv[i+1]));
            cout << "prism_t_spray " << atof(argv[i+1]) << " us" << endl;
            i++;
        } else if (!strcmp(argv[i],"-prism_kappa")) {
            UecSrc::_prism_kappa = atof(argv[i+1]);
            cout << "prism_kappa " << UecSrc::_prism_kappa << endl;
            i++;
```

- [ ] **Step 4: Mirror the parse additions in main_uec_sf.cpp**

In `main_uec_sf.cpp`, find the `-sender_cc_algo` if-chain (~line 98-127) and add the same `else if (!strcmp(argv[i+1],"prism")) UecSrc::_sender_cc_algo = UecSrc::PRISM;` clause alongside the existing `nscc`/`dctcp`/`constant` clauses. Add the same two `-prism_t_spray` / `-prism_kappa` flag branches alongside its other 2-token flag branches (match that file's local `i++`/increment convention — verify by reading a neighboring branch first). If `main_uec_sf.cpp`'s parser structure differs enough that a clean mirror isn't obvious, report DONE_WITH_CONCERNS and leave `main_uec_sf.cpp` unchanged (only `htsim_uec`/main_uec.cpp is exercised by the eval harness).

- [ ] **Step 5: Build all targets**

Build the whole project (not just `htsim_uec`) so `main_uec_sf.cpp` is compiled too and any
`_sf` parse error is caught:
```bash
cmake --build /home/leo/htsim/htsim/sim/build -j 2>&1 | tail -12
```
Expected: clean build of all targets (the stub makes the link succeed).

- [ ] **Step 6: Verify `-sender_cc_algo prism` is accepted and runs (as the NSCC stub)**

Run (1 sender -> host0, 4 MB; prism currently delegates to NSCC):
```bash
cd /home/leo/htsim/htsim/sim/datacenter
P=prism_eval/common
mkdir -p prism_eval/_p1
python3 $P/gen/incast.py prism_eval/_p1/s.cm 1 0 4000000 128 16
END_MS=2 PATHS=8 bash $P/run_lib.sh prism reps 0 fat_tree_128_1os.topo 13 prism_eval/_p1/s.cm flow s prism_eval/_p1
grep -c FLOW_EVENT prism_eval/_p1/s.flow.txt
rm -rf prism_eval/_p1
```
Expected: the run completes (no "UNKNOWN CC ALGO" error) and `s.flow.txt` has FLOW_EVENT rows.

- [ ] **Step 7: Stage & checkpoint** (do NOT commit until approved)
```bash
cd /home/leo/htsim
git add htsim/sim/uec.h htsim/sim/uec.cpp htsim/sim/datacenter/main_uec.cpp htsim/sim/datacenter/main_uec_sf.cpp
git commit -m "prism P1: enum, static params, dispatch, CLI parse for -sender_cc_algo prism"
```

---

### Task 3: Per-flow state + updateCwndOnAck_PRISM (build + run verified)

**Files:**
- Modify: `htsim/sim/uec.h` (per-flow epoch state + method declaration)
- Modify: `htsim/sim/uec.cpp` (the `updateCwndOnAck_PRISM` method body)

- [ ] **Step 1: Add per-flow state + method declaration (uec.h)**

In the `private:` block near `simtime_picosec _avg_delay = 0;` (~line 452), add:
```cpp
    // PRISM epoch state (O(1) scalars). region: 0=INCREASE,1=HOLD,2=DECREASE (prism::Region).
    simtime_picosec _prism_epoch_start   = 0;
    simtime_picosec _prism_epoch_min     = 0;
    simtime_picosec _prism_epoch_max     = 0;
    uint32_t        _prism_epoch_samples = 0;
    int             _prism_region        = 0;  // 0 = INCREASE (cold-start ramp)
    simtime_picosec _prism_ccc           = 0;  // last epoch's C_cc (increase headroom + log)
    simtime_picosec _prism_cspray        = 0;  // last epoch's C_spray (log)
```
(The method was already declared in Task 2; this step only adds the per-flow state fields.)

- [ ] **Step 2: Replace the stub body with the real controller (uec.cpp)**

Replace the entire Task-2 stub body of `UecSrc::updateCwndOnAck_PRISM` (the
`updateCwndOnAck_NSCC(...)` delegate) with the real implementation below. Also add the
file-scope constant just above the method:
```cpp
// PRISM: epoch-based floor-driven control. Reuses NSCC's increase/decrease formulas, driven
// by the (C_cc, C_spray) decomposition instead of avg_delay/ECN. See prism_decompose.h.
static constexpr uint32_t PRISM_MIN_SAMPLES = 3;  // don't decide on a near-empty epoch

void UecSrc::updateCwndOnAck_PRISM(bool skip, simtime_picosec delay, mem_b newly_acked_bytes) {
    if (quick_adapt(false, skip, delay))   // reuse NSCC loss/quick adaptation
        return;

    simtime_picosec q = (delay > 0) ? delay : 0;

    // (a) accumulate epoch min/max of q
    if (_prism_epoch_samples == 0) {
        _prism_epoch_start = eventlist().now();
        _prism_epoch_min = q;
        _prism_epoch_max = q;
    } else {
        _prism_epoch_min = min(_prism_epoch_min, q);
        _prism_epoch_max = max(_prism_epoch_max, q);
    }
    _prism_epoch_samples++;

    // (b) in-epoch action: only the INCREASE region runs NSCC's per-ACK increase machinery,
    //     fed the decided floor (< _target_Qdelay by construction; clamped defensively).
    if (_prism_region == prism::INCREASE) {
        simtime_picosec inc_delay = _prism_ccc;
        if (_target_Qdelay > 0 && inc_delay > _target_Qdelay - 1)
            inc_delay = _target_Qdelay - 1;
        proportional_increase(newly_acked_bytes, inc_delay);
    }

    // (c) epoch boundary: decide region from the decomposition; floor-driven cut at the boundary
    simtime_picosec t_spray = _prism_T_spray > 0 ? _prism_T_spray : _target_Qdelay;
    bool cut = false;
    if (eventlist().now() - _prism_epoch_start >= (simtime_picosec)(_prism_kappa * _base_rtt)
            && _prism_epoch_samples >= PRISM_MIN_SAMPLES) {
        simtime_picosec c_cc = _prism_epoch_min;
        simtime_picosec c_spray = _prism_epoch_max - _prism_epoch_min;
        int region = prism::decide_region(c_cc, c_spray, _target_Qdelay, t_spray);
        if (region == prism::DECREASE && c_cc > _target_Qdelay
                && eventlist().now() - _last_dec_time > _base_rtt) {
            mem_b before = _cwnd;
            _cwnd = (mem_b)(_cwnd * prism::md_factor(c_cc, _target_Qdelay, _gamma));
            _cwnd = max(_cwnd, _min_cwnd);
            _last_dec_time = eventlist().now();
            cut = (_cwnd < before);
        }
        _prism_region = region;
        _prism_ccc = c_cc;
        _prism_cspray = c_spray;
        // (PRISM_EPOCH logging hook is added in Task 4, right here, before the reset.)
        _prism_epoch_samples = 0;  // next ACK starts a fresh epoch (sets min=max=q)
    }
    (void)cut;  // used by the Task 4 logging hook

    // (d) reuse NSCC: apply accumulated _inc_bytes to _cwnd
    set_cwnd_bounds();
    if (_received_bytes > _adjust_bytes_threshold
            || eventlist().now() - _last_adjust_time > _adjust_period_threshold) {
        fulfill_adjustment();
    }
    set_cwnd_bounds();
}
```

- [ ] **Step 3: Build**

Run: `cmake --build /home/leo/htsim/htsim/sim/build --target htsim_uec -j 2>&1 | tail -8`
Expected: clean build (the link error from Task 2 is now resolved).

- [ ] **Step 4: Run PRISM end-to-end and confirm it produces FCT**

Run (reuses the P0 harness; 1 sender -> host0, 4 MB):
```bash
cd /home/leo/htsim/htsim/sim/datacenter
P=prism_eval/common
mkdir -p prism_eval/_p1
python3 $P/gen/incast.py prism_eval/_p1/s.cm 1 0 4000000 128 16
END_MS=2 PATHS=8 bash $P/run_lib.sh prism reps 0 fat_tree_128_1os.topo 13 prism_eval/_p1/s.cm flow,sink s prism_eval/_p1
python3 - prism_eval/_p1/s.flow.txt $P/metrics.py <<'PY'
import sys, importlib.util as u
spec=u.spec_from_file_location("metrics", sys.argv[2]); m=u.module_from_spec(spec); spec.loader.exec_module(m)
s=m.fct_stats(sys.argv[1]); print("PRISM FCT:", s)
assert s["completed"]==1, s
assert 0.0002 < s["avg_s"] < 0.002, s
print("ok prism runs")
PY
rm -rf prism_eval/_p1
```
Expected: `PRISM FCT: {...completed: 1...}` then `ok prism runs`. (A single clean flow has low spread and a low floor, so PRISM should stay in INCREASE and complete normally — FCT in the same band as the NSCC P0 smoke.)

- [ ] **Step 5: Stage & checkpoint** (do NOT commit until approved)
```bash
cd /home/leo/htsim
git add htsim/sim/uec.h htsim/sim/uec.cpp
git commit -m "prism P1: per-flow epoch state + updateCwndOnAck_PRISM (epoch four-quadrant + floor-driven MD)"
```

---

### Task 4: PRISM_EPOCH logging + region-reachability sanity

**Files:**
- Modify: `htsim/sim/uec.cpp` (insert the env-gated epoch log at the marked spot)

- [ ] **Step 1: Add the logging hook**

In `updateCwndOnAck_PRISM`, replace the comment line
`// (PRISM_EPOCH logging hook is added in Task 4, right here, before the reset.)`
with:
```cpp
        {
            static std::ofstream* prism_epoch_log = [](){
                const char* p = getenv("PRISM_EPOCH");
                return (p && *p) ? new std::ofstream(p) : nullptr;
            }();
            if (prism_epoch_log) {
                (*prism_epoch_log)
                    << (uint64_t)timeAsNs(eventlist().now()) << ','
                    << flowId() << ','
                    << (uint64_t)timeAsNs(_base_rtt) << ','
                    << (uint64_t)timeAsNs(c_cc) << ','
                    << (uint64_t)timeAsNs(c_spray) << ','
                    << region << ','
                    << (uint64_t)_cwnd << ','
                    << _prism_epoch_samples << ','
                    << (cut ? 1 : 0) << '\n';
                prism_epoch_log->flush();
            }
        }
```
(This sits after `_prism_cspray = c_spray;` and before `_prism_epoch_samples = 0;`, so `_prism_epoch_samples` still holds the ended epoch's count. It mirrors the existing `PRISM_PATHRTT` static-ofstream hook (~uec.cpp:1051). `<fstream>` is already included for PRISM_PATHRTT.) You may now drop the `(void)cut;` line since `cut` is used.

- [ ] **Step 2: Build**

Run: `cmake --build /home/leo/htsim/htsim/sim/build --target htsim_uec -j 2>&1 | tail -8`
Expected: clean build.

- [ ] **Step 3: Verify the epoch log is emitted, well-formed, and that both INCREASE and DECREASE regions are reachable**

A clean run should show INCREASE epochs; an incast run (shared bottleneck, floor high) should produce DECREASE epochs. Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter
P=prism_eval/common
mkdir -p prism_eval/_p1
# clean: 1 flow
python3 $P/gen/incast.py prism_eval/_p1/clean.cm 1 0 4000000 128 16
PRISM_EPOCH=prism_eval/_p1/clean.epoch.csv END_MS=2 PATHS=8 \
  bash $P/run_lib.sh prism reps 0 fat_tree_128_1os.topo 13 prism_eval/_p1/clean.cm flow s_clean prism_eval/_p1
# incast: 32 flows -> host0 (shared bottleneck -> high floor)
python3 $P/gen/incast.py prism_eval/_p1/incast.cm 32 0 2000000 128 16
PRISM_EPOCH=prism_eval/_p1/incast.epoch.csv END_MS=2 PATHS=8 \
  bash $P/run_lib.sh prism reps 0 fat_tree_128_1os.topo 13 prism_eval/_p1/incast.cm flow s_incast prism_eval/_p1
echo "== clean epoch rows: $(wc -l < prism_eval/_p1/clean.epoch.csv) =="
echo "== clean region histogram (col 6: 0=INC,1=HOLD,2=DEC) =="
cut -d, -f6 prism_eval/_p1/clean.epoch.csv | sort | uniq -c
echo "== incast region histogram =="
cut -d, -f6 prism_eval/_p1/incast.epoch.csv | sort | uniq -c
echo "== incast cut count (col 9) =="
awk -F, '{s+=$9} END{print s+0}' prism_eval/_p1/incast.epoch.csv
rm -rf prism_eval/_p1
```
Expected: clean epoch CSV is non-empty with 9 comma-separated columns; clean run is dominated by region `0` (INCREASE); the incast run contains region `2` (DECREASE) rows and a non-zero cut count. If incast shows **no** DECREASE rows, report DONE_WITH_CONCERNS with the histograms (it may indicate the floor never crosses target in this short run — investigate before proceeding; do not adjust thresholds to force it).

- [ ] **Step 4: Stage & checkpoint** (do NOT commit until approved)
```bash
cd /home/leo/htsim
git add htsim/sim/uec.cpp
git commit -m "prism P1: env-gated PRISM_EPOCH per-epoch log (C_cc/C_spray/region/cut)"
```

---

### Task 5: Offline cross-check tool + selftest (TDD) + real-run check

**Files:**
- Create: `htsim/sim/datacenter/prism_eval/common/prism_epoch_check.py`
- Create/Test: `htsim/sim/datacenter/prism_eval/common/tests/test_prism_epoch_check.py`

The check: for each flow, use the **logged epoch-boundary times** to window the per-ACK `PRISM_PATHRTT` samples, recompute `C_cc = min q`, `C_spray = max q − min q` (with `q = max(raw_rtt − base_rtt, 0)`), and compare to the logged epoch values. Using the logged boundaries avoids re-deriving epoch timing offline. A small fraction of epochs may differ (rare RTS/avg-delay-fallback samples), so the tool asserts a high match rate and reports mismatches.

- [ ] **Step 1: Write the failing selftest**

Create `htsim/sim/datacenter/prism_eval/common/tests/test_prism_epoch_check.py`:
```python
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import prism_epoch_check as pec  # noqa: E402

def test_match():
    # pathrtt rows: time_ns,flow,path,raw_rtt_ns,ecn,cwnd ; base_rtt = 1000 (from epoch log)
    # flow 7, base 1000. Epoch A boundary at t=100 with samples raw {1300,1100} -> q {300,100}
    #   -> C_cc=100, C_spray=200. Epoch B boundary at t=200 with raw {1500} -> q {500}
    #   -> C_cc=500, C_spray=0.
    pathrtt = [
        (10, 7, 0, 1300, 0, 0),
        (50, 7, 0, 1100, 0, 0),
        (150, 7, 0, 1500, 0, 0),
    ]
    # epoch rows: time_ns,flow,base_rtt_ns,C_cc_ns,C_spray_ns,region,cwnd,samples,cut
    epochs = [
        (100, 7, 1000, 100, 200, 0, 0, 2, 0),
        (200, 7, 1000, 500, 0,   0, 0, 1, 0),
    ]
    res = pec.check(pathrtt, epochs)
    assert res["epochs"] == 2, res
    assert res["matched"] == 2, res
    assert res["match_rate"] == 1.0, res
    print("ok cross-check exact")

if __name__ == "__main__":
    test_match()
    print("ALL PASS")
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /home/leo/htsim/htsim/sim/datacenter/prism_eval/common/tests && python3 test_prism_epoch_check.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'prism_epoch_check'`.

- [ ] **Step 3: Write the tool**

Create `htsim/sim/datacenter/prism_eval/common/prism_epoch_check.py`:
```python
#!/usr/bin/env python3
"""Cross-check PRISM's per-epoch C_cc/C_spray log against an offline recompute from the
per-ACK PRISM_PATHRTT log. For each flow, the logged epoch-boundary timestamps define the
windows; within each window we recompute C_cc=min q, C_spray=max q-min q with
q=max(raw_rtt-base_rtt,0), and compare to the logged values. A few epochs may legitimately
differ (rare RTS / avg-delay-fallback samples), so we report a match rate.
Usage: prism_epoch_check.py <pathrtt.csv> <epoch.csv> [min_rate]
"""
import sys

def _read_csv(path, ncols):
    rows = []
    with open(path) as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln:
                continue
            parts = ln.split(",")
            if len(parts) < ncols:
                continue
            rows.append(tuple(int(float(x)) for x in parts[:ncols]))
    return rows

def check(pathrtt, epochs, tol_ns=2):
    """pathrtt: rows (time,flow,path,raw_rtt,ecn,cwnd). epochs: rows
    (time,flow,base,C_cc,C_spray,region,cwnd,samples,cut). Returns dict with counts."""
    # group per flow, sorted by time
    pr_by_flow = {}
    for r in pathrtt:
        pr_by_flow.setdefault(r[1], []).append(r)
    for f in pr_by_flow:
        pr_by_flow[f].sort(key=lambda r: r[0])
    ep_by_flow = {}
    for e in epochs:
        ep_by_flow.setdefault(e[1], []).append(e)
    for f in ep_by_flow:
        ep_by_flow[f].sort(key=lambda e: e[0])

    total = 0
    matched = 0
    mismatches = []
    for flow, eps in ep_by_flow.items():
        prs = pr_by_flow.get(flow, [])
        prev_t = -1
        for (etime, _f, base, ccc, cspray, _region, _cwnd, _samples, _cut) in eps:
            window = [r for r in prs if prev_t < r[0] <= etime]
            prev_t = etime
            qs = [max(r[3] - base, 0) for r in window]
            total += 1
            if not qs:
                mismatches.append((flow, etime, "no-samples"))
                continue
            off_ccc = min(qs)
            off_cspray = max(qs) - off_ccc
            if abs(off_ccc - ccc) <= tol_ns and abs(off_cspray - cspray) <= tol_ns:
                matched += 1
            else:
                mismatches.append((flow, etime, f"logged Ccc={ccc} Cspray={cspray} "
                                                 f"offline Ccc={off_ccc} Cspray={off_cspray}"))
    return {"epochs": total, "matched": matched,
            "match_rate": (matched / total) if total else 0.0,
            "mismatches": mismatches}

def main():
    pathrtt = _read_csv(sys.argv[1], 6)
    epochs = _read_csv(sys.argv[2], 9)
    min_rate = float(sys.argv[3]) if len(sys.argv) > 3 else 0.9
    res = check(pathrtt, epochs)
    print(f"epochs={res['epochs']} matched={res['matched']} match_rate={res['match_rate']:.3f}")
    for m in res["mismatches"][:10]:
        print("  mismatch:", m)
    if res["match_rate"] < min_rate:
        print(f"FAIL: match_rate {res['match_rate']:.3f} < {min_rate}")
        sys.exit(1)
    print("ok prism_epoch_check")

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the selftest to verify it passes**

Run: `cd /home/leo/htsim/htsim/sim/datacenter/prism_eval/common/tests && python3 test_prism_epoch_check.py`
Expected: `ok cross-check exact` / `ALL PASS`.

- [ ] **Step 5: Run the cross-check on a real dual-logged PRISM run**

Run (asymmetric scenario, both logs on):
```bash
cd /home/leo/htsim/htsim/sim/datacenter
P=prism_eval/common
mkdir -p prism_eval/_p1
python3 $P/gen/incast.py prism_eval/_p1/a.cm 16 0 4000000 128 16
PRISM_EPOCH=prism_eval/_p1/a.epoch.csv PRISM_PATHRTT=prism_eval/_p1/a.pathrtt.csv \
  END_MS=2 PATHS=8 bash $P/run_lib.sh prism reps 12 fat_tree_128_1os.topo 13 \
  prism_eval/_p1/a.cm flow s_a prism_eval/_p1
python3 $P/prism_epoch_check.py prism_eval/_p1/a.pathrtt.csv prism_eval/_p1/a.epoch.csv 0.9
rm -rf prism_eval/_p1
```
Expected: `epochs=... matched=... match_rate=>=0.90` then `ok prism_epoch_check`. If match_rate is low, the epoch accumulation is wired wrong — report DONE_WITH_CONCERNS with the printed mismatches; do NOT lower the threshold to pass.

- [ ] **Step 6: Stage & checkpoint** (do NOT commit until approved)
```bash
cd /home/leo/htsim
git add -f htsim/sim/datacenter/prism_eval/common/prism_epoch_check.py htsim/sim/datacenter/prism_eval/common/tests/test_prism_epoch_check.py
git commit -m "prism P1: offline epoch-log cross-check tool + selftest"
```

---

### Task 6: Regression + done-criteria roundup

**Files:** none (verification only).

- [ ] **Step 1: Confirm NSCC still runs and is sane (no regression from the PRISM additions)**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter
P=prism_eval/common
mkdir -p prism_eval/_p1
python3 $P/gen/incast.py prism_eval/_p1/n.cm 1 0 4000000 128 16
END_MS=2 PATHS=8 bash $P/run_lib.sh nscc reps 0 fat_tree_128_1os.topo 13 prism_eval/_p1/n.cm flow s_n prism_eval/_p1
python3 - prism_eval/_p1/s_n.flow.txt $P/metrics.py <<'PY'
import sys, importlib.util as u
spec=u.spec_from_file_location("metrics", sys.argv[2]); m=u.module_from_spec(spec); spec.loader.exec_module(m)
s=m.fct_stats(sys.argv[1]); print("NSCC FCT:", s)
assert s["completed"]==1 and 0.0002 < s["avg_s"] < 0.002, s
print("ok nscc unaffected")
PY
rm -rf prism_eval/_p1
```
Expected: `NSCC FCT: {...}` then `ok nscc unaffected` (NSCC path is separate; PRISM additions must not change it).

- [ ] **Step 2: Re-run all P0 + P1 selftests (regression)**

Run:
```bash
cd /home/leo/htsim/htsim/sim/datacenter/prism_eval/common/tests
python3 test_generators.py && python3 test_metrics.py && python3 test_prism_epoch_check.py
g++ -std=c++17 -I/home/leo/htsim/htsim/sim test_prism_decompose.cpp -o /tmp/tpd && /tmp/tpd
```
Expected: each ends with `ALL PASS` (and the C++ test prints `ALL PASS`).

- [ ] **Step 3: Done-criteria checklist (report each)**

Confirm and report:
1. `prism_decompose.h` unit test passes (decide_region four quadrants + md_factor). ✅/❌
2. `-sender_cc_algo prism` builds, runs, completes a flow with sane FCT. ✅/❌
3. `PRISM_EPOCH` log is well-formed; INCREASE reachable (clean) and DECREASE reachable (incast). ✅/❌
4. Offline cross-check match_rate ≥ 0.90 on a real dual-logged run. ✅/❌
5. NSCC unaffected; all P0+P1 selftests pass. ✅/❌

- [ ] **Step 4: Stage & checkpoint** (nothing to stage; report completion)

No files changed in this task. Report the done-criteria results. (P1 is then complete; the P5 ablation variants and the P2 experiment runs are out of scope.)

---

## Done criteria for P1
- PRISM is selectable (`-sender_cc_algo prism`), builds, and runs end-to-end producing FCT.
- The epoch decomposition is wired correctly (cross-check ≥ 0.90 vs offline recompute).
- All four-quadrant regions are reachable in the expected scenarios (clean→INCREASE, incast→DECREASE).
- NSCC behavior is unaffected; all selftests (P0 + P1) pass.

## Out of scope (later phases)
- P5 ablation variants (Average-as-Floor, No-Spread-Gate, Spread-as-Decrease, Long-Epoch, Oracle-PRISM) — only the `decide_region`/`md_factor` decision points are pre-positioned.
- P2+ experiment runs, STrack (P3), and any PRISM-vs-baseline comparison.
