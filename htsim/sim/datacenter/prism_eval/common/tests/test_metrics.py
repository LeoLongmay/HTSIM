import os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import metrics  # noqa: E402

def test_fct_stats():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "f.flow.txt")
    with open(p, "w") as fh:
        # 3 flows start at t=0, finish at 1ms/2ms/3ms -> FCT 1/2/3 ms
        for fid, tf in [(1, 0.001), (2, 0.002), (3, 0.003)]:
            fh.write(f"0.000000000 Type FLOW_EVENT SrcID {fid} Ev START "
                     f"FlowID {fid} Flowsize 1000\n")
            fh.write(f"{tf:.9f} Type FLOW_EVENT SrcID {fid} Ev FINISH "
                     f"FlowID {fid} Bytes 1000 Pkts 1\n")
        # one flow that started but never finished (no FINISH line)
        fh.write("0.000000000 Type FLOW_EVENT SrcID 4 Ev START "
                 "FlowID 4 Flowsize 1000\n")
    s = metrics.fct_stats(p)
    assert s["completed"] == 3, s
    assert s["total_started"] == 4, s
    assert abs(s["completion_rate"] - 0.75) < 1e-9, s
    assert abs(s["avg_s"] - 0.002) < 1e-9, s
    assert abs(s["max_s"] - 0.003) < 1e-9, s
    assert abs(s["p50_s"] - 0.002) < 1e-9, s
    print("ok fct_stats")

def test_goodput():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "g.sink.txt")
    with open(p, "w") as fh:
        # two receivers, steady rates 40 Gbps + 10 Gbps = 50 Gbps, in-window
        for t in ("0.000600000", "0.001000000"):
            fh.write(f"{t} Type UEC_SINK ID 10 Ev RATE CAck 1 "
                     f"ReorderBuffer 0 Rate 40000000000\n")
            fh.write(f"{t} Type UEC_SINK ID 11 Ev RATE CAck 1 "
                     f"ReorderBuffer 0 Rate 10000000000\n")
    g = metrics.goodput_gbps(p, window_s=(0.5e-3, 1.5e-3))
    assert abs(g - 50.0) < 1e-9, g
    print("ok goodput")

def test_aggregate_goodput():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "g.flow.txt")
    with open(p, "w") as fh:
        # two flows: start 0; finish at 0.001s carrying 1,000,000 and 3,000,000 bytes.
        # makespan = 0.001 - 0.0 = 0.001s; total = 4,000,000 B * 8 / 0.001 / 1e9 = 32 Gbps
        fh.write("0.000000000 Type FLOW_EVENT SrcID 1 Ev START FlowID 1 Flowsize 1000000\n")
        fh.write("0.000000000 Type FLOW_EVENT SrcID 2 Ev START FlowID 2 Flowsize 3000000\n")
        fh.write("0.001000000 Type FLOW_EVENT SrcID 1 Ev FINISH FlowID 1 Bytes 1000000 Pkts 1\n")
        fh.write("0.001000000 Type FLOW_EVENT SrcID 2 Ev FINISH FlowID 2 Bytes 3000000 Pkts 1\n")
    assert abs(metrics.aggregate_goodput_gbps(p) - 32.0) < 1e-6, metrics.aggregate_goodput_gbps(p)
    print("ok aggregate_goodput")

def test_count_cwnd_cuts():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "c.pathrtt.csv")
    with open(p, "w") as fh:
        # flow 5 cwnd: 100,120,90,90,80 -> two decreases (120->90, 90->80)
        for t, cw in [(1,100),(2,120),(3,90),(4,90),(5,80)]:
            fh.write(f"{t},5,0,14000,0,{cw}\n")
        # flow 6 cwnd: 50,60,70 -> zero decreases
        for t, cw in [(1,50),(2,60),(3,70)]:
            fh.write(f"{t},6,0,14000,0,{cw}\n")
    assert metrics.count_cwnd_cuts_from_pathrtt(p) == 2, metrics.count_cwnd_cuts_from_pathrtt(p)
    print("ok count_cwnd_cuts")

