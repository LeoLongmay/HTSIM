#ifndef PRISM_DECOMPOSE_H
#define PRISM_DECOMPOSE_H
// PRISM congestion decomposition — pure logic, no htsim dependencies (uint64_t times).
// Delay decomposition (decide_region/md_factor, picosecond times) + loss/NACK decision (decide_loss). Used by UecSrc::updateCwndOnAck_PRISM / updateCwndOnNack_PRISM; unit-tested standalone.
#include <cstdint>
#include <algorithm>

namespace prism {

enum Region { INCREASE = 0, HOLD = 1, DECREASE = 2 };

// Four-quadrant rule. floor C_cc vs target T_cc; spread C_spray vs tolerance T_spray.
// ">=" counts as "high". P5 ablation variants will branch here (left as the single
// decision point); P1 implements the default rule only.
inline Region decide_region(uint64_t c_cc, uint64_t c_spray,
                            uint64_t t_cc, uint64_t t_spray,
                            double spread_ratio = 0.0) {
    bool floor_high  = c_cc >= t_cc;
    bool spread_high = (c_spray >= t_spray) &&
                       (spread_ratio <= 0.0 || (double)c_spray >= spread_ratio * (double)c_cc);
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

// Loss four-quadrant rule -- the loss/NACK analog of decide_region, used by
// UecSrc::updateCwndOnNack_PRISM. Holds the window when loss is reroutable (a clean path is
// still ACKing) and cuts when loss is uniform or not reroutable. See spec 2026-06-16-prism-loss-decomp.
enum LossAction { LOSS_CUT = 0, LOSS_HOLD = 1 };

inline LossAction decide_loss(bool last_hop, bool enough_evidence,
                              bool clean_path_exists, bool streak_exceeded) {
    if (last_hop)          return LOSS_CUT;   // last-hop receiver incast -> not reroutable
    if (!enough_evidence)  return LOSS_CUT;   // too few good-ACK paths seen yet -> safe default
    if (streak_exceeded)   return LOSS_CUT;   // safety valve: held too long -> force a cut
    if (clean_path_exists) return LOSS_HOLD;  // concentrated loss, clean path exists -> hold, let REPS reroute
    return LOSS_CUT;                          // uniform loss across paths -> genuine congestion
}

}  // namespace prism
#endif  // PRISM_DECOMPOSE_H
