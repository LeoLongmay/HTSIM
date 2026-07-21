#include <cassert>
#include <string>

#include "cbrpacket.h"
#include "eth_pause_packet.h"
#include "queue_lossless_input.h"
#include "queue_lossless_output.h"
#include "shared_buffer_pool.h"

namespace {

class PauseRecorder final : public Queue {
public:
    explicit PauseRecorder(EventList& eventlist)
        : Queue(speedFromGbps(1), 1'000, eventlist, nullptr),
          pause_count(0),
          resume_count(0) {}

    void receivePacket(Packet& pkt) override {
        assert(pkt.type() == ETH_PAUSE);
        const auto& pause = static_cast<EthPausePacket&>(pkt);
        if (pause.sleepTime() == 0) {
            ++resume_count;
        } else {
            ++pause_count;
        }
        pkt.free();
    }

    int pause_count;
    int resume_count;
};

class PacketRecorder final : public PacketSink {
public:
    PacketRecorder() : packet_count(0), name_("lossless pfc packet recorder") {}

    void receivePacket(Packet& pkt) override {
        ++packet_count;
        pkt.free();
    }

    const string& nodename() override { return name_; }

    int packet_count;

private:
    string name_;
};

void pfc_pauses_at_high_watermark_and_resumes_after_drain(EventList& eventlist) {
    LosslessInputQueue::configurePfc(80, 60);

    PauseRecorder recorder(eventlist);
    LosslessInputQueue ingress(eventlist, &recorder);
    SharedBufferPool pool(100, 80, 60);

    LosslessOutputQueue egress(speedFromGbps(100), 1'000, eventlist, nullptr);
    PacketRecorder delivered;
    Route route;
    route.push_back(&egress);
    route.push_back(&delivered);
    PacketFlow flow(nullptr);

    CbrPacket* first = CbrPacket::newpkt(flow, route, 1, 22);
    CbrPacket* second = CbrPacket::newpkt(flow, route, 2, 59);
    ingress.receivePacket(*first);
    ingress.receivePacket(*second);

    assert(recorder.pause_count == 1);
    assert(EventList::doNextEvent());
    assert(recorder.resume_count == 1);
    assert(pool.used() == 0);
    assert(EventList::doNextEvent());
    assert(delivered.packet_count == 2);
}

void output_queue_reserves_only_overflow_and_releases_it_after_drain(EventList& eventlist) {
    LosslessInputQueue::configurePfc(120, 90);

    PauseRecorder recorder(eventlist);
    LosslessInputQueue ingress(eventlist, &recorder);
    LosslessOutputQueue egress(speedFromGbps(100), 100, eventlist, nullptr);
    SharedBufferPool pool(40, 40, 39);
    egress.setSharedBuffer(pool);
    PacketRecorder delivered;
    Route route;
    route.push_back(&egress);
    route.push_back(&delivered);
    PacketFlow flow(nullptr);

    CbrPacket* first = CbrPacket::newpkt(flow, route, 1, 80);
    CbrPacket* second = CbrPacket::newpkt(flow, route, 2, 30);
    ingress.receivePacket(*first);
    ingress.receivePacket(*second);

    assert(pool.used() == 10);
    assert(EventList::doNextEvent());
    assert(EventList::doNextEvent());
    assert(pool.used() == 0);
    assert(delivered.packet_count == 2);
}

void output_queue_rejects_overflow_without_mutating_queue_or_pool(EventList& eventlist) {
    LosslessInputQueue::configurePfc(120, 90);

    PauseRecorder recorder(eventlist);
    LosslessInputQueue ingress(eventlist, &recorder);
    LosslessOutputQueue egress(speedFromGbps(100), 100, eventlist, nullptr);
    SharedBufferPool pool(40, 40, 39);
    egress.setSharedBuffer(pool);
    PacketRecorder delivered;
    Route route;
    route.push_back(&egress);
    route.push_back(&delivered);
    PacketFlow flow(nullptr);

    CbrPacket* first = CbrPacket::newpkt(flow, route, 1, 100);
    ingress.receivePacket(*first);
    const mem_b pool_used_before = pool.used();
    const mem_b queue_size_before = egress.queuesize();

    CbrPacket* rejected = CbrPacket::newpkt(flow, route, 2, 41);
    try {
        ingress.receivePacket(*rejected);
        assert(false);
    } catch (const std::logic_error& error) {
        assert(string(error.what()) == "shared-buffer capacity exceeded");
    }

    assert(pool.used() == pool_used_before);
    assert(egress.queuesize() == queue_size_before);
    rejected->free();
    assert(EventList::doNextEvent());
}

}  // namespace

int main() {
    EventList eventlist;
    pfc_pauses_at_high_watermark_and_resumes_after_drain(eventlist);
    assert(EventList::getPendingSources().empty());
    output_queue_reserves_only_overflow_and_releases_it_after_drain(eventlist);
    assert(EventList::getPendingSources().empty());
    output_queue_rejects_overflow_without_mutating_queue_or_pool(eventlist);
    assert(EventList::getPendingSources().empty());
}
