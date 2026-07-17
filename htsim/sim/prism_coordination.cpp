#include "prism_coordination.h"

#include <algorithm>

bool applyPrismNoProgressHandoff(mem_b& cwnd, mem_b min_cwnd) {
    const mem_b before = cwnd;
    cwnd = std::max(min_cwnd, static_cast<mem_b>(cwnd * 0.9));
    return cwnd < before;
}

PrismResidualCoordinator::PrismResidualCoordinator(PrismCoordinationMode mode,
                                                   simtime_picosec t_cc,
                                                   simtime_picosec t_spray)
    : _mode(mode), _t_cc(t_cc), _t_spray(t_spray) {}

void PrismResidualCoordinator::observeAck(uint64_t epoch_id, uint16_t slot,
                                          uint64_t generation, simtime_picosec qdelay,
                                          bool ecn, bool genuine) {
    if (!genuine) {
        return;
    }
    _observations[{epoch_id, {slot, generation}}] = {qdelay, ecn};
}

PrismCoordinationResult PrismResidualCoordinator::closeEpoch(const PrismCoordinationEpoch& epoch) {
    PrismCoordinationResult result;

    if (!enabled() || epoch.region != prism::HOLD) {
        resetRound();
        _observations.clear();
        return result;
    }

    if (epoch.frozen) {
        _observations.clear();
        return result;
    }

    const bool eligible = epoch.floor < _t_cc && epoch.spread >= _t_spray;
    if (!eligible) {
        resetRound();
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
                addSlotAction(result, slot, PrismCoordinationAction::INVALIDATE, residual,
                              "ecn_marked");
                continue;
            }
            if (residual >= _t_spray) {
                _completed_slots.erase(slot.slot);
                _invalidated_generations[slot.slot] = slot.generation;
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

    const bool all_complete = !_round_slots.empty() &&
        _completed_slots.size() == _round_slots.size();
    if (!all_complete) {
        return result;
    }

    result.round_complete = true;
    result.progress = epoch.spread < _spread_ref;
    if (result.progress) {
        result.actions.push_back(PrismCoordinationAction::ROUND_COMPLETE_PROGRESS);
    } else if (_mode == PrismCoordinationMode::FULL_PRISM) {
        result.handoff_requested = true;
        result.actions.push_back(PrismCoordinationAction::ROUND_COMPLETE_HANDOFF);
    }

    resetRound();
    return result;
}

bool PrismResidualCoordinator::enabled() const {
    return _mode == PrismCoordinationMode::PRISM_RECYCLE ||
           _mode == PrismCoordinationMode::FULL_PRISM;
}

void PrismResidualCoordinator::resetRound() {
    _round_active = false;
    _spread_ref = 0;
    _round_slots.clear();
    _completed_slots.clear();
    _invalidated_generations.clear();
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
    case PrismCoordinationAction::ROUND_COMPLETE_PROGRESS:
    case PrismCoordinationAction::ROUND_COMPLETE_HANDOFF:
        break;
    }
}
