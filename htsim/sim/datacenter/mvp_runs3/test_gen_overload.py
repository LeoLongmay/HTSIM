#!/usr/bin/env python3
"""Self-contained tests for gen_overload (no pytest). Run: python3 test_gen_overload.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen_overload as G

def test_counts_and_placement():
    text, conns = G.build(n_senders=8, dest_pod=0, n_dests=4, size=20_000_000,
                          nodes=128, hpp=16)
    assert len(conns) == 8, conns
    # every sender is OUTSIDE pod0; every dest is INSIDE pod0
    for s, d in conns:
        assert s // 16 != 0, (s, d)            # sender outside pod0
        assert d // 16 == 0 and d < 4, (s, d)  # dest inside pod0, within n_dests
    # round-robin over the 4 dests -> each dest used exactly twice
    used = sorted(d for _, d in conns)
    assert used == [0, 0, 1, 1, 2, 2, 3, 3], used
    assert "Nodes 128" in text and "Connections 8" in text
    print("ok gen_overload counts + placement")

def test_guards():
    try:
        G.build(n_senders=8, dest_pod=0, n_dests=20, nodes=128, hpp=16)  # n_dests>hpp
        assert False, "expected ValueError for n_dests>hpp"
    except ValueError:
        pass
    try:
        G.build(n_senders=200, dest_pod=0, n_dests=4, nodes=128, hpp=16)  # too many senders
        assert False, "expected ValueError for too many senders"
    except ValueError:
        pass
    print("ok gen_overload guards")

if __name__ == "__main__":
    test_counts_and_placement()
    test_guards()
    print("ALL PASS")
