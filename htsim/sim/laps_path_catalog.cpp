#include "laps_path_catalog.h"

#include "pipe.h"
#include "queue.h"
#include "route.h"

#include <limits>
#include <stdexcept>

namespace {

simtime_picosec serializationDelay(mem_b bytes, linkspeed_bps rate) {
    if (bytes <= 0 || rate == 0) {
        throw std::invalid_argument("strict LAPS requires a positive packet size and link rate");
    }
    const unsigned __int128 numerator =
        static_cast<unsigned __int128>(bytes) * 8 * timeFromSec(1.0);
    const unsigned __int128 delay = numerator / rate;
    if (delay > std::numeric_limits<simtime_picosec>::max()) {
        throw std::overflow_error("strict LAPS packet serialization delay overflows");
    }
    return static_cast<simtime_picosec>(delay);
}

simtime_picosec saturatingAdd(simtime_picosec left, simtime_picosec right) {
    if (left > std::numeric_limits<simtime_picosec>::max() - right) {
        throw std::overflow_error("strict LAPS path delay overflows");
    }
    return left + right;
}

}  // namespace

LapsPathCatalog::LapsPathCatalog(std::vector<LapsPathEntry> entries,
                                 LapsRoutePairs route_pairs)
    : entries_(std::move(entries)), route_pairs_(std::move(route_pairs)) {}

std::shared_ptr<const LapsPathCatalog> LapsPathCatalog::build(
    LapsRoutePairs candidates, uint32_t plane,
    linkspeed_bps rate, mem_b data_packet_bytes, uint16_t requested_paths) {
    if (requested_paths == 0 || candidates.size() < requested_paths) {
        throw std::invalid_argument("strict LAPS has insufficient bidirectional path candidates");
    }

    const simtime_picosec packet_serialization = serializationDelay(data_packet_bytes, rate);
    std::vector<LapsPathEntry> entries;
    entries.reserve(requested_paths);
    for (uint16_t pid = 0; pid < requested_paths; ++pid) {
        const LapsRoutePair& pair = candidates.at(pid);
        const Route* const forward = pair.forward.get();
        const Route* const reverse = pair.reverse.get();
        if (forward == nullptr || reverse == nullptr || forward->reverse() != reverse ||
            reverse->reverse() != forward) {
            throw std::invalid_argument("strict LAPS candidate has no mutually linked reverse route");
        }

        simtime_picosec uncongested_data_delay = 0;
        uint16_t switch_count = 0;
        for (size_t hop = 0; hop < forward->size(); ++hop) {
            PacketSink* const sink = forward->at(hop);
            if (sink == nullptr) {
                throw std::invalid_argument("strict LAPS candidate contains a null route hop");
            }
            if (auto* pipe = dynamic_cast<Pipe*>(sink)) {
                uncongested_data_delay = saturatingAdd(uncongested_data_delay, pipe->delay());
            } else if (auto* queue = dynamic_cast<BaseQueue*>(sink)) {
                uncongested_data_delay =
                    saturatingAdd(uncongested_data_delay, packet_serialization);
                if (queue->getSwitch() != nullptr) {
                    if (switch_count == std::numeric_limits<uint16_t>::max()) {
                        throw std::overflow_error("strict LAPS switch count overflows");
                    }
                    ++switch_count;
                }
            }
        }

        const unsigned __int128 margin = static_cast<unsigned __int128>(5) * switch_count *
                                         packet_serialization;
        if (margin > std::numeric_limits<simtime_picosec>::max()) {
            throw std::overflow_error("strict LAPS queue margin overflows");
        }
        entries.push_back({pid, plane, forward, reverse, uncongested_data_delay,
                           saturatingAdd(uncongested_data_delay,
                                         static_cast<simtime_picosec>(margin)),
                           switch_count});
    }
    candidates.resize(requested_paths);
    return std::shared_ptr<const LapsPathCatalog>(
        new LapsPathCatalog(std::move(entries), std::move(candidates)));
}

const LapsPathEntry& LapsPathCatalog::entry(uint16_t pid) const {
    return entries_.at(pid);
}

uint16_t LapsPathCatalog::size() const {
    return static_cast<uint16_t>(entries_.size());
}
