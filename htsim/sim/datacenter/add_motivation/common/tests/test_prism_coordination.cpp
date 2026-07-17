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

std::vector<UecMpCacheSlot> eight_slots() {
    std::vector<UecMpCacheSlot> slots;
    for (uint16_t slot = 0; slot < 8; ++slot) {
        slots.push_back({slot, 1, static_cast<uint32_t>(slot + 6), true, true});
    }
    return slots;
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
    PrismResidualCoordinator coordinator(PrismCoordinationMode::FULL_PRISM, 10, 10);
    auto slots = four_slots();

    coordinator.observeAck(1, 0, 1, 2, false, true);
    coordinator.observeAck(1, 1, 1, 3, false, true);
    coordinator.observeAck(1, 2, 1, 4, false, true);
    coordinator.observeAck(1, 3, 1, 12, false, true);
    auto first = coordinator.closeEpoch(hold_epoch(1, 2, 16, slots));
    assert(first.invalidated_slots == std::vector<uint16_t>({3}));
    assert(!first.round_complete);
    assert(has_action(first, PrismCoordinationAction::INVALIDATE));

    slots[3] = {.slot = 3, .generation = 2, .entropy = 9,
                .valid = true, .ack_validated = true};
    coordinator.observeAck(2, 0, 1, 2, false, true);
    coordinator.observeAck(2, 1, 1, 3, false, true);
    coordinator.observeAck(2, 2, 1, 4, false, true);
    coordinator.observeAck(2, 3, 2, 2, false, true);
    auto second = coordinator.closeEpoch(hold_epoch(2, 2, 17, slots));
    assert(second.round_complete);
    assert(second.handoff_requested);
    assert(!second.progress);
    assert(has_action(second, PrismCoordinationAction::ROUND_COMPLETE_HANDOFF));
}

void stale_or_pending_slots_do_not_complete_a_round() {
    PrismResidualCoordinator coordinator(PrismCoordinationMode::FULL_PRISM, 10, 10);
    const auto slots = four_slots();

    coordinator.observeAck(1, 0, 1, 2, false, true);
    coordinator.observeAck(1, 1, 0, 100, true, true);
    coordinator.observeAck(1, 2, 1, 4, false, true);
    coordinator.observeAck(1, 3, 1, 5, false, true);
    const auto result = coordinator.closeEpoch(hold_epoch(1, 2, 16, slots));

    assert(result.invalidated_slots.empty());
    assert(result.pending_slots == std::vector<uint16_t>({1}));
    assert(!result.round_complete);
    assert(has_action(result, PrismCoordinationAction::PENDING));
}

void ecn_and_non_genuine_observations_are_not_admitted() {
    PrismResidualCoordinator coordinator(PrismCoordinationMode::FULL_PRISM, 10, 10);
    const auto slots = four_slots();

    coordinator.observeAck(1, 0, 1, 2, false, true);
    coordinator.observeAck(1, 1, 1, 2, true, true);
    coordinator.observeAck(1, 2, 1, 2, false, false);
    coordinator.observeAck(1, 3, 1, 5, false, true);
    const auto result = coordinator.closeEpoch(hold_epoch(1, 2, 16, slots));

    assert(result.invalidated_slots == std::vector<uint16_t>({1}));
    assert(result.pending_slots == std::vector<uint16_t>({2}));
    assert(!result.round_complete);
}

void lower_ending_spread_completes_with_progress_without_handoff() {
    PrismResidualCoordinator coordinator(PrismCoordinationMode::FULL_PRISM, 10, 10);
    const auto slots = four_slots();

    coordinator.observeAck(1, 0, 1, 2, false, true);
    coordinator.observeAck(1, 1, 1, 3, false, true);
    coordinator.observeAck(1, 2, 1, 4, false, true);
    assert(!coordinator.closeEpoch(hold_epoch(1, 2, 16, slots)).round_complete);

    coordinator.observeAck(2, 0, 1, 2, false, true);
    coordinator.observeAck(2, 1, 1, 3, false, true);
    coordinator.observeAck(2, 2, 1, 4, false, true);
    coordinator.observeAck(2, 3, 1, 5, false, true);
    const auto result = coordinator.closeEpoch(hold_epoch(2, 2, 15, slots));
    assert(result.round_complete);
    assert(result.progress);
    assert(!result.handoff_requested);
    assert(has_action(result, PrismCoordinationAction::ROUND_COMPLETE_PROGRESS));
}

