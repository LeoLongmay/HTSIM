#include "datacenter/fat_tree_topology.h"
#include "datacenter/fat_tree_switch.h"
#include "prime_path_catalog.h"
#include "queue.h"

#include <cassert>
#include <map>
#include <memory>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

EventList eventlist;

class TerminalSink final : public PacketSink {
public:
    explicit TerminalSink(std::string name) : name_(std::move(name)) {}
    void receivePacket(Packet&) override { ++received_; }
    const string& nodename() override { return name_; }

private:
    std::string name_;
    uint32_t received_ = 0;
};

PrimeRoutePairs takeBidirectionalPaths(FatTreeTopology& topology, uint32_t src,
                                       uint32_t dst) {
    std::unique_ptr<std::vector<const Route*>> paths(topology.get_bidir_paths(src, dst, true));
    PrimeRoutePairs pairs;
    pairs.reserve(paths->size());
    for (const Route* forward : *paths) {
        Route* mutable_forward = const_cast<Route*>(forward);
        pairs.push_back({std::unique_ptr<Route>(mutable_forward),
                         std::unique_ptr<Route>(
                             mutable_forward == nullptr
                                 ? nullptr
                                 : const_cast<Route*>(mutable_forward->reverse()))});
    }
    return pairs;
}

std::shared_ptr<const PrimePathCatalog> buildFatTreePrimeCatalog(uint32_t src,
                                                                  uint32_t dst,
                                                                  uint16_t paths) {
    FatTreeTopologyCfg config(3, 128, speedFromGbps(100), memFromPkt(100),
                              timeFromUs(uint32_t{1}), 0, COMPOSITE, FAIR_PRIO);
    FatTreeTopology topology(&config, nullptr, &eventlist, nullptr);
    return PrimePathCatalog::build(takeBidirectionalPaths(topology, src, dst), 0, paths);
}

void catalog_bijectively_maps_eight_fat_tree_routes_to_two_part_tuples() {
    auto catalog = buildFatTreePrimeCatalog(80, 0, 8);
    assert(catalog->tierCount() == 2);
    std::set<std::vector<uint16_t>> seen;
    for (uint16_t i = 0; i < catalog->size(); ++i) {
        const auto& entry = catalog->entryForIndex(i);
        assert(entry.tuple.ports.size() == 2);
        assert(catalog->entryForEntropy(entry.entropy).catalog_index == i);
        assert(seen.insert(entry.tuple.ports).second);
        assert(entry.forward->reverse() == entry.reverse);
    }
}

void catalog_uses_local_uplink_namespaces_for_three_tier_tuples() {
    FatTreeTopologyCfg config(3, 16, speedFromGbps(100), memFromPkt(100),
                              timeFromUs(uint32_t{1}), 0, COMPOSITE, FAIR_PRIO);
    FatTreeTopology topology(&config, nullptr, &eventlist, nullptr);
    const auto catalog = PrimePathCatalog::build(takeBidirectionalPaths(topology, 8, 0), 0, 4);

    assert(catalog->tierCount() == 2);
    std::set<std::vector<uint16_t>> tuples;
    std::map<std::vector<uint16_t>, uint32_t> entropy_for_tuple;
    for (uint16_t index = 0; index < catalog->size(); ++index) {
        const PrimePathEntry& entry = catalog->entryForIndex(index);
        tuples.insert(entry.tuple.ports);
        entropy_for_tuple.emplace(entry.tuple.ports, entry.entropy);
    }
    assert((tuples == std::set<std::vector<uint16_t>>{{0, 0}, {0, 1}, {1, 0}, {1, 1}}));

    std::vector<uint16_t> mixed_radix_tuple{0, 0};
    for (uint16_t candidate = 0; candidate < 4; ++candidate) {
        const auto mapped = entropy_for_tuple.find(mixed_radix_tuple);
        assert(mapped != entropy_for_tuple.end());
        assert(catalog->entryForEntropy(mapped->second).tuple.ports == mixed_radix_tuple);
        ++mixed_radix_tuple.at(1);
        if (mixed_radix_tuple.at(1) == 2) {
            mixed_radix_tuple.at(1) = 0;
            ++mixed_radix_tuple.at(0);
        }
    }
}

void catalog_rejects_incomplete_cartesian_tuple_sets() {
    FatTreeTopologyCfg config(3, 128, speedFromGbps(100), memFromPkt(100),
                              timeFromUs(uint32_t{1}), 0, COMPOSITE, FAIR_PRIO);
    FatTreeTopology topology(&config, nullptr, &eventlist, nullptr);
    PrimeRoutePairs all_candidates = takeBidirectionalPaths(topology, 80, 0);
    PrimeRoutePairs incomplete;
    incomplete.push_back(std::move(all_candidates.at(0)));  // (0, 0)
    incomplete.push_back(std::move(all_candidates.at(1)));  // (0, 1)
    incomplete.push_back(std::move(all_candidates.at(4)));  // (1, 0)
    incomplete.push_back(std::move(all_candidates.at(8)));  // (2, 0)

    bool rejected = false;
    try {
        PrimePathCatalog::build(std::move(incomplete), 0, 4);
    } catch (const std::invalid_argument&) {
        rejected = true;
    }
    assert(rejected);
}

