#ifndef MNSCC_MEDIAN_H
#define MNSCC_MEDIAN_H
// Pure logic for MNSCC (median@NSCC), from Gerstein et al. 2026 "Congestion Control for
// Spraying with Congested Paths": the median-of-recent-delays statistic and the Nyquist
// history-size rule H = max(min(W/2, 4), 1). Header-only, no side effects; unit-tested in
// datacenter/prism_eval/common/tests/test_mnscc_median.cpp.
#include <algorithm>
#include <cstdint>

namespace mnscc {

// Median of the n most-recent samples in `buf`. Odd n: middle element. Even n: average of the
// two middle elements. n<=1 returns buf[0] (degenerates to the latest signal = plain NSCC).
// Computes on a local copy; does not mutate `buf`. Caller guarantees 1 <= n <= 64.
template <typename T>
inline T median_of(const T* buf, int n) {
    if (n <= 1) return buf[0];
    T tmp[64];                      // n bounded by MNSCC_MAX_H (<=32); 64 is a safe ceiling
    for (int i = 0; i < n; ++i) tmp[i] = buf[i];
    std::sort(tmp, tmp + n);
    if (n & 1) return tmp[n / 2];
    return (tmp[n / 2 - 1] + tmp[n / 2]) / 2;
}

// Nyquist history size for MNSCC: H = max(min(W/2, 4), 1), W = cwnd in packets.
inline int nyquist_h(int w_packets) {
    int h = w_packets / 2;
    if (h > 4) h = 4;
    if (h < 1) h = 1;
    return h;
}

} // namespace mnscc
#endif
