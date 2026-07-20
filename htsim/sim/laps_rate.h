// -*- c-basic-offset: 4; indent-tabs-mode: nil -*-
#ifndef LAPS_RATE_H
#define LAPS_RATE_H

#include <algorithm>
#include <limits>

#include "network.h"

struct LapsRateState {
    linkspeed_bps cur_rate;
    linkspeed_bps tgt_rate;
    uint32_t inc_stage;
    simtime_picosec next_decrease_at;
    simtime_picosec next_increase_at;
};

struct LapsRateSignal {
    bool calibrated;
    bool all_paths_high;
    simtime_picosec target_delay;
    simtime_picosec min_delay;
};

inline simtime_picosec saturatingAdd(simtime_picosec lhs, simtime_picosec rhs) {
    return rhs > std::numeric_limits<simtime_picosec>::max() - lhs
               ? std::numeric_limits<simtime_picosec>::max()
               : lhs + rhs;
}

inline simtime_picosec saturatingDouble(simtime_picosec value) {
    return value > std::numeric_limits<simtime_picosec>::max() / 2
               ? std::numeric_limits<simtime_picosec>::max()
               : 2 * value;
}

inline LapsRateState advanceLapsRate(LapsRateState state, const LapsRateSignal& signal,
                                     simtime_picosec now, linkspeed_bps nic_rate) {
    if (!signal.calibrated) {
        return state;
    }

    if (signal.all_paths_high && now >= state.next_decrease_at) {
        state.tgt_rate = state.cur_rate;
        state.cur_rate /= 2;
        state.inc_stage = 0;
        state.next_decrease_at = saturatingAdd(now, saturatingDouble(signal.min_delay));
        return state;
    }

    if (!signal.all_paths_high && now >= state.next_increase_at) {
        if (state.inc_stage > 5) {
            state.tgt_rate = state.tgt_rate > nic_rate / 2 ? nic_rate : state.tgt_rate * 2;
        }
        state.cur_rate = std::min(nic_rate, (state.cur_rate + state.tgt_rate) / 2);
        state.tgt_rate = std::max(state.tgt_rate, state.cur_rate);
        ++state.inc_stage;
        state.next_increase_at = saturatingAdd(now, saturatingDouble(signal.min_delay));
    }

    return state;
}

#endif  // LAPS_RATE_H
