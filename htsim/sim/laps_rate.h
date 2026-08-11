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

// Rates are integer bits/s.  One bit/s is the smallest representable positive
// LAPS pacing rate; it is deliberately not UEC's historical 1Gbps floor.
inline constexpr linkspeed_bps kLapsMinimumPacingRate = 1;

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

inline linkspeed_bps lapsControlIntervalFloor(mem_b packet_bytes,
                                              simtime_picosec min_delay,
                                              linkspeed_bps nic_rate) {
    if (packet_bytes <= 0 || min_delay == 0 || nic_rate == 0) {
        return std::min(nic_rate, kLapsMinimumPacingRate);
    }
    const simtime_picosec interval = saturatingDouble(min_delay);
    const unsigned __int128 numerator =
        static_cast<unsigned __int128>(packet_bytes) * 8 * timeFromSec(1.0);
    const unsigned __int128 floor =
        (numerator + static_cast<unsigned __int128>(interval) - 1) / interval;
    return floor >= nic_rate ? nic_rate : static_cast<linkspeed_bps>(floor);
}

inline LapsRateState advanceLapsRate(LapsRateState state, const LapsRateSignal& signal,
                                     simtime_picosec now, linkspeed_bps nic_rate,
                                     mem_b packet_bytes = 0) {
    if (!signal.calibrated) {
        return state;
    }

    // Strict LAPS is initialized from a positive NIC speed.  Keep both rate
    // variables in the representable [1 bit/s, NIC] interval so repeated
    // paper-style halving cannot feed a zero divisor to the LAPS pacer.
    const linkspeed_bps minimum_rate = std::max(
        std::min(nic_rate, kLapsMinimumPacingRate),
        lapsControlIntervalFloor(packet_bytes, signal.min_delay, nic_rate));
    state.cur_rate = std::max(minimum_rate, std::min(state.cur_rate, nic_rate));
    state.tgt_rate = std::max(minimum_rate, std::min(state.tgt_rate, nic_rate));

    if (signal.all_paths_high && now >= state.next_decrease_at) {
        state.tgt_rate = state.cur_rate;
        state.cur_rate = std::max(minimum_rate, state.cur_rate / 2);
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
