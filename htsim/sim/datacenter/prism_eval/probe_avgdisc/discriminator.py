#!/usr/bin/env python3
"""READ-ONLY probe for proposal (b): does the AVERAGE per-epoch queuing delay discriminate PRISM's
HOLD epochs between f0 (transient spread -- should grow) and f8 (structural spread -- should hold)?
NO controller change; this only reads PRISM_PATHRTT/PRISM_EPOCH logs.

Mechanism: per flow, bin per-ACK q = max(raw_rtt - base, 0) into base_rtt-wide epochs; per epoch
compute avg_q, C_cc=min(q), C_spray=max(q)-min(q); classify the region with prism::decide_region
(INCREASE / HOLD / DECREASE; T_cc=T_spray=target). For the HOLD epochs report the FLIP FRACTION
P(avg_q < T_cc | HOLD) -- the share of HOLD epochs proposal (b) would convert HOLD->INCREASE.

Proposal (b) is VALID iff the flip fraction is HIGH at f0 (it un-holds the transient -> fixes the
under-growth) and LOW at f8 (it keeps holding the structural spread -> preserves the win).

  python3 discriminator.py            # analyze ./data -> verdict + figure
  python3 discriminator.py --selftest # logic self-check
"""
import os, sys, collections, statistics

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "common"))

BASE_NS = 14022          # flow base_rtt (ns), from the PRISM_EPOCH log base_rtt_ns column
T_CC = 14022.72          # target queuing delay (ns) = _target_Qdelay 14022720 ps; T_spray follows it
T_SPRAY = 14022.72
INCREASE, HOLD, DECREASE = 0, 1, 2
RNAME = {INCREASE: "INCREASE", HOLD: "HOLD", DECREASE: "DECREASE"}

def decide_region(c_cc, c_spray, t_cc=T_CC, t_spray=T_SPRAY):
    """Mirror of prism::decide_region (prism_decompose.h): '>=' counts as high."""
    floor_high = c_cc >= t_cc
    spread_high = c_spray >= t_spray
    if not floor_high and not spread_high:
        return INCREASE
    if not floor_high and spread_high:
        return HOLD
    return DECREASE

def _flow_q_series(pathrtt_path, base_ns=BASE_NS):
    """{flow: [(time_ns, q_ns), ...] time-sorted} from a PRISM_PATHRTT csv
    (time_ns,flow,path,raw_rtt_ns,ecn,cwnd)."""
    per = collections.defaultdict(list)
    with open(pathrtt_path) as fh:
        for ln in fh:
            p = ln.strip().split(",")
            if len(p) < 6:
                continue
            t = int(p[0]); flow = int(p[1]); raw = int(p[3])
            q = raw - base_ns
            per[flow].append((t, q if q > 0 else 0))
    for f in per:
        per[f].sort()
    return per

