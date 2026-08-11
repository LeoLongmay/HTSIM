#include "prime_path_catalog.h"

#include "queue.h"
#include "switch.h"

#include <functional>
#include <limits>
#include <set>
#include <stdexcept>
#include <unordered_map>

namespace {

std::vector<BaseQueue*> sourceUpwardQueues(const Route& route) {
    struct SwitchHop {
        BaseQueue* queue;
        uint32_t source_tier;
        uint32_t destination_tier;
    };

    constexpr uint32_t tor_tier = 1;
    constexpr uint32_t agg_tier = 2;
    constexpr uint32_t core_tier = 3;
    std::vector<SwitchHop> switch_hops;
    bool saw_host_ingress = false;
    bool saw_host_egress = false;

    for (size_t hop = 0; hop < route.size(); ++hop) {
        auto* queue = dynamic_cast<BaseQueue*>(route.at(hop));
        if (queue == nullptr) {
            continue;
        }

        Switch* const source = queue->getSwitch();
        auto* const destination = dynamic_cast<Switch*>(queue->getRemoteEndpoint());
        if (source == nullptr || destination == nullptr) {
            if (source == nullptr && destination != nullptr && hop == 0 &&
                destination->getType() == tor_tier) {
                saw_host_ingress = true;
                continue;
            }
            bool is_last_queue = true;
            for (size_t later_hop = hop + 1; later_hop < route.size(); ++later_hop) {
                if (dynamic_cast<BaseQueue*>(route.at(later_hop)) != nullptr) {
                    is_last_queue = false;
                    break;
                }
            }
            if (source != nullptr && destination == nullptr && is_last_queue &&
                source->getType() == tor_tier) {
                saw_host_egress = true;
                continue;
            }
            throw std::invalid_argument(
                "PRIME candidate has a queue without an expected FatTree switch endpoint");
        }

        const uint32_t source_tier = source->getType();
        const uint32_t destination_tier = destination->getType();
        if (source_tier < tor_tier || source_tier > core_tier ||
            destination_tier < tor_tier || destination_tier > core_tier) {
            throw std::invalid_argument("PRIME candidate has a non-FatTree switch tier");
        }
        switch_hops.push_back({queue, source_tier, destination_tier});
    }

    if (!saw_host_ingress || !saw_host_egress) {
        throw std::invalid_argument("PRIME candidate is missing a FatTree host ingress or egress hop");
    }

    const auto hop_is = [&](size_t index, uint32_t source_tier,
                            uint32_t destination_tier) {
        return switch_hops.at(index).source_tier == source_tier &&
               switch_hops.at(index).destination_tier == destination_tier;
    };
    if (switch_hops.size() == 2 && hop_is(0, tor_tier, agg_tier) &&
        hop_is(1, agg_tier, tor_tier)) {
        return {switch_hops.at(0).queue};
    }
    if (switch_hops.size() == 4 && hop_is(0, tor_tier, agg_tier) &&
        hop_is(1, agg_tier, core_tier) && hop_is(2, core_tier, agg_tier) &&
        hop_is(3, agg_tier, tor_tier)) {
        return {switch_hops.at(0).queue, switch_hops.at(1).queue};
    }

    throw std::invalid_argument("PRIME candidate is not an ordered adjacent FatTree route");
}

uint16_t portForQueue(std::unordered_map<BaseQueue*, uint16_t>& ports, BaseQueue* queue) {
    const auto existing = ports.find(queue);
    if (existing != ports.end()) {
        return existing->second;
    }
    if (ports.size() > std::numeric_limits<uint16_t>::max()) {
        throw std::overflow_error("PRIME tier has too many distinct ports");
    }
    const uint16_t port = static_cast<uint16_t>(ports.size());
    ports.emplace(queue, port);
    return port;
}

void validateCompleteCartesianTupleSet(const std::set<std::vector<uint16_t>>& tuples,
                                       uint16_t tier_count) {
    std::vector<std::set<uint16_t>> values_by_tier(tier_count);
    for (const std::vector<uint16_t>& tuple : tuples) {
        for (uint16_t tier = 0; tier < tier_count; ++tier) {
            values_by_tier.at(tier).insert(tuple.at(tier));
        }
    }

    size_t expected_tuple_count = 1;
    for (const std::set<uint16_t>& values : values_by_tier) {
        if (values.empty() || expected_tuple_count > tuples.size() / values.size()) {
            throw std::invalid_argument(
                "PRIME candidate tuples do not form a complete Cartesian product");
        }
        expected_tuple_count *= values.size();
    }
    if (expected_tuple_count != tuples.size()) {
        throw std::invalid_argument(
            "PRIME candidate tuples do not form a complete Cartesian product");
    }

    std::vector<uint16_t> product_tuple(tier_count);
    const std::function<void(uint16_t)> require_product_tuple = [&](uint16_t tier) {
        if (tier == tier_count) {
            if (tuples.find(product_tuple) == tuples.end()) {
                throw std::invalid_argument(
                    "PRIME candidate tuples do not form a complete Cartesian product");
            }
            return;
        }
        for (uint16_t value : values_by_tier.at(tier)) {
            product_tuple.at(tier) = value;
            require_product_tuple(static_cast<uint16_t>(tier + 1));
        }
    };
    require_product_tuple(0);
}

}  // namespace

