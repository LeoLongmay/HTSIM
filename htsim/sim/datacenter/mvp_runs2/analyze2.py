#!/usr/bin/env python3
"""Per-agg-bundle (and per-pod cross-check) congestion decomposition at the agg->core tier.
C_spray(set,t) = max-min, C_cc(set,t) = min, over the queues in that interchangeable set.
Usage: python3 analyze2.py <tag> [<tag> ...]   (reads mvp_runs2/<tag>.{idmap,q.txt})
"""
import sys, os, re, collections
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BYTES_TO_US = 8e-5          # 1 byte @100Gbps queueing delay: 8 bits / 100e9 * 1e6 us
AGGCORE_RE = re.compile(r'^US(\d+)->CS(\d+)')
HERE = os.path.dirname(os.path.abspath(__file__))

def load_idmap(path):
    """id(int) -> name(str)"""
    idmap = {}
    with open(path) as f:
        for line in f:
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            try:
                qid = int(parts[0])
            except ValueError:
                continue
            idmap[qid] = parts[1].strip()
    return idmap

def agg_core_groups(idmap):
    """agg_index(int) -> [queue_id,...] for US{agg}->CS{core} queues (excludes Pipe-*)."""
    groups = collections.defaultdict(list)
    for qid, name in idmap.items():
        if name.startswith("Pipe-"):  # redundant defense: ^US regex anchor already excludes Pipe-*; keep for clarity
            continue
        m = AGGCORE_RE.match(name)
        if m:
            groups[int(m.group(1))].append(qid)
    return dict(groups)

def pod_groups(groups):
    """pod_index(int) -> [queue_id,...] (union of the pod's 4 agg uplink bundles). pod = agg//4."""
    pods = collections.defaultdict(list)
    for agg, ids in groups.items():
        pods[agg // 4].extend(ids)
    return dict(pods)

def parse_q(path, keep_ids):
    """time_us -> {qid: lastQ_bytes}, only for qid in keep_ids."""
    data = collections.defaultdict(dict)
    with open(path) as f:
        for line in f:
            p = line.split()
            # <t> Type QUEUE_APPROX ID <qid> Ev RANGE LastQ <bytes> MinQ <b> MaxQ <b>
            if len(p) < 9 or p[6] != "RANGE":
                continue
            qid = int(p[4])
            if qid not in keep_ids:
                continue
            data[float(p[0]) * 1e6][qid] = int(p[8])   # LastQ value is p[8], NOT literal p[7]
    return data

def decompose_bundle(data, group_ids):
    """(times, c_spray_us, c_cc_us) over samples where >=2 of the set's queues are present."""
    gset = set(group_ids)
    times, cs, cc = [], [], []
    for t in sorted(data):
        vals = [b for qid, b in data[t].items() if qid in gset]
        if len(vals) < 2:
            continue
        times.append(t)
        cs.append((max(vals) - min(vals)) * BYTES_TO_US)
        cc.append(min(vals) * BYTES_TO_US)
    return times, cs, cc

def steady_stats(times, series, lo=500.0, hi=1500.0):
    """mean/median/p95 over [lo,hi] us window."""
    w = sorted(v for t, v in zip(times, series) if lo <= t <= hi)
    if not w:
        return {"mean": 0.0, "median": 0.0, "p95": 0.0, "n": 0}
    n = len(w)
    return {"mean": sum(w) / n, "median": (w[(n - 1) // 2] + w[n // 2]) / 2,
            "p95": w[min(n - 1, int(0.95 * n))], "n": n}

def analyze_tag(tag, focus_aggs=(0, 1), focus_pods=(0,), win=(500.0, 1500.0)):
    idmap = load_idmap(os.path.join(HERE, f"{tag}.idmap"))
    groups = agg_core_groups(idmap)
    pods = pod_groups(groups)
    keep = set(q for ids in groups.values() for q in ids)
    data = parse_q(os.path.join(HERE, f"{tag}.q.txt"), keep)

    def series_for(ids):
        t, cs, cc = decompose_bundle(data, ids)
        return t, cs, cc, steady_stats(t, cs, *win), steady_stats(t, cc, *win)

    lines = []
    # plot: focus aggs + focus pod
    fig, ax = plt.subplots(figsize=(10, 4))
    for agg in focus_aggs:
        if agg in groups:
            t, cs, cc, cs_s, cc_s = series_for(groups[agg])
            ax.plot(t, cs, linewidth=0.9, label=f"C_spray agg{agg}")
            ax.plot(t, cc, linewidth=0.9, linestyle="--", label=f"C_cc agg{agg}")
            lines.append(f"{tag:16s} agg{agg}: C_spray mean={cs_s['mean']:6.2f} p95={cs_s['p95']:6.2f}us"
                         f"  C_cc mean={cc_s['mean']:6.2f} p95={cc_s['p95']:6.2f}us median={cc_s['median']:6.2f} (n={cc_s['n']})")
    for pod in focus_pods:
        if pod in pods:
            t, cs, cc, cs_s, cc_s = series_for(pods[pod])
            lines.append(f"{tag:16s} POD{pod}: C_spray mean={cs_s['mean']:6.2f} p95={cs_s['p95']:6.2f}us"
                         f"  C_cc mean={cc_s['mean']:6.2f} p95={cc_s['p95']:6.2f}us median={cc_s['median']:6.2f} (n={cc_s['n']})")
    ax.axvspan(win[0], win[1], color="grey", alpha=0.12)
    ax.set_xlabel("time (us)"); ax.set_ylabel("queueing delay (us)")
    ax.set_title(tag); ax.legend(fontsize=8); ax.grid(alpha=0.3); ax.set_xlim(0, 2000)
    plt.tight_layout(); plt.savefig(os.path.join(HERE, f"{tag}.png"), dpi=130); plt.close()
    return "\n".join(lines)

if __name__ == "__main__":
    print("\n".join(analyze_tag(tag) for tag in sys.argv[1:]))
