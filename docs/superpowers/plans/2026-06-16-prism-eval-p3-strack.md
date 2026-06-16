# PRISM Eval P3 — STrack coupled-SOTA baseline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add STrack as a coupled-SOTA congestion-control baseline (`-sender_cc_algo strack`) by porting STrack's Algorithm-4 CC core into `UecSrc`, running on the shared REPS spray, and evaluate it as a 4th arm in the delay-driven Experiment A.

**Architecture:** Pure decision-tree logic in a header-only `strack_cc.h` (mirrors `prism_decompose.h`), wired into `UecSrc::updateCwndOnAck_STRACK` which reuses NSCC's vetted primitives (`quick_adapt`, `proportional_increase`, `multiplicative_decrease`, `fulfill_adjustment`) and adds one new action (`starvation_increase`). Spray/sink/trimming/loss are held fixed (shared with NSCC/PRISM) so the CC decision tree is the only variable. A mandatory STrack-vs-NSCC distinctness check guards against producing an NSCC clone.

**Tech Stack:** C++ (htsim, CMake/`htsim_uec`), Python 3 + matplotlib (figures), bash (repro/harness).

**Spec:** `docs/superpowers/specs/2026-06-16-prism-eval-p3-strack-design.md`

**Commit policy (user standing rule):** the user has said *do NOT `git commit` unless explicitly asked*. The "Commit" steps below stage the work and write the message, but the actual `git commit` is **batched to the phase milestone and runs only on the user's say-so**. Subagents: stage + report; the controller asks the user before committing.

---

## File Structure

| File | New/Mod | Responsibility |
|---|---|---|
| `htsim/sim/strack_cc.h` | **New** | Pure STrack Algorithm-4 decision tree (`strack::decide_action`), `uint64_t` times, no htsim deps, header-only `selftest`-able. |
| `htsim/sim/datacenter/prism_eval/common/tests/test_strack_cc.cpp` | **New** | Standalone unit test of `decide_action` (all 4 actions + boundaries). |
| `htsim/sim/uec.h` | Mod | `STRACK` enum value; `_strack_beta`/`_strack_h` static params; `updateCwndOnAck_STRACK`/`starvation_increase` decls. |
| `htsim/sim/uec.cpp` | Mod | static param defs; `case STRACK` dispatch; `updateCwndOnAck_STRACK` + `starvation_increase` bodies; `#include "strack_cc.h"`. |
| `htsim/sim/datacenter/main_uec.cpp` | Mod | `-sender_cc_algo strack` + `-strack_beta`/`-strack_h` arg parse. |
| `htsim/sim/datacenter/main_uec_sf.cpp` | Mod | `-sender_cc_algo strack` arg parse (consistency). |
| `htsim/sim/datacenter/prism_eval/expA_delaydriven/repro.sh` | Mod | 4th arm (`strack reps`) per cell + STrack mechanism run + build/run the C++ logic test. |
| `htsim/sim/datacenter/prism_eval/expA_delaydriven/make_figs.py` | Mod | add `("strack","STrack","strack")` baseline triple. |
| `htsim/sim/datacenter/prism_eval/common/perf_figs.py` | Mod | mechanism: add STrack cwnd(t) line + NSCC-vs-STrack distinctness print. |
| `htsim/sim/datacenter/prism_eval/expA_delaydriven/README.md` | Mod | record the 4-arm result honestly (controller-owned, Task 6). |

---

## Task 1: `strack_cc.h` pure-logic header + unit test (TDD)

**Files:**
- Create: `htsim/sim/strack_cc.h`
- Test: `htsim/sim/datacenter/prism_eval/common/tests/test_strack_cc.cpp`

- [ ] **Step 1: Write the failing test** — `test_strack_cc.cpp`

