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

if __name__ == "__main__":
    test_fct_stats()
    test_goodput()
    print("ALL PASS")
