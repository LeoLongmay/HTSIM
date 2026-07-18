// -*- c-basic-offset: 4; indent-tabs-mode: nil -*-
#include "laps_recovery.h"

#include <algorithm>
#include <iterator>
#include <limits>

LapsRecoveryDomain::LapsRecoveryDomain(EventList& eventlist)
    : EventSource(eventlist, "laps recovery"),
      timer_handle_(eventlist.nullHandle()),
      timer_deadline_(0) {}

LapsAttempt LapsRecoveryDomain::sent(LapsPathKey path, LapsRecoveryOwner& owner,
                                     UecBasePacket::seq_t seq, mem_b bytes) {
    const auto path_it = paths_.try_emplace(path).first;
    PathState& state = path_it->second;
    const LapsAttempt attempt(next_attempt_id_++);
    state.records.push_back({attempt, &owner, seq, bytes});
    state.deadline = EventList::now() + kRto;
    updateTimer();
    return attempt;
}

bool LapsRecoveryDomain::acknowledge(LapsAttempt attempt) {
    return detachWithInference(attempt);
}

bool LapsRecoveryDomain::nack(LapsAttempt attempt) {
    return detachWithInference(attempt);
}

bool LapsRecoveryDomain::retire(LapsAttempt attempt) {
    if (!attempt) {
        return false;
    }

    for (auto path_it = paths_.begin(); path_it != paths_.end(); ++path_it) {
        PathState& state = path_it->second;
        const auto record_it = std::find_if(state.records.begin(), state.records.end(),
                                            [&](const Record& record) {
                                                return record.attempt == attempt;
                                            });
        if (record_it == state.records.end()) {
            continue;
        }

        state.records.erase(record_it);
        if (state.records.empty()) {
            paths_.erase(path_it);
        } else {
            state.deadline = EventList::now() + kRto;
        }
        updateTimer();
        return true;
    }
    return false;
}

bool LapsRecoveryDomain::detachWithInference(LapsAttempt attempt) {
    if (!attempt) {
        return false;
    }

    for (auto path_it = paths_.begin(); path_it != paths_.end(); ++path_it) {
        PathState& state = path_it->second;
        const auto matched = std::find_if(state.records.begin(), state.records.end(),
                                          [&](const Record& record) {
                                              return record.attempt == attempt;
                                          });
        if (matched == state.records.end()) {
            continue;
        }

        std::vector<Record> inferred_losses;
        for (auto record_it = state.records.begin(); record_it != matched; ++record_it) {
            inferred_losses.push_back(*record_it);
        }
        state.records.erase(state.records.begin(), std::next(matched));

        if (state.records.empty()) {
            paths_.erase(path_it);
        } else {
            state.deadline = EventList::now() + kRto;
        }
        // The old attempts are no longer visible before a callback can send
        // again and register a new handle.
        updateTimer();
        for (const Record& record : inferred_losses) {
            record.owner->lapsRecover(record.attempt, record.seq, record.bytes);
        }
        return true;
    }
    return false;
}

void LapsRecoveryDomain::removeOwner(LapsRecoveryOwner& owner) {
    for (auto path_it = paths_.begin(); path_it != paths_.end();) {
        PathState& state = path_it->second;
        const size_t old_size = state.records.size();
        state.records.remove_if([&](const Record& record) { return record.owner == &owner; });
        if (state.records.empty()) {
            path_it = paths_.erase(path_it);
        } else {
            if (state.records.size() != old_size) {
                state.deadline = EventList::now() + kRto;
            }
            ++path_it;
        }
    }
    updateTimer();
}

void LapsRecoveryDomain::doNextEvent() {
    timer_handle_ = eventlist().nullHandle();
    timer_deadline_ = 0;

    std::vector<Record> expired_records;
    for (auto path_it = paths_.begin(); path_it != paths_.end();) {
        if (path_it->second.deadline <= EventList::now()) {
            const PathState& state = path_it->second;
            expired_records.insert(expired_records.end(), state.records.begin(), state.records.end());
            path_it = paths_.erase(path_it);
        } else {
            ++path_it;
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
    if (paths_.empty()) {
        if (timer_handle_ != eventlist().nullHandle()) {
            eventlist().cancelPendingSourceByHandle(*this, timer_handle_);
            timer_handle_ = eventlist().nullHandle();
        }
        timer_deadline_ = 0;
        return;
    }

    simtime_picosec earliest_deadline = std::numeric_limits<simtime_picosec>::max();
    for (const auto& [path, state] : paths_) {
        earliest_deadline = std::min(earliest_deadline, state.deadline);
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
