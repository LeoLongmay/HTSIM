#include "laps_cc.h"

#include <cassert>
#include <limits>

namespace {

UecMpLapsSignal readySignal(bool all_paths_high, simtime_picosec threshold,
                            simtime_picosec max_real_latency) {
    UecMpLapsSignal signal;
    signal.ready = true;
    signal.all_paths_high = all_paths_high;
    signal.sampled_paths = 4;
    signal.threshold = threshold;
    signal.max_real_latency = max_real_latency;
    return signal;
}

void incomplete_samples_hold() {
    UecMpLapsSignal signal;
    signal.ready = false;
    signal.all_paths_high = true;

    const LapsCwndDecision decision = decideLapsCwnd(signal, 100, 0, 0);
    assert(decision.action == LapsCwndAction::Hold);
}

void one_path_at_or_below_threshold_cannot_decrease() {
    const LapsCwndDecision decision =
        decideLapsCwnd(readySignal(false, 20, 80), 100, 0, 0);
    assert(decision.action != LapsCwndAction::MultiplicativeDecrease);
}

void all_paths_strictly_above_threshold_decrease_once() {
    const LapsCwndDecision decision =
        decideLapsCwnd(readySignal(true, 20, 80), 100, 0, 0);
    assert(decision.action == LapsCwndAction::MultiplicativeDecrease);
    assert(decision.next_allowed_at == 260);
}

void repeated_high_observation_before_real_latency_gate_holds() {
    const LapsCwndDecision decision =
        decideLapsCwnd(readySignal(true, 20, 80), 150, 0, 260);
    assert(decision.action == LapsCwndAction::Hold);
    assert(decision.next_allowed_at == 260);
}

void safe_observation_increases_only_after_threshold_gate() {
    const UecMpLapsSignal signal = readySignal(false, 20, 80);
    const LapsCwndDecision first = decideLapsCwnd(signal, 100, 0, 0);
    assert(first.action == LapsCwndAction::AdditiveIncrease);
    assert(first.next_allowed_at == 140);

    const LapsCwndDecision repeated = decideLapsCwnd(signal, 120, first.next_allowed_at, 0);
    assert(repeated.action == LapsCwndAction::Hold);
    assert(repeated.next_allowed_at == 140);

    const LapsCwndDecision after_gate =
        decideLapsCwnd(signal, first.next_allowed_at, first.next_allowed_at, 0);
    assert(after_gate.action == LapsCwndAction::AdditiveIncrease);
}

void decision_gate_saturates_instead_of_wrapping() {
    const simtime_picosec max_time = std::numeric_limits<simtime_picosec>::max();
    const LapsCwndDecision decision = decideLapsCwnd(
        readySignal(true, 20, max_time / 2 + 1), 100, 0, 0);
    assert(decision.action == LapsCwndAction::MultiplicativeDecrease);
    assert(decision.next_allowed_at == max_time);
}

}  // namespace

int main() {
    incomplete_samples_hold();
    one_path_at_or_below_threshold_cannot_decrease();
    all_paths_strictly_above_threshold_decrease_once();
    repeated_high_observation_before_real_latency_gate_holds();
    safe_observation_increases_only_after_threshold_gate();
    decision_gate_saturates_instead_of_wrapping();
}
