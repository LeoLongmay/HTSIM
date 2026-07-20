#include <cassert>
#include <memory>
#include <string>
#include <vector>

#include "config.h"
#define private public
#include "uec.h"
#undef private

namespace {

EventList eventlist;

class CapturingSink final : public PacketSink {
public:
    explicit CapturingSink(std::string name) : name_(std::move(name)) {}

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

}  // namespace

int main() {
    strict_laps_data_and_rtx_use_catalog_forward_route();
    strict_laps_ack_and_probe_ack_use_catalog_reverse_route();
    pooled_packet_clears_laps_metadata();
}
