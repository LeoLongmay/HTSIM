import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import prism_epoch_check as pec  # noqa: E402

def test_match():
    # The checker uses each epoch's LOGGED base (col 3) and q = max(raw_rtt - base, 0),
    # windowed by the logged epoch-boundary times. Epochs whose logged base is above the
    # flow's final (min) base are SKIPPED (base still settling).
    # flow 7 (base constant 1000, all settled): raw {1300,1100,1500} -> q {300,100,500}.
    #   Epoch A (t<=100): {300,100} -> C_cc=100, C_spray=200 ; Epoch B (100<t<=200): {500} -> C_cc=500, C_spray=0
    # flow 8: epoch1 logged base 1100 (> final 1000) -> SKIPPED; epoch2 base 1000, raw 1300 -> q 300 -> C_cc=300, C_spray=0
    pathrtt = [
        (10,  7, 0, 1300, 0, 0),
        (50,  7, 0, 1100, 0, 0),
        (150, 7, 0, 1500, 0, 0),
        (60,  8, 0, 1300, 0, 0),
    ]
    # epoch rows: time_ns,flow,base_rtt_ns,C_cc_ns,C_spray_ns,region,cwnd,samples,cut
    epochs = [
        (100, 7, 1000, 100, 200, 0, 0, 2, 0),
        (200, 7, 1000, 500, 0,   0, 0, 1, 0),
        (50,  8, 1100, 999, 999, 0, 0, 1, 0),  # unsettled base -> skipped (values ignored)
        (100, 8, 1000, 300, 0,   0, 0, 1, 0),
    ]
    res = pec.check(pathrtt, epochs)
    assert res["epochs"] == 4, res
    assert res["skipped"] == 1, res
    assert res["checked"] == 3, res
    assert res["matched"] == 3, res
    assert res["match_rate"] == 1.0, res
    print("ok cross-check exact (logged base + skip-unsettled)")

def test_detects_wrong_values():
    # A settled epoch whose logged C_cc/C_spray are WRONG must NOT match (guards the FAIL path):
    # flow 9, base 1000, raw {1300,1100} -> q {300,100} -> correct C_cc=100, C_spray=200.
    pathrtt = [(10, 9, 0, 1300, 0, 0), (50, 9, 0, 1100, 0, 0)]
    epochs = [(100, 9, 1000, 999, 999, 0, 0, 2, 0)]  # deliberately wrong values
    res = pec.check(pathrtt, epochs)
    assert res["checked"] == 1, res
    assert res["matched"] == 0, res
    assert res["match_rate"] == 0.0, res
    print("ok cross-check detects wrong values")

if __name__ == "__main__":
    test_match()
    test_detects_wrong_values()
    print("ALL PASS")