def epochs_from_pathrtt(pathrtt_path, base_ns=BASE_NS, t_cc=T_CC, t_spray=T_SPRAY, min_samples=2):
    """Reconstruct per-flow epochs (fixed base_ns-wide time bins). Returns a list of epoch dicts
    {flow, avg, c_cc, c_spray, region, n, half} ('early'/'late' = first/second half of the flow's
    active span). Bins with < min_samples ACKs are dropped (no meaningful spread)."""
    per = _flow_q_series(pathrtt_path, base_ns)
    out = []
    for flow, rows in per.items():
        if len(rows) < min_samples:
            continue
        t0 = rows[0][0]; span = rows[-1][0] - t0
        buckets = collections.defaultdict(list)
        for t, q in rows:
            buckets[(t - t0) // base_ns].append(q)
        for b in sorted(buckets):
            qs = buckets[b]
            if len(qs) < min_samples:
                continue
            c_cc = min(qs); c_spray = max(qs) - min(qs); avg = sum(qs) / len(qs)
            t_rel = b * base_ns + base_ns / 2
            out.append({"flow": flow, "avg": avg, "c_cc": c_cc, "c_spray": c_spray,
                        "region": decide_region(c_cc, c_spray, t_cc, t_spray), "n": len(qs),
                        "half": "early" if (span > 0 and t_rel < span / 2) else "late"})
    return out

def epoch_log_region_dist(epoch_path, t_cc=T_CC, t_spray=T_SPRAY):
    """Region fractions from the controller's OWN per-epoch C_cc/C_spray (PRISM_EPOCH col 3,4) --
    the faithful baseline our pathrtt reconstruction is cross-checked against."""
    cnt = collections.Counter()
    with open(epoch_path) as fh:
        for ln in fh:
            p = ln.strip().split(",")
            if len(p) < 9:
                continue
            cnt[decide_region(int(p[3]), int(p[4]), t_cc, t_spray)] += 1
    tot = sum(cnt.values()) or 1
    return {RNAME[r]: cnt[r] / tot for r in (INCREASE, HOLD, DECREASE)}, tot

def _frac_below(vals, thr):
    return (sum(1 for v in vals if v < thr) / len(vals)) if vals else float("nan")

def summarize(bins, t_cc=T_CC):
    """Region distribution + HOLD-epoch avg stats, incl. the proposal-(b) flip fraction."""
    reg = collections.Counter(b["region"] for b in bins)
    tot = len(bins) or 1
    hold = [b for b in bins if b["region"] == HOLD]
    hold_avgs = [b["avg"] for b in hold]
    hold_early = [b["avg"] for b in hold if b["half"] == "early"]
    hold_late = [b["avg"] for b in hold if b["half"] == "late"]
    return {
        "n_epochs": len(bins),
        "region_frac": {RNAME[r]: reg[r] / tot for r in (INCREASE, HOLD, DECREASE)},
        "n_hold": len(hold),
        "flip_frac": _frac_below(hold_avgs, t_cc),          # P(avg < T_cc | HOLD) == proposal (b) un-holds
        "hold_avg_mean_us": (statistics.mean(hold_avgs) / 1000.0) if hold_avgs else float("nan"),
        "hold_avg_median_us": (statistics.median(hold_avgs) / 1000.0) if hold_avgs else float("nan"),
        "flip_frac_early": _frac_below(hold_early, t_cc),
        "flip_frac_late": _frac_below(hold_late, t_cc),
        "hold_avgs": hold_avgs,
    }

def analyze(data_dir, faileds=(0, 8), seeds=(13, 14, 15)):
    res = {}
    for f in faileds:
        allbins, reg_xchecks = [], []
        for s in seeds:
            pr = os.path.join(data_dir, f"probe_prism_f{f}_s{s}.pathrtt.csv")
            ep = os.path.join(data_dir, f"probe_prism_f{f}_s{s}.epoch.csv")
            if not os.path.exists(pr):
                continue
            allbins.extend(epochs_from_pathrtt(pr))
            if os.path.exists(ep):
                reg_xchecks.append(epoch_log_region_dist(ep)[0])
        res[f] = summarize(allbins)
        if reg_xchecks:
            res[f]["epochlog_region_frac"] = {k: statistics.mean(d[k] for d in reg_xchecks)
                                              for k in ("INCREASE", "HOLD", "DECREASE")}
    return res

def render(res, figs_dir):
    import matplotlib.pyplot as plt
    import plot_style
    plot_style.apply_style(13)
    fig, (axc, axb) = plt.subplots(1, 2, figsize=(10.0, 3.8))
    # (1) CDF of avg_q in HOLD epochs, per failed, vs T_cc
    for f in sorted(res):
        avs = sorted(v / 1000.0 for v in res[f]["hold_avgs"])
        if not avs:
            continue
        ys = [(i + 1) / len(avs) for i in range(len(avs))]
        axc.plot(avs, ys, lw=2.0, label=f"failed={f} (HOLD epochs, n={len(avs)})")
    axc.axvline(T_CC / 1000.0, color="gray", ls="--", lw=1.3, label=f"T_cc ({T_CC/1000:.1f}us)")
    axc.set_xlabel("avg queuing delay in HOLD epoch (us)")
    axc.set_ylabel("CDF")
    axc.set_title("Does avg separate f0 vs f8 HOLD epochs?", fontsize=11)
    axc.grid(alpha=0.3); axc.legend(fontsize=8)
    # (2) flip fraction P(avg<T_cc | HOLD) per failed
    fs = sorted(res)
    flips = [res[f]["flip_frac"] for f in fs]
    bars = axb.bar([str(f) for f in fs], flips, color=["tab:green" if f == 0 else "tab:red" for f in fs])
    for b, v in zip(bars, flips):
        axb.text(b.get_x() + b.get_width() / 2, v + 0.02, f"{v:.2f}", ha="center", fontsize=10)
    axb.set_ylim(0, 1.0)
    axb.set_xlabel("failed")
    axb.set_ylabel("flip fraction  P(avg < T_cc | HOLD)")
    axb.set_title("Proposal (b): HOLD->INCREASE share", fontsize=11)
    axb.grid(alpha=0.3, axis="y")
    plt.tight_layout()
    plot_style.save(fig, "figP_avg_discriminator", figs_dir)
    plt.close(fig)

def verdict(res):
    f0 = res.get(0, {}); f8 = res.get(8, {})
    lines = []
    for f in sorted(res):
        r = res[f]
        rl = r["region_frac"]; xl = r.get("epochlog_region_frac")
        lines.append(f"failed={f}: epochs={r['n_epochs']} regions(recon) "
                     f"INC={rl['INCREASE']:.2f}/HOLD={rl['HOLD']:.2f}/DEC={rl['DECREASE']:.2f}"
                     + (f"  [epochlog HOLD={xl['HOLD']:.2f} xcheck]" if xl else ""))
        lines.append(f"           HOLD epochs={r['n_hold']}  avg(HOLD) mean={r['hold_avg_mean_us']:.1f}us "
                     f"median={r['hold_avg_median_us']:.1f}us  flip P(avg<T_cc|HOLD)={r['flip_frac']:.2f} "
                     f"(early={r['flip_frac_early']:.2f}, late={r['flip_frac_late']:.2f})")
    f0flip = f0.get("flip_frac", float("nan")); f8flip = f8.get("flip_frac", float("nan"))
    sep = (f0flip - f8flip) if (f0flip == f0flip and f8flip == f8flip) else float("nan")
    lines.append("")
    lines.append(f"VERDICT: f0 flip={f0flip:.2f}  f8 flip={f8flip:.2f}  separation={sep:.2f}")
    if f0flip >= 0.6 and f8flip <= 0.4:
        lines.append("  => proposal (b) VALID: avg un-holds f0's transient while keeping f8's structural HOLD.")
    elif sep == sep and sep >= 0.25:
        lines.append("  => proposal (b) PARTIAL: avg separates f0/f8 but not cleanly; would help f0 at some f8 cost.")
    else:
        lines.append("  => proposal (b) WEAK: avg does NOT separate f0 from f8 HOLD epochs; (b) unlikely to help.")
    return "\n".join(lines)

def selftest():
    # decide_region truth table
    assert decide_region(0, 0) == INCREASE
    assert decide_region(0, 1e9) == HOLD
    assert decide_region(1e9, 0) == DECREASE
    assert decide_region(1e9, 1e9) == DECREASE
    # synthetic pathrtt: one flow, two epochs (base_ns wide). epoch0: q={0,20000} -> c_cc=0,
    # spread=20000>=T -> HOLD, avg=10000<T_cc -> FLIPS. epoch1: q={0,1000} -> spread small -> INCREASE.
    import tempfile
    d = tempfile.mkdtemp()
    p = os.path.join(d, "probe_prism_f0_s13.pathrtt.csv")
    with open(p, "w") as fh:
        # cols: time,flow,path,raw_rtt,ecn,cwnd ; raw=base+q
        fh.write(f"1000,1,0,{BASE_NS+0},0,100000\n")
        fh.write(f"2000,1,1,{BASE_NS+20000},0,100000\n")        # epoch0 (t-t0 < base_ns)
        fh.write(f"{BASE_NS+3000},1,0,{BASE_NS+0},0,100000\n")   # epoch1
        fh.write(f"{BASE_NS+4000},1,1,{BASE_NS+1000},0,100000\n")
    bins = epochs_from_pathrtt(p)
    assert len(bins) == 2, bins
    e0 = [b for b in bins if b["region"] == HOLD]
    assert len(e0) == 1 and abs(e0[0]["avg"] - 10000) < 1e-6, e0
    assert e0[0]["c_cc"] == 0 and e0[0]["c_spray"] == 20000, e0
    inc = [b for b in bins if b["region"] == INCREASE]
    assert len(inc) == 1, bins
    s = summarize(bins)
    assert s["n_hold"] == 1 and abs(s["flip_frac"] - 1.0) < 1e-9, s   # avg 15000 < T_cc -> flips
    import shutil
    shutil.rmtree(d)
    print("ok discriminator selftest")

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        DATA = os.path.join(HERE, "data")
        FIGS = os.path.join(HERE, "figs")
        os.makedirs(FIGS, exist_ok=True)
        res = analyze(DATA)
        print(verdict(res))
        render(res, FIGS)
        print(f"[discriminator] wrote {FIGS}/figP_avg_discriminator.{{png,pdf}}")
