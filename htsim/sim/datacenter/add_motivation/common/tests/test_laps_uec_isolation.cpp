#include <cassert>
#include <memory>

#include "config.h"
#define private public
#include "uec.h"
#undef private

namespace {

void laps_sources_share_one_nic_recovery_domain(EventList& eventlist) {
    UecSrc::_sender_based_cc = true;
    UecSrc::_receiver_based_cc = true;
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

void non_laps_source_never_joins_paired_recovery_on_the_same_nic(EventList& eventlist) {
    UecSrc::_sender_based_cc = true;
    UecSrc::_receiver_based_cc = true;
    UecSrc::_sender_cc_algo = UecSrc::LAPS;

    UecNIC nic(1, eventlist, speedFromGbps(100), 1);
    UecSrc laps(nullptr, eventlist, std::make_unique<UecMpLaps>(1, false, 1.0), nic, 1);
    UecSrc non_laps(nullptr, eventlist, std::make_unique<UecMpEcmp>(1, false), nic, 1);
    laps.setDst(10);

    assert(laps.isStrictLaps());
    assert(!non_laps.isStrictLaps());
    assert(!nic._laps_recovery);

    laps.createSendRecord(3, 40, 1'300, {}, true);
    laps._in_flight += 1'300;
    nic.lapsRecovery().sent(laps.lapsPathKey(3), laps, 40, 1'300);

    non_laps.createSendRecord(4, 50, 1'400, {}, true);
    non_laps._in_flight = 1'400;
    non_laps._rtx_queue.emplace(60, 1'500);
    non_laps._rtx_backlog = 1'500;
    const auto non_laps_tx_count_before = non_laps._tx_bitmap.size();
    const auto non_laps_tx_size_before = non_laps._tx_bitmap.at(50).pkt_size;
    const auto non_laps_tx_path_before = non_laps._tx_bitmap.at(50).path_id;
    const auto non_laps_tx_strict_before = non_laps._tx_bitmap.at(50).strict_laps_data;
    const auto non_laps_rtx_before = non_laps._rtx_queue;
    const mem_b non_laps_flight_before = non_laps._in_flight;
    const mem_b non_laps_rtx_backlog_before = non_laps._rtx_backlog;

    assert(EventList::doNextEvent());
    assert(EventList::now() == timeFromUs(uint32_t{8000}));
    assert(laps._tx_bitmap.empty());
    assert(laps._rtx_queue.count(40) == 1);
    assert(non_laps._tx_bitmap.size() == non_laps_tx_count_before);
    assert(non_laps._tx_bitmap.count(50) == 1);
    assert(non_laps._tx_bitmap.at(50).pkt_size == non_laps_tx_size_before);
    assert(non_laps._tx_bitmap.at(50).path_id == non_laps_tx_path_before);
    assert(non_laps._tx_bitmap.at(50).strict_laps_data == non_laps_tx_strict_before);
    assert(non_laps._rtx_queue == non_laps_rtx_before);
    assert(non_laps._in_flight == non_laps_flight_before);
    assert(non_laps._rtx_backlog == non_laps_rtx_backlog_before);

    non_laps.recalculateRTO();
    assert(non_laps._rtx_timeout_pending);
    non_laps.cancelRTO();
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

void unpaired_laps_preserves_legacy_uec_behavior(EventList& eventlist) {
    UecSrc::_sender_based_cc = true;
    UecSrc::_receiver_based_cc = false;
    UecSrc::_sender_cc_algo = UecSrc::LAPS;

    UecNIC nic(4, eventlist, speedFromGbps(100), 1);
    UecSrc source(nullptr, eventlist, std::make_unique<UecMpEcmp>(1, false), nic, 1);
    assert(!source.isStrictLaps());
    assert(source.updateCwndOnNack == &UecSrc::updateCwndOnNack_NSCC);

    source.createSendRecord(0, 71, 1'500, {}, true);
    source.recalculateRTO();
    assert(source._rtx_timeout_pending);
    source.cancelRTO();
}

}  // namespace

int main() {
    EventList eventlist;
    laps_sources_share_one_nic_recovery_domain(eventlist);
    assert(EventList::getPendingSources().empty());
    non_laps_source_never_joins_paired_recovery_on_the_same_nic(eventlist);
    assert(EventList::getPendingSources().empty());
    laps_pacer_uses_packet_serialization_at_current_rate(eventlist);
    assert(EventList::getPendingSources().empty());
    strict_laps_data_never_arms_the_generic_rto(eventlist);
    assert(EventList::getPendingSources().empty());
    unpaired_laps_preserves_legacy_uec_behavior(eventlist);
    assert(EventList::getPendingSources().empty());
}
