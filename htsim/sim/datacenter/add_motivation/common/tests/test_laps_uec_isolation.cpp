#include <cassert>
#include <memory>

#include "config.h"
#define private public
#include "uec.h"
#undef private
#include "queue.h"

namespace {

class Tick final : public EventSource {
public:
    explicit Tick(EventList& eventlist) : EventSource(eventlist, "laps test tick") {}
    void doNextEvent() override {}
};

void setStrictGlobals() {
    UecSrc::_sender_based_cc = true;
    UecSrc::_receiver_based_cc = true;
    UecSrc::_sender_cc_algo = UecSrc::LAPS;
}

LapsPathKey installSharedPhysicalPath(UecSrc& source, Queue& first, Queue& second) {
    source.lapsSetPathResolver([&](uint32_t, uint32_t, vector<const BaseQueue*>& queues) {
        queues = {&first, &second};
        return true;
    });
    LapsPathKey path;
    assert(source.lapsResolvePath(7, path));
    return path;
}

LapsAttempt installStrictRecord(UecSrc& source, LapsRecoveryDomain& domain,
                                const LapsPathKey& path, uint32_t entropy,
                                UecBasePacket::seq_t seq, mem_b bytes) {
    source.createSendRecord(entropy, seq, bytes, {}, true);
    source._in_flight += bytes;
    const LapsAttempt attempt = domain.sent(path, source, seq, bytes);
    source._tx_bitmap.at(seq).laps_attempt = attempt;
    return attempt;
}

void strict_laps_uses_canonical_shared_paths_and_retires_all_ack_forms(EventList& eventlist) {
    setStrictGlobals();

    Queue q1(speedFromGbps(100), 100'000, eventlist, nullptr);
    Queue q2(speedFromGbps(100), 100'000, eventlist, nullptr);
    q1.forceName("source|uplink");
    q2.forceName("spine:egress");
    UecNIC nic(0, eventlist, speedFromGbps(100), 1);
    UecSrc first(nullptr, eventlist, std::make_unique<UecMpLaps>(2, false, 1.0), nic, 1);
    UecSrc second(nullptr, eventlist, std::make_unique<UecMpLaps>(2, false, 1.0), nic, 1);
    first.setDst(9);
    second.setDst(9);

    const LapsPathKey first_entropy_0 = installSharedPhysicalPath(first, q1, q2);
    const LapsPathKey second_entropy_1 = installSharedPhysicalPath(second, q1, q2);
    assert(first_entropy_0.queue_fingerprint == second_entropy_1.queue_fingerprint);
    // Length-prefixing, rather than a raw delimiter, is the canonical identity.
    assert(first_entropy_0.queue_fingerprint == "13:source|uplink12:spine:egress");

    Queue q3(speedFromGbps(100), 100'000, eventlist, nullptr);
    q3.forceName("other-path");
    const LapsPathKey other_path("10:other-path");
    LapsRecoveryDomain& domain = nic.lapsRecovery();
    installStrictRecord(first, domain, first_entropy_0, 0, 10, 1'000);
    installStrictRecord(second, domain, second_entropy_1, 1, 20, 1'100);
    installStrictRecord(first, domain, first_entropy_0, 0, 30, 1'200);
    installStrictRecord(first, domain, other_path, 1, 50, 1'300);

    // Exact ACK of 30 infers 10/20 lost on the shared physical path.  Its
    // SACK retires 50 on another path.
    UecAckPacket* ack = UecAckPacket::newpkt(*first.flow(), nullptr, 0, 50, 30, 0,
                                             false, 0, 255);
    ack->set_bitmap(1);
    first.processAck(*ack);
    ack->free();

    assert(first._rtx_queue.count(10) == 1);
    assert(second._rtx_queue.count(20) == 1);
    assert(first._tx_bitmap.count(30) == 1);
    assert(second._tx_bitmap.empty());
    UecAckPacket* cumulative = UecAckPacket::newpkt(*first.flow(), nullptr, 31, 0, 30,
                                                    0, false, 0, 255);
    first.processAck(*cumulative);
    cumulative->free();
    assert(first._tx_bitmap.empty());
    // Every strict attempt was detached before generic UEC record erasure, so
    // no delayed strict-recovery callback remains at kRto.
    assert(!EventList::doNextEvent());
}

void strict_nack_retires_old_attempt_before_retry(EventList& eventlist) {
    setStrictGlobals();

    UecNIC nic(1, eventlist, speedFromGbps(100), 1);
    UecSrc source(nullptr, eventlist, std::make_unique<UecMpLaps>(2, false, 1.0), nic, 1);
    const LapsPathKey old_path("8:old-path");
    const LapsPathKey retry_path("10:retry-path");
    LapsRecoveryDomain& domain = nic.lapsRecovery();
    const LapsAttempt old_attempt = installStrictRecord(source, domain, old_path, 0, 40, 1'300);

    UecNackPacket* nack = UecNackPacket::newpkt(*source.flow(), nullptr, 40, 0, 0, 0);
    source.processNack(*nack);
    nack->free();
    assert(source._tx_bitmap.empty());
    assert(source._rtx_queue.count(40) == 1);

    Tick tick(eventlist);
    eventlist.sourceIsPending(tick, timeFromUs(uint32_t{8000}));
    assert(EventList::doNextEvent());
    assert(EventList::now() == timeFromUs(uint32_t{8000}));
    // The old path's deadline cannot fire after strict NACK detached it.
    assert(source._rtx_queue.count(40) == 1);

    source._rtx_queue.clear();
    source._rtx_backlog = 0;
    const LapsAttempt retry_attempt =
        installStrictRecord(source, domain, retry_path, 1, 40, 1'300);
    assert(retry_attempt != old_attempt);
    assert(source._tx_bitmap.at(40).laps_attempt == retry_attempt);
    assert(EventList::doNextEvent());
    assert(EventList::now() == timeFromUs(uint32_t{16000}));
    assert(source._tx_bitmap.empty());
    assert(source._rtx_queue.count(40) == 1);
}

void non_laps_source_never_joins_paired_recovery_on_the_same_nic(EventList& eventlist) {
    setStrictGlobals();

    UecNIC nic(2, eventlist, speedFromGbps(100), 1);
    UecSrc laps(nullptr, eventlist, std::make_unique<UecMpLaps>(1, false, 1.0), nic, 1);
    UecSrc non_laps(nullptr, eventlist, std::make_unique<UecMpEcmp>(1, false), nic, 1);
    assert(laps.isStrictLaps());
    assert(!non_laps.isStrictLaps());
    LapsPathKey ignored;
    non_laps.lapsSetPathResolver({});
    assert(!non_laps.lapsResolvePath(0, ignored));

    laps.createSendRecord(3, 40, 1'300, {}, true);
    laps._in_flight += 1'300;
    LapsRecoveryDomain& domain = nic.lapsRecovery();
    const LapsAttempt attempt = domain.sent(LapsPathKey("11:laps-path"), laps, 40, 1'300);
    laps._tx_bitmap.at(40).laps_attempt = attempt;

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
    assert(EventList::now() == timeFromUs(uint32_t{24000}));
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
}

void laps_pacer_uses_packet_serialization_at_current_rate(EventList& eventlist) {
    UecSrc::_sender_based_cc = true;
    UecSrc::_receiver_based_cc = false;
    UecSrc::_sender_cc_algo = UecSrc::LAPS;

    UecNIC nic(3, eventlist, speedFromGbps(100), 1);
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

    UecNIC nic(4, eventlist, speedFromGbps(100), 1);
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
    setStrictGlobals();

    UecNIC nic(3, eventlist, speedFromGbps(100), 1);
    UecSrc source(nullptr, eventlist, std::make_unique<UecMpEcmp>(1, false), nic, 1);
    assert(!source.isStrictLaps());
    assert(source.updateCwndOnNack == &UecSrc::updateCwndOnNack_NSCC);
    source.createSendRecord(0, 71, 1'500, {}, true);
    source.recalculateRTO();
    assert(source._rtx_timeout_pending);
    source.cancelRTO();
    assert(!nic.hasLapsRecovery());
}

}  // namespace

int main() {
    EventList eventlist;
    strict_laps_uses_canonical_shared_paths_and_retires_all_ack_forms(eventlist);
    assert(EventList::getPendingSources().empty());
    strict_nack_retires_old_attempt_before_retry(eventlist);
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
