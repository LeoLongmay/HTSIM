#!/usr/bin/env python3
"""Self-contained tests for analyze2 (no pytest). Run: python3 test_analyze2.py"""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze2 as A

def test_agg_core_groups_filters_layers():
    idmap = {
        1700: "US0->CS0(0)", 1701: "Pipe-US0->CS0(0)",
        1706: "US0->CS4(0)", 1712: "US0->CS8(0)", 1718: "US0->CS12(0)",
        1800: "US1->CS0(0)", 1806: "US1->CS4(0)",
        50: "LS0->US0(0)",     # tor->agg, must be excluded
        60: "US0->LS_3(0)",    # agg->tor downlink, must be excluded
        70: "LS0->DST2(0)",    # tor->host, must be excluded
    }
    g = A.agg_core_groups(idmap)
    assert set(g.keys()) == {0, 1}, g
    assert sorted(g[0]) == [1700, 1706, 1712, 1718], g[0]   # Pipe excluded
    assert sorted(g[1]) == [1800, 1806], g[1]
    print("ok agg_core_groups")

def test_pod_groups():
    groups = {0: [1700, 1706], 1: [1800], 2: [1900], 3: [2000], 4: [2100]}
    pods = A.pod_groups(groups)
    assert sorted(pods[0]) == [1700, 1706, 1800, 1900, 2000], pods[0]  # aggs 0..3
    assert sorted(pods[1]) == [2100], pods[1]                          # agg 4
    print("ok pod_groups")

def test_decompose_uses_p8_and_bundle():
    # agg0 uplinks at t=600us: [12450, 4150, 4150, 4150] bytes; plus a foreign queue
    q = (
        "0.000600000 Type QUEUE_APPROX ID 1700 Ev RANGE LastQ 12450 MinQ 0 MaxQ 12450\n"
        "0.000600000 Type QUEUE_APPROX ID 1706 Ev RANGE LastQ 4150 MinQ 0 MaxQ 4150\n"
        "0.000600000 Type QUEUE_APPROX ID 1712 Ev RANGE LastQ 4150 MinQ 0 MaxQ 4150\n"
        "0.000600000 Type QUEUE_APPROX ID 1718 Ev RANGE LastQ 4150 MinQ 0 MaxQ 4150\n"
        "0.000600000 Type QUEUE_APPROX ID 50 Ev RANGE LastQ 999999 MinQ 0 MaxQ 999999\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".q.txt", delete=False) as f:
        f.write(q); path = f.name
    keep = {1700, 1706, 1712, 1718}
    data = A.parse_q(path, keep)
    os.unlink(path)
    t, cs, cc = A.decompose_bundle(data, [1700, 1706, 1712, 1718])
    assert t == [600.0], t
    assert abs(cs[0] - 0.664) < 1e-6, cs   # (12450-4150)*8e-5
    assert abs(cc[0] - 0.332) < 1e-6, cc   # 4150*8e-5
    print("ok decompose (p[8] field, bundle filter)")

def test_steady_window():
    times = [100.0, 600.0, 1000.0, 1600.0]
    series = [9.0, 1.0, 3.0, 9.0]          # only 600 and 1000 fall in [500,1500]
    s = A.steady_stats(times, series, 500.0, 1500.0)
    assert s["n"] == 2, s
    assert abs(s["mean"] - 2.0) < 1e-9, s
    assert abs(s["median"] - 2.0) < 1e-9, s
    assert abs(s["p95"] - 3.0) < 1e-9, s
    print("ok steady_stats window")

if __name__ == "__main__":
    test_agg_core_groups_filters_layers()
    test_pod_groups()
    test_decompose_uses_p8_and_bundle()
    test_steady_window()
    print("ALL PASS")
