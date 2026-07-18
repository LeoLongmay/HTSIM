// -*- c-basic-offset: 4; indent-tabs-mode: nil -*-
#include "laps_recovery.h"

#include <algorithm>
#include <iterator>
#include <limits>

namespace {

simtime_picosec twiceOrMax(simtime_picosec delay) {
    return delay > std::numeric_limits<simtime_picosec>::max() / 2
               ? std::numeric_limits<simtime_picosec>::max()
               : 2 * delay;
}

}  // namespace

LapsRecoveryDomain::LapsRecoveryDomain(EventList& eventlist)
    : EventSource(eventlist, "laps recovery"),
      timer_handle_(eventlist.nullHandle()),
      timer_deadline_(0) {}

LapsAttempt LapsRecoveryDomain::sent(LapsPathKey path, LapsRecoveryOwner& owner,
                                     UecBasePacket::seq_t seq, mem_b bytes) {
    const auto path_it = paths_.try_emplace(OwnerPathKey{std::move(path), &owner}).first;
    PathState& state = path_it->second;
    const LapsAttempt attempt(next_attempt_id_++);
    state.records.push_back({attempt, &owner, seq, bytes});
    arm(state);
    updateTimer();
    return attempt;
}

bool LapsRecoveryDomain::acknowledge(
    LapsAttempt attempt, std::optional<simtime_picosec> one_way_delay) {
    const auto located = findAttempt(attempt);
    if (!located) {
        return false;
    }

    PathState& state = *located->state;
    if (one_way_delay && *one_way_delay != 0) {
        state.one_way_delay = *one_way_delay;
    }
    std::vector<Record> inferred_losses(state.records.begin(), located->record);
    state.records.erase(state.records.begin(), std::next(located->record));
    if (!state.records.empty()) {
        arm(state);
    }
    updateTimer();
    for (const Record& record : inferred_losses) {
        record.owner->lapsRecover(record.attempt, record.seq, record.bytes);
    }
    return true;
}

bool LapsRecoveryDomain::nack(LapsAttempt attempt) {
    return detach(attempt);
}

bool LapsRecoveryDomain::retire(LapsAttempt attempt) {
    return detach(attempt);
}

std::optional<LapsRecoveryDomain::LocatedAttempt> LapsRecoveryDomain::findAttempt(
    LapsAttempt attempt) {
    if (!attempt) {
        return std::nullopt;
    }

    for (auto path_it = paths_.begin(); path_it != paths_.end(); ++path_it) {
        PathState& state = path_it->second;
        const auto record_it = std::find_if(state.records.begin(), state.records.end(),
                                            [&](const Record& record) {
                                                return record.attempt == attempt;
                                            });
        if (record_it != state.records.end()) {
            return LocatedAttempt{&state, record_it};
        }
    }
    return std::nullopt;
}

bool LapsRecoveryDomain::detach(LapsAttempt attempt) {
    const auto located = findAttempt(attempt);
    if (!located) {
        return false;
    }

    PathState& state = *located->state;
    state.records.erase(located->record);
    if (!state.records.empty()) {
        arm(state);
    }
    updateTimer();
    return true;
}

void LapsRecoveryDomain::arm(PathState& state) {
    const simtime_picosec interval = state.one_way_delay
                                         ? twiceOrMax(*state.one_way_delay)
                                         : kBootstrapRto;
    state.deadline = EventList::now() > std::numeric_limits<simtime_picosec>::max() - interval
                         ? std::numeric_limits<simtime_picosec>::max()
                         : EventList::now() + interval;
}

void LapsRecoveryDomain::removeOwner(LapsRecoveryOwner& owner) {
    for (auto path_it = paths_.begin(); path_it != paths_.end();) {
        if (path_it->first.owner == &owner) {
            path_it = paths_.erase(path_it);
        } else {
            ++path_it;
        }
    }
    updateTimer();
}

void LapsRecoveryDomain::doNextEvent() {
    timer_handle_ = eventlist().nullHandle();
    timer_deadline_ = 0;

    std::vector<Record> expired_records;
    for (auto& [path, state] : paths_) {
        if (!state.records.empty() && state.deadline <= EventList::now()) {
            expired_records.insert(expired_records.end(), state.records.begin(), state.records.end());
            state.records.clear();
        }
    }

    // Re-arm from the still-live paths before owner callbacks can register
    // fresh attempts for an expired physical path.
    updateTimer();
    for (const Record& record : expired_records) {
        record.owner->lapsRecover(record.attempt, record.seq, record.bytes);
    }
}

void LapsRecoveryDomain::updateTimer() {
    simtime_picosec earliest_deadline = std::numeric_limits<simtime_picosec>::max();
    bool has_active_deadline = false;
    for (const auto& [path, state] : paths_) {
        if (!state.records.empty()) {
            has_active_deadline = true;
            earliest_deadline = std::min(earliest_deadline, state.deadline);
        }
    }

    if (!has_active_deadline) {
        if (timer_handle_ != eventlist().nullHandle()) {
            eventlist().cancelPendingSourceByHandle(*this, timer_handle_);
            timer_handle_ = eventlist().nullHandle();
        }
        timer_deadline_ = 0;
        return;
    }

    if (timer_handle_ != eventlist().nullHandle() && timer_deadline_ == earliest_deadline) {
        return;
    }
    if (timer_handle_ != eventlist().nullHandle()) {
        eventlist().cancelPendingSourceByHandle(*this, timer_handle_);
    }
    timer_deadline_ = earliest_deadline;
    timer_handle_ = eventlist().sourceIsPendingGetHandle(*this, timer_deadline_);
    if (timer_handle_ == eventlist().nullHandle()) {
        timer_deadline_ = 0;
    }
}
