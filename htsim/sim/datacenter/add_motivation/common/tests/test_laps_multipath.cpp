#include "uec_mp.h"

#include <cassert>
#include <cstdlib>
#include <stdexcept>

namespace {

void low_latency_path_receives_more_softmax_selections() {
    srandom(17);
    UecMpLaps laps(4, false, 0.01);
    laps.configurePaths({10, 100, 100, 100});
    for (uint32_t path = 0; path != 4; ++path) {
        laps.observeLapsDelay(path, path == 0 ? 10 : 100, 1'000);
    }

    unsigned counts[4] = {};
    for (uint64_t seq = 0; seq != 4'000; ++seq) {
        ++counts[laps.nextEntropy(seq, 16) & 3];
    }
    for (uint32_t path = 1; path != 4; ++path) {
        assert(counts[0] > counts[path]);
        assert(counts[path] > 0);
    }
}

void zero_beta_sprays_uniformly_across_paths() {
    srandom(23);
    UecMpLaps laps(4, false, 0.0);
    laps.configurePaths({10, 100, 100, 100});
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

void catalog_base_values_calibrate_the_signal_before_traffic_observations() {
    UecMpLaps laps(4, false, 1.0);
    laps.configurePaths({10, 100, 100, 100});
    const UecMpLapsSignal signal = laps.lapsSignal(0);
    assert(signal.calibrated);
    assert(signal.target_delay == 100);
    assert(signal.min_delay == 10);
    assert(!signal.all_paths_high);
}

void strict_all_path_high_uses_the_calibrated_target_delay() {
    UecMpLaps laps(4, false, 1.0);
    laps.configurePaths({10, 100, 100, 100});
    for (uint32_t path = 0; path != 4; ++path) {
        laps.observeLapsDelay(path, path == 0 ? 10 : 100, 0);
    }

    assert(!laps.lapsSignal(0).all_paths_high);
    for (uint32_t path = 0; path != 4; ++path) {
        laps.observeLapsDelay(path, 101, 1);
    }
    const UecMpLapsSignal signal = laps.lapsSignal(1);
    assert(signal.calibrated);
    assert(signal.target_delay == 100);
    assert(signal.min_delay == 101);
    assert(signal.all_paths_high);
}

void stale_pid_has_zero_weight_until_probe_ack() {
    UecMpLaps laps(4, false, 8.0);
    laps.configurePaths({100, 100, 100, 100});
    for (uint16_t pid = 0; pid < 4; ++pid) {
        laps.observeLapsDelay(pid, 100, 0);
    }

    assert(laps.nextLapsDeadline(0) == 201);
    const auto probe = laps.nextLapsProbePid(201);
    assert(probe.has_value());
    assert(*probe == 0);
    assert(!laps.pathIsSelectable(0));
    for (int i = 0; i < 2'000; ++i) {
        assert(laps.nextLapsPid() != 0);
    }

    laps.observeLapsProbe(*probe, 100, 201);
    assert(laps.pathIsSelectable(0));
}

void multiple_stale_paths_are_probed_in_rotation() {
    UecMpLaps laps(4, false, 8.0);
    laps.configurePaths({10, 10, 10, 10});
    for (uint32_t path = 0; path != 4; ++path) {
        laps.observeLapsDelay(path, 10, 0);
    }

    const auto first = laps.nextLapsProbePid(21);
    const auto second = laps.nextLapsProbePid(21);
    assert(first.has_value());
    assert(second.has_value());
    assert(*first == 0);
    assert(*second == 1);
}

void path_after_stale_timeout_is_probed() {
    UecMpLaps laps(4, false, 8.0);
    laps.configurePaths({10, 10, 10, 10});
    for (uint32_t path = 0; path != 4; ++path) {
        laps.observeLapsDelay(path, 10, 0);
    }

    assert(!laps.nextLapsProbePid(20).has_value());
    const auto probe = laps.nextLapsProbePid(21);
    assert(probe.has_value());
    assert(*probe == 0);
}

void stale_samples_block_all_path_high_until_refreshed() {
    UecMpLaps laps(4, false, 8.0);
    laps.configurePaths({10, 10, 10, 10});
    for (uint32_t path = 0; path != 4; ++path) {
        laps.observeLapsDelay(path, 10, 0);
        laps.observeLapsDelay(path, 30, 0);
    }

    laps.observeLapsDelay(0, 30, 61);
    // Expiry becomes non-selectable when the deadline-driven probe is issued.
    const auto first_probe = laps.nextLapsProbePid(61);
    assert(first_probe.has_value());
    assert(*first_probe == 1);
    const UecMpLapsSignal stale_signal = laps.lapsSignal(61);
    // Probed PIDs are invalid/zero-weight, but the remaining valid PID still
    // drives Algorithm 2's all-valid-paths congestion decision.
    assert(stale_signal.calibrated);
    assert(stale_signal.target_delay == 10);
    assert(stale_signal.min_delay == 30);
    assert(stale_signal.all_paths_high);

    for (uint32_t path = 2; path != 4; ++path) {
        const auto probe = laps.nextLapsProbePid(61);
        assert(probe.has_value());
        assert(*probe == path);
    }
    const UecMpLapsSignal probed_signal = laps.lapsSignal(61);
    assert(probed_signal.calibrated);
    assert(probed_signal.all_paths_high);

    for (uint32_t path = 1; path != 4; ++path) {
        laps.observeLapsProbe(path, 30, 61);
    }
    const UecMpLapsSignal refreshed_signal = laps.lapsSignal(61);
    assert(refreshed_signal.calibrated);
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
    catalog_base_values_calibrate_the_signal_before_traffic_observations();
    strict_all_path_high_uses_the_calibrated_target_delay();
    stale_pid_has_zero_weight_until_probe_ack();
    multiple_stale_paths_are_probed_in_rotation();
    path_after_stale_timeout_is_probed();
    stale_samples_block_all_path_high_until_refreshed();
    rejects_non_power_of_two_path_count();
}