void appendPrimeTransportEndpoints(PrimeRoutePairs& candidates,
                                   PacketSink& forward_endpoint,
                                   PacketSink& reverse_endpoint) {
    for (PrimeRoutePair& pair : candidates) {
        if (!pair.forward || !pair.reverse || pair.forward->reverse() != pair.reverse.get() ||
            pair.reverse->reverse() != pair.forward.get()) {
            throw std::invalid_argument("PRIME candidate has no mutually linked reverse route");
        }
        pair.forward->push_back(&forward_endpoint);
        pair.reverse->push_back(&reverse_endpoint);
    }
}

PrimePathCatalog::PrimePathCatalog(std::vector<PrimePathEntry> entries,
                                   PrimeRoutePairs route_pairs, uint16_t tier_count)
    : entries_(std::move(entries)), route_pairs_(std::move(route_pairs)), tier_count_(tier_count) {}

std::shared_ptr<const PrimePathCatalog> PrimePathCatalog::build(PrimeRoutePairs candidates,
                                                                  uint32_t plane,
                                                                  uint16_t requested_paths) {
    if (plane != 0) {
        throw std::invalid_argument("PRIME supports only plane zero");
    }
    if (requested_paths == 0 || (requested_paths & (requested_paths - 1)) != 0 ||
        candidates.size() < requested_paths) {
        throw std::invalid_argument("PRIME has insufficient bidirectional path candidates");
    }

    std::vector<PrimePathEntry> entries;
    entries.reserve(requested_paths);
    // An MP-EV part is an uplink number within the switch that consumes that
    // part, not a globally compressed queue identifier.  For part zero that
    // switch is the source TOR; for part one it is the reached aggregation
    // switch.  Keep an independent compact queue-to-port map for every such
    // switch at every tuple tier.
    std::vector<std::unordered_map<Switch*, std::unordered_map<BaseQueue*, uint16_t>>>
        ports_by_tier;
    std::set<std::vector<uint16_t>> tuples;
    uint16_t tier_count = 0;

    for (uint16_t index = 0; index < requested_paths; ++index) {
        const PrimeRoutePair& pair = candidates.at(index);
        const Route* const forward = pair.forward.get();
        const Route* const reverse = pair.reverse.get();
        if (forward == nullptr || reverse == nullptr || forward->reverse() != reverse ||
            reverse->reverse() != forward) {
            throw std::invalid_argument("PRIME candidate has no mutually linked reverse route");
        }

        const std::vector<BaseQueue*> upward = sourceUpwardQueues(*forward);
        if (tier_count == 0) {
            tier_count = static_cast<uint16_t>(upward.size());
            ports_by_tier.resize(tier_count);
        } else if (upward.size() != tier_count) {
            throw std::invalid_argument("PRIME candidates have mixed FatTree tier counts");
        }

        PrimeTuple tuple;
        tuple.ports.reserve(tier_count);
        for (uint16_t tier = 0; tier < tier_count; ++tier) {
            Switch* const consuming_switch = upward.at(tier)->getSwitch();
            if (consuming_switch == nullptr) {
                throw std::invalid_argument("PRIME upward hop has no consuming switch");
            }
            tuple.ports.push_back(
                portForQueue(ports_by_tier.at(tier)[consuming_switch], upward.at(tier)));
        }
        if (!tuples.insert(tuple.ports).second) {
            throw std::invalid_argument("PRIME candidates contain duplicate MP-EV tuples");
        }

        entries.push_back({index, index, std::move(tuple), forward, reverse});
    }

    validateCompleteCartesianTupleSet(tuples, tier_count);

    candidates.resize(requested_paths);
    return std::shared_ptr<const PrimePathCatalog>(
        new PrimePathCatalog(std::move(entries), std::move(candidates), tier_count));
}

const PrimePathEntry& PrimePathCatalog::entryForEntropy(uint32_t entropy) const {
    return entries_.at(entropy);
}

const PrimePathEntry& PrimePathCatalog::entryForIndex(uint16_t catalog_index) const {
    return entries_.at(catalog_index);
}

uint16_t PrimePathCatalog::size() const {
    return static_cast<uint16_t>(entries_.size());
}

uint16_t PrimePathCatalog::tierCount() const {
    return tier_count_;
}
