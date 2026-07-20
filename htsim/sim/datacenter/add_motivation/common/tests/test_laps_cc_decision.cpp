#include "laps_rate.h"

#include <cassert>
#include <limits>

namespace {

LapsRateSignal signal(bool calibrated, bool all_paths_high, simtime_picosec target_delay,
                      simtime_picosec min_delay) {
    return {calibrated, all_paths_high, target_delay, min_delay};
}

void uncalibrated_signal_holds_every_rate_field() {
    const LapsRateState initial = {speedFromGbps(80), speedFromGbps(100), 3, 90, 70};

    const LapsRateState result = advanceLapsRate(
        initial, signal(false, true, 20, 30), 100, speedFromGbps(100));

    assert(result.cur_rate == initial.cur_rate);
    assert(result.tgt_rate == initial.tgt_rate);
    assert(result.inc_stage == initial.inc_stage);
    assert(result.next_decrease_at == initial.next_decrease_at);
    assert(result.next_increase_at == initial.next_increase_at);
}

void all_paths_high_halves_100_gbps_to_50_gbps() {
    const LapsRateState result = advanceLapsRate(
        {speedFromGbps(100), speedFromGbps(120), 4, 0, 0}, signal(true, true, 20, 30), 100,
        speedFromGbps(100));

    assert(result.cur_rate == speedFromGbps(50));
    assert(result.tgt_rate == speedFromGbps(100));
    assert(result.inc_stage == 0);
    assert(result.next_decrease_at == 160);
    assert(result.next_increase_at == 0);
}

void decrease_is_blocked_until_its_two_minimum_real_delay_cooldown() {
    const LapsRateState initial = {speedFromGbps(50), speedFromGbps(100), 2, 160, 0};

    const LapsRateState result = advanceLapsRate(
        initial, signal(true, true, 20, 30), 159, speedFromGbps(100));

    assert(result.cur_rate == initial.cur_rate);
    assert(result.tgt_rate == initial.tgt_rate);
    assert(result.inc_stage == initial.inc_stage);
    assert(result.next_decrease_at == initial.next_decrease_at);
    assert(result.next_increase_at == initial.next_increase_at);
}

void safe_signal_advances_50_gbps_to_75_gbps() {
    const LapsRateState result = advanceLapsRate(
        {speedFromGbps(50), speedFromGbps(100), 0, 0, 0}, signal(true, false, 20, 30), 100,
        speedFromGbps(100));

    assert(result.cur_rate == speedFromGbps(75));
    assert(result.tgt_rate == speedFromGbps(100));
    assert(result.inc_stage == 1);
    assert(result.next_increase_at == 160);
}

void stage_six_doubles_the_target_rate() {
    const LapsRateState result = advanceLapsRate(
        {speedFromGbps(50), speedFromGbps(100), 6, 0, 0}, signal(true, false, 20, 30), 100,
        speedFromGbps(400));

    assert(result.cur_rate == speedFromGbps(125));
    assert(result.tgt_rate == speedFromGbps(200));
    assert(result.inc_stage == 7);
    assert(result.next_increase_at == 160);
}

void decrease_uses_the_paper_halving_rule_without_a_uec_rate_floor() {
    const LapsRateState result = advanceLapsRate(
        {speedFromGbps(1), speedFromGbps(1), 3, 0, 0}, signal(true, true, 20, 30), 100,
        speedFromGbps(100));

    assert(result.cur_rate == speedFromGbps(0.5));
    assert(result.tgt_rate == speedFromGbps(1));
}

void increase_never_exceeds_the_nic_rate() {
    const LapsRateState result = advanceLapsRate(
        {speedFromGbps(200), speedFromGbps(300), 6, 0, 0}, signal(true, false, 20, 30), 100,
        speedFromGbps(200));

    assert(result.cur_rate == speedFromGbps(200));
    assert(result.tgt_rate == speedFromGbps(200));
}

void cooldown_times_saturate_instead_of_wrapping() {
    const simtime_picosec max_time = std::numeric_limits<simtime_picosec>::max();
    const LapsRateState result = advanceLapsRate(
        {speedFromGbps(100), speedFromGbps(100), 0, 0, 0},
        signal(true, true, 20, max_time / 2 + 1), 100, speedFromGbps(100));

    assert(result.next_decrease_at == max_time);
}

void cooldown_uses_two_times_minimum_real_delay() {
    const LapsRateSignal sampled = {true, true, 80, 30};
    const LapsRateState result = advanceLapsRate(
        {speedFromGbps(100), speedFromGbps(100), 0, 0, 0}, sampled, 100,
        speedFromGbps(100));

    assert(result.cur_rate == speedFromGbps(50));
    assert(result.next_decrease_at == 160);
}

}  // namespace

int main() {
    uncalibrated_signal_holds_every_rate_field();
    all_paths_high_halves_100_gbps_to_50_gbps();
    decrease_is_blocked_until_its_two_minimum_real_delay_cooldown();
    safe_signal_advances_50_gbps_to_75_gbps();
    stage_six_doubles_the_target_rate();
    decrease_uses_the_paper_halving_rule_without_a_uec_rate_floor();
    increase_never_exceeds_the_nic_rate();
    cooldown_times_saturate_instead_of_wrapping();
    cooldown_uses_two_times_minimum_real_delay();
}
