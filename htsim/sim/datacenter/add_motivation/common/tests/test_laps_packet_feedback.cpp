#include "uec.h"

#include <cassert>
#include <memory>

namespace {

class NoopEventSource final : public EventSource {
public:
    explicit NoopEventSource(EventList& eventlist) : EventSource(eventlist, "noop") {}
    void doNextEvent() override {}
};

void lapsFeedbackCarriesOneWayDelayAndResetsPooledPackets() {
    constexpr simtime_picosec send_time = 100;
    constexpr simtime_picosec receive_time = 275;

    EventList eventlist;
    NoopEventSource clock(eventlist);
    UecNIC nic(0, eventlist, speedFromGbps(100), 1);
    UecSrc source(nullptr, eventlist, std::make_unique<UecMpEcmp>(1, false), nic, 1);
    UecSink sink(nullptr, nullptr, nic, 1);
    Route reverse_route;
    sink.connectPort(0, source, reverse_route);

    PacketFlow flow(nullptr);
    Route data_route;
    UecDataPacket* data = UecDataPacket::newpkt(
        flow, data_route, 0, 1'500, UecDataPacket::DATA_PULL, 0);
    data->set_pathid(0);
    data->setLapsSendTime(send_time);

    EventList::sourceIsPending(clock, receive_time);
    assert(EventList::doNextEvent());

    UecAckPacket* ack = sink.sack(0, 0, 0, false, false, data);
    assert(ack->lapsDelayValid());
    assert(ack->lapsOneWayDelay() == receive_time - send_time);

    ack->free();
    data->free();

    UecDataPacket* reused_data = UecDataPacket::newpkt(
        flow, data_route, 1, 1'500, UecDataPacket::DATA_PULL, 0);
    UecAckPacket* reused_ack = UecAckPacket::newpkt(
        flow, nullptr, 0, 0, 0, 0, false, 0, 0);
    assert(!reused_data->lapsSendTimeValid());
    assert(reused_data->lapsSendTime() == 0);
    assert(!reused_ack->lapsDelayValid());
    assert(reused_ack->lapsOneWayDelay() == 0);

    reused_ack->free();
    reused_data->free();
}

}  // namespace

int main() {
    lapsFeedbackCarriesOneWayDelayAndResetsPooledPackets();
}
