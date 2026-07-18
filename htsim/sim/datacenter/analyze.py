#!/usr/bin/env python3
"""把按时间采样的队列快照分解为 C_spray 和 C_cc"""
import collections
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BYTES_TO_US = 8e-3 / 100  # 100 Gbps 链路:1 字节 ≈ 0.00008 μs 排队延迟


def parse(path):
    """返回 {time_us: {queue_id: lastQ_bytes}}"""
    data = collections.defaultdict(dict)
    with open(path) as f:
        for line in f:
            # 格式: <t> Type QUEUE_APPROX ID <qid> Ev RANGE LastQ <b> MinQ <b> MaxQ <b>
            p = line.split()
            if len(p) < 8:
                continue
            t_us = float(p[0]) * 1e6
            qid = int(p[4])
            # 字段布局: ... p[4]=qid p[5]=Ev p[6]=RANGE p[7]="LastQ" p[8]=<值> ...
            # (prompt 原脚本误用 p[7]——那是字面量 "LastQ";真正的字节数在 p[8])
            lastQ = int(p[8])
            data[t_us][qid] = lastQ
    return data


def decompose(data):
    """对每个时间点,在所有观测到的队列上计算 max-min 和 min"""
    times, c_spray, c_cc = [], [], []
    for t, qs in sorted(data.items()):
        vals = list(qs.values())
        if not vals:
            continue
        times.append(t)
        c_spray.append(max(vals) - min(vals))
        c_cc.append(min(vals))
    return times, c_spray, c_cc


def summarize(tag):
    data = parse(f'mvp_runs/{tag}.q.txt')
    t, cs, cc = decompose(data)
    cs_us = [x * BYTES_TO_US for x in cs]
    cc_us = [x * BYTES_TO_US for x in cc]

    # 关注流的活跃窗口(0–500 μs 是动作集中区)
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(t, cs_us, label='C_spray = max-min', linewidth=1.2)
    ax.plot(t, cc_us, label='C_cc = min', linewidth=1.2)
    ax.set_xlabel('time (us)')
    ax.set_ylabel('queueing delay proxy (us)')
    ax.set_xlim(0, 500)
    ax.set_title(tag)
    ax.legend()
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(f'mvp_runs/{tag}.png', dpi=130)
    plt.close()

    # 统计
    peak_cs = max(cs_us) if cs_us else 0
    peak_cc = max(cc_us) if cc_us else 0
    mean_cs = sum(cs_us) / len(cs_us) if cs_us else 0
    mean_cc = sum(cc_us) / len(cc_us) if cc_us else 0
    print(f'{tag:20s}  C_spray peak={peak_cs:6.2f}us mean={mean_cs:5.2f}us  '
          f'C_cc peak={peak_cc:6.2f}us mean={mean_cc:5.2f}us')


for tag in ['A_reps_sym', 'B_reps_asym2', 'C_reps_asym8', 'D_ops_asym2']:
    summarize(tag)
