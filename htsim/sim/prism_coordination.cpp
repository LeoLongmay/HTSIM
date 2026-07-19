#include "prism_coordination.h"

#include <algorithm>

bool applyPrismNoProgressHandoff(mem_b& cwnd, mem_b min_cwnd) {
    const mem_b before = cwnd;
    cwnd = std::max(min_cwnd, static_cast<mem_b>(cwnd * 0.9));
    return cwnd < before;
}

PrismResidualCoordinator::PrismResidualCoordinator(PrismCoordinationMode mode,
                                                   simtime_picosec t_cc,
                                                   simtime_picosec t_spray,
                                                   simtime_picosec base_rtt)
    : _mode(mode), _t_cc(t_cc), _t_spray(t_spray),
      _outcome_window_ps(base_rtt * 4) {}

void PrismResidualCoordinator::observeAck(uint64_t epoch_id, uint16_t slot,
                                          uint64_t generation, simtime_picosec qdelay,
                                          bool ecn, bool genuine) {
    if (!genuine) {
        return;
    }
    _observations[{epoch_id, {slot, generation}}] = {qdelay, ecn};
}

void PrismResidualCoordinator::observeReplacementReservation(uint16_t slot,
                                                              uint64_t generation) {
    beginOutcomeReplacement(slot, generation);
}

void PrismResidualCoordinator::observeConsumedHighResidual(uint64_t epoch_id, uint16_t slot,
                                                            uint64_t generation, uint32_t entropy,
                                                            simtime_picosec residual_ps) {
    if (!outcomeEnabled() || residual_ps < _t_spray) {
        return;
    }
    _outcome_consumed_high_residuals[{epoch_id, {slot, generation}}] = {
        entropy, residual_ps};
}

bool PrismResidualCoordinator::observeReplacementAdmission(uint16_t slot,
                                                            uint64_t generation) {
    if (!outcomeEnabled() || !_outcome_tracking) {
        return false;
    }
    const auto replacement = _outcome_replacements.find(slot);
    if (replacement == _outcome_replacements.end() ||
        replacement->second.admitted || generation <= replacement->second.invalidated_generation) {
        return false;
    }
    replacement->second.replacement_generation = generation;
    replacement->second.admitted = true;
    replacement->second.reuse_validated = false;
    _outcome_replacements_validated = false;
    return true;
}

bool PrismResidualCoordinator::isOutcomeReplacement(uint16_t slot, uint64_t generation) const {
    if (!outcomeEnabled() || !_outcome_tracking) {
        return false;
    }
    const auto replacement = _outcome_replacements.find(slot);
    return replacement != _outcome_replacements.end() && replacement->second.admitted &&
           replacement->second.replacement_generation == generation;
}

void PrismResidualCoordinator::observeReplacementReuse(uint16_t slot,
                                                        uint64_t generation,
                                                        simtime_picosec residual_ps,
                                                        bool ecn, bool genuine,
                                                        simtime_picosec timestamp) {
    if (!outcomeEnabled()) {
        return;
    }
    const auto replacement = _outcome_replacements.find(slot);
    if (replacement == _outcome_replacements.end() || !replacement->second.admitted ||
        generation != replacement->second.replacement_generation || !genuine || ecn ||
        residual_ps >= _t_spray) {
        return;
    }
    replacement->second.reuse_validated = true;

    const bool all_validated = !_outcome_replacements.empty() &&
        std::all_of(_outcome_replacements.begin(), _outcome_replacements.end(),
                    [](const auto& entry) { return entry.second.reuse_validated; });
    if (all_validated && !_outcome_replacements_validated) {
        _outcome_replacements_validated = true;
        snapshotOutcomePre(timestamp);
    }
}