void catalog_rejects_non_power_of_two_path_requests() {
    FatTreeTopologyCfg config(2, 32, speedFromGbps(100), memFromPkt(100),
                              timeFromUs(uint32_t{1}), 0, COMPOSITE, FAIR_PRIO);
    FatTreeTopology topology(&config, nullptr, &eventlist, nullptr);

    bool rejected = false;
    try {
        PrimePathCatalog::build(takeBidirectionalPaths(topology, 0, 8), 0, 3);
    } catch (const std::invalid_argument&) {
        rejected = true;
    }
    assert(rejected);
}

void catalog_rejects_non_adjacent_fat_tree_tier_jumps() {
    FatTreeSwitch tor(eventlist, "tor", FatTreeSwitch::TOR, 0, 0, nullptr);
    FatTreeSwitch core(eventlist, "core", FatTreeSwitch::CORE, 0, 0, nullptr);
    Queue ingress_queue(speedFromGbps(100), memFromPkt(100), eventlist, nullptr);
    Queue direct_queue(speedFromGbps(100), memFromPkt(100), eventlist, nullptr);
    Queue egress_queue(speedFromGbps(100), memFromPkt(100), eventlist, nullptr);
    ingress_queue.setRemoteEndpoint(&tor);
    tor.addPort(&direct_queue);
    direct_queue.setRemoteEndpoint(&core);
    tor.addPort(&egress_queue);

    auto forward = std::make_unique<Route>();
    auto reverse = std::make_unique<Route>();
    forward->push_back(&ingress_queue);
    forward->push_back(&direct_queue);
    forward->push_back(&egress_queue);
    forward->set_reverse(reverse.get());
    reverse->set_reverse(forward.get());
    PrimeRoutePairs pairs;
    pairs.push_back({std::move(forward), std::move(reverse)});

    bool rejected = false;
    try {
        PrimePathCatalog::build(std::move(pairs), 0, 1);
    } catch (const std::invalid_argument&) {
        rejected = true;
    }
    assert(rejected);
}

void catalog_maps_two_tier_routes_to_unique_one_part_tuples() {
    FatTreeTopologyCfg config(2, 32, speedFromGbps(100), memFromPkt(100),
                              timeFromUs(uint32_t{1}), 0, COMPOSITE, FAIR_PRIO);
    FatTreeTopology topology(&config, nullptr, &eventlist, nullptr);
    const auto catalog = PrimePathCatalog::build(takeBidirectionalPaths(topology, 0, 8), 0, 4);

    assert(catalog->tierCount() == 1);
    std::set<std::vector<uint16_t>> seen;
    for (uint16_t index = 0; index < catalog->size(); ++index) {
        const PrimePathEntry& entry = catalog->entryForIndex(index);
        assert(entry.tuple.ports.size() == 1);
        assert(seen.insert(entry.tuple.ports).second);
        assert(catalog->entryForEntropy(entry.entropy).catalog_index == index);
        assert(entry.forward->reverse() == entry.reverse);
        assert(entry.reverse->reverse() == entry.forward);
    }
}

void catalog_owns_reciprocal_routes_with_appended_transport_endpoints() {
    TerminalSink destination("prime destination");
    TerminalSink source("prime source");
    std::shared_ptr<const PrimePathCatalog> catalog;
    {
        FatTreeTopologyCfg config(3, 128, speedFromGbps(100), memFromPkt(100),
                                  timeFromUs(uint32_t{1}), 0, COMPOSITE, FAIR_PRIO);
        FatTreeTopology topology(&config, nullptr, &eventlist, nullptr);
        PrimeRoutePairs candidates = takeBidirectionalPaths(topology, 80, 0);
        appendPrimeTransportEndpoints(candidates, destination, source);
        catalog = PrimePathCatalog::build(std::move(candidates), 0, 4);
    }

    const PrimePathEntry& entry = catalog->entryForIndex(0);
    assert(entry.forward->at(entry.forward->size() - 1) == &destination);
    assert(entry.reverse->at(entry.reverse->size() - 1) == &source);
    assert(entry.forward->reverse() == entry.reverse);
    assert(entry.reverse->reverse() == entry.forward);
}