```cpp
#include "strack_cc.h"
#include <cassert>
#include <cstdio>
using namespace strack;
// target = 6, 2*target = 12 (picosecond-scale integers; units irrelevant to the logic).
int main() {
    // No ECN (ecn=false): increase branch.
    assert(decide_action(false, 3, 99, 6) == INCREASE_PROP);    // delay<target -> prop increase
    assert(decide_action(false, 13, 99, 6) == STARVATION_BUMP); // delay>2*target, no ECN -> beta bump
    assert(decide_action(false, 6, 99, 6) == HOLD);             // delay==target (not <) -> hold
    assert(decide_action(false, 9, 99, 6) == HOLD);             // target<delay<2*target -> hold
    assert(decide_action(false, 12, 99, 6) == HOLD);            // delay==2*target (not >) -> hold
    // ECN marked (ecn=true): decrease branch, keyed on AVG delay.
    assert(decide_action(true, 99, 9, 6) == MULT_DECREASE);     // avg>target -> MD
    assert(decide_action(true, 99, 6, 6) == HOLD);              // avg==target (not >) -> hold (path switch)
    assert(decide_action(true, 99, 3, 6) == HOLD);              // avg<target -> hold (Scenario #2)
    printf("ok strack decide_action\n");
    return 0;
}
```

- [ ] **Step 2: Run test to verify it fails (no header yet)**

Run: `cd htsim/sim && g++ -I. datacenter/prism_eval/common/tests/test_strack_cc.cpp -o /tmp/test_strack_cc`
Expected: FAIL — `fatal error: strack_cc.h: No such file or directory`.

- [ ] **Step 3: Write minimal implementation** — `htsim/sim/strack_cc.h`

```cpp
#ifndef STRACK_CC_H
#define STRACK_CC_H
// STrack congestion control — pure decision logic, no htsim dependencies (uint64_t times,
// picoseconds). Ported from STrack paper Algorithm 4 (Strack/paper/, §3.2). Used by
// UecSrc::updateCwndOnAck_STRACK and unit-tested standalone. The coupled-SOTA baseline:
// ECN-gated, and its multiplicative decrease keys off the AVERAGE delay (the signal
// conflation PRISM's decomposition is contrasted against). See prism_decompose.h for the peer.
#include <cstdint>

namespace strack {

enum Action { INCREASE_PROP = 0, STARVATION_BUMP = 1, MULT_DECREASE = 2, HOLD = 3 };

// STrack Algorithm 4 decision tree. `target` = base target queuing delay (= _target_Qdelay).
//  - No ECN  -> increase branch: prop-increase if delay<target; beta starvation bump if the
//    queue has drained (no ECN) yet this packet still saw delay>2*target; else hold.
//  - ECN set -> decrease branch: multiplicative decrease iff the AVERAGE delay exceeds target;
//    otherwise hold (mark with low avg => switch path, keep window: STrack Scenario #2).
// ">" / "<" are strict; equality holds (no action) — matches the paper's threshold semantics
// and keeps proportional_increase's `target>delay` precondition satisfied on the INCREASE path.
inline Action decide_action(bool ecn, uint64_t delay, uint64_t avg_delay, uint64_t target) {
    if (!ecn) {
        if (delay > 2 * target) return STARVATION_BUMP;
        if (delay < target)     return INCREASE_PROP;
        return HOLD;
    }
    if (avg_delay > target) return MULT_DECREASE;
    return HOLD;
}

}  // namespace strack
#endif  // STRACK_CC_H
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd htsim/sim && g++ -I. datacenter/prism_eval/common/tests/test_strack_cc.cpp -o /tmp/test_strack_cc && /tmp/test_strack_cc`
Expected: PASS — prints `ok strack decide_action`.

- [ ] **Step 5: Stage (commit batched to milestone — see Commit policy)**

```bash
git add htsim/sim/strack_cc.h htsim/sim/datacenter/prism_eval/common/tests/test_strack_cc.cpp
# commit message (run only on user approval at milestone):
#   prism_eval P3: STrack Algorithm-4 decision tree (pure logic) + unit test
```