void PrismResidualCoordinator::observeClassifiedAck(simtime_picosec timestamp,
                                                     simtime_picosec residual_ps,
                                                     bool ecn, bool genuine,
                                                     uint64_t acked_bytes) {
    if (!outcomeEnabled() || !genuine || acked_bytes == 0 || _outcome_window_ps == 0) {
        return;
    }
    if (!_outcome_tracking) {
        observeOutcomeBaseline(timestamp, residual_ps, ecn, acked_bytes);
        return;
    }
    if (!_outcome_active_bucket.has_value()) {
        _outcome_active_bucket = OutcomeBucket{timestamp, 0, 0};
    }
    if (timestamp < _outcome_active_bucket->start) {
        return;
    }
    while (_outcome_active_bucket.has_value() &&
           timestamp >= _outcome_active_bucket->start + _outcome_window_ps) {
        const OutcomeBucket completed = *_outcome_active_bucket;
        completeOutcomeBucket(completed);
        if (!_outcome_tracking) {
            return;
        }
        _outcome_active_bucket = OutcomeBucket{completed.start + _outcome_window_ps, 0, 0};
        if (timestamp >= _outcome_active_bucket->start + _outcome_window_ps) {
            resetOutcomeState();
            return;
        }
    }
    if (!_outcome_active_bucket.has_value()) {
        return;
    }
    _outcome_active_bucket->classified_bytes += acked_bytes;
    if (ecn || residual_ps >= _t_spray) {
        _outcome_active_bucket->harmful_bytes += acked_bytes;
    }
}

void PrismResidualCoordinator::observeFullHandoffAck(simtime_picosec timestamp,
                                                      simtime_picosec base_rtt,
                                                      simtime_picosec residual, bool ecn,
                                                      bool genuine, uint64_t acked_bytes) {
    if (!fullHandoffEnabled() || !genuine) {
        return;
    }
    if (base_rtt > 0) {
        _full_base_rtts.push_back(base_rtt);
        if (_full_base_rtts.size() > 3) {
            _full_base_rtts.pop_front();
        }
    }
    const bool harmful = ecn || residual >= _t_spray;
    if (acked_bytes > 0) {
        _full_ack_samples.push_back({timestamp, acked_bytes, harmful});
        trimFullAckSamples(timestamp);
    }

    if (_full_handoff_state != FullHandoffState::EVIDENCE_PENDING ||
        !_full_pending_evidence.has_value() ||
        timestamp <= _full_pending_evidence->terminal_ps) {
        return;
    }

    const PendingFullEvidence& pending = *_full_pending_evidence;
    const simtime_picosec elapsed = timestamp - pending.terminal_ps;
    PrismHandoffWindow* post = elapsed < pending.base_rtt_ps ? &_full_post1 : &_full_post2;
    post->acked_bytes += acked_bytes;
    if (harmful) {
        post->harmful_bytes += acked_bytes;
    }
    if (elapsed >= pending.base_rtt_ps && elapsed - pending.base_rtt_ps >= pending.base_rtt_ps) {
        completeFullHandoffEvidence();
    }
}

void PrismResidualCoordinator::setOutcomeBaseRtt(simtime_picosec base_rtt) {
    if (!outcomeEnabled() || base_rtt == 0) {
        return;
    }
    const simtime_picosec window_ps = base_rtt * 4;
    if (_outcome_window_ps == window_ps) {
        return;
    }
    _outcome_window_ps = window_ps;
    resetOutcomeState();
}

bool PrismResidualCoordinator::outcomeTracking() const {
    return _outcome_tracking;
}

bool PrismResidualCoordinator::outcomeReplacementsValidated() const {
    return _outcome_replacements_validated;
}

std::optional<PrismOutcome> PrismResidualCoordinator::takeOutcome() {
    std::optional<PrismOutcome> outcome = _outcome_event;
    _outcome_event.reset();
    return outcome;
}

std::optional<PrismFullHandoffEvidence> PrismResidualCoordinator::takeFullHandoffEvidence() {
    std::optional<PrismFullHandoffEvidence> evidence = _full_handoff_event;
    _full_handoff_event.reset();
    if (_full_handoff_state == FullHandoffState::LATCHED && evidence.has_value() &&
        !evidence->handoff_requested) {
        resetFullHandoffState();
    }
    return evidence;
}