void full_prism_clean_equal_spread_completion_does_not_handoff() {
    PrismResidualCoordinator coordinator(PrismCoordinationMode::FULL_PRISM, 10, 10);
    const auto slots = eight_slots();

    for (uint16_t slot = 0; slot < 8; ++slot) {
        coordinator.observeAck(1, slot, 1, 3, false, true);
    }
    const auto result = coordinator.closeEpoch(hold_epoch(1, 2, 16, slots));

    assert(result.round_complete);
    assert(!result.progress);
    assert(!result.handoff_requested);
    assert(has_action(result, PrismCoordinationAction::ROUND_COMPLETE_CLEAN));
}

void prism_recycle_never_handoffs() {
    PrismResidualCoordinator coordinator(PrismCoordinationMode::PRISM_RECYCLE, 10, 10);
    const auto slots = four_slots();

    coordinator.observeAck(1, 0, 1, 2, false, true);
    coordinator.observeAck(1, 1, 1, 3, false, true);
    coordinator.observeAck(1, 2, 1, 4, false, true);
    assert(!coordinator.closeEpoch(hold_epoch(1, 2, 16, slots)).round_complete);

    coordinator.observeAck(2, 0, 1, 2, false, true);
    coordinator.observeAck(2, 1, 1, 3, false, true);
    coordinator.observeAck(2, 2, 1, 4, false, true);
    coordinator.observeAck(2, 3, 1, 5, false, true);
    const auto result = coordinator.closeEpoch(hold_epoch(2, 2, 16, slots));
    assert(result.round_complete);
    assert(!result.progress);
    assert(!result.handoff_requested);
    assert(!has_action(result, PrismCoordinationAction::ROUND_COMPLETE_HANDOFF));
}

void non_hold_clears_and_frozen_hold_pauses_ordinary_refresh_state() {
    PrismResidualCoordinator coordinator(PrismCoordinationMode::FULL_PRISM, 10, 10);
    const auto slots = four_slots();

    coordinator.observeAck(1, 0, 1, 2, false, true);
    coordinator.observeAck(1, 1, 1, 3, false, true);
    coordinator.observeAck(1, 2, 1, 4, false, true);
    assert(!coordinator.closeEpoch(hold_epoch(1, 2, 16, slots)).round_complete);

    coordinator.observeAck(2, 0, 1, 2, false, true);
    coordinator.observeAck(2, 1, 1, 3, false, true);
    coordinator.observeAck(2, 2, 1, 4, false, true);
    coordinator.observeAck(2, 3, 1, 5, false, true);
    const auto non_hold = coordinator.closeEpoch({2, 2, 16, prism::INCREASE, false, slots});
    assert(non_hold.actions.empty());
    assert(!non_hold.round_complete);

    coordinator.observeAck(3, 0, 1, 2, false, true);
    coordinator.observeAck(3, 1, 1, 3, false, true);
    coordinator.observeAck(3, 2, 1, 4, false, true);
    coordinator.observeAck(3, 3, 1, 5, false, true);
    const auto restarted = coordinator.closeEpoch(hold_epoch(3, 2, 15, slots));
    assert(restarted.round_complete);
    assert(!restarted.progress);
    assert(!restarted.handoff_requested);
    assert(has_action(restarted, PrismCoordinationAction::ROUND_COMPLETE_CLEAN));

    PrismResidualCoordinator frozen_coordinator(PrismCoordinationMode::FULL_PRISM, 10, 10);
    frozen_coordinator.observeAck(1, 0, 1, 2, false, true);
    frozen_coordinator.observeAck(1, 1, 1, 3, false, true);
    frozen_coordinator.observeAck(1, 2, 1, 4, false, true);
    assert(!frozen_coordinator.closeEpoch(hold_epoch(1, 2, 16, slots)).round_complete);

    frozen_coordinator.observeAck(2, 0, 1, 2, false, true);
    frozen_coordinator.observeAck(2, 1, 1, 3, false, true);
    frozen_coordinator.observeAck(2, 2, 1, 4, false, true);
    frozen_coordinator.observeAck(2, 3, 1, 5, false, true);
    const auto frozen = frozen_coordinator.closeEpoch(hold_epoch(2, 2, 16, slots, true));
    assert(frozen.actions.empty());
    assert(!frozen.round_complete);

    frozen_coordinator.observeAck(3, 0, 1, 2, false, true);
    frozen_coordinator.observeAck(3, 1, 1, 3, false, true);
    frozen_coordinator.observeAck(3, 2, 1, 4, false, true);
    frozen_coordinator.observeAck(3, 3, 1, 5, false, true);
    const auto resumed = frozen_coordinator.closeEpoch(hold_epoch(3, 2, 15, slots));
    assert(resumed.round_complete);
    assert(resumed.progress);
    assert(!resumed.handoff_requested);
}

