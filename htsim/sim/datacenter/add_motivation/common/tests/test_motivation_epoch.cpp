#include "motivation_epoch.h"

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

}  // namespace

int main() {
    closesWithRawSameEpochExtremaAndCoverage();
    ignoresNonGenuineSamplesAndDefersSparseEpochs();
    smoothsAndDecidesOnlyWhenAnEpochCloses();
}