PrismCoordinationResult PrismResidualCoordinator::closeEpoch(const PrismCoordinationEpoch& epoch) {
    PrismCoordinationResult result;

    if (!enabled() || epoch.region != prism::HOLD) {
        resetRound(!outcomeEnabled() || !_outcome_tracking);
        if (fullHandoffEnabled()) {
            resetFullHandoffState();
        }
        _observations.clear();
        return result;
    }

    if (epoch.frozen) {
        if (fullHandoffEnabled()) {
            resetFullHandoffState();
        }
        _observations.clear();
        return result;
    }

    const bool eligible = epoch.floor < _t_cc && epoch.spread >= _t_spray;
    if (!eligible) {
        resetRound(!outcomeEnabled() || !_outcome_tracking);
        if (fullHandoffEnabled()) {
            resetFullHandoffState();
        }
        _observations.clear();
        return result;
    }

    if (fullHandoffEnabled()) {
        const std::optional<PrismFullHandoffEvidence> evidence = takeFullHandoffEvidence();
        if (evidence.has_value() && evidence->handoff_requested) {
            result.handoff_requested = true;
            result.actions.push_back(PrismCoordinationAction::ROUND_COMPLETE_HANDOFF);
        }
    }

    if (outcomeEnabled()) {
        std::set<SlotGeneration> scheduled;
        for (auto entry = _outcome_consumed_high_residuals.begin();
             entry != _outcome_consumed_high_residuals.end();) {
            if (entry->first.epoch_id < epoch.epoch_id) {
                entry = _outcome_consumed_high_residuals.erase(entry);
                continue;
            }
            if (entry->first.epoch_id > epoch.epoch_id) {
                ++entry;
                continue;
            }

            const SlotGeneration consumed = entry->first.slot_generation;
            const ConsumedHighResidual candidate = entry->second;
            const auto current = std::find_if(
                epoch.slots.begin(), epoch.slots.end(),
                [&candidate](const UecMpCacheSlot& slot) {
                    return slot.valid && slot.entropy == candidate.entropy;
                });
            if (current != epoch.slots.end()) {
                const SlotGeneration current_key{current->slot, current->generation};
                if (scheduled.insert(current_key).second) {
                    addSlotAction(result, *current, PrismCoordinationAction::INVALIDATE,
                                  candidate.residual_ps, "recycled_high_residual");
                }
            } else if (scheduled.insert(consumed).second) {
                UecMpCacheSlot vacant;
                vacant.slot = consumed.slot;
                vacant.generation = consumed.generation;
                vacant.entropy = candidate.entropy;
                addSlotAction(result, vacant, PrismCoordinationAction::RESERVE,
                              candidate.residual_ps, "consumed_high_residual");
            }
            entry = _outcome_consumed_high_residuals.erase(entry);
        }
        if (!result.slot_actions.empty()) {
            result.round_id = ++_round_id;
        }
        _observations.clear();
        return result;
    }

    if (!_round_active) {
        _round_active = true;
        ++_round_id;
        _spread_ref = epoch.spread;
        _round_slots.clear();
        _completed_slots.clear();
        _invalidated_generations.clear();
        for (const UecMpCacheSlot& slot : epoch.slots) {
            _round_slots.insert(slot.slot);
        }
    }
    result.round_id = _round_id;
    result.spread_ref_ps = _spread_ref;

    std::vector<UecMpCacheSlot> slots = epoch.slots;
    std::sort(slots.begin(), slots.end(), [](const UecMpCacheSlot& lhs, const UecMpCacheSlot& rhs) {
        return lhs.slot < rhs.slot;
    });

    for (const UecMpCacheSlot& slot : slots) {
        if (_round_slots.find(slot.slot) == _round_slots.end()) {
            continue;
        }
        const SlotGeneration key{slot.slot, slot.generation};
        const auto observation = _observations.find({epoch.epoch_id, key});
        const bool has_matching_observation = observation != _observations.end();
        const bool completed = _completed_slots.find(slot.slot) != _completed_slots.end();
        if (!has_matching_observation && completed) {
            continue;
        }
        simtime_picosec residual = 0;
        if (has_matching_observation) {
            residual = observation->second.qdelay > epoch.floor
                           ? observation->second.qdelay - epoch.floor
                           : 0;
            if (observation->second.ecn) {
                _completed_slots.erase(slot.slot);
                _invalidated_generations[slot.slot] = slot.generation;
                _round_had_invalidation = true;
                addSlotAction(result, slot, PrismCoordinationAction::INVALIDATE, residual,
                              "ecn_marked");
                continue;
            }
            if (residual >= _t_spray) {
                _completed_slots.erase(slot.slot);
                _invalidated_generations[slot.slot] = slot.generation;
                _round_had_invalidation = true;
                addSlotAction(result, slot, PrismCoordinationAction::INVALIDATE, residual,
                              "residual_threshold");
                continue;
            }
        }
        if (!slot.ack_validated || (!slot.valid && !has_matching_observation)) {
            if (!completed) {
                addSlotAction(result, slot, PrismCoordinationAction::PENDING, 0,
                              "slot_not_refreshable");
            }
            continue;
        }
        if (!has_matching_observation) {
            addSlotAction(result, slot, PrismCoordinationAction::PENDING, 0,
                          "missing_epoch_observation");
            continue;
        }

        const auto invalidated = _invalidated_generations.find(slot.slot);
        if (invalidated != _invalidated_generations.end() &&
            slot.generation <= invalidated->second) {
            addSlotAction(result, slot, PrismCoordinationAction::PENDING, residual,
                          "awaiting_replacement");
            continue;
        }

        _completed_slots.insert(slot.slot);
        _invalidated_generations.erase(slot.slot);
        addSlotAction(result, slot, PrismCoordinationAction::RETAIN, residual,
                      "residual_below_threshold");
    }

    _observations.clear();

    if (outcomeEnabled()) {
        return result;
    }

    const bool all_complete = !_round_slots.empty() &&
        _completed_slots.size() == _round_slots.size();
    if (!all_complete) {
        return result;
    }

    result.round_complete = true;
    result.progress = epoch.spread < _spread_ref;
    if (result.progress) {
        result.actions.push_back(PrismCoordinationAction::ROUND_COMPLETE_PROGRESS);
        if (_full_handoff_state == FullHandoffState::SECOND_ROUND) {
            resetFullHandoffState();
        }
    } else if (fullHandoffEnabled()) {
        if (_full_handoff_state == FullHandoffState::IDLE) {
            _full_handoff_state = FullHandoffState::SECOND_ROUND;
            _full_handoff_first_round_id = result.round_id;
        } else if (_full_handoff_state == FullHandoffState::SECOND_ROUND) {
            beginFullHandoffEvidence(result.round_id, epoch.end_ps);
        }
        result.actions.push_back(PrismCoordinationAction::ROUND_COMPLETE_RETRY);
    } else {
        result.actions.push_back(PrismCoordinationAction::ROUND_COMPLETE_CLEAN);
    }

    resetRound();
    return result;
}