void late_observation_from_an_older_epoch_is_pending() {
    PrismResidualCoordinator coordinator(PrismCoordinationMode::FULL_PRISM, 10, 10);
    const std::vector<UecMpCacheSlot> slots = {{0, 1, 6, true, true}};

    coordinator.observeAck(1, 0, 1, 2, false, true);
    const auto result = coordinator.closeEpoch(hold_epoch(2, 2, 16, slots));

    assert(result.pending_slots == std::vector<uint16_t>({0}));
    assert(!result.round_complete);
    assert(!result.handoff_requested);
}

void coordination_results_preserve_trace_values() {
    PrismResidualCoordinator coordinator(PrismCoordinationMode::FULL_PRISM, 10, 10);
    const auto slots = four_slots();

    coordinator.observeAck(1, 0, 1, 2, false, true);
    coordinator.observeAck(1, 1, 1, 3, false, true);
    coordinator.observeAck(1, 2, 1, 4, false, true);
    coordinator.observeAck(1, 3, 1, 12, false, true);
    const auto result = coordinator.closeEpoch(hold_epoch(1, 2, 16, slots));

    assert(result.round_id == 1);
    assert(result.spread_ref_ps == 16);
    assert(result.slot_actions[0].residual_ps == 0);
    assert(result.slot_actions[0].reason == "residual_below_threshold");
    assert(result.slot_actions[3].residual_ps == 10);
    assert(result.slot_actions[3].reason == "residual_threshold");
}

void completed_physical_slots_survive_reps_freshness_consumption() {
    PrismResidualCoordinator coordinator(PrismCoordinationMode::FULL_PRISM, 10, 10);
    auto slots = eight_slots();

    for (uint16_t slot = 0; slot < 7; ++slot) {
        coordinator.observeAck(1, slot, 1, 3, false, true);
    }
    const auto first = coordinator.closeEpoch(hold_epoch(1, 2, 16, slots));
    assert(!first.round_complete);

    // REPS selection consumes freshness, but the physical slot was completed in epoch 1.
    slots[0].ack_validated = false;
    coordinator.observeAck(2, 7, 1, 3, false, true);
    const auto second = coordinator.closeEpoch(hold_epoch(2, 2, 16, slots));
    assert(second.round_complete);
    assert(!second.handoff_requested);
    assert(has_action(second, PrismCoordinationAction::ROUND_COMPLETE_CLEAN));
}

void ack_validated_consumed_token_completes_a_refresh_round_with_progress() {
    PrismResidualCoordinator coordinator(PrismCoordinationMode::FULL_PRISM, 10, 10);
    auto slots = eight_slots();

    for (uint16_t slot = 0; slot < 8; ++slot) {
        if (slot == 3) {
            continue;
        }
        coordinator.observeAck(1, slot, 1, 3, false, true);
    }
    assert(!coordinator.closeEpoch(hold_epoch(1, 2, 16, slots)).round_complete);

    slots[3].valid = false;
    for (uint16_t slot = 0; slot < 8; ++slot) {
        coordinator.observeAck(2, slot, 1, 3, false, true);
    }
    const auto result = coordinator.closeEpoch(hold_epoch(2, 2, 15, slots));

    assert(result.invalidated_slots.empty());
    assert(result.pending_slots.empty());
    assert(result.retained_slots == std::vector<uint16_t>({0, 1, 2, 3, 4, 5, 6, 7}));
    assert(result.round_complete);
    assert(result.progress);
    assert(!result.handoff_requested);
}

void invalidated_slot_requires_a_clean_new_generation() {
    PrismResidualCoordinator coordinator(PrismCoordinationMode::FULL_PRISM, 10, 10);
    auto slots = eight_slots();

    for (uint16_t slot = 0; slot < 8; ++slot) {
        coordinator.observeAck(1, slot, 1, slot == 3 ? 12 : 3, false, true);
    }
    const auto first = coordinator.closeEpoch(hold_epoch(1, 2, 16, slots));
    assert(first.invalidated_slots == std::vector<uint16_t>({3}));
    assert(!first.round_complete);

    slots[3] = {3, 2, 9, true, true};
    coordinator.observeAck(2, 3, 1, 3, false, true);
    const auto stale = coordinator.closeEpoch(hold_epoch(2, 2, 16, slots));
    assert(stale.pending_slots == std::vector<uint16_t>({3}));
    assert(!stale.round_complete);

    coordinator.observeAck(3, 3, 2, 3, false, true);
    const auto replacement = coordinator.closeEpoch(hold_epoch(3, 2, 16, slots));
    assert(replacement.round_complete);
    assert(replacement.handoff_requested);
}

