# PRISM loss/NACK decomposition — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend PRISM's congestion decomposition from the delay signal to the loss/trim-NACK signal (a flag-gated `updateCwndOnNack_PRISM`) so PRISM holds its window on reroutable (concentrated) loss and cuts only on uniform loss, then test whether this lets PRISM beat REPS+NSCC in the trimming regime (where P2 tied).

**Architecture:** Pure decision logic `prism::decide_loss` in `prism_decompose.h` (unit-tested). `UecSrc` maintains per-epoch sets of distinct entropies that ACK'd-good vs fabric-NACK'd; on a NACK, `updateCwndOnNack_PRISM` applies the four-quadrant loss rule (HOLD = no cwnd change; CUT = the NSCC NACK response). Gated by `-prism_loss_decomp` (default OFF → byte-identical to today's PRISM). Retransmission and REPS rerouting are untouched. A new trimming-regime eval group compares PRISM-delay-only vs PRISM-loss-decomp.

**Tech Stack:** C++ (htsim, `htsim_uec` via CMake), Python 3 + matplotlib, bash.

**Spec:** `docs/superpowers/specs/2026-06-16-prism-loss-decomp-design.md`

**Commit policy (user standing rule):** do NOT `git commit` unless explicitly asked. "Stage" steps `git add` only; the milestone commit (Task 6) runs solely on the user's approval.

---

## File Structure

| File | New/Mod | Responsibility |
|---|---|---|
| `htsim/sim/prism_decompose.h` | Mod | add `LossAction` + `decide_loss` (pure logic) next to `decide_region`. |
| `htsim/sim/datacenter/prism_eval/common/tests/test_prism_decompose.cpp` | Mod | add 5 `decide_loss` assertions. |
| `htsim/sim/uec.h` | Mod | NACK fn-ptr + `_NSCC`/`_DCTCP` decls `bool skip→uint32_t ev`; `updateCwndOnNack_PRISM` decl; per-epoch loss state members; `_prism_loss_decomp`/`_prism_loss_streak_cap` statics; `PRISM_LOSS_MIN_GOOD`. |
| `htsim/sim/uec.cpp` | Mod | rename param in `_NSCC`/`_DCTCP` defs; dispatch `PRISM→updateCwndOnNack_PRISM`; implement it; `processAck` evs_good accrual; epoch-boundary streak/reset + logging; static defs. |
| `htsim/sim/datacenter/main_uec.cpp` | Mod | parse `-prism_loss_decomp`, `-prism_loss_streak_cap`. |
| `htsim/sim/datacenter/prism_eval/expA_lossdecomp/` | **New** | `repro.sh` (4-arm trimming Exp A) + `make_figs.py` (perf_figs wrapper + loss-HOLD fraction) + `README.md` + `figs/`. |

---

## Task 1: `prism::decide_loss` pure logic + unit test (TDD)

**Files:** Modify `htsim/sim/prism_decompose.h`; Modify `htsim/sim/datacenter/prism_eval/common/tests/test_prism_decompose.cpp`

- [ ] **Step 1: Add the 5 failing assertions** to `test_prism_decompose.cpp` (before its final `printf`/`return`):

```cpp
    // decide_loss: loss four-quadrant. (last_hop, enough_evidence, clean_path_exists, streak_exceeded)
    assert(decide_loss(true,  true,  true,  false) == LOSS_CUT);   // last_hop incast -> cut
    assert(decide_loss(false, false, true,  false) == LOSS_CUT);   // not enough good-ACK evidence -> cut
    assert(decide_loss(false, true,  true,  true)  == LOSS_CUT);   // streak valve tripped -> cut
    assert(decide_loss(false, true,  true,  false) == LOSS_HOLD);  // concentrated/reroutable -> hold
    assert(decide_loss(false, true,  false, false) == LOSS_CUT);   // uniform loss -> cut
    printf("ok decide_loss\n");
```

- [ ] **Step 2: Build the test to verify it fails** (no `decide_loss` yet)

Run: `cd /home/leo/htsim/htsim/sim && g++ -I. datacenter/prism_eval/common/tests/test_prism_decompose.cpp -o /tmp/test_prism_dec`
Expected: FAIL — `error: 'decide_loss' was not declared` (and `LOSS_CUT`/`LOSS_HOLD` undeclared).

- [ ] **Step 3: Add `decide_loss` to `prism_decompose.h`** (inside `namespace prism`, after `md_factor`):

```cpp
// Loss four-quadrant rule -- the loss/NACK analog of decide_region, used by
// UecSrc::updateCwndOnNack_PRISM. Holds the window when loss is reroutable (a clean path is
// still ACKing) and cuts when loss is uniform or not reroutable. See spec 2026-06-16-prism-loss-decomp.
enum LossAction { LOSS_CUT = 0, LOSS_HOLD = 1 };

inline LossAction decide_loss(bool last_hop, bool enough_evidence,
                              bool clean_path_exists, bool streak_exceeded) {
    if (last_hop)          return LOSS_CUT;   // last-hop receiver incast -> not reroutable
    if (!enough_evidence)  return LOSS_CUT;   // too few good-ACK paths seen yet -> safe default
    if (streak_exceeded)   return LOSS_CUT;   // safety valve: held too long -> force a cut
    if (clean_path_exists) return LOSS_HOLD;  // concentrated loss, clean path exists -> hold, let REPS reroute
    return LOSS_CUT;                          // uniform loss across paths -> genuine congestion
}
```

- [ ] **Step 4: Build + run the test to verify it passes**

Run: `cd /home/leo/htsim/htsim/sim && g++ -I. datacenter/prism_eval/common/tests/test_prism_decompose.cpp -o /tmp/test_prism_dec && /tmp/test_prism_dec`
Expected: prints `ok decide_region` then `ok decide_loss` (and any existing trailing line).

- [ ] **Step 5: Stage (DO NOT COMMIT)**

```bash
git -C /home/leo/htsim add htsim/sim/prism_decompose.h htsim/sim/datacenter/prism_eval/common/tests/test_prism_decompose.cpp
```

---

## Task 2: UecSrc loss-decomposition controller (the core; one cohesive unit)

**Files:** Modify `htsim/sim/uec.h`, `htsim/sim/uec.cpp`

- [ ] **Step 1: NACK fn-ptr signature — `bool skip → uint32_t ev`** in `uec.h`.

Change the three declarations:
- line ~314: `void updateCwndOnNack_NSCC(bool skip, mem_b nacked_bytes, bool last_hop);` → `void updateCwndOnNack_NSCC(uint32_t ev, mem_b nacked_bytes, bool last_hop);`
- line ~317: `void updateCwndOnNack_DCTCP(bool skip, mem_b nacked_bytes, bool last_hop);` → `(uint32_t ev, mem_b nacked_bytes, bool last_hop);`
- line ~323: `void (UecSrc::*updateCwndOnNack)(bool skip, mem_b nacked_bytes, bool last_hop);` → `void (UecSrc::*updateCwndOnNack)(uint32_t ev, mem_b nacked_bytes, bool last_hop);`

And add the PRISM NACK decl right after the `_NSCC` one:
```cpp
    void updateCwndOnNack_PRISM(uint32_t ev, mem_b nacked_bytes, bool last_hop);
```

- [ ] **Step 2: Rename the param in the `_NSCC`/`_DCTCP` definitions** in `uec.cpp` (bodies unchanged — neither reads it; verified).
- `updateCwndOnNack_NSCC` (line ~1627): `(bool skip, ...)` → `(uint32_t ev, ...)`.
- `updateCwndOnNack_DCTCP` (line ~1237): `(bool skip, ...)` → `(uint32_t ev, ...)`.

(The call site `uec.cpp:1850` already passes `ev`; no change there.)

- [ ] **Step 3: Add per-epoch loss state + statics** to `uec.h`, immediately after the PRISM epoch-state block (after `_prism_genuine_sample` member, ~line 470):

```cpp
    // PRISM loss/NACK decomposition (flag-gated). Per-epoch distinct entropies that ACK'd-good
    // vs fabric-NACK'd; the streak is the safety valve. See prism::decide_loss.
    std::set<uint32_t> _prism_loss_evs_good;
    std::set<uint32_t> _prism_loss_evs_nacked;
    int  _prism_loss_hold_streak = 0;
    bool _prism_loss_epoch_held  = false;
```

Add to the static-params area (near `_prism_kappa`, ~line 370):
```cpp
    static bool     _prism_loss_decomp;       // -prism_loss_decomp; default false (== today's PRISM)
    static uint32_t _prism_loss_streak_cap;   // -prism_loss_streak_cap; consecutive HOLD epochs -> force cut
```
Ensure `#include <set>` is present at the top of `uec.h` (add if absent).

- [ ] **Step 4: Static defs + the `PRISM_LOSS_MIN_GOOD` constant** in `uec.cpp`, after the PRISM/STrack static defs (~line 101):

```cpp
bool     UecSrc::_prism_loss_decomp     = false;
uint32_t UecSrc::_prism_loss_streak_cap = 4;
```
And near the PRISM constants (above `updateCwndOnAck_PRISM`, by `PRISM_MIN_SAMPLES`):
```cpp
static constexpr uint32_t PRISM_LOSS_MIN_GOOD = 2;  // distinct good-ACK paths before trusting "clean path"
```

- [ ] **Step 5: Dispatch PRISM NACK to the new handler** — `uec.cpp` ~601, in the `case PRISM:` block, change:
```cpp
                updateCwndOnNack = &UecSrc::updateCwndOnNack_NSCC;  // reuse NSCC NACK/loss handling
```
to:
```cpp
                updateCwndOnNack = &UecSrc::updateCwndOnNack_PRISM;
```

- [ ] **Step 6: Implement `updateCwndOnNack_PRISM`** in `uec.cpp`, immediately after `updateCwndOnNack_NSCC` ends (~line 1652):

```cpp
// PRISM loss/NACK decomposition. Flag off -> exactly NSCC. Flag on -> hold the window on
// reroutable (concentrated) loss, cut on uniform/last-hop loss. Retransmission + REPS rerouting
// happen in processNack regardless; this only gates the cwnd response. See prism::decide_loss.
void UecSrc::updateCwndOnNack_PRISM(uint32_t ev, mem_b nacked_bytes, bool last_hop) {
    if (!_prism_loss_decomp) {            // off -> byte-identical to today's PRISM (NSCC NACK)
        updateCwndOnNack_NSCC(ev, nacked_bytes, last_hop);
        return;
    }
    if (!last_hop)
        _prism_loss_evs_nacked.insert(ev);

    bool enough = _prism_loss_evs_good.size() >= PRISM_LOSS_MIN_GOOD;
    bool clean  = false;                  // a path that ACK'd good this epoch and did NOT fabric-NACK
    for (uint32_t g : _prism_loss_evs_good)
        if (_prism_loss_evs_nacked.find(g) == _prism_loss_evs_nacked.end()) { clean = true; break; }
    bool streak_exceeded = (_prism_loss_hold_streak >= (int)_prism_loss_streak_cap);

    prism::LossAction action = prism::decide_loss(last_hop, enough, clean, streak_exceeded);

    // env-gated per-NACK loss log (mirrors PRISM_EPOCH); for the loss-HOLD-fraction metric.
    {
        static std::ofstream* prism_loss_log = [](){
            const char* p = getenv("PRISM_LOSS");
            return (p && *p) ? new std::ofstream(p) : nullptr;
        }();
        if (prism_loss_log) {
            (*prism_loss_log) << (uint64_t)timeAsNs(eventlist().now()) << ',' << flowId() << ','
                              << ev << ',' << (last_hop ? 1 : 0) << ','
                              << (action == prism::LOSS_HOLD ? 1 : 0) << '\n';
            prism_loss_log->flush();
        }
    }

    if (action == prism::LOSS_HOLD) {
        _prism_loss_epoch_held = true;    // no quick_adapt, no cwnd cut -- REPS reroutes, retransmit proceeds
        return;
    }
    updateCwndOnNack_NSCC(ev, nacked_bytes, last_hop);   // CUT: the standard NSCC NACK response
}
```

- [ ] **Step 7: Accrue good-ACK entropies** in `processAck` — `uec.cpp`, right after `_prism_genuine_sample = true;` (line ~1088):

```cpp
            if (_sender_cc_algo == PRISM && _prism_loss_decomp && !pkt.ecn_echo())
                _prism_loss_evs_good.insert(pkt.ev());   // a genuinely clean (non-ECN) path this epoch
```

- [ ] **Step 8: Epoch-boundary streak update + reset** in `updateCwndOnAck_PRISM` — `uec.cpp`, inside the epoch-boundary block, right before `_prism_epoch_samples = 0;` (line ~1563):

```cpp
        if (_prism_loss_decomp) {
            if (_prism_loss_epoch_held && !_prism_loss_evs_nacked.empty())
                _prism_loss_hold_streak++;   // persistent reroutable loss -> count toward the valve
            else
                _prism_loss_hold_streak = 0;  // a cut epoch (or no loss) resets the valve
            _prism_loss_evs_good.clear();
            _prism_loss_evs_nacked.clear();
            _prism_loss_epoch_held = false;
        }
```

- [ ] **Step 9: Build `htsim_uec`**

Run: `cd /home/leo/htsim/htsim/sim/build && cmake --build . --target htsim_uec -j 2>&1 | tail -20`
Expected: clean build (no errors about `decide_loss`, `_prism_loss_*`, `std::set`, or the signature change).

- [ ] **Step 10: Re-run the logic test (regression)**

Run: `cd /home/leo/htsim/htsim/sim && g++ -I. datacenter/prism_eval/common/tests/test_prism_decompose.cpp -o /tmp/test_prism_dec && /tmp/test_prism_dec`
Expected: `ok decide_region` + `ok decide_loss`.

- [ ] **Step 11: Smoke-run PRISM with loss-decomp ON in the trimming regime** (no `-disable_trim`)

Run (from `/home/leo/htsim/htsim/sim/datacenter`):
```bash
mkdir -p /tmp/ld_smoke
python3 prism_eval/common/gen/many2many.py /tmp/ld_smoke/m2m.cm 64 16 pairs 2000000 128 16
PATHS=8 END_MS=2 EXTRA_ARGS="-prism_loss_decomp 1" PRISM_LOSS=/tmp/ld_smoke/loss.csv \
  bash prism_eval/common/run_lib.sh prism reps 8 fat_tree_128_1os.topo 13 /tmp/ld_smoke/m2m.cm flow,sink ld_smoke /tmp/ld_smoke
grep -c "prism_loss_decomp" /tmp/ld_smoke/ld_smoke.stdout
echo "loss-log rows:"; wc -l < /tmp/ld_smoke/loss.csv
echo "fabric-NACK HOLD fraction:"; awk -F, '$4==0{t++; h+=$5} END{if(t)printf "%d/%d=%.3f\n",h,t,h/t; else print "no fabric NACKs"}' /tmp/ld_smoke/loss.csv
python3 -c "import sys;sys.path.insert(0,'prism_eval/common');import metrics;print('cr',metrics.fct_stats('/tmp/ld_smoke/ld_smoke.flow.txt')['completion_rate'])"
```
Expected: runs; `prism_loss_decomp` echoed; `loss.csv` non-empty; a finite HOLD fraction printed; completion_rate in (0,1]. (Values judged in Task 5, not gated here — but completion_rate should be sane, not collapsed.)

- [ ] **Step 12: Stage (DO NOT COMMIT)**

```bash
git -C /home/leo/htsim add htsim/sim/uec.h htsim/sim/uec.cpp
```

---

## Task 3: Arg parsing + build + smoke

**Files:** Modify `htsim/sim/datacenter/main_uec.cpp`

- [ ] **Step 1: Add the flag parsers** — `main_uec.cpp`, after the `-strack_h` block (added in P3, ~after the `-prism_kappa`/`-strack_*` chain):

```cpp
        } else if (!strcmp(argv[i],"-prism_loss_decomp")) {
            UecSrc::_prism_loss_decomp = (atoi(argv[i+1]) != 0);
            cout << "prism_loss_decomp " << UecSrc::_prism_loss_decomp << endl;
            i++;
        } else if (!strcmp(argv[i],"-prism_loss_streak_cap")) {
            UecSrc::_prism_loss_streak_cap = atoi(argv[i+1]);
            cout << "prism_loss_streak_cap " << UecSrc::_prism_loss_streak_cap << endl;
            i++;
```
(Match the surrounding value-flag index-advance — the P3 `-strack_beta` block uses a per-branch `i++`; mirror it.)

- [ ] **Step 2: Rebuild**

Run: `cd /home/leo/htsim/htsim/sim/build && cmake --build . --target htsim_uec -j 2>&1 | tail -8`
Expected: `Built target htsim_uec`.

- [ ] **Step 3: Confirm both flags parse**

Run (from `/home/leo/htsim/htsim/sim/datacenter`):
```bash
PATHS=8 END_MS=2 EXTRA_ARGS="-prism_loss_decomp 1 -prism_loss_streak_cap 6" \
  bash prism_eval/common/run_lib.sh prism reps 0 fat_tree_128_1os.topo 13 /tmp/ld_smoke/m2m.cm flow,sink ld_flagcheck /tmp/ld_smoke 2>&1 >/dev/null
grep -E "prism_loss_decomp 1|prism_loss_streak_cap 6" /tmp/ld_smoke/ld_flagcheck.stdout
```
Expected: both echo lines present.

- [ ] **Step 4: Stage (DO NOT COMMIT)**

```bash
git -C /home/leo/htsim add htsim/sim/datacenter/main_uec.cpp
```

---

## Task 4: Eval group `expA_lossdecomp/` (trimming-regime, 4 arms)

**Files:** Create `repro.sh`, `make_figs.py`, `README.md` (scaffold) under `htsim/sim/datacenter/prism_eval/expA_lossdecomp/`.

- [ ] **Step 1: Create `make_figs.py`** (thin wrapper over perf_figs + loss-HOLD fraction):

```python
#!/usr/bin/env python3
"""Trimming-regime loss-decomposition Exp A figures. Thin wrapper over common/perf_figs.py
(figL1_main_perf + figL2_mechanism) plus a loss-HOLD-fraction print from the PRISM_LOSS log.
  python3 make_figs.py            # render
  python3 make_figs.py --selftest # aggregation self-check
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))
import perf_figs  # noqa: E402

DATA = os.path.join(HERE, "data"); FIGS = os.path.join(HERE, "figs")
BASELINES = [("ops", "OPS+NSCC", "ops"), ("reps", "REPS+NSCC", "reps"),
             ("prism", "PRISM (delay-only)", "prism"), ("prismL", "PRISM (+loss-decomp)", "ccc")]
FAILED = [0, 2, 4, 8, 12]; SEEDS = [13, 14, 15, 16, 17]
XLABEL = "# constrained core->agg links (-failed), trimming regime"

def loss_hold_fraction(path):
    """fabric-NACK HOLD fraction from a PRISM_LOSS csv: time,flow,ev,last_hop,action."""
    held = total = 0
    if not os.path.exists(path):
        return None
    for ln in open(path):
        p = ln.strip().split(",")
        if len(p) < 5:
            continue
        if p[3] == "0":               # fabric NACK (!last_hop)
            total += 1; held += (p[4] == "1")
    return (held, total)

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        perf_figs.selftest()
    else:
        os.makedirs(FIGS, exist_ok=True)
        perf_figs.render_main_perf(DATA, FIGS, "expL", BASELINES, FAILED, SEEDS, "figL1_main_perf", XLABEL)
        perf_figs.render_mechanism(DATA, FIGS, "expL", "figL2_mechanism", 8)
        lf = loss_hold_fraction(os.path.join(DATA, "expL_prismL_mech.loss.csv"))
        if lf:
            print(f"[figL2_mechanism] loss-HOLD fraction @failed=8 = {lf[0]}/{lf[1]} = "
                  f"{(lf[0]/lf[1] if lf[1] else float('nan')):.3f}  (>0 => loss decomposition is active)")
        else:
            print("[figL2_mechanism] no PRISM_LOSS log found for prismL mechanism run")
```
(`perf_figs.render_mechanism` reads `expL_prism_mech.*`; the prismL arm's mechanism cwnd line is not added by the shared renderer — the loss-HOLD fraction is the prismL-specific diagnostic here. `ccc` = red, distinct from PRISM-delay-only green.)

- [ ] **Step 2: Create `repro.sh`** (trimming Exp A, 4 arms, all fresh):

```bash
#!/bin/bash
# Loss-decomposition Exp A, TRIMMING regime (P2 setup: NO -disable_trim, END=2). 4 arms:
# ops / reps / prism (delay-only, -prism_loss_decomp 0) / prismL (loss-decomp, -prism_loss_decomp 1).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; COMMON="$(cd "$HERE/../common" && pwd)"; DC="$(cd "$HERE/../.." && pwd)"
REL="prism_eval/expA_lossdecomp"; cd "$DC"
[ -x ./htsim_uec ] || { echo "ERROR: ./htsim_uec missing -- build it first"; exit 1; }
mkdir -p "$REL/data"
SEEDS="13 14 15 16 17"; FAILEDS="0 2 4 8 12"; TOPO=fat_tree_128_1os.topo; ENDV="${EXP_END:-2}"

echo "== self-tests =="
python3 "$HERE/make_figs.py" --selftest
( cd "$COMMON/tests" && python3 test_metrics.py >/dev/null && echo "ok common metrics selftest" )
( cd "$DC/.." && g++ -I. datacenter/prism_eval/common/tests/test_prism_decompose.cpp -o /tmp/test_prism_dec && /tmp/test_prism_dec )

echo "== workload (many2many 64->16 pod0, 2MB) =="
python3 "$COMMON/gen/many2many.py" "$REL/data/m2m.cm" 64 16 pairs 2000000 128 16
CM="$REL/data/m2m.cm"; OUT="$REL/data"

echo "== main sweep (trimming): 4 arms x failed{0,2,4,8,12} x 5 seeds =="
for f in $FAILEDS; do for s in $SEEDS; do
  PATHS=8 END_MS="$ENDV" bash "$COMMON/run_lib.sh" nscc oblivious "$f" "$TOPO" "$s" "$CM" flow,sink "expL_ops_f${f}_s${s}" "$OUT"
  PATHS=8 END_MS="$ENDV" bash "$COMMON/run_lib.sh" nscc reps      "$f" "$TOPO" "$s" "$CM" flow,sink "expL_reps_f${f}_s${s}" "$OUT"
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="-prism_loss_decomp 0" PRISM_EPOCH="$OUT/expL_prism_f${f}_s${s}.epoch.csv" \
    bash "$COMMON/run_lib.sh" prism reps "$f" "$TOPO" "$s" "$CM" flow,sink "expL_prism_f${f}_s${s}" "$OUT"
  PATHS=8 END_MS="$ENDV" EXTRA_ARGS="-prism_loss_decomp 1" PRISM_EPOCH="$OUT/expL_prismL_f${f}_s${s}.epoch.csv" \
    bash "$COMMON/run_lib.sh" prism reps "$f" "$TOPO" "$s" "$CM" flow,sink "expL_prismL_f${f}_s${s}" "$OUT"
done; done

echo "== mechanism (failed=8, seed=13) =="
PATHS=8 END_MS="$ENDV" PRISM_PATHRTT="$OUT/expL_reps_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" nscc reps 8 "$TOPO" 13 "$CM" flow,sink expL_reps_mech "$OUT"
PATHS=8 END_MS="$ENDV" EXTRA_ARGS="-prism_loss_decomp 0" PRISM_EPOCH="$OUT/expL_prism_mech.epoch.csv" PRISM_PATHRTT="$OUT/expL_prism_mech.pathrtt.csv" \
  bash "$COMMON/run_lib.sh" prism reps 8 "$TOPO" 13 "$CM" flow,sink expL_prism_mech "$OUT"
PATHS=8 END_MS="$ENDV" EXTRA_ARGS="-prism_loss_decomp 1" PRISM_EPOCH="$OUT/expL_prismL_mech.epoch.csv" PRISM_PATHRTT="$OUT/expL_prismL_mech.pathrtt.csv" PRISM_LOSS="$OUT/expL_prismL_mech.loss.csv" \
  bash "$COMMON/run_lib.sh" prism reps 8 "$TOPO" 13 "$CM" flow,sink expL_prismL_mech "$OUT"

echo "== render figL1 + figL2 + loss-HOLD fraction =="
python3 "$HERE/make_figs.py"
echo "== done: figs/figL1_main_perf.* figs/figL2_mechanism.* =="
```

- [ ] **Step 3: `chmod +x` + selftest the wrapper**

Run:
```bash
chmod +x /home/leo/htsim/htsim/sim/datacenter/prism_eval/expA_lossdecomp/repro.sh
cd /home/leo/htsim/htsim/sim/datacenter/prism_eval/expA_lossdecomp && python3 make_figs.py --selftest
bash -n repro.sh
```
Expected: `ok perf_figs aggregation selftest`; `bash -n` clean.

- [ ] **Step 4: 1-cell wiring check** (prism off + on produce files; loss log appears)

Run (from `/home/leo/htsim/htsim/sim/datacenter`):
```bash
cd /home/leo/htsim/htsim/sim/datacenter
python3 prism_eval/common/gen/many2many.py prism_eval/expA_lossdecomp/data/m2m.cm 64 16 pairs 2000000 128 16
for arm in "prism -prism_loss_decomp 0 expL_prism" "prismL -prism_loss_decomp 1 expL_prismL"; do set -- $arm; done
PATHS=8 END_MS=2 EXTRA_ARGS="-prism_loss_decomp 1" PRISM_LOSS=prism_eval/expA_lossdecomp/data/expL_prismL_mech.loss.csv \
  bash prism_eval/common/run_lib.sh prism reps 8 fat_tree_128_1os.topo 13 prism_eval/expA_lossdecomp/data/m2m.cm flow,sink expL_prismL_f8_s13 prism_eval/expA_lossdecomp/data
ls -la prism_eval/expA_lossdecomp/data/expL_prismL_f8_s13.flow.txt prism_eval/expA_lossdecomp/data/expL_prismL_mech.loss.csv
```
Expected: both files exist non-empty (wiring check only — full grid is Task 5).

- [ ] **Step 5: Create a `README.md` scaffold** (filled with results in Task 6):

```markdown
# Experiment A — Loss/NACK Decomposition (trimming regime)

**Why.** P2 (trimming default) tied because loss/NACK-driven control masked PRISM's delay
decomposition (floor-MD ~5%). This group adds PRISM's loss decomposition (`-prism_loss_decomp 1`):
hold the window on reroutable (concentrated) loss, cut on uniform/last-hop loss. Tests whether it
turns the P2 tie into a win in the trimming regime.

## Setup
Trimming-default Exp A (P2 setup: many2many 64->16 pod0 2MB; fat_tree_128_1os; -paths 8; END=2;
NO -disable_trim; -failed {0,2,4,8,12}; seeds {13..17}). 4 arms: OPS+NSCC, REPS+NSCC,
PRISM (delay-only, flag off), PRISM (+loss-decomp, flag on). Mechanism at failed=8, seed=13.

## Figures
- `figs/figL1_main_perf` -- goodput / avg-FCT / P99-FCT vs # constrained links (4 lines).
- `figs/figL2_mechanism` -- signal + cwnd(t); prints the **loss-HOLD fraction** (fabric NACKs held
  / total) -- the loss analog of the delay floor-MD fraction.

## Result
(filled in Task 6 -- honest, including a tie/negative if that is the outcome)

## Reproduce
```
bash prism_eval/expA_lossdecomp/repro.sh   # from sim/datacenter; ~100 sweep + 3 mechanism sims
```
```

- [ ] **Step 6: Stage (DO NOT COMMIT)**

```bash
git -C /home/leo/htsim add htsim/sim/datacenter/prism_eval/expA_lossdecomp/make_figs.py \
  htsim/sim/datacenter/prism_eval/expA_lossdecomp/repro.sh \
  htsim/sim/datacenter/prism_eval/expA_lossdecomp/README.md
```

---

## Task 5: Full trimming run + do-no-harm check — controller-owned

**Files:** none (gitignored `data/` + `figs/figL1_main_perf.*`, `figs/figL2_mechanism.*`).

- [ ] **Step 1: Run the full repro**

Run (from `/home/leo/htsim/htsim/sim/datacenter`): `bash prism_eval/expA_lossdecomp/repro.sh`
Expected: selftests pass (incl. `ok decide_loss`); ~100 sweep + 3 mechanism sims; renders figL1/figL2; prints the per-baseline table + the loss-HOLD fraction.

- [ ] **Step 2: Headline + attribution + safety read.** From the `[figL1_main_perf]` table: does PRISM (+loss-decomp) beat REPS+NSCC under asymmetry (failed ≥ 4) where PRISM (delay-only) tied? Is the loss-HOLD fraction ≫ 0 (decomposition active)? Are all arms' completion_rate sane (a prismL completion drop signals unsafe holding → report it; the streak valve should prevent collapse).

- [ ] **Step 3: Do-no-harm delay-driven check** (loss-decomp must be ~inert under `-disable_trim`)

Run (from `/home/leo/htsim/htsim/sim/datacenter`):
```bash
for cfg in "0 off" "1 on"; do set -- $cfg; \
  PATHS=8 END_MS=8 EXTRA_ARGS="-disable_trim -prism_loss_decomp $1" \
   bash prism_eval/common/run_lib.sh prism reps 8 fat_tree_128_1os.topo 13 prism_eval/expA_lossdecomp/data/m2m.cm flow,sink ld_dnh_$2 prism_eval/expA_lossdecomp/data; done
python3 -c "import sys;sys.path.insert(0,'prism_eval/common');import metrics as m; \
g=lambda t:round(m.aggregate_goodput_gbps(f'prism_eval/expA_lossdecomp/data/{t}.flow.txt'),1); \
print('delay-driven f8 goodput  off:',g('ld_dnh_off'),' on:',g('ld_dnh_on'))"
```
Expected: off ≈ on (loss-decomp inert in the no-trim regime — few/no fabric NACKs). Report any divergence.

---

## Task 6: Honest write-up + memory + commit — controller-owned

**Files:** Modify `expA_lossdecomp/README.md`; (after milestone) memory `prism-eval-roadmap.md` + `MEMORY.md`.

- [ ] **Step 1: Fill the README Result section** — the 4-arm trimming table (goodput/avg-FCT/cr), the headline verdict (does loss-decomp turn the P2 tie into a win under asymmetry?), the attribution (prismL vs prism-delay-only), the loss-HOLD fraction (decomposition active?), the do-no-harm result, and any completion-rate/safety caveat. State a tie/negative straight if that is the outcome — this is the crux question; do not force a positive.

- [ ] **Step 2: Milestone commit (ON USER APPROVAL ONLY)** — ask first. On approval:
```bash
git -C /home/leo/htsim add -f htsim/sim/datacenter/prism_eval/expA_lossdecomp/figs/figL1_main_perf.* \
  htsim/sim/datacenter/prism_eval/expA_lossdecomp/figs/figL2_mechanism.*
git -C /home/leo/htsim add htsim/sim/datacenter/prism_eval/expA_lossdecomp/README.md \
  docs/superpowers/specs/2026-06-16-prism-loss-decomp-design.md \
  docs/superpowers/plans/2026-06-16-prism-loss-decomp.md
git -C /home/leo/htsim commit -m "prism_eval (b): PRISM loss/NACK decomposition + trimming-regime Exp A"
```

- [ ] **Step 3: Update memory** (`prism-eval-roadmap.md` status: loss-decomp done + the crux verdict) — only after the user approves.

---

## Self-Review (against the spec)

**Spec coverage:**
- §3.1 `decide_loss` + test → Task 1. ✓
- §3.2 per-epoch loss state + where updated (processAck good / NACK / boundary) → Task 2 Steps 3,7,8. ✓
- §3.3 `updateCwndOnNack_PRISM` (signature, HOLD=no-op, CUT=NSCC, flag-off==NSCC) → Task 2 Steps 1,2,5,6. ✓
- §3.4 flags + `PRISM_LOSS_MIN_GOOD` → Task 2 Step 4 + Task 3. ✓
- §3.5 logging (PRISM_LOSS per-NACK) → Task 2 Step 6 (log) + Task 4 (loss-HOLD fraction). ✓
- §4 eval (trimming Exp A, 4 arms, loss-HOLD metric, do-no-harm check) → Tasks 4,5. ✓
- §6 safety (completion_rate watch, streak valve, retransmit-always) → Task 2 Step 6/8 + Task 5 Step 2. ✓

**Placeholder scan:** all code shown; no TBD. README Result is explicitly controller-filled in Task 6 (a result, not a code placeholder).

**Type/name consistency:** `decide_loss(bool,bool,bool,bool)→LossAction{LOSS_CUT,LOSS_HOLD}` identical in header, test, and the Task-2 switch. `_prism_loss_decomp`(bool)/`_prism_loss_streak_cap`(uint32_t)/`_prism_loss_evs_good`/`_prism_loss_evs_nacked`(set<uint32_t>)/`_prism_loss_hold_streak`(int)/`_prism_loss_epoch_held`(bool)/`PRISM_LOSS_MIN_GOOD` declared (uec.h/uec.cpp) ↔ used (Task 2) ↔ parsed (Task 3) consistently. NACK fn-ptr `(uint32_t ev, mem_b, bool)` consistent across decls, defs, the call site (already passes ev), and dispatch. Eval tags `expL_{ops,reps,prism,prismL}_f{f}_s{s}` + `_mech` consistent across repro.sh and make_figs BASELINES.
