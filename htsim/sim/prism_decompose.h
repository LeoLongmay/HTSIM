#ifndef PRISM_DECOMPOSE_H
#define PRISM_DECOMPOSE_H
// PRISM congestion decomposition — pure logic, no htsim dependencies (uint64_t times).
// Used by UecSrc::updateCwndOnAck_PRISM and unit-tested standalone. Times in picoseconds.
#include <cstdint>
#include <algorithm>

namespace prism {

enum Region { INCREASE = 0, HOLD = 1, DECREASE = 2 };

// Four-quadrant rule. floor C_cc vs target T_cc; spread C_spray vs tolerance T_spray.
// ">=" counts as "high". P5 ablation variants will branch here (left as the single
// decision point); P1 implements the default rule only.
inline Region decide_region(uint64_t c_cc, uint64_t c_spray,
                            uint64_t t_cc, uint64_t t_spray) {
    bool floor_high  = c_cc    >= t_cc;
    bool spread_high = c_spray >= t_spray;
    if (!floor_high && !spread_high) return INCREASE;  // floor safe, paths balanced
    if (!floor_high &&  spread_high) return HOLD;       // clean path exists; let REPS rebalance
    return DECREASE;                                    // floor high: even the best path is queued
}

// Multiplicative-decrease multiplier (NSCC's formula, fed the floor): max(1 - g*(Ccc-Tcc)/Ccc, 0.5).
// Returns 1.0 (no cut) when C_cc <= T_cc.
inline double md_factor(uint64_t c_cc, uint64_t t_cc, double gamma) {
    if (c_cc <= t_cc) return 1.0;
    double f = 1.0 - gamma * (double)(c_cc - t_cc) / (double)c_cc;
    return std::max(f, 0.5);
}

}  // namespace prism
#endif  // PRISM_DECOMPOSE_H
