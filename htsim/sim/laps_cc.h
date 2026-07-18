// -*- c-basic-offset: 4; indent-tabs-mode: nil -*-
#ifndef LAPS_CC_H
#define LAPS_CC_H

#include <limits>

#include "uec_mp.h"

enum class LapsCwndAction { Hold, AdditiveIncrease, MultiplicativeDecrease };

struct LapsCwndDecision {
    LapsCwndAction action;
    simtime_picosec next_allowed_at;
};

inline simtime_picosec lapsNextAllowedAt(simtime_picosec now, simtime_picosec interval) {
    return interval > std::numeric_limits<simtime_picosec>::max() - now
               ? std::numeric_limits<simtime_picosec>::max()
               : now + interval;
}

inline simtime_picosec lapsDoubleInterval(simtime_picosec value) {
    return value > std::numeric_limits<simtime_picosec>::max() / 2
               ? std::numeric_limits<simtime_picosec>::max()
               : 2 * value;
}

inline LapsCwndDecision decideLapsCwnd(const UecMpLapsSignal& signal, simtime_picosec now,
                                       simtime_picosec next_increase_at,
                                       simtime_picosec next_decrease_at) {
    if (!signal.ready) {
        return {LapsCwndAction::Hold, 0};
    }

    if (signal.all_paths_high) {
        if (now < next_decrease_at) {
            return {LapsCwndAction::Hold, next_decrease_at};
        }
        return {LapsCwndAction::MultiplicativeDecrease,
                lapsNextAllowedAt(now, lapsDoubleInterval(signal.max_real_latency))};
    }

    if (now < next_increase_at) {
        return {LapsCwndAction::Hold, next_increase_at};
    }
    return {LapsCwndAction::AdditiveIncrease,
            lapsNextAllowedAt(now, lapsDoubleInterval(signal.threshold))};
}

#endif  // LAPS_CC_H
