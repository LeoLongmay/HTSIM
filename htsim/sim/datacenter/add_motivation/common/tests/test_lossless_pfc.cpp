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

void pfc_pauses_at_high_watermark_and_resumes_after_drain() {
    EventList eventlist;
    LosslessInputQueue::configurePfc(80, 60);

    PauseRecorder recorder(eventlist);
    LosslessInputQueue ingress(eventlist, &recorder);
    SharedBufferPool pool(100, 80, 60);
    ingress.setSharedBuffer(pool);

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
    assert(pool.used() == 59);
    assert(delivered.packet_count == 1);
}

}  // namespace

int main() {
    pfc_pauses_at_high_watermark_and_resumes_after_drain();
}