---

## Task 2: Wire STRACK into `UecSrc` (enum, params, dispatch, controller body)

**Files:**
- Modify: `htsim/sim/uec.h` (enum ~219; method decls ~310; param decls ~368)
- Modify: `htsim/sim/uec.cpp` (static defs ~97; dispatch ~601; new method bodies near `updateCwndOnAck_PRISM` ~1473; `#include` at top)

- [ ] **Step 1: Add the enum value** — `uec.h` line 219

Change:
```cpp
    enum Sender_CC { DCTCP, NSCC, CONSTANT, PRISM};
```
to:
```cpp
    enum Sender_CC { DCTCP, NSCC, CONSTANT, PRISM, STRACK};
```

- [ ] **Step 2: Declare the new params** — `uec.h`, in the PRISM params block (after `_prism_kappa`, ~line 370)

```cpp
    // STrack (coupled-SOTA baseline) params. CC core reuses NSCC's _gamma/_eta/_target_Qdelay.
    static double _strack_beta;   // starvation-bump scale (Table 1 beta; dimensionless, default 5.0)
    static double _strack_h;      // per-hop target scale; default 0 (fixed target, see spec §3)
```

- [ ] **Step 3: Declare the new methods** — `uec.h`, after `updateCwndOnAck_PRISM` decl (~line 311)

```cpp
    void updateCwndOnAck_STRACK(bool skip, simtime_picosec delay, mem_b newly_acked_bytes);
    void starvation_increase();
```

- [ ] **Step 4: Define the statics** — `uec.cpp`, after the PRISM static defs (~line 98)

```cpp
double UecSrc::_strack_beta = 5.0;   // STrack Table 1 beta scale; tuned in P5 sensitivity
double UecSrc::_strack_h    = 0.0;   // fixed target (no live hop_count plumbing); see spec §3
```

- [ ] **Step 5: Add the include** — `uec.cpp`, near the other prism include

Find the line that includes `prism_decompose.h` (top of file with the other includes) and add directly after it:
```cpp
#include "strack_cc.h"
```
(If `prism_decompose.h` is included inside a function instead, place `#include "strack_cc.h"` at the top of `uec.cpp` with the other `#include`s.)

- [ ] **Step 6: Add the dispatch case** — `uec.cpp` ~line 601, after the `PRISM` case

```cpp
            case STRACK:
                updateCwndOnAck = &UecSrc::updateCwndOnAck_STRACK;
                updateCwndOnNack = &UecSrc::updateCwndOnNack_NSCC;  // reuse NSCC NACK/loss handling
                break;
```

- [ ] **Step 7: Implement the controller body** — `uec.cpp`, immediately after `updateCwndOnAck_PRISM` (and its helpers) end (~after line 1570)

