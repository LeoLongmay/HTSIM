import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "gen"))
import permutation  # noqa: E402
import many2many  # noqa: E402
import incast  # noqa: E402

def _parse_cm(text):
    """Parse a .cm string into [(src,dst),...] and validate the header counts."""
    lines = text.strip().split("\n")
    assert lines[0].startswith("Nodes "), lines[0]
    assert lines[1].startswith("Connections "), lines[1]
    declared = int(lines[1].split()[1])
    conns = []
    for ln in lines[2:]:
        lhs = ln.split(" start ")[0]          # "<s>-><d>"
        s, d = lhs.split("->")
        conns.append((int(s), int(d)))
    assert len(conns) == declared, (len(conns), declared)
    return conns

def test_permutation():
    text, conns = permutation.build(active_frac=0.5, size=1000, nodes=128, seed=1)
    assert _parse_cm(text) == conns
    assert " start 0 " not in text, "no flow may start at t=0"
    srcs = [s for s, _ in conns]
    dsts = [d for _, d in conns]
    assert len(set(srcs)) == len(srcs), "senders must be distinct"
    assert len(set(dsts)) == len(dsts), "receivers must be distinct"
    assert all(s != d for s, d in conns), "no self-pair"
    assert all(0 <= s < 128 and 0 <= d < 128 for s, d in conns), "valid host ids"
    text2, _ = permutation.build(active_frac=0.5, size=1000, nodes=128, seed=1)
    assert text2 == text
    text3, _ = permutation.build(active_frac=0.5, size=1000, nodes=128, seed=2)
    assert text3 != text
    print("ok permutation")

def test_many2many_pairs():
    text, conns = many2many.build(n_send=8, n_recv=4, pattern="pairs",
                                  size=1000, nodes=128, hpp=16, seed=1)
    assert _parse_cm(text) == conns
    assert " start 0 " not in text, "no flow may start at t=0"
    assert len(conns) == 8, len(conns)
    assert all(d < 16 for _, d in conns), "receivers in pod0"
    assert all(s >= 16 for s, _ in conns), "senders outside pod0"
    print("ok many2many pairs")

def test_many2many_all():
    text, conns = many2many.build(n_send=3, n_recv=4, pattern="all",
                                  size=1000, nodes=128, hpp=16, seed=1)
    assert _parse_cm(text) == conns
    assert len(conns) == 12, "cross product 3x4"
    print("ok many2many all")

def test_incast():
    text, conns = incast.build(n=32, dest=0, size=1000, nodes=128, hpp=16)
    assert _parse_cm(text) == conns
    assert len(conns) == 32, len(conns)
    assert all(d == 0 for _, d in conns), "all -> dest 0"
    assert all(s // 16 != 0 for s, _ in conns), "senders outside dest pod"
    text2, _ = incast.build(n=4, dest=0, size=1000, nodes=128, hpp=16, stagger_ps=1000)
    starts = [int(ln.split(" start ")[1].split(" size ")[0])
              for ln in text2.strip().split("\n")[2:]]
    assert starts == [1000, 2000, 3000, 4000], starts  # START_PS=1000 floor + i*stagger
    assert all(s > 0 for s in starts), "no flow may start at t=0 (simulator drops START)"
    print("ok incast")

if __name__ == "__main__":
    test_permutation()
    test_many2many_pairs()
    test_many2many_all()
    test_incast()
    print("ALL PASS")