bool PrismResidualCoordinator::enabled() const {
    return _mode == PrismCoordinationMode::PRISM_RECYCLE ||
           _mode == PrismCoordinationMode::FULL_PRISM ||
           _mode == PrismCoordinationMode::OUTCOME_RECYCLE;
}

bool PrismResidualCoordinator::outcomeEnabled() const {
    return _mode == PrismCoordinationMode::OUTCOME_RECYCLE;
}

void PrismResidualCoordinator::beginOutcomeReplacement(uint16_t slot, uint64_t generation) {
    if (!outcomeEnabled()) {
        return;
    }
    if (!_outcome_tracking) {
        _outcome_tracking = true;
        _outcome_replacements.clear();
        _outcome_pre.reset();
    }
    resetOutcomeValidationProgress();
    _outcome_replacements[slot] = {generation, 0, false, false};
}

void PrismResidualCoordinator::resetOutcomeValidationProgress() {
    _outcome_replacements_validated = false;
    _outcome_active_bucket.reset();
    _outcome_post1.reset();
    _outcome_post2.reset();
    _outcome_event.reset();
}

void PrismResidualCoordinator::resetOutcomeState() {
    _outcome_tracking = false;
    _outcome_replacements.clear();
    _outcome_replacements_validated = false;
    _outcome_baseline_bucket.reset();
    _outcome_active_bucket.reset();
    _outcome_last_pre_bucket.reset();
    _outcome_pre.reset();
    _outcome_post1.reset();
    _outcome_post2.reset();
    _outcome_event.reset();
}

