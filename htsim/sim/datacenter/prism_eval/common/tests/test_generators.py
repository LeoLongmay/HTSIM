import os, sys, subprocess, re
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "gen"))
import permutation  # noqa: E402
import many2many  # noqa: E402
import incast  # noqa: E402
import ai_ring  # noqa: E402
import coll_ring  # noqa: E402

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

def test_ai_ring():
    text, conns = ai_ring.build(nodes=128, servers=16, gpus_per_server=8,
                                stride=8, size=13697024, seed=1)
    assert _parse_cm(text) == conns
    assert " start 0 " not in text, "no flow may start at t=0"
    assert len(conns) == 128, len(conns)
    srcs = [s for s, _ in conns]; dsts = [d for _, d in conns]
    assert len(set(srcs)) == 128 and len(set(dsts)) == 128, "permutation: distinct src and dst"
    assert all(s != d for s, d in conns), "no self-pair"
    assert all(0 <= s < 128 and 0 <= d < 128 for s, d in conns), "valid host ids"
    assert all(s // 8 != d // 8 for s, d in conns), "every flow inter-server (server s -> s+1)"
    assert " size 13697024" in text, "MSwift Llama-70B HSDP flow size"
    text2, _ = ai_ring.build(seed=1)
    assert text2 == text, "deterministic per seed"
    text3, _ = ai_ring.build(seed=2)
    assert text3 != text, "random server placement varies with seed"
    print("ok ai_ring")

def _orig_gen(script, args):
    """Run an htsim native generator into a temp .cm and return its text."""
    import tempfile, subprocess, sys as _sys, os as _os
    orig = _os.path.join(HERE, "..", "..", "..", "connection_matrices", script)
    out = tempfile.mktemp(suffix=".cm")
    subprocess.run([_sys.executable, orig, out, *[str(a) for a in args]],
                   capture_output=True, check=True)
    with open(out) as fh:
        return fh.read()

def _norm_start(text):
    return re.sub(r" start \d+", " start X", text)

def test_coll_ring():
    text, nc, nt = coll_ring.build(nodes=128, groupsize=128, flowsize=131072, seed=13)
    assert nc == 128 * (2 * 128 - 1) == 32640, nc
    assert nt == 128 * (2 * 128 - 2) == 32512, nt
    lines = text.strip().split("\n")
    assert lines[0] == "Nodes 128" and lines[1] == "Connections 32640" and lines[2] == "Triggers 32512"
    assert " start 0" not in text, "no flow may start at t=0"
    assert text.count(" start ") == 128, "one start per ring chain"
    assert text.count("trigger id ") == 32512, "trigger declarations"
    # differential: identical to the htsim original (gen_allreduce.py) modulo the start value
    orig = _orig_gen("gen_allreduce.py", [128, 128, 128, 131072, 0, 13])
    assert _norm_start(text) == _norm_start(orig), "port must match the native generator exactly"
    # determinism + seed-variance
    assert coll_ring.build(seed=13)[0] == text
    assert coll_ring.build(seed=14)[0] != text
    print("ok coll_ring")

if __name__ == "__main__":
    test_permutation()
    test_many2many_pairs()
    test_many2many_all()
    test_incast()
    test_ai_ring()
    test_coll_ring()
    print("ALL PASS")
