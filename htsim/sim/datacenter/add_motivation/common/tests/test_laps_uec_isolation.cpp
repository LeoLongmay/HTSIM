#include <cassert>
#include <memory>

#include "config.h"
#define private public
#include "uec.h"
#undef private

namespace {

void laps_sources_share_one_nic_recovery_domain(EventList& eventlist) {
    UecSrc::_sender_based_cc = true;
    UecSrc::_receiver_based_cc = false;
    UecSrc::_sender_cc_algo = UecSrc::LAPS;

    UecNIC nic(0, eventlist, speedFromGbps(100), 1);
    UecSrc first(nullptr, eventlist, std::make_unique<UecMpLaps>(1, false, 1.0), nic, 1);
    UecSrc second(nullptr, eventlist, std::make_unique<UecMpLaps>(1, false, 1.0), nic, 1);
    first.setDst(9);
    second.setDst(9);

    assert(first.isStrictLaps());
    assert(second.isStrictLaps());
    assert(!nic._laps_recovery);

    const LapsPathKey path = first.lapsPathKey(7);
    first.createSendRecord(7, 10, 1'000, {});
    first._in_flight += 1'000;
    second.createSendRecord(7, 20, 1'100, {});
    second._in_flight += 1'100;
    first.createSendRecord(7, 30, 1'200, {});
    first._in_flight += 1'200;

    LapsRecoveryDomain& domain = nic.lapsRecovery();
    domain.sent(path, first, 10, 1'000);
    domain.sent(path, second, 20, 1'100);
    domain.sent(path, first, 30, 1'200);

    UecAckPacket* later_ack = UecAckPacket::newpkt(
        *first.flow(), nullptr, 0, 30, 30, 7, false, 0, 255);
    later_ack->set_bitmap(1);
    first.processAck(*later_ack);
    later_ack->free();

    assert(first._rtx_queue.count(10) == 1);
    assert(second._rtx_queue.count(20) == 1);
    assert(first._rtx_queue.count(30) == 0);
    assert(first._tx_bitmap.count(10) == 0);
    assert(second._tx_bitmap.count(20) == 0);
    assert(first._tx_bitmap.count(30) == 0);
}

void non_laps_source_never_creates_or_joins_recovery_domain(EventList& eventlist) {
    UecSrc::_sender_based_cc = true;
    UecSrc::_receiver_based_cc = false;
    UecSrc::_sender_cc_algo = UecSrc::LAPS;

    UecNIC nic(1, eventlist, speedFromGbps(100), 1);
    UecSrc non_laps(nullptr, eventlist, std::make_unique<UecMpEcmp>(1, false), nic, 1);

    assert(!non_laps.isStrictLaps());
    assert(!nic._laps_recovery);
}

void laps_pacer_uses_packet_serialization_at_current_rate(EventList& eventlist) {
    UecSrc::_sender_based_cc = true;
    UecSrc::_receiver_based_cc = false;
    UecSrc::_sender_cc_algo = UecSrc::LAPS;

    UecNIC nic(2, eventlist, speedFromGbps(100), 1);
    UecSrc source(nullptr, eventlist, std::make_unique<UecMpLaps>(1, false, 1.0), nic, 1);
    source._laps_rate.cur_rate = speedFromGbps(50);

    source.advanceLapsPacer(1'500);
    const simtime_picosec expected = 1'500ULL * 8ULL * 1000ULL / 50ULL;
    assert(source._laps_next_send_at == EventList::now() + expected);
    assert(EventList::now() < source._laps_next_send_at);

    source._backlog = 1'500;
    source.sendIfPermitted();
    assert(source._laps_pacer_timer_when == source._laps_next_send_at);
    assert(source._stats.new_pkts_sent == 0);
}

void strict_laps_data_never_arms_the_generic_rto(EventList& eventlist) {
    UecSrc::_sender_based_cc = true;
    UecSrc::_receiver_based_cc = false;
    UecSrc::_sender_cc_algo = UecSrc::LAPS;

    UecNIC nic(3, eventlist, speedFromGbps(100), 1);
    UecSrc source(nullptr, eventlist, std::make_unique<UecMpLaps>(1, false, 1.0), nic, 1);
    source.createSendRecord(0, 1, 1'500, {}, true);
    source.recalculateRTO();
    assert(!source._rtx_timeout_pending);

    source.createSendRecord(0, 2, UecBasePacket::get_ack_size(), {});
    source.recalculateRTO();
    assert(source._rtx_timeout_pending);
    source.cancelRTO();
}

}  // namespace

int main() {
    EventList eventlist;
    laps_sources_share_one_nic_recovery_domain(eventlist);
    non_laps_source_never_creates_or_joins_recovery_domain(eventlist);
    laps_pacer_uses_packet_serialization_at_current_rate(eventlist);
    strict_laps_data_never_arms_the_generic_rto(eventlist);
}
