#include "uec_mp.h"

#include <cassert>
#include <cstdlib>
#include <stdexcept>

namespace {

void low_latency_path_receives_more_softmax_selections() {
    srandom(17);
    UecMpLaps laps(4, false, 8.0);
    for (uint32_t path = 0; path != 4; ++path) {
        laps.observeLapsDelay(path, path == 0 ? 10 : 100, 1'000);
    }

    unsigned counts[4] = {};
    for (uint64_t seq = 0; seq != 4'000; ++seq) {
        ++counts[laps.nextEntropy(seq, 16) & 3];
    }
    for (uint32_t path = 1; path != 4; ++path) {
        assert(counts[0] > counts[path]);
    }
}

void zero_beta_sprays_uniformly_across_paths() {
    srandom(23);
    UecMpLaps laps(4, false, 0.0);
    for (uint32_t path = 0; path != 4; ++path) {
        laps.observeLapsDelay(path, path == 0 ? 10 : 100, 1'000);
    }

    unsigned counts[4] = {};
    for (uint64_t seq = 0; seq != 4'000; ++seq) {
        ++counts[laps.nextEntropy(seq, 16) & 3];
    }
    for (unsigned count : counts) {
        assert(count > 800);
        assert(count < 1'200);
    }
}

void signal_is_not_ready_until_every_path_has_a_sample() {
    UecMpLaps laps(4, false, 8.0);
    laps.observeLapsDelay(0, 10, 1'000);
    laps.observeLapsDelay(1, 100, 1'000);
    laps.observeLapsDelay(2, 100, 1'000);
    assert(!laps.lapsSignal(1'000, 0).ready);

    laps.observeLapsDelay(3, 100, 1'000);
    const UecMpLapsSignal signal = laps.lapsSignal(1'000, 0);
    assert(signal.ready);
    assert(!signal.all_paths_high);
}

void stale_path_is_probed_and_probe_feedback_refreshes_it() {
    UecMpLaps laps(4, false, 8.0);
    laps.observeLapsDelay(0, 10, 0);
    for (uint32_t path = 1; path != 4; ++path) {
        laps.observeLapsDelay(path, 100, 100);
    }

    const auto probe = laps.nextLapsProbeEntropy(100);
    assert(probe.has_value());
    assert((*probe & 3) == 0);

    laps.observeLapsProbe(*probe, 10, 100);
    assert(!laps.nextLapsProbeEntropy(100).has_value());
}

void multiple_stale_paths_are_probed_in_rotation() {
    UecMpLaps laps(4, false, 8.0);
    for (uint32_t path = 0; path != 4; ++path) {
        laps.observeLapsDelay(path, 10, 0);
    }

    const auto first = laps.nextLapsProbeEntropy(100);
    const auto second = laps.nextLapsProbeEntropy(100);
    assert(first.has_value());
    assert(second.has_value());
    assert((*first & 3) == 0);
    assert((*second & 3) == 1);
}

void path_at_exact_stale_timeout_is_probed() {
    UecMpLaps laps(4, false, 8.0);
    for (uint32_t path = 0; path != 4; ++path) {
        laps.observeLapsDelay(path, 10, 0);
    }

    const auto probe = laps.nextLapsProbeEntropy(20);
    assert(probe.has_value());
    assert((*probe & 3) == 0);
}

void stale_samples_block_all_path_high_until_refreshed() {
    UecMpLaps laps(4, false, 8.0);
    for (uint32_t path = 0; path != 4; ++path) {
        laps.observeLapsDelay(path, 10, 0);
        laps.observeLapsDelay(path, 30, 0);
    }

    laps.observeLapsDelay(0, 30, 60);
    const UecMpLapsSignal stale_signal = laps.lapsSignal(60, 10);
    assert(!stale_signal.ready);
    assert(!stale_signal.all_paths_high);

    for (uint32_t path = 1; path != 4; ++path) {
        const auto probe = laps.nextLapsProbeEntropy(60);
        assert(probe.has_value());
        assert((*probe & 3) == path);
    }
    const UecMpLapsSignal probed_signal = laps.lapsSignal(60, 10);
    assert(!probed_signal.ready);
    assert(!probed_signal.all_paths_high);

    for (uint32_t path = 1; path != 4; ++path) {
        laps.observeLapsProbe(path, 30, 60);
    }
    const UecMpLapsSignal refreshed_signal = laps.lapsSignal(60, 10);
    assert(refreshed_signal.ready);
    assert(refreshed_signal.all_paths_high);
}

void rejects_non_power_of_two_path_count() {
    bool rejected = false;
    try {
        UecMpLaps laps(3, false, 8.0);
    } catch (const std::invalid_argument&) {
        rejected = true;
    }
    assert(rejected);
}

}  // namespace

int main() {
    low_latency_path_receives_more_softmax_selections();
    zero_beta_sprays_uniformly_across_paths();
    signal_is_not_ready_until_every_path_has_a_sample();
    stale_path_is_probed_and_probe_feedback_refreshes_it();
    multiple_stale_paths_are_probed_in_rotation();
    path_at_exact_stale_timeout_is_probed();
    stale_samples_block_all_path_high_until_refreshed();
    rejects_non_power_of_two_path_count();
}
