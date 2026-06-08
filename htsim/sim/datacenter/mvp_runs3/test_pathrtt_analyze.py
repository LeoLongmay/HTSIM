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

def test_p95_nearest_rank():
    times = [500.0 + i for i in range(20)]   # all inside [500,1500]
    series = list(range(20))                  # sorted values 0..19
    s = A.steady_stats(times, series, 500.0, 1500.0)
    assert s["n"] == 20, s
    assert s["p95"] == 18, s   # nearest-rank p95 of 0..19 = ceil(0.95*20)-1 = index 18

def test_single_path_zero_spray():
    rows = [(1000,0,10,100),(12000,0,10,150)]   # flow 0, ONE path (10)
    import tempfile, os
    f = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False)
    for r in rows: f.write(",".join(str(x) for x in r) + "\n")
    f.close()
    data = A.parse_csv(f.name); os.unlink(f.name)
    mins = A.rtt_min_per_path(data)
    t, cs, cc = A.decompose(data, mins, flow_id=0, bin_ns=10000, t0=0, t1=20000)
    # bin0: latest 100 -> q=0; bin1: latest 150 -> q=50. single path => spray always 0.
    assert cs == [0, 0], cs
    assert cc == [0, 50], cc
    print("ok single-path zero spray")

def test_aggregate_cross_flow_median():
    # 2 flows x 2 paths. Each path: a pre-window min sample (400us) + elevated samples
    # at 500us and 1000us, so q is constant across the [500,1500]us window (carry-forward).
    # flow0: path10 q=50, path20 q=90 -> C_spray=40, C_cc=50
    # flow1: path30 q=30, path40 q=70 -> C_spray=40, C_cc=30
    # median across flows: C_spray=median([40,40])=40 ; C_cc=median([50,30])=40
    # rtt values in ns; aggregate_tag converts q to us (divide by 1000), so
    # q10 = 150000-100000 = 50000ns = 50us, etc.
    rows = [(400000,0,10,100000),(500000,0,10,150000),(1000000,0,10,150000),
            (400000,0,20,100000),(500000,0,20,190000),(1000000,0,20,190000),
            (400000,1,30,100000),(500000,1,30,130000),(1000000,1,30,130000),
            (400000,1,40,100000),(500000,1,40,170000),(1000000,1,40,170000)]
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "_testagg.pathrtt.csv")
    with open(path, "w") as f:
        for r in rows:
            f.write(",".join(str(x) for x in r) + "\n")
    try:
        agg = A.aggregate_tag("_testagg", min_samples=1)
        assert agg["nflows"] == 2, agg
        assert abs(agg["cspray_med"] - 40.0) < 1e-9, agg
        assert abs(agg["ccc_med"] - 40.0) < 1e-9, agg
        # min_samples filter is on IN-WINDOW samples: each flow has 4 in [500,1500]us
        # (the 400us sample is pre-window); requiring 7 -> no eligible flow
        assert A.aggregate_tag("_testagg", min_samples=7) is None
    finally:
        os.unlink(path)
    print("ok aggregate cross-flow median + min_samples filter")

def test_rtt_min_per_flow():
    rows = [(1000,0,10,300),(2000,0,20,100),(3000,0,10,250),(4000,1,30,500)]
    p = _csv(rows); data = A.parse_csv(p); os.unlink(p)
    mf = A.rtt_min_per_flow(data)
    assert mf[0] == 100, mf   # min over BOTH paths of flow0
    assert mf[1] == 500, mf
    print("ok rtt_min_per_flow")

def test_global_baseline_cancels():
    # flow0, 2 paths. global floor = 100 (min over all samples).
    # bin1 latest: path10=150, path20=200.
    # C_spray(global) = max(150,200)-min(150,200) = 50  (independent of baseline)
    # C_cc(global)    = min(150,200)-100         = 50
    rows = [(1000,0,10,100),(2000,0,20,100),
            (12000,0,10,150),(13000,0,20,200)]
    p = _csv(rows); data = A.parse_csv(p); os.unlink(p)
    mp = A.rtt_min_per_path(data); mf = A.rtt_min_per_flow(data)
    t, cs, cc = A.decompose(data, mp, 0, bin_ns=10000, t0=0, t1=20000,
                            baseline="global", rtt_min_flow=mf)
    assert cs == [0, 50], cs   # bin0 qs(0,0); bin1 qs(50,100) -> spray 50
    assert cc == [0, 50], cc
    print("ok global baseline cancels")

