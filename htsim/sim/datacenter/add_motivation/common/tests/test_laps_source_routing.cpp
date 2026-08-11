#include <cassert>
#include <memory>
#include <string>
#include <vector>

#include "config.h"
#include "pipe.h"
#define private public
#include "uec.h"
#undef private

namespace {

EventList eventlist;

void setLapsGlobals() {
    UecSrc::_sender_based_cc = true;
    UecSrc::_receiver_based_cc = false;
    UecSrc::_sender_cc_algo = UecSrc::LAPS;
}

void setLapsControlGlobals() {
    UecSrc::_sender_based_cc = true;
    UecSrc::_receiver_based_cc = false;
    UecSrc::_sender_cc_algo = UecSrc::LAPS_CONTROL;
}

void setLapsControlPaperAckGlobals() {
    UecSrc::_sender_based_cc = true;
    UecSrc::_receiver_based_cc = false;
    UecSrc::_sender_cc_algo = UecSrc::LAPS_CONTROL_PAPERACK;
}

class CapturingSink final : public Pipe {
public:
    explicit CapturingSink(std::string name)
        : Pipe(timeFromUs(uint32_t{1}), EventList::getTheEventList()), name_(std::move(name)) {}

    void receivePacket(Packet& pkt) override { packets.push_back(&pkt); }
    const std::string& nodename() override { return name_; }

