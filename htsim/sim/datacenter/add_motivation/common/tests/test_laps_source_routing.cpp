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

class LocalizedLapsFixture {
public:
    LocalizedLapsFixture()
        : source_nic(0, eventlist, speedFromGbps(100), 2),
          sink_nic(1, eventlist, speedFromGbps(100), 2),
          source(nullptr, eventlist, std::make_unique<UecMpLaps>(4, false, 1.0), source_nic, 2),
          sink(nullptr, nullptr, sink_nic, 2),
          plane0(makeCatalogPlane(0)),
          plane1(makeCatalogPlane(1)) {
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
    setLapsGlobals();
    localized_laps_keeps_catalog_pairing_but_resprays_retransmissions();
    pooled_packet_clears_laps_metadata();
}