def test_global_vs_own_structural_slow():
    # path10 fast: min 100, latest 110.  path20 structurally slow: min 300, latest 320.
    # own:    q10=10, q20=20  -> C_spray=10  (slow path's slowness hidden in its own min)
    # global: B=100; q10=10, q20=220 -> C_spray=210  (slow path now shows in C_spray) = iv-a fix
    rows = [(1000,0,10,100),(2000,0,20,300),
            (12000,0,10,110),(13000,0,20,320)]
    p = _csv(rows); data = A.parse_csv(p); os.unlink(p)
    mp = A.rtt_min_per_path(data); mf = A.rtt_min_per_flow(data)
    _, cs_own, _  = A.decompose(data, mp, 0, bin_ns=10000, t0=10000, t1=20000)
    _, cs_glob, _ = A.decompose(data, mp, 0, bin_ns=10000, t0=10000, t1=20000,
                                baseline="global", rtt_min_flow=mf)
    assert cs_own == [10], cs_own
    assert cs_glob == [210], cs_glob
    print("ok global vs own structural slow (iv-a fix)")

def test_const_baseline():
    # const_base = 100 (a fixed external floor). After consuming all samples,
    # latest path10=150, path20=200.
    # C_spray = max(50,100)-min(50,100) = 50  (= max rtt - min rtt, baseline cancels)
    # C_cc    = min(50,100) = 50              (= min path rtt 150 - 100)
    rows = [(1000,0,10,140),(2000,0,20,140),
            (12000,0,10,150),(13000,0,20,200)]
    p = _csv(rows); data = A.parse_csv(p); os.unlink(p)
    mp = A.rtt_min_per_path(data)
    t, cs, cc = A.decompose(data, mp, 0, bin_ns=10000, t0=10000, t1=20000,
                            baseline="const", const_base=100)
    assert cs == [50], cs
    assert cc == [50], cc
    print("ok const baseline")

def test_const_requires_base():
    rows = [(1000,0,10,140),(12000,0,10,150)]
    p = _csv(rows); data = A.parse_csv(p); os.unlink(p)
    mp = A.rtt_min_per_path(data)
    try:
        A.decompose(data, mp, 0, baseline="const")  # const_base missing
        assert False, "expected ValueError for const without const_base"
    except ValueError:
        pass
    print("ok const requires base")

def test_aggregate_rows_matches_tag():
    # aggregate_rows(parsed rows) must equal aggregate_tag(file) on the same data.
    rows = [(400000,0,10,100000),(500000,0,10,150000),(1000000,0,10,150000),
            (400000,0,20,100000),(500000,0,20,190000),(1000000,0,20,190000),
            (400000,1,30,100000),(500000,1,30,130000),(1000000,1,30,130000),
            (400000,1,40,100000),(500000,1,40,170000),(1000000,1,40,170000)]
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "_testaggrows.pathrtt.csv")
    with open(path, "w") as f:
        for r in rows:
            f.write(",".join(str(x) for x in r) + "\n")
    try:
        direct = A.aggregate_rows(A.parse_csv(path), min_samples=1)
        viatag = A.aggregate_tag("_testaggrows", min_samples=1)
        assert direct == viatag, (direct, viatag)
        assert direct["nflows"] == 2 and abs(direct["cspray_med"] - 40.0) < 1e-9, direct
        assert A.aggregate_rows([], min_samples=1) is None
    finally:
        os.unlink(path)
    print("ok aggregate_rows matches tag")

if __name__ == "__main__":
    test_rtt_min_per_path()
    test_decompose_bins_and_carryforward()
    test_steady_stats()
    test_p95_nearest_rank()
    test_single_path_zero_spray()
    test_aggregate_cross_flow_median()
    test_rtt_min_per_flow()
    test_global_baseline_cancels()
    test_global_vs_own_structural_slow()
    test_const_baseline()
    test_const_requires_base()
    test_aggregate_rows_matches_tag()
    print("ALL PASS")