```cpp
// STrack (coupled SOTA): Algorithm-4 ECN-gated controller, MD keyed on AVERAGE delay.
// Reuses NSCC primitives; the only STrack-specific action is the beta starvation bump.
// Distinct from NSCC: where NSCC runs an aggressive fair_increase on !ecn && delay>=target,
// STrack holds (fairness via periodic eta only) and bumps only when delay>2*target. See
// strack_cc.h / spec 2026-06-16-prism-eval-p3-strack-design.md.
void UecSrc::updateCwndOnAck_STRACK(bool skip, simtime_picosec delay, mem_b newly_acked_bytes) {
    if (quick_adapt(false, skip, delay))   // reuse NSCC achievedBDP fast-converge + loss/quick adapt
        return;

    simtime_picosec avg = get_avg_delay();
    switch (strack::decide_action(skip, delay, avg, _target_Qdelay)) {
        case strack::INCREASE_PROP:
            proportional_increase(newly_acked_bytes, delay);  // _target_Qdelay>delay holds here
            break;
        case strack::STARVATION_BUMP:
            starvation_increase();
            break;
        case strack::MULT_DECREASE:
            multiplicative_decrease();  // self-gates avg>target & once-per-base_rtt; keys on avg
            break;
        case strack::HOLD:
            break;
    }

    set_cwnd_bounds();

    if (_received_bytes > _adjust_bytes_threshold ||
        eventlist().now() - _last_adjust_time > _adjust_period_threshold) {
        fulfill_adjustment();  // applies accumulated _inc_bytes + periodic _eta
    }

    set_cwnd_bounds();

    if (_flow.flow_id() == _debug_flowid)
        cout << timeAsUs(eventlist().now()) << " flowid " << _flow.flow_id()
             << " final _strack_cwnd " << _cwnd << " _basertt " << timeAsUs(_base_rtt) << endl;
}

// STrack Algorithm 4 Line #7: cwnd += beta/cwnd. beta carried in mtu^2 units via _strack_beta
// (dimensionless scale) so the per-ACK bump is self-clocking like Swift's ai/cwnd.
void UecSrc::starvation_increase() {
    if (_cwnd > 0) {
        mem_b bump = (mem_b)(_strack_beta * (double)_mtu * (double)_mtu / (double)_cwnd);
        _cwnd += max(bump, (mem_b)1);
    }
}
```

- [ ] **Step 8: Build `htsim_uec`**