def test_parse_prism_epoch_and_qbins():
    d = tempfile.mkdtemp()
    ep = os.path.join(d, "e.epoch.csv")
    with open(ep, "w") as fh:
        # time,flow,base,ccc,cspray,region,cwnd,samples,cut
        fh.write("1000,7,14000,2000,5000,1,100000,4,0\n")
        fh.write("2000,7,14000,9000,1000,2,80000,4,1\n")
    rows = metrics.parse_prism_epoch(ep)
    assert len(rows) == 2 and rows[1]["cut"] == 1 and rows[0]["c_cc_ns"] == 2000, rows
    assert sum(r["cut"] for r in rows) == 1, rows
    pr = os.path.join(d, "q.pathrtt.csv")
    with open(pr, "w") as fh:
        # base 14000ns; bin 0-20us: raw 15000(q=1000ns=1us) and 19000(q=5us) -> min 1, mean 3 (us)
        fh.write("1000,7,0,15000,0,0\n")    # t=1us
        fh.write("5000,7,0,19000,0,0\n")    # t=5us
    bins = metrics.qdelay_bins(pr, base_ns=14000, bin_us=20)
    assert len(bins) == 1, bins
    tmid, minq, meanq = bins[0]
    assert abs(minq - 1.0) < 1e-9 and abs(meanq - 3.0) < 1e-9, bins
    print("ok parse_prism_epoch + qdelay_bins")

def test_jain_fairness():
    d = tempfile.mkdtemp()
    # equal throughput: 2 flows, same size + same FCT -> Jain = 1.0
    p = os.path.join(d, "fair.flow.txt")
    with open(p, "w") as fh:
        for fid in (1, 2):
            fh.write(f"0.000000000 Type FLOW_EVENT SrcID {fid} Ev START FlowID {fid} Flowsize 1000\n")
            fh.write(f"0.001000000 Type FLOW_EVENT SrcID {fid} Ev FINISH FlowID {fid} Bytes 1000 Pkts 1\n")
    assert abs(metrics.jain_fairness(p) - 1.0) < 1e-9, metrics.jain_fairness(p)
    # skewed: flow1 tput 1000/1ms, flow2 tput 1000/3ms -> 0.5 < Jain < 1
    p2 = os.path.join(d, "skew.flow.txt")
    with open(p2, "w") as fh:
        fh.write("0.000000000 Type FLOW_EVENT SrcID 1 Ev START FlowID 1 Flowsize 1000\n")
        fh.write("0.001000000 Type FLOW_EVENT SrcID 1 Ev FINISH FlowID 1 Bytes 1000 Pkts 1\n")
        fh.write("0.000000000 Type FLOW_EVENT SrcID 2 Ev START FlowID 2 Flowsize 1000\n")
        fh.write("0.003000000 Type FLOW_EVENT SrcID 2 Ev FINISH FlowID 2 Bytes 1000 Pkts 1\n")
    j = metrics.jain_fairness(p2)
    assert 0.5 < j < 1.0, j
    # <2 completed -> nan
    import math
    p3 = os.path.join(d, "one.flow.txt")
    with open(p3, "w") as fh:
        fh.write("0.000000000 Type FLOW_EVENT SrcID 1 Ev START FlowID 1 Flowsize 1000\n")
        fh.write("0.001000000 Type FLOW_EVENT SrcID 1 Ev FINISH FlowID 1 Bytes 1000 Pkts 1\n")
    assert math.isnan(metrics.jain_fairness(p3)), metrics.jain_fairness(p3)
    print("ok jain_fairness")

def test_fct_slowdown():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "sd.flow.txt")
    # 1,250,000 B = 1e7 bits; at 100 Gbps ideal-transmit = 1e7/1e11 = 100us; base_rtt 0;
    # FCT = 200us -> slowdown = 2.0
    with open(p, "w") as fh:
        fh.write("0.000000000 Type FLOW_EVENT SrcID 1 Ev START FlowID 1 Flowsize 1250000\n")
        fh.write("0.000200000 Type FLOW_EVENT SrcID 1 Ev FINISH FlowID 1 Bytes 1250000 Pkts 1\n")
    sd = metrics.fct_slowdown(p, link_gbps=100.0, base_rtt_s=0.0)
    assert abs(sd["mean"] - 2.0) < 1e-9, sd
    print("ok fct_slowdown")

if __name__ == "__main__":
    test_fct_stats()
    test_goodput()
    test_aggregate_goodput()
    test_count_cwnd_cuts()
    test_parse_prism_epoch_and_qbins()
    test_jain_fairness()
    test_fct_slowdown()
    print("ALL PASS")