void late_ack_for_an_invalidated_consumed_token_remains_pending() {
    PrismResidualCoordinator coordinator(PrismCoordinationMode::FULL_PRISM, 10, 10);
    auto slots = eight_slots();

    for (uint16_t slot = 0; slot < 8; ++slot) {
        coordinator.observeAck(1, slot, 1, slot == 3 ? 12 : 3, false, true);
    }
    const auto first = coordinator.closeEpoch(hold_epoch(1, 2, 16, slots));
    assert(first.invalidated_slots == std::vector<uint16_t>({3}));
    assert(!first.round_complete);

    slots[3].valid = false;
    slots[3].ack_validated = true;
    coordinator.observeAck(2, 3, 1, 3, false, true);
    const auto late = coordinator.closeEpoch(hold_epoch(2, 2, 16, slots));

    assert(late.pending_slots == std::vector<uint16_t>({3}));
    assert(late.slot_actions[0].reason == "awaiting_replacement");
    assert(!late.round_complete);
}

void ecn_observation_invalidates_the_matching_cached_slot() {
    PrismResidualCoordinator coordinator(PrismCoordinationMode::FULL_PRISM, 10, 10);
    const auto slots = four_slots();

    coordinator.observeAck(1, 0, 1, 2, false, true);
    coordinator.observeAck(1, 1, 1, 2, true, true);
    coordinator.observeAck(1, 2, 1, 2, false, true);
    coordinator.observeAck(1, 3, 1, 2, false, true);
    const auto result = coordinator.closeEpoch(hold_epoch(1, 2, 16, slots));

    assert(result.invalidated_slots == std::vector<uint16_t>({1}));
    assert(result.slot_actions[1].reason == "ecn_marked");
}

void ecn_observation_invalidates_a_slot_consumed_before_its_ack() {
    PrismResidualCoordinator coordinator(PrismCoordinationMode::FULL_PRISM, 10, 10);
    auto slots = four_slots();
    slots[1].valid = false;

    coordinator.observeAck(1, 0, 1, 2, false, true);
    coordinator.observeAck(1, 1, 1, 2, true, true);
    coordinator.observeAck(1, 2, 1, 2, false, true);
    coordinator.observeAck(1, 3, 1, 2, false, true);
    const auto result = coordinator.closeEpoch(hold_epoch(1, 2, 16, slots));

    assert(result.invalidated_slots == std::vector<uint16_t>({1}));
    assert(result.slot_actions[1].reason == "ecn_marked");
}

void coordinator_uses_independent_cc_and_spray_thresholds_at_boundaries() {
    PrismResidualCoordinator coordinator(PrismCoordinationMode::FULL_PRISM, 10, 14);
    const auto slots = four_slots();

    for (uint16_t slot = 0; slot < 4; ++slot) {
        coordinator.observeAck(1, slot, 1, 3, false, true);
    }
    const auto ineligible = coordinator.closeEpoch(hold_epoch(1, 10, 20, slots));
    assert(ineligible.actions.empty());

    for (uint16_t slot = 0; slot < 4; ++slot) {
        coordinator.observeAck(2, slot, 1, slot == 3 ? 23 : 3, false, true);
    }
    const auto high_residual = coordinator.closeEpoch(hold_epoch(2, 9, 14, slots));
    assert(high_residual.invalidated_slots == std::vector<uint16_t>({3}));
    assert(high_residual.slot_actions[3].residual_ps == 14);
}

void no_progress_handoff_applies_one_gentle_cut() {
    mem_b cwnd = 10000;
    assert(applyPrismNoProgressHandoff(cwnd, 1000));
    assert(cwnd == 9000);

    cwnd = 1000;
    assert(!applyPrismNoProgressHandoff(cwnd, 1000));
    assert(cwnd == 1000);
}

}  // namespace

int main() {
    full_prism_invalidates_before_handoffing_a_completed_round();
    stale_or_pending_slots_do_not_complete_a_round();
    ecn_and_non_genuine_observations_are_not_admitted();
    lower_ending_spread_completes_with_progress_without_handoff();
    full_prism_clean_equal_spread_completion_does_not_handoff();
    prism_recycle_never_handoffs();
    non_hold_clears_and_frozen_hold_pauses_ordinary_refresh_state();
    late_observation_from_an_older_epoch_is_pending();
    coordination_results_preserve_trace_values();
    completed_physical_slots_survive_reps_freshness_consumption();
    ack_validated_consumed_token_completes_a_refresh_round_with_progress();
    invalidated_slot_requires_a_clean_new_generation();
    late_ack_for_an_invalidated_consumed_token_remains_pending();
    ecn_observation_invalidates_the_matching_cached_slot();
    ecn_observation_invalidates_a_slot_consumed_before_its_ack();
    coordinator_uses_independent_cc_and_spray_thresholds_at_boundaries();
    no_progress_handoff_applies_one_gentle_cut();
}