Run: `cd htsim/sim/build && cmake --build . --target htsim_uec -j 2>&1 | tail -20`
Expected: links cleanly, produces the `htsim_uec` binary. (If the build dir differs, use the same build command the repo's existing `htsim_uec` was built with.)

- [ ] **Step 9: Re-run the Task-1 logic test (regression)**

Run: `cd htsim/sim && g++ -I. datacenter/prism_eval/common/tests/test_strack_cc.cpp -o /tmp/test_strack_cc && /tmp/test_strack_cc`
Expected: PASS — `ok strack decide_action`.

- [ ] **Step 10: Stage (commit batched to milestone)**

```bash
git add htsim/sim/uec.h htsim/sim/uec.cpp
# message: prism_eval P3: port STrack CC core into UecSrc (-sender_cc_algo strack)
```

---

## Task 3: Arg parsing (`strack` algo + `-strack_beta`/`-strack_h`) + smoke run

**Files:**
- Modify: `htsim/sim/datacenter/main_uec.cpp` (cc-algo block ~205–219; flag block near prism ~193–199)
- Modify: `htsim/sim/datacenter/main_uec_sf.cpp` (cc-algo block ~101–116)

- [ ] **Step 1: Add `strack` to the cc-algo parser** — `main_uec.cpp`, after the `prism` branch (~line 216)

```cpp
            else if (!strcmp(argv[i+1],"strack"))
                UecSrc::_sender_cc_algo = UecSrc::STRACK;
```

- [ ] **Step 2: Add the STrack flag parsers** — `main_uec.cpp`, after the `-prism_kappa` block (~line 199)

```cpp
        } else if (!strcmp(argv[i],"-strack_beta")) {
            UecSrc::_strack_beta = atof(argv[i+1]);
            cout << "strack_beta " << UecSrc::_strack_beta << endl;
        } else if (!strcmp(argv[i],"-strack_h")) {
            UecSrc::_strack_h = atof(argv[i+1]);
            cout << "strack_h " << UecSrc::_strack_h << endl;
```
(Insert as additional `else if` branches in the same argv parse chain; keep the trailing structure consistent with the surrounding `-prism_*` branches.)

- [ ] **Step 3: Add `strack` to `main_uec_sf.cpp`** — after its `prism` branch (~line 108)

```cpp
            else if (!strcmp(argv[i + 1], "strack"))
                UecSrc::_sender_cc_algo = UecSrc::STRACK;
```

- [ ] **Step 4: Rebuild**

Run: `cd htsim/sim/build && cmake --build . --target htsim_uec -j 2>&1 | tail -20`
Expected: clean build.

- [ ] **Step 5: Smoke-run STrack on the existing delay-driven workload (1 cell)**

Run (from `htsim/sim/datacenter`):
```bash
PATHS=8 END_MS=8 EXTRA_ARGS="-disable_trim" \
  bash prism_eval/common/run_lib.sh strack reps 8 fat_tree_128_1os.topo 13 \
  prism_eval/expA_delaydriven/data/m2m.cm flow,sink smoke_strack /tmp/strack_smoke
```
Expected: runs to completion; `/tmp/strack_smoke/smoke_strack.flow.txt` exists and contains `FINISH` FLOW_EVENT lines (flows complete). Confirm stdout shows `sender based algo strack`.

- [ ] **Step 6: Sanity-check the smoke output**

Run:
```bash
cd htsim/sim/datacenter && python3 -c "import sys; sys.path.insert(0,'prism_eval/common'); import metrics; \
print('goodput', metrics.aggregate_goodput_gbps('/tmp/strack_smoke/smoke_strack.flow.txt')); \
print('fct', metrics.fct_stats('/tmp/strack_smoke/smoke_strack.flow.txt')['completion_rate'])"
```
Expected: a finite goodput (Gbps) and a completion_rate in (0,1]. (Values judged honestly in Task 6, not gated here.)

- [ ] **Step 7: Stage (commit batched to milestone)**

```bash
git add htsim/sim/datacenter/main_uec.cpp htsim/sim/datacenter/main_uec_sf.cpp
# message: prism_eval P3: parse -sender_cc_algo strack + -strack_beta/-strack_h
```

---

## Task 4: Extend the delay-driven Exp A harness with the STrack 4th arm

**Files:**
- Modify: `htsim/sim/datacenter/prism_eval/expA_delaydriven/repro.sh`
- Modify: `htsim/sim/datacenter/prism_eval/expA_delaydriven/make_figs.py`
- Modify: `htsim/sim/datacenter/prism_eval/common/perf_figs.py`

- [ ] **Step 1: Add the STrack baseline triple** — `make_figs.py`

Change the `BASELINES` list to include STrack (color `strack` already exists in `plot_style.COLORS`):
```python
BASELINES = [("ops", "OPS+NSCC", "ops"), ("reps", "REPS+NSCC", "reps"),
             ("strack", "STrack", "strack"), ("prism", "PRISM", "prism")]
```

- [ ] **Step 2: Add the STrack sweep arm** — `repro.sh`, inside the `for f ... for s ...` loop, after the `prism` run

```bash
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" bash "$COMMON/run_lib.sh" strack reps "$f" "$TOPO" "$s" "$CM" flow,sink "expA_strack_f${f}_s${s}" "$OUT"
```

- [ ] **Step 3: Add the STrack mechanism run** — `repro.sh`, in the mechanism block (failed=8, seed=13), after the prism mechanism run

```bash
PATHS=8 END_MS="$ENDV" EXTRA_ARGS="$DD" PRISM_PATHRTT="$OUT/expA_strack_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" strack reps 8 "$TOPO" 13 "$CM" flow,sink expA_strack_mech "$OUT"
```

- [ ] **Step 4: Build + run the C++ logic test in the selftest preamble** — `repro.sh`, in the `== self-test analysis ==` block (after the python selftests)

```bash
( cd "$DC/.." && g++ -I. datacenter/prism_eval/common/tests/test_strack_cc.cpp -o /tmp/test_strack_cc && /tmp/test_strack_cc )
```
(`$DC` is `sim/datacenter`; `$DC/..` is `sim`, where `strack_cc.h` lives. Adjust the relative path if `repro.sh`'s `DC` differs — the goal is `g++ -I<sim> .../test_strack_cc.cpp`.)

- [ ] **Step 5: Add the NSCC-vs-STrack distinctness print + STrack cwnd line** — `perf_figs.py`, in `render_mechanism`

After the existing `prism_pr`/`reps_pr` cwnd plotting, add a STrack arm and the distinctness print:
```python
    strack_pr = os.path.join(data_dir, f"{tag_prefix}_strack_mech.pathrtt.csv")
    if os.path.exists(strack_pr):
        ts, cs = cwnd_series(strack_pr)
        ax_cw.plot(ts, cs, color=plot_style.COLORS["strack"], lw=2.0, label="STrack")
        strack_dec = metrics.count_cwnd_cuts_from_pathrtt(strack_pr)
        print(f"[{fig_stem}] DISTINCTNESS (per-ACK cwnd-decreases @failed={mech_failed}): "
              f"STrack={strack_dec}  REPS+NSCC={reps_dec}  "
              f"(must differ measurably; identical => STrack collapsed to NSCC, revisit spec Approach B)")
```
(Place after `reps_dec` is computed and `ax_cw` is built, before `plt.tight_layout()`. `cwnd_series` and `reps_dec` already exist in this function.)

- [ ] **Step 6: Validate the wiring on a 1-seed slice (not the full sweep)**

Run (from `htsim/sim/datacenter`):
```bash
cd htsim/sim/datacenter
SEEDS_BACKUP_NOTE="full sweep is Task 6; here just prove the 4th arm wires up"
for f in 0 8; do
  PATHS=8 END_MS=8 EXTRA_ARGS="-disable_trim" bash prism_eval/common/run_lib.sh strack reps "$f" fat_tree_128_1os.topo 13 prism_eval/expA_delaydriven/data/m2m.cm flow,sink "expA_strack_f${f}_s13" prism_eval/expA_delaydriven/data
done
```
Expected: produces `expA_strack_f0_s13.flow.txt` and `expA_strack_f8_s13.flow.txt`. (This is a wiring check; the figure + full grid come in Task 6.)

- [ ] **Step 7: Verify `make_figs.py --selftest` still passes with 4 baselines**

Run: `cd htsim/sim/datacenter/prism_eval/expA_delaydriven && python3 make_figs.py --selftest`
Expected: `ok perf_figs aggregation selftest` (the selftest only fabricates ops/reps/prism; the 4th baseline must not break aggregation — it tolerates missing STrack files via the `if not os.path.exists` guard in `aggregate`).

- [ ] **Step 8: Stage (commit batched to milestone)**

```bash
git add htsim/sim/datacenter/prism_eval/expA_delaydriven/repro.sh \
        htsim/sim/datacenter/prism_eval/expA_delaydriven/make_figs.py \
        htsim/sim/datacenter/prism_eval/common/perf_figs.py
# message: prism_eval P3: STrack 4th arm in delay-driven Exp A harness + distinctness check
```

---

## Task 5: Full delay-driven Exp A run (4 arms) — controller-owned

**Files:** none (produces gitignored raw data under `expA_delaydriven/data/` + regenerated figures).

- [ ] **Step 1: Run the full repro**

Run (from `htsim/sim/datacenter`): `bash prism_eval/expA_delaydriven/repro.sh`
Expected: selftests pass (incl. `ok strack decide_action`); ~100 sweep sims (4 arms × 5 failed × 5 seeds) + 4 mechanism sims; renders `figA1dd_main_perf.{png,pdf}` (now 4 lines) + `figA2dd_mechanism.{png,pdf}`; prints the per-baseline goodput/FCT table and the DISTINCTNESS line.

- [ ] **Step 2: Read the distinctness gate**

Confirm the printed `DISTINCTNESS` line shows STrack's per-ACK cwnd-decrease count **differs measurably** from REPS+NSCC's, and eyeball `figA2dd_mechanism` cwnd(t) — STrack and REPS+NSCC trajectories must be visibly distinct. If they are byte-identical, STOP and report (do not proceed to the write-up as if STrack is a valid baseline); this triggers a spec revisit (Approach B).

- [ ] **Step 3: Record completion rates honestly**

From the `[figA1dd_main_perf]` printout, note STrack's `cr=` per failed level alongside the other arms (FCT is only unconfounded where cr≈1.00, as established for the other arms at END=8).

---

## Task 6: Honest write-up + README + memory — controller-owned

**Files:**
- Modify: `htsim/sim/datacenter/prism_eval/expA_delaydriven/README.md`
- Modify (after milestone): `~/.claude/projects/-home-leo-htsim/memory/prism-eval-roadmap.md` + `MEMORY.md` pointer

- [ ] **Step 1: Update the README** with the 4-arm result table (add a STrack column/row to the goodput/avg-FCT table), the distinctness-check outcome (STrack ≠ NSCC, with the cut-count delta), and an honest verdict: does PRISM beat the coupled-but-averaging STrack under asymmetry, tie, or lose? State it straight; no tuning to force an outcome.

- [ ] **Step 2: Note STrack-specific caveats** (e.g., if STrack lands between REPS+NSCC and PRISM, or if the β default looks off — flag β sensitivity as a P5 item, do not re-tune here).

- [ ] **Step 3: Update memory** (`prism-eval-roadmap.md` status line: P3 STrack committed + one-line result) and the `MEMORY.md` pointer — only after the user approves the milestone commit.

- [ ] **Step 4: Milestone commit (ON USER APPROVAL ONLY)**

Per the Commit policy, ask the user before committing. On approval:
```bash
git add -f htsim/sim/datacenter/prism_eval/expA_delaydriven/figs/figA1dd_main_perf.* \
           htsim/sim/datacenter/prism_eval/expA_delaydriven/figs/figA2dd_mechanism.*
git add htsim/sim/datacenter/prism_eval/expA_delaydriven/README.md
git commit -m "prism_eval P3: STrack coupled-SOTA baseline + 4-arm delay-driven Exp A"
```
(Raw `data/` stays gitignored; figures are force-added per the reproducibility standard.)

---

## Self-Review (against the spec)

**Spec coverage:**
- §2 deltas (conservative no-ECN branch, β bump, ECN-gated tree as pure fn) → Task 1 (`decide_action`) + Task 2 (`starvation_increase`, dispatch). ✓
- §3 simplifications (fixed target/`h=0`, reuse `quick_adapt`, reuse NSCC NACK) → Task 2 Steps 6–7 (`_strack_h=0`, `quick_adapt` early-return, `updateCwndOnNack_NSCC`). ✓
- §4 controller (enum/dispatch/arg/params/bodies) → Tasks 2 & 3. ✓
- §5 experiment (4th arm + 4-line figs) → Task 4. ✓
- §6 distinctness gate + honesty → Task 4 Step 5 (print) + Task 5 Step 2 (gate) + Task 6 (honest write-up). ✓
- §7 reproducibility (selftests in repro, seeds {13..17}, figures `git add -f`, raw gitignored) → Task 4 Step 4, Task 5, Task 6 Step 4. ✓

**Placeholder scan:** every code step shows full code; no TBD/TODO; β units made concrete (`_strack_beta * _mtu² / _cwnd`). ✓

**Type/name consistency:** `strack::Action {INCREASE_PROP, STARVATION_BUMP, MULT_DECREASE, HOLD}` used identically in `strack_cc.h`, the test, and the dispatch switch; `decide_action(bool,uint64_t,uint64_t,uint64_t)` signature matches the call (`skip`,`delay`,`avg`,`_target_Qdelay` — all `simtime_picosec`=`uint64_t`); `_strack_beta`/`_strack_h` declared (uec.h) + defined (uec.cpp) + parsed (main_uec.cpp) consistently; `updateCwndOnAck_STRACK`/`starvation_increase` decl ↔ def ↔ dispatch consistent. ✓
