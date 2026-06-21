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

def cct_inflation(flow_path, size_bytes, link_gbps=100.0, base_rtt_s=14e-6):
    """Collective Completion Time and its inflation over a zero-queue lower bound (MSwift,
    Gerstein et al. 2026). CCT = worst-case FCT across the collective's COMPLETED flows
    (fct_stats max_s). Zero-queue lower bound LB = base_rtt_s + size_bytes*8/(link_gbps*1e9).
    Returns (cct_s, inflation_pct) where inflation_pct = (cct_s - LB)/LB*100; (nan, nan) if no
    flow completed."""
    cct = fct_stats(flow_path)["max_s"]
    if cct != cct:                              # nan -> nothing completed
        return (float("nan"), float("nan"))
    lb = base_rtt_s + size_bytes * 8.0 / (link_gbps * 1e9)
    return (cct, (cct - lb) / lb * 100.0)

def aggregate_goodput_gbps(flow_path):
    """Window-free aggregate goodput (Gbps) for a finite workload: total bytes of COMPLETED
    flows * 8 / makespan, where makespan = last finish - first start of the COMPLETED flows
    (seconds). Robust for finite flows (no steady-window choice needed) and for staggered
    starts / partial completion (the span covers only flows that actually finished, so an
    early flow that never completes does not stretch the denominator). 0.0 if nothing completed.
    Pair with completion_rate to surface incomplete-flow skew."""
    starts, finishes = parse_flow_events(flow_path)
    if not finishes or not starts:
        return 0.0
    done = [k for k in finishes if k in starts]
    if not done:
        return 0.0
    total_bytes = sum(finishes[k][1] for k in done)
    first_start = min(starts[k] for k in done)
    last_finish = max(finishes[k][0] for k in done)
    span = last_finish - first_start
    if span <= 0:
        return 0.0
    return total_bytes * 8.0 / span / 1e9

def jain_fairness(flow_path):
    """Jain's fairness index over per-flow throughput (bytes / FCT) of the COMPLETED flows.
    Returns a float in (0, 1] (1.0 = perfectly fair); nan if fewer than 2 completed flows."""
    starts, finishes = parse_flow_events(flow_path)
    tput = [finishes[k][1] / (finishes[k][0] - starts[k])
            for k in finishes if k in starts and finishes[k][0] > starts[k]]
    n = len(tput)
    if n < 2:
        return float("nan")
    s = sum(tput); s2 = sum(t * t for t in tput)
    return (s * s) / (n * s2) if s2 > 0 else float("nan")

def fct_slowdown(flow_path, link_gbps=100.0, base_rtt_s=14e-6):
    """Per-flow slowdown = FCT / (base_rtt_s + bytes*8 / (link_gbps*1e9)); returns {'mean','p99'}.
    Built for varied-size workloads; redundant at uniform flow size (where slowdown is proportional
    to FCT), so not rendered there. nan if no completed flows."""
    starts, finishes = parse_flow_events(flow_path)
    rate = link_gbps * 1e9
    sd = []
    for k in finishes:
        if k not in starts:
            continue
        fct = finishes[k][0] - starts[k]
        ideal = base_rtt_s + finishes[k][1] * 8.0 / rate
        if ideal > 0:
            sd.append(fct / ideal)
    if not sd:
        return {"mean": float("nan"), "p99": float("nan")}
    sd.sort()
    return {"mean": statistics.mean(sd), "p99": _percentile(sd, 99)}

def count_cwnd_cuts_from_pathrtt(pathrtt_path):
    """Count window-cut events across all flows from a PRISM_PATHRTT csv
    (time_ns,flow,path,raw_rtt_ns,ecn,cwnd): per flow, in time order, a 'cut' is any sample
    whose cwnd is strictly less than the previous sample's cwnd. Returns the total count."""
    per_flow = collections.defaultdict(list)
    with open(pathrtt_path) as fh:
        for ln in fh:
            p = ln.strip().split(",")
            if len(p) < 6:
                continue
            per_flow[int(p[1])].append((int(p[0]), int(p[5])))   # (time, cwnd)
    cuts = 0
    for rows in per_flow.values():
        rows.sort(key=lambda r: r[0])   # by time only; stable -> ties keep logged order
        for i in range(1, len(rows)):
            if rows[i][1] < rows[i - 1][1]:
                cuts += 1
    return cuts

def parse_prism_epoch(epoch_path):
    """Parse a PRISM_EPOCH csv into a list of dicts (time order preserved as written).
    Columns: time_ns,flow_id,base_rtt_ns,c_cc_ns,c_spray_ns,region,cwnd_bytes,samples,cut."""
    cols = ["time_ns", "flow_id", "base_rtt_ns", "c_cc_ns", "c_spray_ns",
            "region", "cwnd_bytes", "samples", "cut"]
    rows = []
    with open(epoch_path) as fh:
        for ln in fh:
            p = ln.strip().split(",")
            if len(p) < 9:
                continue
            rows.append({c: int(p[i]) for i, c in enumerate(cols)})
    return rows

def qdelay_bins(pathrtt_path, base_ns=13945, bin_us=20):
    """Bin per-ACK queuing delay q=max(raw_rtt-base,0) (from a PRISM_PATHRTT csv) into fixed
    time bins; return [(t_mid_us, min_q_us, mean_q_us), ...] sorted by time. Used for the
    mechanism figure (the 'avg the controller reacts to' vs the 'floor it ignores')."""
    bin_ns = bin_us * 1000
    acc = collections.defaultdict(list)
    with open(pathrtt_path) as fh:
        for ln in fh:
            p = ln.strip().split(",")
            if len(p) < 6:
                continue
            t = int(p[0]); raw = int(p[3])
            q = raw - base_ns
            if q < 0:
                q = 0
            acc[t // bin_ns].append(q)
    out = []
    for b in sorted(acc):
        qs = acc[b]
        t_mid_us = (b * bin_ns + bin_ns / 2) / 1000.0
        out.append((t_mid_us, min(qs) / 1000.0, (sum(qs) / len(qs)) / 1000.0))
    return out

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
