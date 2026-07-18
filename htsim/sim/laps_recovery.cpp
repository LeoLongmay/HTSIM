// -*- c-basic-offset: 4; indent-tabs-mode: nil -*-
#include "laps_recovery.h"

#include <algorithm>
#include <iterator>
#include <limits>

LapsRecoveryDomain::LapsRecoveryDomain(EventList& eventlist)
    : EventSource(eventlist, "laps recovery"),
      timer_handle_(eventlist.nullHandle()),
      timer_deadline_(0) {}

void LapsRecoveryDomain::sent(LapsPathKey path, LapsRecoveryOwner& owner,
                              UecBasePacket::seq_t seq, mem_b bytes) {
    const auto path_it = paths_.try_emplace(path).first;
    PathState& state = path_it->second;
    state.records.push_back({&owner, seq, bytes});
    state.deadline = EventList::now() + kRto;
    updateTimer();
}

bool LapsRecoveryDomain::acknowledge(LapsPathKey path, LapsRecoveryOwner& owner,
                                     UecBasePacket::seq_t seq, mem_b bytes) {
    const auto path_it = paths_.find(path);
    if (path_it == paths_.end()) {
        return false;
    }

    PathState& state = path_it->second;
    const auto matched = std::find_if(state.records.begin(), state.records.end(),
                                      [&](const Record& record) {
                                          return record.owner == &owner && record.seq == seq &&
                                                 record.bytes == bytes;
                                      });
    if (matched == state.records.end()) {
        return false;
    }

    for (auto record_it = state.records.begin(); record_it != matched; ++record_it) {
        record_it->owner->lapsRecover(record_it->seq, record_it->bytes);
    }
    state.records.erase(state.records.begin(), std::next(matched));

    if (state.records.empty()) {
        paths_.erase(path_it);
    } else {
        state.deadline = EventList::now() + kRto;
    }
    updateTimer();
    return true;
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

    for (const Record& record : expired_records) {
        record.owner->lapsRecover(record.seq, record.bytes);
    }
    updateTimer();
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
