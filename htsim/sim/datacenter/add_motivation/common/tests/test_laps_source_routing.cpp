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

class StrictLapsFixture {
public:
    StrictLapsFixture()
        : source_nic(0, eventlist, speedFromGbps(100), 2),
          sink_nic(1, eventlist, speedFromGbps(100), 2),
          source(nullptr, eventlist, std::make_unique<UecMpLaps>(4, false, 1.0), source_nic, 2),
          sink(nullptr, nullptr, sink_nic, 2),
          plane0(makeCatalogPlane(0)),
          plane1(makeCatalogPlane(1)) {
        UecSrc::_sender_based_cc = true;
        UecSrc::_receiver_based_cc = false;
        UecSrc::_sender_cc_algo = UecSrc::LAPS;

        for (uint32_t plane = 0; plane < 2; ++plane) {
            source.connectPort(plane, forward_fib[plane], reverse_fib[plane], sink, 0);
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
    size_t reversePacketCount(uint32_t plane, uint16_t pid) const {
        return (plane == 0 ? plane0 : plane1).reverse_sinks.at(pid)->packets.size();
    }

    UecNIC source_nic;
    UecNIC sink_nic;
    UecSrc source;
    UecSink sink;

private:
    Route forward_fib[2];
    Route reverse_fib[2];
    CatalogPlane plane0;
    CatalogPlane plane1;
};

void strict_laps_data_and_rtx_use_catalog_forward_route() {
    StrictLapsFixture f;

    f.source._backlog = 1'500;
    assert(f.source.sendNewPacket(f.forwardFib(1)) == 1'500);
    const uint16_t data_pid = static_cast<uint16_t>(f.source._tx_bitmap.at(0).path_id & 3);
    const Packet* data = f.lastForwardPacket(1, data_pid);
    assert(data != nullptr);
    assert(data->route() == f.catalog(1).entry(data_pid).forward);
    assert(static_cast<const UecDataPacket*>(data)->lapsPidValid());
    assert(static_cast<const UecDataPacket*>(data)->lapsPinnedRoute());

    f.source._rtx_queue.emplace(10, 1'500);
    f.source._rtx_backlog = 1'500;
    const mem_b sent = f.source.sendRtxPacket(f.forwardFib(0));
    assert(sent == 1'500);
    const uint16_t pid = static_cast<uint16_t>(f.source._tx_bitmap.at(10).path_id & 3);
    const Packet* rtx = f.lastForwardPacket(0, pid);
    assert(rtx != nullptr);
    assert(rtx->route() == f.catalog(0).entry(pid).forward);
    assert(static_cast<const UecDataPacket*>(rtx)->lapsPinnedRoute());
}

void strict_laps_waits_for_probe_ack_when_every_pid_is_pending() {
    StrictLapsFixture f;
    auto* laps = dynamic_cast<UecMpLaps*>(f.source._mp.get());
    assert(laps != nullptr);
    for (auto& state : laps->_paths) {
        state.probe_pending = true;
    }

    f.source._cwnd = 0;
    f.source._backlog = 1'500;
    assert(f.source.sendNewPacket(f.forwardFib(0)) == 0);
    assert(f.source._backlog == 1'500);
    assert(f.source._in_flight == 0);
    assert(f.source._tx_bitmap.empty());
}

void strict_laps_pacer_not_sender_cwnd_admits_data() {
    StrictLapsFixture f;
    f.source._cwnd = 0;
    f.source._backlog = 1'500;

    // The strict LAPS sender is paced by its LAPS rate; inherited UEC cwnd
    // admission must not prevent the NIC from starting this packet.
    f.source.sendIfPermitted();
    assert(f.source._stats.new_pkts_sent == 1);
}

void strict_laps_pacer_not_sender_cwnd_admits_retransmission() {
    StrictLapsFixture f;
    f.source._cwnd = 0;
    f.source._rtx_queue.emplace(7, 1'500);
    f.source._rtx_backlog = 1'500;

    f.source.sendIfPermitted();
    assert(f.source._stats.rtx_pkts_sent == 1);
    assert(f.source._tx_bitmap.count(7) == 1);
}

void strict_laps_recovery_replays_original_plane_when_other_port_is_free() {
    StrictLapsFixture f;
    constexpr UecDataPacket::seq_t seqno = 70;
    constexpr uint16_t pid = 2;
    LapsPathKey original_path;
    assert(f.source.lapsResolvePath(pid, f.forwardFib(1), original_path));

    f.source._rtx_queue.emplace(seqno, 1'500);
    f.source._rtx_backlog = 1'500;
    assert(f.source._laps_rtx_routes.emplace(
        seqno, UecSrc::LapsRtxRoute{pid, {}, original_path, 1, pid}).second);

    // The caller receives plane 0 because it is free, but strict LAPS recovery
    // must replay the plane-1 catalog identity recorded for this packet.
    assert(f.source.sendRtxPacket(f.forwardFib(0)) == 1'500);
    const Packet* replay = f.lastForwardPacket(1, pid);
    assert(replay != nullptr);
    assert(replay->route() == f.catalog(1).entry(pid).forward);
    assert(static_cast<const UecDataPacket*>(replay)->lapsPid() == pid);
}

void strict_laps_ack_and_probe_ack_use_catalog_reverse_route() {
    StrictLapsFixture f;
    PacketFlow flow(nullptr);
    UecDataPacket* data = UecDataPacket::newpkt(
        flow, f.catalog(1).entry(1).forward ? *f.catalog(1).entry(1).forward : f.forwardFib(1),
        20, 1'500, UecDataPacket::DATA_PULL, 0);
    data->setLapsPid(1);
    data->setLapsPinnedRoute(true);
    UecAckPacket* ack = f.sink.sack(1, 20, 20, false, false, data);
    assert(ack->route() == f.catalog(1).entry(1).reverse);
    assert(ack->lapsPid() == 1);
    assert(ack->lapsPinnedRoute());
    f.sink_nic.sendControlPacket(ack, nullptr, &f.sink);
    assert(f.lastReversePacket(1, 1) == ack);
    ack->free();

    UecDataPacket* probe = UecDataPacket::newpkt(
        flow, *f.catalog(0).entry(3).forward, 21, UecBasePacket::ACKSIZE,
        UecDataPacket::DATA_PROBE, 0);
    probe->setLapsPid(3);
    probe->setLapsPinnedRoute(true);
    UecAckPacket* probe_ack = f.sink.sack(3, 21, 21, false, false, probe);
    probe_ack->set_probe_ack(true);
    assert(probe_ack->route() == f.catalog(0).entry(3).reverse);
    assert(probe_ack->lapsPid() == 3);
    assert(probe_ack->lapsPinnedRoute());
    probe_ack->free();
    probe->free();
    data->free();

    auto* multipath = dynamic_cast<UecMpLaps*>(f.source._mp.get());
    assert(multipath != nullptr);
    for (auto& state : multipath->_paths) {
        state.valid = true;
        state.real_latency = 0;
        state.last_update = EventList::now();
    }
    f.source.sendLapsProbe();
    const uint16_t probe_pid = 0;
    const Packet* plane0_probe = f.lastForwardPacket(0, probe_pid);
    const Packet* plane1_probe = f.lastForwardPacket(1, probe_pid);
    const Packet* sent_probe = plane0_probe != nullptr ? plane0_probe : plane1_probe;
    assert(sent_probe != nullptr);
    assert(static_cast<const UecDataPacket*>(sent_probe)->lapsPinnedRoute());
    assert(sent_probe->route() == (plane0_probe != nullptr ? f.catalog(0).entry(probe_pid).forward
                                                            : f.catalog(1).entry(probe_pid).forward));
}

void strict_laps_acks_every_data_packet() {
    StrictLapsFixture f;
    f.source.setFlowsize(3'000);
    PacketFlow& flow = *f.source.flow();

    auto* first = UecDataPacket::newpkt(flow, *f.catalog(0).entry(0).forward, 0, 1'500,
                                         UecDataPacket::DATA_PULL, 0);
    first->setLapsPid(0);
    first->setLapsPinnedRoute(true);
    f.sink.processData(*first);
    assert(f.reversePacketCount(0, 0) == 1);

    auto* second = UecDataPacket::newpkt(flow, *f.catalog(1).entry(2).forward, 1, 1'500,
                                          UecDataPacket::DATA_PULL, 0);
    second->setLapsPid(2);
    second->setLapsPinnedRoute(true);
    f.sink.processData(*second);
    assert(f.reversePacketCount(1, 2) == 1);

    first->free();
    second->free();
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

void pooled_non_laps_control_cannot_keep_a_pinned_route() {
    StrictLapsFixture f;
    PacketFlow flow(nullptr);

    f.sink.connectPort(0, f.source, *f.catalog(0).entry(0).reverse);
    f.sink.connectPort(1, f.source, *f.catalog(0).entry(0).reverse);
    auto* primed = UecNackPacket::newpkt(flow, f.catalog(1).entry(2).reverse,
                                         1, 0, 0, 0);
    static_cast<Packet&>(*primed).set_route(*f.catalog(1).entry(2).reverse);
    primed->setLapsPid(2);
    primed->setLapsPinnedRoute(true);
    primed->free();

    auto* nack = UecNackPacket::newpkt(flow, nullptr, 2, 0, 0, 0);
    assert(!nack->lapsPidValid());
    assert(!nack->lapsPinnedRoute());
    f.sink_nic._rr_port = 1;
    f.sink_nic.sendControlPacket(nack, nullptr, &f.sink);
    assert(f.lastReversePacket(0, 0) == nack);
    nack->free();
}

}  // namespace

int main() {
    strict_laps_data_and_rtx_use_catalog_forward_route();
    strict_laps_waits_for_probe_ack_when_every_pid_is_pending();
    strict_laps_pacer_not_sender_cwnd_admits_data();
    strict_laps_pacer_not_sender_cwnd_admits_retransmission();
    strict_laps_recovery_replays_original_plane_when_other_port_is_free();
    strict_laps_ack_and_probe_ack_use_catalog_reverse_route();
    strict_laps_acks_every_data_packet();
    pooled_packet_clears_laps_metadata();
    pooled_non_laps_control_cannot_keep_a_pinned_route();
}
    void enableRouteAudit() {
        route_audit = std::make_shared<LapsRouteAudit>();
        source.lapsSetRouteAudit(route_audit);
        sink.lapsSetRouteAudit(source, route_audit);
    }
    LapsRouteAudit& audit() const {
        assert(route_audit);
        return *route_audit;
    }
    void selectOnly(uint16_t pid) {
        auto* laps = dynamic_cast<UecMpLaps*>(source._mp.get());
        assert(laps != nullptr);
        for (uint16_t current = 0; current < laps->_paths.size(); ++current) {
            laps->_paths[current].valid = current == pid;
            laps->_paths[current].probe_pending = false;
        }
    }
    UecDataPacket* sendDataOnPid(uint16_t pid, uint32_t plane) {
        selectOnly(pid);
        source._backlog = 1'500;
        assert(source.sendNewPacket(forwardFib(plane)) == 1'500);
        auto* packet = const_cast<UecDataPacket*>(
            static_cast<const UecDataPacket*>(lastForwardPacket(plane, pid)));
        assert(packet != nullptr && packet->epsn() == source._highest_sent - 1);
        return packet;
    }
    void acknowledge(UecDataPacket& data) {
        const uint16_t pid = data.lapsPid();
        UecAckPacket* ack = sink.sack(pid, data.epsn(), data.epsn(), false, false, &data);
        source.processAck(*ack);
        ack->free();
    }
    std::shared_ptr<LapsRouteAudit> route_audit;
void one_pid_drop_uses_reverse_ack_and_recovers_only_that_pid() {
    StrictLapsFixture f;
    f.enableRouteAudit();

    // This is deliberately a fixture-only loss injection: do not deliver the
    // first PID-0 packet.  The next PID-0 ACK must infer and recover only it.
    UecDataPacket* dropped = f.sendDataOnPid(0, 0);
    assert(dropped->epsn() == 0);
    UecDataPacket* delivered_on_zero = f.sendDataOnPid(0, 0);
    assert(delivered_on_zero->epsn() == 1);

    // Keep the deterministic recovery queued so the assertion observes the
    // exact inferred sequence before the NIC schedules it.
    f.source._speculating = true;
    UecSrc::_receiver_based_cc = true;
    f.acknowledge(*delivered_on_zero);
    UecSrc::_receiver_based_cc = false;
    assert(f.source._rtx_queue.size() == 1);
    assert(f.source._rtx_queue.begin()->first == dropped->epsn());
    assert(f.source._laps_rtx_routes.at(dropped->epsn()).pid == 0);

    UecDataPacket* delivered_on_one = f.sendDataOnPid(1, 1);
    assert(delivered_on_one->epsn() == 2);
    f.acknowledge(*delivered_on_one);
    assert(f.source._rtx_queue.size() == 1);

    // Replay the single inferred loss and prove it retained PID 0.
    f.source._speculating = false;
    f.selectOnly(0);
    assert(f.source.sendRtxPacket(f.forwardFib(1)) == 1'500);
    const Packet* retransmission = f.lastForwardPacket(0, 0);
    assert(retransmission != nullptr);
    assert(static_cast<const UecDataPacket*>(retransmission)->epsn() == dropped->epsn());
    assert(static_cast<const UecDataPacket*>(retransmission)->lapsPid() == 0);
    assert(f.audit().verify());
}

    one_pid_drop_uses_reverse_ack_and_recovers_only_that_pid();