    std::vector<Packet*> packets;

private:
    std::string name_;
};

class AdvanceTime final : public EventSource {
public:
    explicit AdvanceTime(EventList& events) : EventSource(events, "advance time") {}
    void doNextEvent() override {}
};

struct CatalogPlane {
    std::vector<std::unique_ptr<CapturingSink>> forward_sinks;
    std::vector<std::unique_ptr<CapturingSink>> reverse_sinks;
    std::shared_ptr<const LapsPathCatalog> catalog;
};

CatalogPlane makeCatalogPlane(uint32_t plane) {
    CatalogPlane result;
    LapsRoutePairs pairs;
    for (uint16_t pid = 0; pid < 4; ++pid) {
        result.forward_sinks.push_back(std::make_unique<CapturingSink>(
            "forward-" + std::to_string(plane) + "-" + std::to_string(pid)));
        result.reverse_sinks.push_back(std::make_unique<CapturingSink>(
            "reverse-" + std::to_string(plane) + "-" + std::to_string(pid)));
        auto forward = std::make_unique<Route>();
        auto reverse = std::make_unique<Route>();
        forward->push_back(result.forward_sinks.back().get());
        reverse->push_back(result.reverse_sinks.back().get());
        forward->set_reverse(reverse.get());
        reverse->set_reverse(forward.get());
        pairs.push_back({std::move(forward), std::move(reverse)});
    }
    result.catalog = LapsPathCatalog::build(std::move(pairs), plane, speedFromGbps(100),
                                            1'500, 4);
    return result;
}

class LocalizedLapsFixture {
public:
    LocalizedLapsFixture()
        : source_nic(0, eventlist, speedFromGbps(100), 2),
          sink_nic(1, eventlist, speedFromGbps(100), 2),
          source(nullptr, eventlist, std::make_unique<UecMpLaps>(4, false, 1.0), source_nic, 2),
          sink(nullptr, nullptr, sink_nic, 2),
          plane0(makeCatalogPlane(0)),
          plane1(makeCatalogPlane(1)) {
        ordinary_reverse_sink = std::make_unique<CapturingSink>("ordinary-reverse");
        for (uint32_t plane = 0; plane < 2; ++plane) {
            reverse_fib[plane].push_back(ordinary_reverse_sink.get());
            source.connectPort(plane, forward_fib[plane], reverse_fib[plane], sink,
                               EventList::now());
            const auto& catalog = plane == 0 ? plane0.catalog : plane1.catalog;
            source.lapsSetPathCatalog(plane, catalog);
            sink.lapsSetPathCatalog(source, plane, catalog);
        }
    }

    const LapsPathCatalog& catalog(uint32_t plane) const {
        return *(plane == 0 ? plane0.catalog : plane1.catalog);
    }
    const Route& forwardFib(uint32_t plane) const { return forward_fib[plane]; }
    const Packet* lastForwardPacket(uint32_t plane, uint16_t pid) const {
        const auto& packets = (plane == 0 ? plane0 : plane1).forward_sinks.at(pid)->packets;
        return packets.empty() ? nullptr : packets.back();
    }
    const Packet* lastReversePacket(uint32_t plane, uint16_t pid) const {
        const auto& packets = (plane == 0 ? plane0 : plane1).reverse_sinks.at(pid)->packets;
        return packets.empty() ? nullptr : packets.back();
    }
    size_t ordinaryReversePacketCount() const { return ordinary_reverse_sink->packets.size(); }
    void selectOnly(uint16_t pid) {
        auto* laps = dynamic_cast<UecMpLaps*>(source._mp.get());
        assert(laps != nullptr);
        for (uint16_t current = 0; current < laps->_paths.size(); ++current) {
            laps->_paths[current].valid = current == pid;
            laps->_paths[current].probe_pending = false;
        }
    }

    UecNIC source_nic;
    UecNIC sink_nic;
    UecSrc source;
    UecSink sink;

private:
    std::unique_ptr<CapturingSink> ordinary_reverse_sink;
    Route forward_fib[2];
    Route reverse_fib[2];
    CatalogPlane plane0;
    CatalogPlane plane1;
};

void localized_laps_keeps_catalog_pairing_but_resprays_retransmissions() {
    LocalizedLapsFixture f;
    constexpr uint32_t plane = 0;
    constexpr uint16_t original_pid = 1;
    constexpr uint16_t retry_pid = 3;

    f.selectOnly(original_pid);
    f.source._backlog = 1'500;
    assert(f.source.sendNewPacket(f.forwardFib(plane)) == 1'500);
    const auto* data = static_cast<const UecDataPacket*>(f.lastForwardPacket(plane, original_pid));
    assert(data != nullptr);
    const auto seqno = data->epsn();

    // LAPS data and its ACK remain catalog-paired.
    assert(data->lapsPidValid());
    assert(data->route() == f.catalog(plane).entry(original_pid).forward);
    UecAckPacket* ack = f.sink.sack(original_pid, data->epsn(), data->epsn(), false, false,
                                     const_cast<UecDataPacket*>(data));
    assert(ack->route() == f.catalog(plane).entry(original_pid).reverse);
    ack->free();

    // Generic recovery has no retained strict replay route.  Force PID 3 to be
    // the current low-delay choice and verify the retry is sent on PID 3, not
    // the original PID 1.
    f.source._send_blocked_on_nic = true;
    UecNackPacket* nack = UecNackPacket::newpkt(*f.source.flow(), nullptr, seqno,
                                                 original_pid, 0, 0);
    f.source.processNack(*nack);
    nack->free();
    f.source._send_blocked_on_nic = false;
    f.selectOnly(retry_pid);
    assert(f.source._rtx_queue.count(seqno) == 1);
    assert(f.source.sendRtxPacket(f.forwardFib(plane)) == 1'500);
    const auto* retry = static_cast<const UecDataPacket*>(f.lastForwardPacket(plane, retry_pid));
    assert(retry != nullptr);
    assert(retry->lapsPid() == retry_pid);
    assert(retry->route() == f.catalog(plane).entry(retry_pid).forward);
}

void laps_defers_retransmission_while_every_pid_is_probe_pending() {
    LocalizedLapsFixture f;
    auto* laps = dynamic_cast<UecMpLaps*>(f.source._mp.get());
    assert(laps != nullptr);

    f.source._rtx_queue.emplace(91, 1'500);
    f.source._rtx_backlog = 1'500;
    const mem_b credit_before = f.source._credit;
    const mem_b in_flight_before = f.source._in_flight;
    const mem_b backlog_before = f.source._rtx_backlog;
    for (auto& state : laps->_paths) state.probe_pending = true;

    assert(f.source.sendRtxPacket(f.forwardFib(0)) == 0);
    assert(f.source._rtx_queue.count(91) == 1);
    assert(f.source._rtx_backlog == backlog_before);
    assert(f.source._credit == credit_before);
    assert(f.source._in_flight == in_flight_before);
}

void laps_defers_rts_while_every_pid_is_probe_pending() {
    LocalizedLapsFixture f;
    auto* laps = dynamic_cast<UecMpLaps*>(f.source._mp.get());
    assert(laps != nullptr);
    for (auto& state : laps->_paths) state.probe_pending = true;

    const auto highest_sent_before = f.source._highest_sent;
    const auto rts_sent_before = f.source._stats.rts_pkts_sent;
    const auto last_rts_before = f.source._last_rts;
    const auto rto_pending_before = f.source._rtx_timeout_pending;
    const auto rto_before = f.source._rtx_timeout;
    const auto rto_handle_before = f.source._rto_timer_handle;
    const auto send_records_before = f.source._tx_bitmap.size();
    const auto controls_before = f.source_nic._control.size();

    f.source.sendRTS();

    assert(f.source._highest_sent == highest_sent_before);
    assert(f.source._stats.rts_pkts_sent == rts_sent_before);
    assert(f.source._last_rts == last_rts_before);
    assert(f.source._rtx_timeout_pending == rto_pending_before);
    assert(f.source._rtx_timeout == rto_before);
    assert(f.source._rto_timer_handle == rto_handle_before);
    assert(f.source._tx_bitmap.size() == send_records_before);
    assert(f.source_nic._control.size() == controls_before);
}

void pooled_packet_clears_laps_metadata() {
    PacketFlow flow(nullptr);
    Route route;
    auto* first = UecDataPacket::newpkt(flow, route, 1, 1'500, UecDataPacket::DATA_PULL, 0);
    first->setLapsPid(3);
    first->setLapsPinnedRoute(true);
    first->free();
    auto* reused = UecDataPacket::newpkt(flow, route, 2, 1'500, UecDataPacket::DATA_PULL, 0);
    assert(!reused->lapsPidValid());
    assert(!reused->lapsPinnedRoute());
    reused->free();
}

void paperack_immediately_acks_data_with_paired_pid_delay_and_route() {
    setLapsControlPaperAckGlobals();
    AdvanceTime advance(eventlist);
    const simtime_picosec one_way_delay = timeFromUs(uint32_t{1});
    const simtime_picosec send_time = EventList::now();
    EventList::sourceIsPendingRel(advance, one_way_delay);
    assert(EventList::doNextEvent());
    assert(EventList::now() == send_time + one_way_delay);

    LocalizedLapsFixture f;
    constexpr uint32_t plane = 0;
    constexpr uint16_t pid = 2;
    auto* data = UecDataPacket::newpkt(*f.source.flow(), *f.catalog(plane).entry(pid).forward,
                                       0, 1'500, UecDataPacket::DATA_PULL, 0);
    data->set_pathid(pid);
    data->setLapsPid(pid);

    // A non-AR, non-ECN packet after the initial packet is normally delayed.
    // Paper ACKs must still be emitted immediately.
    f.source.setFlowsize(10'000);
    f.sink._received_bytes = 1'500;
    data->setLapsSendTime(send_time);
    f.sink.processData(*data);
    auto* immediate_ack = static_cast<UecAckPacket*>(
        const_cast<Packet*>(f.lastReversePacket(plane, pid)));
    assert(immediate_ack != nullptr);
    assert(immediate_ack->lapsPidValid() && immediate_ack->lapsPid() == pid);
    assert(immediate_ack->lapsDelayValid());
    assert(immediate_ack->lapsOneWayDelay() == one_way_delay);
    assert(immediate_ack->lapsOneWayDelay() > 0);
    assert(immediate_ack->lapsPinnedRoute());
    assert(immediate_ack->route() == f.catalog(plane).entry(pid).reverse);
    immediate_ack->free();
    data->free();
}

void legacy_laps_control_ack_remains_unpinned() {
    setLapsControlGlobals();
    LocalizedLapsFixture f;
    constexpr uint32_t plane = 0;
    constexpr uint16_t pid = 2;
    auto* data = UecDataPacket::newpkt(*f.source.flow(), *f.catalog(plane).entry(pid).forward,
                                       0, 1'500, UecDataPacket::DATA_PULL, 0);
    data->setLapsPid(pid);

    UecAckPacket* ack = f.sink.sack(pid, 0, 0, false, false, data);
    assert(ack->lapsPidValid() && ack->lapsPid() == pid);
    assert(!ack->lapsPinnedRoute());
    assert(ack->route() == nullptr);
    ack->free();

    // A non-AR, non-ECN subsequent packet remains subject to UEC ACK
    // thinning for the legacy control arm.
    f.source.setFlowsize(10'000);
    f.sink._received_bytes = 1'500;
    const size_t ordinary_reverse_before = f.ordinaryReversePacketCount();
    f.sink.processData(*data);
    assert(f.ordinaryReversePacketCount() == ordinary_reverse_before);
    data->free();
}

void paperack_and_legacy_control_share_probe_cap_policy() {
    setLapsControlGlobals();
    LocalizedLapsFixture legacy;
    assert(legacy.source.usesLapsControlProbeCap());
    setLapsControlPaperAckGlobals();
    LocalizedLapsFixture paperack;
    assert(paperack.source.usesLapsControlProbeCap());
    setLapsGlobals();
    LocalizedLapsFixture strict;
    assert(!strict.source.usesLapsControlProbeCap());
}

void paperack_and_legacy_control_schedule_probe_cap_behavior() {
    const simtime_picosec last_probe_at = EventList::now() + 1'000;
    const simtime_picosec probe_interval = 500;
    const simtime_picosec expected_earliest = last_probe_at + probe_interval;

    setLapsControlGlobals();
    LocalizedLapsFixture legacy;
    auto* legacy_laps = dynamic_cast<UecMpLaps*>(legacy.source._mp.get());
    legacy_laps->configurePaths({100, 100, 100, 100});
    const simtime_picosec legacy_now = EventList::now();
    for (uint16_t pid = 0; pid < 4; ++pid) {
        legacy_laps->observeLapsDelay(pid, 100, legacy_now);
    }
    const auto legacy_raw_deadline = legacy_laps->nextLapsDeadline(EventList::now());
    assert(legacy_raw_deadline.has_value());
    legacy.source._laps_last_probe_at = last_probe_at;
    legacy.source._laps_probe_interval = probe_interval;
    legacy.source.scheduleLapsProbe();
    assert(legacy.source._laps_probe_timer_when >= expected_earliest);
    assert(legacy.source._laps_probe_timer_when >= *legacy_raw_deadline);

    setLapsControlPaperAckGlobals();
    LocalizedLapsFixture paperack;
    auto* paperack_laps = dynamic_cast<UecMpLaps*>(paperack.source._mp.get());
    paperack_laps->configurePaths({100, 100, 100, 100});
    const simtime_picosec paperack_now = EventList::now();
    for (uint16_t pid = 0; pid < 4; ++pid) {
        paperack_laps->observeLapsDelay(pid, 100, paperack_now);
    }
    const auto paperack_raw_deadline = paperack_laps->nextLapsDeadline(EventList::now());
    assert(paperack_raw_deadline.has_value());
    paperack.source._laps_last_probe_at = last_probe_at;
    paperack.source._laps_probe_interval = probe_interval;
    paperack.source.scheduleLapsProbe();
    assert(paperack.source._laps_probe_timer_when >= expected_earliest);
    assert(paperack.source._laps_probe_timer_when >= *paperack_raw_deadline);

    setLapsGlobals();
    LocalizedLapsFixture strict;
    auto* strict_laps = dynamic_cast<UecMpLaps*>(strict.source._mp.get());
    strict_laps->configurePaths({100, 100, 100, 100});
    const simtime_picosec strict_now = EventList::now();
    for (uint16_t pid = 0; pid < 4; ++pid) {
        strict_laps->observeLapsDelay(pid, 100, strict_now);
    }
    const auto strict_raw_deadline = strict_laps->nextLapsDeadline(EventList::now());
    assert(strict_raw_deadline.has_value());
    strict.source._laps_last_probe_at = last_probe_at;
    strict.source._laps_probe_interval = probe_interval;
    strict.source.scheduleLapsProbe();
    assert(strict.source._laps_probe_timer_when == *strict_raw_deadline);
}

}  // namespace

int main() {
    setLapsGlobals();
    paperack_immediately_acks_data_with_paired_pid_delay_and_route();
    setLapsGlobals();
    localized_laps_keeps_catalog_pairing_but_resprays_retransmissions();
    laps_defers_retransmission_while_every_pid_is_probe_pending();
    laps_defers_rts_while_every_pid_is_probe_pending();
    pooled_packet_clears_laps_metadata();
    legacy_laps_control_ack_remains_unpinned();
    paperack_and_legacy_control_share_probe_cap_policy();
    paperack_and_legacy_control_schedule_probe_cap_behavior();
}
