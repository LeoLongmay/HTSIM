#!/usr/bin/env python3
"""Pure selector for the PRISM T_spray tuning experiment. Encodes the PRE-REGISTERED success
criterion (spec 2026-06-16-prism-eval-tspray-tuning-design.md §4) so the choice of T_spray* is
reproducible and not cherry-picked. No plotting / no htsim deps -> unit-testable standalone:
    python3 tspray_select.py --selftest
"""
import sys

def select_tspray(f0_goodput, f8_goodput, reps_f8_goodput, f0_floor, plateau_frac=0.02):
    """Pick T_spray* from Stage-1 endpoint aggregates.

    Args:
      f0_goodput: {t_spray_us: mean goodput Gbps at failed=0}
      f8_goodput: {t_spray_us: mean goodput Gbps at failed=8}
      reps_f8_goodput: REPS+NSCC mean goodput at failed=8 (the win reference)
      f0_floor: min f0 goodput to count as "recovered" (e.g. OPS+NSCC f0 level)
      plateau_frac: treat f0 within this fraction of the best as a plateau.

    Precondition: keys of f0_goodput and f8_goodput must be identical (same TSLIST).

    Criterion: a T_spray PASSES iff f0_goodput >= f0_floor AND f8_goodput >= 1.15*reps_f8_goodput.
    Among passing values pick the one MAXIMIZING f0 goodput; on a plateau (within plateau_frac of
    the best passing f0) pick the SMALLEST T_spray (least deviation from default, least risk).

    Returns dict: {chosen, bar_f8, passing(sorted list), best_f0}. chosen is None if none pass
    (=> contingency: ratio-based spread test, separate spec).
    """
    bar_f8 = 1.15 * reps_f8_goodput
    passing = [ts for ts in sorted(f0_goodput)
               if f0_goodput[ts] >= f0_floor and f8_goodput[ts] >= bar_f8]
    if not passing:
        return {"chosen": None, "bar_f8": bar_f8, "passing": [], "best_f0": None}
    best_f0 = max(f0_goodput[ts] for ts in passing)
    chosen = min(ts for ts in passing if f0_goodput[ts] >= best_f0 * (1 - plateau_frac))
    return {"chosen": chosen, "bar_f8": bar_f8, "passing": passing, "best_f0": best_f0}

def select_tspray_maximize_f8(f0_goodput, f8_goodput, f0_ref, f0_tol_frac=0.01):
    """Pivot selector (spec §7): maximize the asymmetric (f8) win subject to do-no-harm at f0.
    Eligible T_spray have f0_goodput >= f0_ref*(1-f0_tol_frac), where f0_ref is the default
    (largest-T_spray) f0. Among eligible, pick MAX f8; tie -> LARGER T_spray (closer to default,
    less aggressive). Precondition: keys of f0_goodput and f8_goodput must be identical.
    Returns {chosen, f0_bar, eligible(sorted), best_f8}; chosen None if none eligible."""
    f0_bar = f0_ref * (1 - f0_tol_frac)
    eligible = [ts for ts in sorted(f0_goodput) if f0_goodput[ts] >= f0_bar]
    if not eligible:
        return {"chosen": None, "f0_bar": f0_bar, "eligible": [], "best_f8": None}
    best_f8 = max(f8_goodput[ts] for ts in eligible)
    chosen = max(eligible, key=lambda ts: (f8_goodput[ts], ts))
    return {"chosen": chosen, "f0_bar": f0_bar, "eligible": eligible, "best_f8": best_f8}

def selftest():
    # Case A: exactly one value threads it (raising T_spray recovers f0 but eventually dents f8).
    f0 = {6: 869, 12: 900, 18: 950, 24: 960, 36: 970}
    f8 = {6: 504, 12: 500, 18: 498, 24: 480, 36: 450}
    r = select_tspray(f0, f8, reps_f8_goodput=431, f0_floor=906)
    assert abs(r["bar_f8"] - 495.65) < 0.01, r
    assert r["passing"] == [18], r          # excluded: 6:f0(869)<906; 12:f0(900)<906; 24:f8(480)<495.65; 36:f8(450)<495.65
    assert r["chosen"] == 18, r
    # Case B: plateau among passing -> pick smallest T_spray.
    f0b = {6: 869, 12: 910, 18: 950, 24: 952}
    f8b = {6: 504, 12: 500, 18: 498, 24: 496}
    rb = select_tspray(f0b, f8b, reps_f8_goodput=431, f0_floor=906)
    assert rb["passing"] == [12, 18, 24], rb
    assert rb["chosen"] == 18, rb           # best_f0=952; within 2% -> {18,24}; smallest=18
    # Case C: none pass (f0 never recovers) -> contingency.
    f0c = {6: 869, 12: 880, 18: 895}
    f8c = {6: 504, 12: 500, 18: 498}
    rc = select_tspray(f0c, f8c, reps_f8_goodput=431, f0_floor=906)
    assert rc["chosen"] is None and rc["passing"] == [], rc
    # Case D: f8 constraint binds (high f0 but win lost) -> excluded.
    f0d = {6: 869, 24: 980}
    f8d = {6: 504, 24: 470}
    rd = select_tspray(f0d, f8d, reps_f8_goodput=431, f0_floor=906)
    assert rd["chosen"] is None, rd         # 24 has great f0 but f8 470 < 495.65
    # --- pivot selector: maximize f8 subject to do-no-harm at f0 (f0_ref = default-T_spray f0) ---
    # Case E: all eligible; max f8 is at ts=2 (580) -> chosen=2 (NOT because it is smallest).
    f0e = {2: 880, 3: 882, 4: 881, 6: 874, 9: 872, 14: 869}
    f8e = {2: 580, 3: 570, 4: 560, 6: 548, 9: 520, 14: 504}
    re_ = select_tspray_maximize_f8(f0e, f8e, f0_ref=f0e[14])
    assert abs(re_["f0_bar"] - 860.31) < 0.1, re_     # 869*0.99
    assert re_["eligible"] == [2, 3, 4, 6, 9, 14], re_
    assert re_["chosen"] == 2 and abs(re_["best_f8"] - 580) < 1e-9, re_
    # Case F: T_spray=2 harms f0 (below the do-no-harm bar) -> excluded; best eligible f8 at ts=3.
    f0f = {2: 840, 3: 882, 4: 881, 6: 874, 9: 872, 14: 869}
    rf = select_tspray_maximize_f8(f0f, f8e, f0_ref=f0f[14])
    assert 2 not in rf["eligible"] and rf["eligible"] == [3, 4, 6, 9, 14], rf
    assert rf["chosen"] == 3, rf
    # Case G: f8 tie among eligible -> pick the LARGER T_spray.
    f0g = {4: 880, 6: 880, 14: 869}
    f8g = {4: 560, 6: 560, 14: 504}
    rg = select_tspray_maximize_f8(f0g, f8g, f0_ref=f0g[14])
    assert rg["chosen"] == 6, rg
    # Case H: only the default clears the bar -> chosen falls back to the default.
    f0h = {2: 800, 3: 810, 14: 869}
    f8h = {2: 580, 3: 570, 14: 504}
    rh = select_tspray_maximize_f8(f0h, f8h, f0_ref=f0h[14])
    assert rh["eligible"] == [14] and rh["chosen"] == 14, rh
    print("ok tspray_select")

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        print("usage: tspray_select.py --selftest")
