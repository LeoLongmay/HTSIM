#ifndef SWIFT_CC_H
#define SWIFT_CC_H
// Pure logic for the Swift CC (Kumar et al., SIGCOMM 2020): Algorithm 1's MD factor and the §3.5
// flow-scaled target delay, ported into the UecSrc framework. Header-only, no side effects;
// unit-tested in datacenter/prism_eval/common/tests/test_swift_cc.cpp. We work in the QUEUING-delay
// domain (delay = raw_rtt - base_rtt), so §3.5's base_target + #hops*h terms fold into base_q.
// Times are picoseconds (== simtime_picosec == uint64_t); kept as uint64_t so the header is
// standalone-compilable for the unit test.
#include <algorithm>
#include <cmath>
#include <cstdint>

namespace swift {

// §3.5 flow-scaling coefficients: a = fs_range / (1/sqrt(fs_min) - 1/sqrt(fs_max)), b = -a/sqrt(fs_max).
inline void fs_coeffs(double fs_range, double fs_min_cwnd, double fs_max_cwnd, double& a, double& b) {
    a = fs_range / (1.0 / std::sqrt(fs_min_cwnd) - 1.0 / std::sqrt(fs_max_cwnd));
    b = -a / std::sqrt(fs_max_cwnd);
}

// §3.5 target in the queuing-delay domain: base_q + clamp(a/sqrt(cwnd_pkts) + b, 0, fs_range).
// cwnd_pkts <= 0 -> base_q (no scaling). Larger cwnd -> smaller scaling term (target -> base_q).
inline uint64_t target_delay_q(double cwnd_pkts, uint64_t base_q, double a, double b, double fs_range) {
    if (cwnd_pkts <= 0.0) return base_q;
    double fs = a / std::sqrt(cwnd_pkts) + b;
    if (fs > fs_range) fs = fs_range;
    if (fs < 0.0) fs = 0.0;
    return base_q + (uint64_t)std::round(fs);
}

// Algorithm 1 MD factor: max(1 - beta*(delay-target)/delay, 1 - max_mdf).
// Caller guarantees delay >= target and delay > 0 (only the MD branch calls this).
inline double md_factor(uint64_t delay, uint64_t target, double beta, double max_mdf) {
    double f = 1.0 - beta * (double)(delay - target) / (double)delay;
    double lo = 1.0 - max_mdf;
    return f > lo ? f : lo;
}

} // namespace swift
#endif
