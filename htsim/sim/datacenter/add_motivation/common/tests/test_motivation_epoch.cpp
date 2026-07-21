#include "motivation_epoch.h"
#include "uec_mp.h"

#include <cassert>
#include <cstdint>

namespace {

void closesWithRawSameEpochExtremaAndCoverage() {
    MotivationEpochObserver observer(1.0, 3, 1.0, 0.0);

    assert(!observer.observe(0, 2000, true, 1, 0, 10000));
    assert(!observer.observe(5000, 9000, true, 2, 1, 10000));
    auto result = observer.observe(10000, 5000, true, 1, 0, 10000);

    assert(result);
    assert(result->epoch_id == 0);
    assert(result->start_ps == 0);
    assert(result->end_ps == 10000);
    assert(result->raw_floor_ps == 2000);
    assert(result->raw_spread_ps == 7000);
    assert(result->smooth_floor_ps == 2000);
    assert(result->smooth_spread_ps == 7000);
    assert(result->sample_count == 3);
    assert(result->entropy_coverage == 2);
    assert(result->physical_path_coverage == 2);
    assert(observer.currentEpochId() == 1);
}

void ignoresNonGenuineSamplesAndDefersSparseEpochs() {
    MotivationEpochObserver observer(1.0, 3, 1.0, 0.0);

    assert(!observer.observe(0, 1, false, 99, 99, 10000));
    assert(!observer.observe(1000, 3000, true, 3, UINT64_MAX, 10000));
    assert(!observer.observe(11000, 8000, true, 4, UINT64_MAX, 10000));
    assert(observer.currentSampleCount() == 2);

    auto result = observer.observe(12000, 6000, true, 3, UINT64_MAX, 10000);
    assert(result);
    assert(result->start_ps == 1000);
    assert(result->sample_count == 3);
    assert(result->raw_floor_ps == 3000);
    assert(result->raw_spread_ps == 5000);
    assert(result->entropy_coverage == 2);
    assert(result->physical_path_coverage == 0);
}

void smoothsAndDecidesOnlyWhenAnEpochCloses() {
    MotivationEpochObserver observer(1.0, 2, 0.5, 0.0);

    assert(!observer.observe(0, 2000, true, 1, 0, 10000, 6000, 6000));
    auto first = observer.observe(10000, 10000, true, 2, 1, 10000, 6000, 6000);
    assert(first);
    assert(first->smooth_floor_ps == 2000);
    assert(first->smooth_spread_ps == 8000);
    assert(first->observed_region == prism::HOLD);

    assert(!observer.observe(11000, 10000, true, 1, 0, 10000, 6000, 6000));
    auto second = observer.observe(21000, 14000, true, 1, 0, 10000, 6000, 6000);
    assert(second);
    assert(second->smooth_floor_ps == 6000);
    assert(second->smooth_spread_ps == 6000);
    assert(second->observed_region == prism::DECREASE);
}

UecMpSelection selection(uint32_t entropy, uint64_t token_id) {
    return UecMpSelection{entropy, UecMpSelection::RECYCLED, token_id};
}

void correlatesAckSelectionWithItsExactLifecycleRecord() {
    MotivationAckSelectionState state;
    const UecMpSelection first_probe = selection(3, 101);
    const UecMpSelection second_probe = selection(5, 102);
    const UecMpSelection current_send = selection(7, 201);

    state.rememberProbe(41, first_probe);
    state.rememberProbe(42, second_probe);

    const UecMpSelection probe_collision =
        state.consumeAckSelection(true, 41, &current_send);
    assert(probe_collision.entropy == first_probe.entropy);
    assert(probe_collision.token_id == first_probe.token_id);

    const UecMpSelection duplicate_probe =
        state.consumeAckSelection(true, 41, &current_send);
    assert(duplicate_probe.source == UecMpSelection::UNKNOWN);
    assert(duplicate_probe.token_id == UecMpSelection::NO_TOKEN);

    const UecMpSelection later_probe =
        state.consumeAckSelection(true, 42, &current_send);
    assert(later_probe.token_id == second_probe.token_id);

    const UecMpSelection stale_normal =
        state.consumeAckSelection(false, 41, nullptr);
    assert(stale_normal.source == UecMpSelection::UNKNOWN);
    assert(stale_normal.token_id == UecMpSelection::NO_TOKEN);

    const UecMpSelection exact_normal =
        state.consumeAckSelection(false, 41, &current_send);
    assert(exact_normal.entropy == current_send.entropy);
    assert(exact_normal.token_id == current_send.token_id);
}

void boundsUnacknowledgedProbeSelections() {
    MotivationAckSelectionState state;
    for (uint64_t seqno = 0; seqno <= MotivationAckSelectionState::MAX_PROBE_RECORDS;
         ++seqno) {
        state.rememberProbe(seqno, selection(static_cast<uint32_t>(seqno), seqno));
    }

    const UecMpSelection evicted = state.consumeAckSelection(true, 0, nullptr);
    assert(evicted.source == UecMpSelection::UNKNOWN);
    assert(evicted.token_id == UecMpSelection::NO_TOKEN);

    const UecMpSelection newest = state.consumeAckSelection(
        true, MotivationAckSelectionState::MAX_PROBE_RECORDS, nullptr);
    assert(newest.token_id == MotivationAckSelectionState::MAX_PROBE_RECORDS);
}

}  // namespace

int main() {
    closesWithRawSameEpochExtremaAndCoverage();
    ignoresNonGenuineSamplesAndDefersSparseEpochs();
    smoothsAndDecidesOnlyWhenAnEpochCloses();
    correlatesAckSelectionWithItsExactLifecycleRecord();
    boundsUnacknowledgedProbeSelections();
}
