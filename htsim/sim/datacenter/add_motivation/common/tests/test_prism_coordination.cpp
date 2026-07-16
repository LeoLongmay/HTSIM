#include "prism_coordination.h"

#include <algorithm>
#include <cassert>
#include <utility>
#include <vector>

namespace {

std::vector<UecMpCacheSlot> four_slots() {
    return {{0, 1, 6, true, true},
            {1, 1, 7, true, true},
            {2, 1, 8, true, true},
            {3, 1, 9, true, true}};
}

PrismCoordinationEpoch hold_epoch(uint64_t epoch_id, simtime_picosec floor,
                                  simtime_picosec spread,
                                  std::vector<UecMpCacheSlot> slots,
                                  bool frozen = false) {
    return {epoch_id, floor, spread, prism::HOLD, frozen, std::move(slots)};
}

bool has_action(const PrismCoordinationResult& result, PrismCoordinationAction action) {
    return std::find(result.actions.begin(), result.actions.end(), action) != result.actions.end();
}

void full_prism_invalidates_before_handoffing_a_completed_round() {
    PrismResidualCoordinator coordinator(PrismCoordinationMode::FULL_PRISM, 10);
    auto slots = four_slots();

    coordinator.observeAck(0, 1, 2, false, true);
    coordinator.observeAck(1, 1, 3, false, true);
    coordinator.observeAck(2, 1, 4, false, true);
    coordinator.observeAck(3, 1, 12, false, true);
    auto first = coordinator.closeEpoch(hold_epoch(1, 2, 16, slots));
    assert(first.invalidated_slots == std::vector<uint16_t>({3}));
    assert(!first.round_complete);
    assert(has_action(first, PrismCoordinationAction::INVALIDATE));

    slots[3] = {.slot = 3, .generation = 2, .entropy = 9,
                .valid = true, .ack_validated = true};
    coordinator.observeAck(0, 1, 2, false, true);
    coordinator.observeAck(1, 1, 3, false, true);
    coordinator.observeAck(2, 1, 4, false, true);
    coordinator.observeAck(3, 2, 2, false, true);
    auto second = coordinator.closeEpoch(hold_epoch(2, 2, 17, slots));
    assert(second.round_complete);
    assert(second.handoff);
    assert(!second.progress);
    assert(has_action(second, PrismCoordinationAction::ROUND_COMPLETE_HANDOFF));
}

void stale_or_pending_slots_do_not_complete_a_round() {
    PrismResidualCoordinator coordinator(PrismCoordinationMode::FULL_PRISM, 10);
    const auto slots = four_slots();

    coordinator.observeAck(0, 1, 2, false, true);
    coordinator.observeAck(1, 0, 100, true, true);
    coordinator.observeAck(2, 1, 4, false, true);
    coordinator.observeAck(3, 1, 5, false, true);
    const auto result = coordinator.closeEpoch(hold_epoch(1, 2, 16, slots));

    assert(result.invalidated_slots.empty());
    assert(result.pending_slots == std::vector<uint16_t>({1}));
    assert(!result.round_complete);
    assert(has_action(result, PrismCoordinationAction::PENDING));
}

void ecn_and_non_genuine_observations_are_not_admitted() {
    PrismResidualCoordinator coordinator(PrismCoordinationMode::FULL_PRISM, 10);
    const auto slots = four_slots();

    coordinator.observeAck(0, 1, 2, false, true);
    coordinator.observeAck(1, 1, 2, true, true);
    coordinator.observeAck(2, 1, 2, false, false);
    coordinator.observeAck(3, 1, 5, false, true);
    const auto result = coordinator.closeEpoch(hold_epoch(1, 2, 16, slots));

    assert(result.invalidated_slots == std::vector<uint16_t>({1}));
    assert(result.pending_slots == std::vector<uint16_t>({2}));
    assert(!result.round_complete);
}

void lower_ending_spread_completes_with_progress_without_handoff() {
    PrismResidualCoordinator coordinator(PrismCoordinationMode::FULL_PRISM, 10);
    const auto slots = four_slots();

    coordinator.observeAck(0, 1, 2, false, true);
    coordinator.observeAck(1, 1, 3, false, true);
    coordinator.observeAck(2, 1, 4, false, true);
    assert(!coordinator.closeEpoch(hold_epoch(1, 2, 16, slots)).round_complete);

    coordinator.observeAck(0, 1, 2, false, true);
    coordinator.observeAck(1, 1, 3, false, true);
    coordinator.observeAck(2, 1, 4, false, true);
    coordinator.observeAck(3, 1, 5, false, true);
    const auto result = coordinator.closeEpoch(hold_epoch(2, 2, 15, slots));
    assert(result.round_complete);
    assert(result.progress);
    assert(!result.handoff);
    assert(has_action(result, PrismCoordinationAction::ROUND_COMPLETE_PROGRESS));
}

void prism_recycle_never_handoffs() {
    PrismResidualCoordinator coordinator(PrismCoordinationMode::PRISM_RECYCLE, 10);
    const auto slots = four_slots();

    coordinator.observeAck(0, 1, 2, false, true);
    coordinator.observeAck(1, 1, 3, false, true);
    coordinator.observeAck(2, 1, 4, false, true);
    assert(!coordinator.closeEpoch(hold_epoch(1, 2, 16, slots)).round_complete);

    coordinator.observeAck(0, 1, 2, false, true);
    coordinator.observeAck(1, 1, 3, false, true);
    coordinator.observeAck(2, 1, 4, false, true);
    coordinator.observeAck(3, 1, 5, false, true);
    const auto result = coordinator.closeEpoch(hold_epoch(2, 2, 16, slots));
    assert(result.round_complete);
    assert(!result.progress);
    assert(!result.handoff);
    assert(!has_action(result, PrismCoordinationAction::ROUND_COMPLETE_HANDOFF));
}

void non_hold_clears_and_frozen_hold_pauses_ordinary_refresh_state() {
    PrismResidualCoordinator coordinator(PrismCoordinationMode::FULL_PRISM, 10);
    const auto slots = four_slots();

    coordinator.observeAck(0, 1, 2, false, true);
    coordinator.observeAck(1, 1, 3, false, true);
    coordinator.observeAck(2, 1, 4, false, true);
    assert(!coordinator.closeEpoch(hold_epoch(1, 2, 16, slots)).round_complete);

    coordinator.observeAck(0, 1, 2, false, true);
    coordinator.observeAck(1, 1, 3, false, true);
    coordinator.observeAck(2, 1, 4, false, true);
    coordinator.observeAck(3, 1, 5, false, true);
    const auto non_hold = coordinator.closeEpoch({2, 2, 16, prism::INCREASE, false, slots});
    assert(non_hold.actions.empty());
    assert(!non_hold.round_complete);

    coordinator.observeAck(0, 1, 2, false, true);
    coordinator.observeAck(1, 1, 3, false, true);
    coordinator.observeAck(2, 1, 4, false, true);
    coordinator.observeAck(3, 1, 5, false, true);
    const auto restarted = coordinator.closeEpoch(hold_epoch(3, 2, 15, slots));
    assert(restarted.round_complete);
    assert(!restarted.progress);
    assert(restarted.handoff);

    PrismResidualCoordinator frozen_coordinator(PrismCoordinationMode::FULL_PRISM, 10);
    frozen_coordinator.observeAck(0, 1, 2, false, true);
    frozen_coordinator.observeAck(1, 1, 3, false, true);
    frozen_coordinator.observeAck(2, 1, 4, false, true);
    assert(!frozen_coordinator.closeEpoch(hold_epoch(1, 2, 16, slots)).round_complete);

    frozen_coordinator.observeAck(0, 1, 2, false, true);
    frozen_coordinator.observeAck(1, 1, 3, false, true);
    frozen_coordinator.observeAck(2, 1, 4, false, true);
    frozen_coordinator.observeAck(3, 1, 5, false, true);
    const auto frozen = frozen_coordinator.closeEpoch(hold_epoch(2, 2, 16, slots, true));
    assert(frozen.actions.empty());
    assert(!frozen.round_complete);

    frozen_coordinator.observeAck(0, 1, 2, false, true);
    frozen_coordinator.observeAck(1, 1, 3, false, true);
    frozen_coordinator.observeAck(2, 1, 4, false, true);
    frozen_coordinator.observeAck(3, 1, 5, false, true);
    const auto resumed = frozen_coordinator.closeEpoch(hold_epoch(3, 2, 15, slots));
    assert(resumed.round_complete);
    assert(resumed.progress);
    assert(!resumed.handoff);
}

}  // namespace

int main() {
    full_prism_invalidates_before_handoffing_a_completed_round();
    stale_or_pending_slots_do_not_complete_a_round();
    ecn_and_non_genuine_observations_are_not_admitted();
    lower_ending_spread_completes_with_progress_without_handoff();
    prism_recycle_never_handoffs();
    non_hold_clears_and_frozen_hold_pauses_ordinary_refresh_state();
}
