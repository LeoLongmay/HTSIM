#ifndef STRACK_CC_H
#define STRACK_CC_H
// STrack congestion control — pure decision logic, no htsim dependencies (uint64_t times,
// picoseconds). Ported from the STrack paper, Algorithm 4 (§3.2; paper under Strack/paper/ in this repo). Used by
// UecSrc::updateCwndOnAck_STRACK and unit-tested standalone. The coupled-SOTA baseline:
// ECN-gated, and its multiplicative decrease keys off the AVERAGE delay (the signal
// conflation PRISM's decomposition is contrasted against). See prism_decompose.h for the peer.
#include <cstdint>

namespace strack {

enum Action { INCREASE_PROP = 0, STARVATION_BUMP = 1, MULT_DECREASE = 2, HOLD = 3 };

// STrack Algorithm 4 decision tree. `target` = base target queuing delay (= _target_Qdelay).
//  - No ECN  -> increase branch: prop-increase if delay<target; beta starvation bump if the
//    queue has drained (no ECN) yet this packet still saw delay>2*target; else hold.
//  - ECN set -> decrease branch: multiplicative decrease iff the AVERAGE delay exceeds target;
//    otherwise hold (mark with low avg => switch path, keep window: STrack Scenario #2).
// ">" / "<" are strict; equality holds (no action) — matches the paper's threshold semantics
// and keeps proportional_increase's `target>delay` precondition satisfied on the INCREASE path.
inline Action decide_action(bool ecn, uint64_t delay, uint64_t avg_delay, uint64_t target) {
    if (!ecn) {
        // Starvation check first (mutually exclusive with increase; order follows Algorithm 4's special-case-first reading).
        if (delay > 2 * target) return STARVATION_BUMP;
        if (delay < target)     return INCREASE_PROP;
        return HOLD;
    }
    if (avg_delay > target) return MULT_DECREASE;
    return HOLD;
}

}  // namespace strack
#endif  // STRACK_CC_H