void PrismResidualCoordinator::observeOutcomeBaseline(simtime_picosec timestamp,
                                                       simtime_picosec residual_ps, bool ecn,
                                                       uint64_t acked_bytes) {
    if (!_outcome_baseline_bucket.has_value()) {
        _outcome_baseline_bucket = OutcomeBucket{timestamp, 0, 0};
    }
    if (timestamp < _outcome_baseline_bucket->start) {
        return;
    }
    while (timestamp >= _outcome_baseline_bucket->start + _outcome_window_ps) {
        if (_outcome_baseline_bucket->classified_bytes > 0) {
            _outcome_last_pre_bucket = *_outcome_baseline_bucket;
        }
        const simtime_picosec next_start =
            _outcome_baseline_bucket->start + _outcome_window_ps;
        _outcome_baseline_bucket = OutcomeBucket{next_start, 0, 0};
        if (timestamp >= next_start + _outcome_window_ps) {
            _outcome_baseline_bucket = OutcomeBucket{timestamp, 0, 0};
            break;
        }
    }
    _outcome_baseline_bucket->classified_bytes += acked_bytes;
    if (ecn || residual_ps >= _t_spray) {
        _outcome_baseline_bucket->harmful_bytes += acked_bytes;
    }
}

void PrismResidualCoordinator::completeOutcomeBucket(const OutcomeBucket& bucket) {
    if (bucket.classified_bytes == 0) {
        resetOutcomeState();
        return;
    }
    if (!_outcome_replacements_validated) {
        _outcome_last_pre_bucket = bucket;
        return;
    }
    const PrismOutcomeWindow window = makeOutcomeWindow(bucket);
    if (!_outcome_pre.has_value()) {
        return;
    }
    if (!_outcome_post1.has_value()) {
        _outcome_post1 = window;
        return;
    }
    if (!_outcome_post2.has_value()) {
        _outcome_post2 = window;
        _outcome_event = PrismOutcome{_round_id, _outcome_window_ps, *_outcome_pre,
                                      *_outcome_post1, *_outcome_post2};
        _outcome_tracking = false;
        _outcome_replacements.clear();
        _outcome_replacements_validated = false;
        _outcome_baseline_bucket.reset();
        _outcome_last_pre_bucket.reset();
        _outcome_active_bucket.reset();
    }
}

void PrismResidualCoordinator::snapshotOutcomePre(simtime_picosec timestamp) {
    const OutcomeBucket* pre_bucket = nullptr;
    if (_outcome_last_pre_bucket.has_value() &&
        _outcome_last_pre_bucket->classified_bytes > 0) {
        pre_bucket = &*_outcome_last_pre_bucket;
    } else if (_outcome_baseline_bucket.has_value() &&
               _outcome_baseline_bucket->classified_bytes > 0) {
        pre_bucket = &*_outcome_baseline_bucket;
    }
    if (pre_bucket == nullptr) {
        _outcome_active_bucket.reset();
        return;
    }
    _outcome_pre = makeOutcomeWindow(*pre_bucket);
    _outcome_active_bucket = OutcomeBucket{timestamp, 0, 0};
}

PrismOutcomeWindow PrismResidualCoordinator::makeOutcomeWindow(const OutcomeBucket& bucket) const {
    return {bucket.start, bucket.start + _outcome_window_ps,
            bucket.classified_bytes, bucket.harmful_bytes,
            static_cast<double>(bucket.harmful_bytes) /
                static_cast<double>(bucket.classified_bytes)};
}

bool PrismResidualCoordinator::fullHandoffEnabled() const {
    return _mode == PrismCoordinationMode::FULL_PRISM;
}

simtime_picosec PrismResidualCoordinator::fullHandoffBaseRtt() const {
    if (_full_base_rtts.empty()) {
        return 0;
    }
    return *std::min_element(_full_base_rtts.begin(), _full_base_rtts.end());
}

PrismHandoffWindow PrismResidualCoordinator::fullHandoffWindow(simtime_picosec start,
                                                                simtime_picosec end) const {
    PrismHandoffWindow window{0, 0};
    for (const FullAckSample& sample : _full_ack_samples) {
        if (sample.timestamp < start || sample.timestamp > end) {
            continue;
        }
        window.acked_bytes += sample.acked_bytes;
        if (sample.harmful) {
            window.harmful_bytes += sample.acked_bytes;
        }
    }
    return window;
}