void catalog_rejects_unexpected_queue_without_switch_data() {
    FatTreeTopologyCfg config(2, 32, speedFromGbps(100), memFromPkt(100),
                              timeFromUs(uint32_t{1}), 0, COMPOSITE, FAIR_PRIO);
    FatTreeTopology topology(&config, nullptr, &eventlist, nullptr);
    PrimeRoutePairs pairs = takeBidirectionalPaths(topology, 0, 8);
    pairs.at(0).forward->push_back(pairs.at(0).forward->at(0));

    bool rejected = false;
    try {
        PrimePathCatalog::build(std::move(pairs), 0, 1);
    } catch (const std::invalid_argument&) {
        rejected = true;
    }
    assert(rejected);
}

void catalog_rejects_duplicate_tuples() {
    FatTreeTopologyCfg config(2, 32, speedFromGbps(100), memFromPkt(100),
                              timeFromUs(uint32_t{1}), 0, COMPOSITE, FAIR_PRIO);
    FatTreeTopology topology(&config, nullptr, &eventlist, nullptr);
    PrimeRoutePairs pairs = takeBidirectionalPaths(topology, 0, 8);
    pairs.at(1).forward = std::unique_ptr<Route>(pairs.at(0).forward->clone());
    pairs.at(1).reverse = std::unique_ptr<Route>(pairs.at(0).reverse->clone());
    pairs.at(1).forward->set_reverse(pairs.at(1).reverse.get());
    pairs.at(1).reverse->set_reverse(pairs.at(1).forward.get());

    bool rejected = false;
    try {
        PrimePathCatalog::build(std::move(pairs), 0, 2);
    } catch (const std::invalid_argument&) {
        rejected = true;
    }
    assert(rejected);
}

void catalog_rejects_mixed_two_and_three_tier_candidates() {
    FatTreeTopologyCfg two_tier_config(2, 32, speedFromGbps(100), memFromPkt(100),
                                       timeFromUs(uint32_t{1}), 0, COMPOSITE, FAIR_PRIO);
    FatTreeTopologyCfg three_tier_config(3, 128, speedFromGbps(100), memFromPkt(100),
                                         timeFromUs(uint32_t{1}), 0, COMPOSITE, FAIR_PRIO);
    FatTreeTopology two_tier(&two_tier_config, nullptr, &eventlist, nullptr);
    FatTreeTopology three_tier(&three_tier_config, nullptr, &eventlist, nullptr);
    PrimeRoutePairs two_tier_pairs = takeBidirectionalPaths(two_tier, 0, 8);
    PrimeRoutePairs three_tier_pairs = takeBidirectionalPaths(three_tier, 80, 0);
    PrimeRoutePairs mixed;
    mixed.push_back(std::move(two_tier_pairs.at(0)));
    mixed.push_back(std::move(three_tier_pairs.at(0)));

    bool rejected = false;
    try {
        PrimePathCatalog::build(std::move(mixed), 0, 2);
    } catch (const std::invalid_argument&) {
        rejected = true;
    }
    assert(rejected);
}

void catalog_rejects_nonzero_planes() {
    FatTreeTopologyCfg config(2, 32, speedFromGbps(100), memFromPkt(100),
                              timeFromUs(uint32_t{1}), 0, COMPOSITE, FAIR_PRIO);
    FatTreeTopology topology(&config, nullptr, &eventlist, nullptr);

    bool rejected = false;
    try {
        PrimePathCatalog::build(takeBidirectionalPaths(topology, 0, 8), 1, 4);
    } catch (const std::invalid_argument&) {
        rejected = true;
    }
    assert(rejected);
}

void catalog_rejects_nonreciprocal_route_pairs() {
    PrimeRoutePairs pairs;
    pairs.push_back({std::make_unique<Route>(), std::make_unique<Route>()});

    bool rejected = false;
    try {
        PrimePathCatalog::build(std::move(pairs), 0, 1);
    } catch (const std::invalid_argument&) {
        rejected = true;
    }
    assert(rejected);
}

}  // namespace

int main() {
    catalog_bijectively_maps_eight_fat_tree_routes_to_two_part_tuples();
    catalog_uses_local_uplink_namespaces_for_three_tier_tuples();
    catalog_rejects_incomplete_cartesian_tuple_sets();
    catalog_rejects_non_power_of_two_path_requests();
    catalog_rejects_non_adjacent_fat_tree_tier_jumps();
    catalog_maps_two_tier_routes_to_unique_one_part_tuples();
    catalog_owns_reciprocal_routes_with_appended_transport_endpoints();
    catalog_rejects_unexpected_queue_without_switch_data();
    catalog_rejects_duplicate_tuples();
    catalog_rejects_mixed_two_and_three_tier_candidates();
    catalog_rejects_nonzero_planes();
    catalog_rejects_nonreciprocal_route_pairs();
}
