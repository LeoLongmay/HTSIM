// -*- c-basic-offset: 4; indent-tabs-mode: nil -*-
#ifndef MOTIVATION_BACKGROUND_H
#define MOTIVATION_BACKGROUND_H

#include <cstdint>
#include <string>
#include <vector>

#include "config.h"
#include "eventlist.h"
#include "motivation_trace.h"
#include "network.h"

struct MotivationBackgroundSpec {
    uint32_t background_id;
    uint32_t src;
    uint32_t dst;
    uint32_t path_index;
    linkspeed_bps rate;
    simtime_picosec start_ps;
    simtime_picosec stop_ps;
};

std::vector<MotivationBackgroundSpec> loadMotivationBackgroundConfig(
    const std::string& path);
std::string motivationBackgroundQueueFingerprint(const route_t& route);

class MotivationBackgroundSink : public PacketSink {
public:
    MotivationBackgroundSink() = default;

    void receivePacket(Packet& packet) override;
    const std::string& nodename() override { return _nodename; }
    uint64_t deliveredBytes() const { return _delivered_bytes; }

private:
    std::string _nodename = "motivation_background_sink";
    uint64_t _delivered_bytes = 0;
};

class MotivationBackgroundSource : public EventSource {
public:
    MotivationBackgroundSource(EventList& eventlist, const MotivationBackgroundSpec& spec,
                               MotivationTraceWriter& trace_writer,
                               std::string queue_fingerprint);

    void connect(route_t& route, MotivationBackgroundSink& sink);
    void doNextEvent() override;

    simtime_picosec period() const { return _period; }
    uint64_t sentBytes() const { return _sent_bytes; }

private:
    static constexpr uint32_t kPacketBytes = 1500;

    void log(const char* operation, uint64_t delivered_bytes);
    void sendPacket();

    MotivationBackgroundSpec _spec;
    MotivationTraceWriter& _trace_writer;
    std::string _queue_fingerprint;
    PacketFlow _flow;
    route_t* _route = nullptr;
    MotivationBackgroundSink* _sink = nullptr;
    simtime_picosec _period;
    uint64_t _sent_bytes = 0;
    uint64_t _next_packet_id = 0;
    bool _started = false;
    bool _finished = false;
};

#endif