void PrismResidualCoordinator::beginFullHandoffEvidence(uint64_t second_round_id,
                                                         simtime_picosec terminal_ps) {
    const simtime_picosec base_rtt = fullHandoffBaseRtt();
    if (base_rtt == 0 || terminal_ps == 0) {
        resetFullHandoffState();
        return;
    }
    const simtime_picosec pre_start = terminal_ps > base_rtt ? terminal_ps - base_rtt : 0;
    _full_pending_evidence = {_full_handoff_first_round_id, second_round_id, terminal_ps,
                              base_rtt, fullHandoffWindow(pre_start, terminal_ps)};
    _full_post1 = {0, 0};
    _full_post2 = {0, 0};
    _full_handoff_state = FullHandoffState::EVIDENCE_PENDING;
}

void PrismResidualCoordinator::completeFullHandoffEvidence() {
    if (!_full_pending_evidence.has_value()) {
        return;
    }
    const PendingFullEvidence& pending = *_full_pending_evidence;
    const bool complete_windows = pending.pre.acked_bytes > 0 && _full_post1.acked_bytes > 0 &&
                                  _full_post2.acked_bytes > 0;
    const bool rate_not_higher = _full_post1.acked_bytes <= pending.pre.acked_bytes &&
                                 _full_post2.acked_bytes <= pending.pre.acked_bytes;
    const bool harmful_tail_not_lower =
        static_cast<long double>(_full_post2.harmful_bytes) /
            static_cast<long double>(_full_post2.acked_bytes) >=
        static_cast<long double>(pending.pre.harmful_bytes) /
            static_cast<long double>(pending.pre.acked_bytes);
    _full_handoff_event = {pending.first_round_id, pending.second_round_id,
                           pending.base_rtt_ps, pending.pre, _full_post1, _full_post2,
                           complete_windows && rate_not_higher && harmful_tail_not_lower};
    _full_pending_evidence.reset();
    _full_ack_samples.clear();
    _full_handoff_state = FullHandoffState::LATCHED;
}

void PrismResidualCoordinator::resetFullHandoffState() {
    _full_handoff_state = FullHandoffState::IDLE;
    _full_handoff_first_round_id = 0;
    _full_base_rtts.clear();
    _full_ack_samples.clear();
    _full_pending_evidence.reset();
    _full_post1 = {0, 0};
    _full_post2 = {0, 0};
    _full_handoff_event.reset();
}

void PrismResidualCoordinator::trimFullAckSamples(simtime_picosec timestamp) {
    const simtime_picosec base_rtt = fullHandoffBaseRtt();
    if (base_rtt == 0) {
        return;
    }
    const simtime_picosec retention_ps = base_rtt * 3;
    while (!_full_ack_samples.empty() && timestamp >= _full_ack_samples.front().timestamp &&
           timestamp - _full_ack_samples.front().timestamp > retention_ps) {
        _full_ack_samples.pop_front();
    }
}

void PrismResidualCoordinator::resetRound(bool reset_outcome) {
    _round_active = false;
    _round_had_invalidation = false;
    _spread_ref = 0;
    _round_slots.clear();
    _completed_slots.clear();
    _invalidated_generations.clear();
    _outcome_consumed_high_residuals.clear();
    if (reset_outcome) {
        resetOutcomeState();
    }
}

void PrismResidualCoordinator::addSlotAction(PrismCoordinationResult& result,
                                              const UecMpCacheSlot& slot,
                                              PrismCoordinationAction action,
                                              simtime_picosec residual_ps,
                                              const char* reason) const {
    result.actions.push_back(action);
    result.slot_actions.push_back({slot.slot, slot.generation, action, residual_ps, reason});
    switch (action) {
    case PrismCoordinationAction::RETAIN:
        result.retained_slots.push_back(slot.slot);
        break;
    case PrismCoordinationAction::INVALIDATE:
        result.invalidated_slots.push_back(slot.slot);
        break;
    case PrismCoordinationAction::PENDING:
        result.pending_slots.push_back(slot.slot);
        break;
    case PrismCoordinationAction::RESERVE:
        break;
    case PrismCoordinationAction::ROUND_COMPLETE_PROGRESS:
    case PrismCoordinationAction::ROUND_COMPLETE_HANDOFF:
    case PrismCoordinationAction::ROUND_COMPLETE_RETRY:
    case PrismCoordinationAction::ROUND_COMPLETE_CLEAN:
        break;
    }
}
