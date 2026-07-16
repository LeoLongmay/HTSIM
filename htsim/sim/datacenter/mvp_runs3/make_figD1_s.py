#!/usr/bin/env python3
"""Render the isolated FigD1 reproduction without touching the paper figures."""
import argparse
import collections
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pathrtt_analyze as A


def timeseries_median(csv, const_base, bin_ns=10000, tmax_us=2000, min_samples=200):
    rows = A.parse_csv(csv)
    mins = A.rtt_min_per_path(rows)
    minf = A.rtt_min_per_flow(rows)
    counts = collections.Counter(row[1] for row in rows)
    t1 = tmax_us * 1000
    cs_by_bin = collections.defaultdict(list)
    cc_by_bin = collections.defaultdict(list)
    for flow, count in counts.items():
        if count < min_samples:
            continue
        t_ns, cs, cc = A.decompose(rows, mins, flow, baseline="const",
                                   rtt_min_flow=minf, const_base=const_base, t0=0, t1=t1)
        for timestamp, spray, cc_only in zip(t_ns, cs, cc):
            cs_by_bin[timestamp].append(spray)
            cc_by_bin[timestamp].append(cc_only)
    bins = sorted(cs_by_bin)
    return ([timestamp / 1000 for timestamp in bins],
            [statistics.median(cs_by_bin[timestamp]) / 1000 for timestamp in bins],
            [statistics.median(cc_by_bin[timestamp]) / 1000 for timestamp in bins])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--timeseries", required=True)
    parser.add_argument("--output-stem", required=True)
    args = parser.parse_args()

    bprop = min(row[3] for row in A.parse_csv(args.baseline))
    times, spray, cc_only = timeseries_median(args.timeseries, const_base=bprop)
    if not times:
        raise RuntimeError("no time-series samples passed the FigD1 sample gate")

    with plt.rc_context({"font.size": 24}):
        plt.figure()
        plt.plot(times, spray, lw=2, label=r"$C_{spray}$ (LB-removable)")
        plt.plot(times, cc_only, "--", lw=2, label=r"$C_{cc}$ (CC-only)")
        plt.axvspan(500, 1500, color="grey", alpha=0.12)
        plt.xlabel("time (us)")
        plt.ylabel("Queueing delay (us)")
        plt.ylim(0, 26)
        plt.xlim(0, 2000)
        plt.xticks([0, 500, 1000, 1500, 2000])
        plt.grid(alpha=0.3)
        plt.tight_layout()
        plt.savefig(args.output_stem + ".png", dpi=140, bbox_inches="tight", pad_inches=0.05)
        plt.savefig(args.output_stem + ".pdf", bbox_inches="tight", pad_inches=0.05)
        plt.close()
    print(f"FigD1 samples={len(times)} bprop_ns={bprop}")


if __name__ == "__main__":
    main()
