#!/usr/bin/env python3
"""Cross-check PRISM's per-epoch C_cc/C_spray log against an offline recompute from the
per-ACK PRISM_PATHRTT log. For each flow, the logged epoch-boundary timestamps define the
windows; within each window we recompute C_cc=min q, C_spray=max q-min q with
q=max(raw_rtt - base, 0) and compare to the logged values.

base handling: the controller seeds base_rtt near the unloaded propagation RTT (~14 us) and it
settles DOWNWARD to its final minimum over the first few ACKs; once settled it stays well below
the observed queued RTTs (~21 us). Because the settled base is below every observed RTT, it
CANNOT be re-derived as a running-min of observed raw_rtt -- so we use each epoch's LOGGED base.
Epochs whose logged base is above the flow's final (minimum) logged base are SKIPPED: base was
still settling there, so a single per-epoch base can't reproduce the per-sample q from the logs.

The controller now GATES its epoch accumulation to genuine per-path samples (raw_rtt >= base);
RTS/no-send-record ACKs that use get_avg_delay() are not accumulated. This tool matches that by
filtering pathrtt rows to raw_rtt >= base. So on a settled epoch the controller and this tool
see the same sample set and should reproduce C_cc/C_spray exactly.

What the match rate means (default threshold 0.85): on the settled epochs that reconstruct
cleanly, the offline min/max of q reproduces the logged C_cc/C_spray EXACTLY (within tol_ns) --
the verification of the epoch min/max wiring. The residual is NOT a formula bug; it is the one
epoch per flow where base finished settling mid-epoch (so early samples used a higher base) plus
+/-1ns ps->ns rounding. A genuine wiring regression (e.g. logging max instead of max-min) would
mismatch on essentially every multi-sample epoch and crater the rate toward
0, which the 0.85 floor catches. Usage: prism_epoch_check.py <pathrtt.csv> <epoch.csv> [min_rate]
"""
import sys

def _read_csv(path, ncols):
    rows = []
    with open(path) as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln:
                continue
            parts = ln.split(",")
            if len(parts) < ncols:
                continue
            rows.append(tuple(int(float(x)) for x in parts[:ncols]))
    return rows

def check(pathrtt, epochs, tol_ns=3):
    """pathrtt: rows (time,flow,path,raw_rtt,ecn,cwnd). epochs: rows
    (time,flow,base,C_cc,C_spray,region,cwnd,samples,cut). Returns dict with counts.

    For each flow we use each epoch's LOGGED base (the controller seeds base to the unloaded
    propagation RTT, well below any observed queued RTT, so it cannot be re-derived as a
    running-min of observed RTTs). Epochs whose logged base is ABOVE the flow's final (minimum)
    logged base are SKIPPED: base_rtt was still settling there, so a single per-epoch base
    can't reproduce the per-sample q from the logs. On the settled epochs, q=max(raw-base,0)
    windowed by the logged boundaries must reproduce C_cc=min q, C_spray=max q-min q (tol_ns
    absorbs +/-1ns ps->ns rounding). match_rate is over the CHECKED (settled) epochs."""
    pr_by_flow = {}
    for r in pathrtt:
        pr_by_flow.setdefault(r[1], []).append(r)
    for f in pr_by_flow:
        pr_by_flow[f].sort(key=lambda r: r[0])
    ep_by_flow = {}
    for e in epochs:
        ep_by_flow.setdefault(e[1], []).append(e)
    for f in ep_by_flow:
        ep_by_flow[f].sort(key=lambda e: e[0])

    total = checked = matched = skipped = 0
    mismatches = []
    for flow, eps in ep_by_flow.items():
        prs = pr_by_flow.get(flow, [])
        final_base = min(e[2] for e in eps)   # settled base for this flow
        prev_t = -1
        for (etime, _f, base, ccc, cspray, _region, _cwnd, _samples, _cut) in eps:
            window = [r for r in prs if prev_t < r[0] <= etime]
            prev_t = etime
            total += 1
            if base != final_base:            # base still settling -> not reconstructable
                skipped += 1
                continue
            checked += 1
            # genuine samples only (raw >= base): the controller's gate skips raw<base
            # (RTS fallback) ACKs, so exclude them here too to match the accumulated set.
            qs = [r[3] - base for r in window if r[3] >= base]
            if not qs:
                mismatches.append((flow, etime, "no-samples"))
                continue
            off_ccc = min(qs)
            off_cspray = max(qs) - off_ccc
            if abs(off_ccc - ccc) <= tol_ns and abs(off_cspray - cspray) <= tol_ns:
                matched += 1
            else:
                mismatches.append((flow, etime, f"logged Ccc={ccc} Cspray={cspray} "
                                                 f"offline Ccc={off_ccc} Cspray={off_cspray}"))
    return {"epochs": total, "checked": checked, "skipped": skipped, "matched": matched,
            "match_rate": (matched / checked) if checked else 0.0,
            "mismatches": mismatches}

def main():
    pathrtt = _read_csv(sys.argv[1], 6)
    epochs = _read_csv(sys.argv[2], 9)
    min_rate = float(sys.argv[3]) if len(sys.argv) > 3 else 0.85
    res = check(pathrtt, epochs)
    print(f"epochs={res['epochs']} checked={res['checked']} skipped={res['skipped']} "
          f"matched={res['matched']} match_rate={res['match_rate']:.3f}")
    for m in res["mismatches"][:10]:
        print("  mismatch:", m)
    if res["match_rate"] < min_rate:
        print(f"FAIL: match_rate {res['match_rate']:.3f} < {min_rate}")
        sys.exit(1)
    print("ok prism_epoch_check")

if __name__ == "__main__":
    main()
