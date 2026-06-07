#!/usr/bin/env python3
"""Self-contained tests for pathrtt_analyze (no pytest). Run: python3 test_pathrtt_analyze.py"""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pathrtt_analyze as A

def _csv(rows):
    f = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False)
    for r in rows:
        f.write(",".join(str(x) for x in r) + "\n")
    f.close()
    return f.name

def test_rtt_min_per_path():
    rows = [(1000,0,10,100),(12000,0,10,150),(2000,0,20,200),(13000,0,20,260)]
    p = _csv(rows); data = A.parse_csv(p); os.unlink(p)
    mins = A.rtt_min_per_path(data)
    assert mins[(0,10)] == 100, mins
    assert mins[(0,20)] == 200, mins
    print("ok rtt_min_per_path")

def test_decompose_bins_and_carryforward():
    # flow 0, two paths. bin=10000ns (10us). t in [0,30000).
    rows = [(1000,0,10,100),(2000,0,20,200),    # bin0: latest 100,200 -> q 0,0
            (12000,0,10,150),(13000,0,20,260)]  # bin1: latest 150,260 -> q 50,60
    p = _csv(rows); data = A.parse_csv(p); os.unlink(p)
    mins = A.rtt_min_per_path(data)
    times, cspray, ccc = A.decompose(data, mins, flow_id=0, bin_ns=10000, t0=0, t1=30000)
    # three bins: [0,10000) [10000,20000) [20000,30000)
    assert times == [0, 10000, 20000], times
    # bin0: q10=0, q20=0 -> ccc=0, cspray=0
    assert ccc[0] == 0 and cspray[0] == 0, (ccc, cspray)
    # bin1: q10=150-100=50, q20=260-200=60 -> ccc=50, cspray=10
    assert ccc[1] == 50 and cspray[1] == 10, (ccc, cspray)
    # bin2: no new samples -> carry forward latest (150,260) -> same as bin1
    assert ccc[2] == 50 and cspray[2] == 10, (ccc, cspray)
    print("ok decompose (binning + carry-forward + min/max)")

def test_steady_stats():
    s = A.steady_stats([100,600,1000,1600],[9.0,1.0,3.0,9.0],500,1500)
    assert s["n"]==2 and abs(s["mean"]-2.0)<1e-9 and abs(s["median"]-2.0)<1e-9, s
    print("ok steady_stats")

if __name__ == "__main__":
    test_rtt_min_per_path()
    test_decompose_bins_and_carryforward()
    test_steady_stats()
    print("ALL PASS")
