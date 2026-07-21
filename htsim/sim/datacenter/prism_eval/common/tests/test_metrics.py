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

def test_cct_inflation():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "c.flow.txt")
    with open(p, "w") as fh:
        # 2 flows start ~0; finish at 2 ms and 3 ms -> CCT (worst FCT) = 3 ms
        fh.write("0.000000000 Type FLOW_EVENT SrcID 1 Ev START FlowID 1 Flowsize 1000000\n")
        fh.write("0.000000000 Type FLOW_EVENT SrcID 2 Ev START FlowID 2 Flowsize 1000000\n")
        fh.write("0.002000000 Type FLOW_EVENT SrcID 1 Ev FINISH FlowID 1 Bytes 1000000 Pkts 1\n")
        fh.write("0.003000000 Type FLOW_EVENT SrcID 2 Ev FINISH FlowID 2 Bytes 1000000 Pkts 1\n")
    cct, infl = metrics.cct_inflation(p, size_bytes=1_000_000, link_gbps=100.0, base_rtt_s=14e-6)
    assert abs(cct - 0.003) < 1e-9, cct
    lb = 14e-6 + 1_000_000 * 8.0 / 1e11           # = 9.4e-5 s
    assert abs(infl - (0.003 - lb) / lb * 100.0) < 1e-6, infl
    print("ok cct_inflation")

def test_collective_makespan():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "c.flow.txt")
    with open(p, "w") as fh:
        # 3 flows: starts 0.000/0.001/0.000, finishes 0.002/0.005/0.003
        # makespan = max(finish) - min(start) = 0.005 - 0.000 = 0.005 s; one started-but-unfinished
        fh.write("0.000000000 Type FLOW_EVENT SrcID 1 Ev START FlowID 1 Flowsize 1000\n")
        fh.write("0.001000000 Type FLOW_EVENT SrcID 2 Ev START FlowID 2 Flowsize 1000\n")
        fh.write("0.000000000 Type FLOW_EVENT SrcID 3 Ev START FlowID 3 Flowsize 1000\n")
        fh.write("0.000500000 Type FLOW_EVENT SrcID 4 Ev START FlowID 4 Flowsize 1000\n")  # never finishes
        fh.write("0.002000000 Type FLOW_EVENT SrcID 1 Ev FINISH FlowID 1 Bytes 1000 Pkts 1\n")
        fh.write("0.005000000 Type FLOW_EVENT SrcID 2 Ev FINISH FlowID 2 Bytes 1000 Pkts 1\n")
        fh.write("0.003000000 Type FLOW_EVENT SrcID 3 Ev FINISH FlowID 3 Bytes 1000 Pkts 1\n")
    mk, cr = metrics.collective_makespan(p)
    assert abs(mk - 0.005) < 1e-9, mk
    assert abs(cr - 0.75) < 1e-9, cr        # 3 of 4 completed
    print("ok collective_makespan")

def test_sink_rate_series():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "s.sink.txt")
    with open(p, "w") as fh:
        # 2 connections (ID 100, 101); ID 100 has 2 samples out of order in time
        fh.write("0.000500000 Type UEC_SINK ID 100 Ev RATE CAck 1 ReorderBuffer 0 Rate 40000000000\n")
        fh.write("0.000100000 Type UEC_SINK ID 100 Ev RATE CAck 1 ReorderBuffer 0 Rate 20000000000\n")
        fh.write("0.000300000 Type UEC_SINK ID 101 Ev RATE CAck 1 ReorderBuffer 0 Rate 10000000000\n")
    s = metrics.sink_rate_series(p)
    assert set(s.keys()) == {100, 101}, s
    # ID 100 sorted by t: (0.0001,20Gbps) then (0.0005,40Gbps)
    assert s[100][0] == (0.0001, 20.0) and s[100][1] == (0.0005, 40.0), s[100]
    assert s[101] == [(0.0003, 10.0)], s[101]
    print("ok sink_rate_series")

def test_tor_downqueue_delay_series():
    d = tempfile.mkdtemp()
    idmap = os.path.join(d, "r.idmap")
    with open(idmap, "w") as fh:
        fh.write("164 QueuelogSampling\n")
        fh.write("165 LS0->DST0(0)\n")      # the dest-0 last-hop downlink queue
        fh.write("168 SRC0->LS0(0)\n")      # uplink (decoy, must NOT match)
        fh.write("171 LS0->DST1(0)\n")      # another host (decoy)
    assert metrics.find_dest_downqueue_id(idmap, 0) == 165, metrics.find_dest_downqueue_id(idmap, 0)
    assert metrics.find_dest_downqueue_id(idmap, 9) is None
    q = os.path.join(d, "r.q.txt")
    with open(q, "w") as fh:
        # id 165 over time (MaxQ token at the end); plus a decoy id 171 to be filtered out.
        # 41500 B * 8 / 100e9 * 1e6 = 3.32 us ; 83000 B -> 6.64 us
        fh.write("0.000008000 Type QUEUE_APPROX ID 165 Ev RANGE LastQ 41500 MinQ 0 MaxQ 41500\n")
        fh.write("0.000004000 Type QUEUE_APPROX ID 165 Ev RANGE LastQ 83000 MinQ 0 MaxQ 83000\n")
        fh.write("0.000004000 Type QUEUE_APPROX ID 171 Ev RANGE LastQ 99999 MinQ 0 MaxQ 99999\n")
    s = metrics.tor_downqueue_delay_series(q, idmap, 0, link_gbps=100.0)
    assert len(s) == 2, s                      # only id 165 rows, decoy 171 filtered
    assert s[0][0] == 0.000004 and abs(s[0][1] - 6.64) < 1e-9, s   # sorted by t
    assert s[1][0] == 0.000008 and abs(s[1][1] - 3.32) < 1e-9, s
    assert metrics.tor_downqueue_delay_series(q, idmap, 9) == []   # queue not found
    print("ok tor_downqueue_delay_series")

if __name__ == "__main__":
    test_fct_stats()
    test_goodput()
    test_aggregate_goodput()
    test_count_cwnd_cuts()
    test_parse_prism_epoch_and_qbins()
    test_jain_fairness()
    test_fct_slowdown()
    test_cct_inflation()
    test_collective_makespan()
    test_sink_rate_series()
    test_tor_downqueue_delay_series()
    print("ALL PASS")
