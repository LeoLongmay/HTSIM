#include "prism_coordination.h"

#include <algorithm>

PrismResidualCoordinator::PrismResidualCoordinator(PrismCoordinationMode mode,
                                                   simtime_picosec threshold)
    : _mode(mode), _threshold(threshold) {}

void PrismResidualCoordinator::observeAck(uint16_t slot, uint64_t generation,
                                          simtime_picosec qdelay, bool ecn, bool genuine) {
    if (!genuine) {
        return;
    }
    _observations[{slot, generation}] = {qdelay, ecn};
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

    const bool eligible = epoch.floor < _threshold && epoch.spread >= _threshold;
    if (!eligible) {
        resetRound();
        _observations.clear();
        return result;
    }

    if (!_round_active) {
        _round_active = true;
        _spread_ref = epoch.spread;
        _completed.clear();
    }

    std::vector<UecMpCacheSlot> slots = epoch.slots;
    std::sort(slots.begin(), slots.end(), [](const UecMpCacheSlot& lhs, const UecMpCacheSlot& rhs) {
        return lhs.slot < rhs.slot;
    });

    std::set<SlotGeneration> current_slots;
    for (const UecMpCacheSlot& slot : slots) {
        if (slot.valid && slot.ack_validated) {
            current_slots.insert({slot.slot, slot.generation});
        }
    }
    for (auto it = _completed.begin(); it != _completed.end();) {
        if (current_slots.find(*it) == current_slots.end()) {
            it = _completed.erase(it);
        } else {
            ++it;
        }
    }

    for (const UecMpCacheSlot& slot : slots) {
        const SlotGeneration key{slot.slot, slot.generation};
        const auto observation = _observations.find(key);
        if (!slot.valid || !slot.ack_validated || observation == _observations.end()) {
            _completed.erase(key);
            addSlotAction(result, slot, PrismCoordinationAction::PENDING);
            continue;
        }

        const simtime_picosec residual = observation->second.qdelay > epoch.floor
                                             ? observation->second.qdelay - epoch.floor
                                             : 0;
        if (observation->second.ecn || residual >= _threshold) {
            _completed.erase(key);
            addSlotAction(result, slot, PrismCoordinationAction::INVALIDATE);
            continue;
        }

        _completed.insert(key);
        addSlotAction(result, slot, PrismCoordinationAction::RETAIN);
    }

    _observations.clear();

    const bool all_complete = !slots.empty() && std::all_of(
        slots.begin(), slots.end(), [this](const UecMpCacheSlot& slot) {
            return slot.valid && slot.ack_validated &&
                   _completed.find({slot.slot, slot.generation}) != _completed.end();
        });
    if (!all_complete) {
        return result;
    }

    result.round_complete = true;
    result.progress = epoch.spread < _spread_ref;
    if (result.progress) {
        result.actions.push_back(PrismCoordinationAction::ROUND_COMPLETE_PROGRESS);
    } else if (_mode == PrismCoordinationMode::FULL_PRISM) {
        result.handoff = true;
        result.actions.push_back(PrismCoordinationAction::ROUND_COMPLETE_HANDOFF);
    }

    _spread_ref = epoch.spread;
    _completed.clear();
    return result;
}

bool PrismResidualCoordinator::enabled() const {
    return _mode == PrismCoordinationMode::PRISM_RECYCLE ||
           _mode == PrismCoordinationMode::FULL_PRISM;
}

void PrismResidualCoordinator::resetRound() {
    _round_active = false;
    _spread_ref = 0;
    _completed.clear();
}

void PrismResidualCoordinator::addSlotAction(PrismCoordinationResult& result,
                                              const UecMpCacheSlot& slot,
                                              PrismCoordinationAction action) const {
    result.actions.push_back(action);
    result.slot_actions.push_back({slot.slot, slot.generation, action});
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
