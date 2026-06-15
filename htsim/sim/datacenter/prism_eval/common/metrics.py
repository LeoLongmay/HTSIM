"""Metric parsers for prism_eval. Reads decoded-ASCII htsim logs (produced by
run_lib.sh): flow events (FCT) and UEC_SINK RATE (goodput). Stdlib only."""
import collections
import statistics

def parse_flow_events(path):
    """Return (starts, finishes) dicts keyed by (srcid, flowid).
      starts[key]    = start_time_seconds
      finishes[key]  = (finish_time_seconds, bytes)
    Line format (decoded):
      <t> Type FLOW_EVENT SrcID <id> Ev START  FlowID <fid> Flowsize <b>
      <t> Type FLOW_EVENT SrcID <id> Ev FINISH FlowID <fid> Bytes <b> Pkts <p>
    """
    starts, finishes = {}, {}
    with open(path) as fh:
        for ln in fh:
            t = ln.split()
            if "FLOW_EVENT" not in t:
                continue
            time = float(t[0])
            srcid = int(t[t.index("SrcID") + 1])
            ev = t[t.index("Ev") + 1]
            fid = int(t[t.index("FlowID") + 1])
            key = (srcid, fid)
            if ev == "START":
                starts[key] = time
            elif ev == "FINISH":
                nbytes = int(t[t.index("Bytes") + 1])
                finishes[key] = (time, nbytes)
    return starts, finishes

def _percentile(sorted_vals, p):
    """Nearest-rank percentile on a pre-sorted, non-empty list."""
    if not sorted_vals:
        return float("nan")
    i = int(round(p / 100.0 * (len(sorted_vals) - 1)))
    i = max(0, min(len(sorted_vals) - 1, i))
    return sorted_vals[i]

def fct_stats(flow_path):
    """Flow-completion-time stats (seconds) from a decoded flow-event log.
    Only flows with both START and FINISH count toward FCT; started-but-unfinished
    flows count toward total_started and lower completion_rate."""
    starts, finishes = parse_flow_events(flow_path)
    fcts = sorted(tf - starts[k] for k, (tf, _) in finishes.items() if k in starts)
    total = len(starts)
    completed = len(fcts)
    return {
        "completed": completed,
        "total_started": total,
        "completion_rate": (completed / total) if total else float("nan"),
        "avg_s": statistics.mean(fcts) if fcts else float("nan"),
        "p50_s": _percentile(fcts, 50),
        "p95_s": _percentile(fcts, 95),
        "p99_s": _percentile(fcts, 99),
        "max_s": fcts[-1] if fcts else float("nan"),
    }

def goodput_gbps(sink_path, window_s=(0.5e-3, 1.5e-3)):
    """Steady-window aggregate goodput (Gbps) = mean over in-window timestamps of the
    summed UEC_SINK Rate (bits/s). Line format (decoded):
      <t> Type UEC_SINK ID <id> Ev RATE CAck <c> ReorderBuffer <r> Rate <bits/s>
    (Rate is token index 12.) Doubles as the utilization signal used by figG/figI."""
    per_t = collections.defaultdict(float)
    with open(sink_path) as fh:
        for ln in fh:
            p = ln.split()
            if len(p) >= 13 and "UEC_SINK" in p:
                per_t[float(p[0])] += float(p[12])
    tail = [v / 1e9 for t, v in per_t.items() if window_s[0] <= t <= window_s[1]]
    return statistics.mean(tail) if tail else 0.0
