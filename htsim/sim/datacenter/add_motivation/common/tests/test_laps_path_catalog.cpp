#include "laps_path_catalog.h"
#include "datacenter/fat_tree_topology.h"
#include "uec.h"

#include <cassert>
#include <memory>
#include <vector>

namespace {

EventList eventlist;

LapsRoutePairs takeBidirectionalPaths(FatTreeTopology& topology, uint32_t src, uint32_t dst) {
    std::unique_ptr<std::vector<const Route*>> paths(topology.get_bidir_paths(src, dst, true));
    LapsRoutePairs pairs;
    pairs.reserve(paths->size());
    for (const Route* forward : *paths) {
        Route* mutable_forward = const_cast<Route*>(forward);
        pairs.push_back({std::unique_ptr<Route>(mutable_forward),
                         std::unique_ptr<Route>(
                             mutable_forward == nullptr ? nullptr
                                                        : const_cast<Route*>(mutable_forward->reverse()))});
    }
    return pairs;
}

std::shared_ptr<const LapsPathCatalog> makeKnownCatalog(linkspeed_bps rate,
                                                        mem_b data_packet_bytes) {
    FatTreeTopologyCfg config(3, 16, rate, memFromPkt(100), timeFromUs(uint32_t{1}),
                              0, COMPOSITE, FAIR_PRIO);
    FatTreeTopology topology(&config, nullptr, &eventlist, nullptr);
    return LapsPathCatalog::build(takeBidirectionalPaths(topology, 0, 15), 0, rate,
                                  data_packet_bytes, 4);
}

void catalog_assigns_stable_pid_and_reverse_route() {
    const linkspeed_bps rate = speedFromGbps(100);
    FatTreeTopologyCfg config(3, 16, rate, memFromPkt(100), timeFromUs(uint32_t{1}), 0,
                              COMPOSITE, FAIR_PRIO);
    FatTreeTopology topology(&config, nullptr, &eventlist, nullptr);
    const auto catalog = LapsPathCatalog::build(takeBidirectionalPaths(topology, 0, 15), 0,
                                                rate, 1500, 4);

    assert(catalog->size() == 4);
    for (uint16_t pid = 0; pid < 4; ++pid) {
        const auto& entry = catalog->entry(pid);
        assert(entry.pid == pid);
        assert(entry.forward->reverse() == entry.reverse);
        assert(entry.reverse->reverse() == entry.forward);
    }
}

void catalog_owns_selected_route_pairs_after_candidate_container_is_destroyed() {
    const linkspeed_bps rate = speedFromGbps(100);
    std::shared_ptr<const LapsPathCatalog> catalog;
    {
        FatTreeTopologyCfg config(3, 16, rate, memFromPkt(100), timeFromUs(uint32_t{1}), 0,
                                  COMPOSITE, FAIR_PRIO);
        FatTreeTopology topology(&config, nullptr, &eventlist, nullptr);
        catalog = LapsPathCatalog::build(takeBidirectionalPaths(topology, 0, 15), 0, rate,
                                         1500, 4);
    }

    const auto& entry = catalog->entry(0);
    assert(entry.forward->reverse() == entry.reverse);
    assert(entry.reverse->reverse() == entry.forward);
}

void non_laps_sink_does_not_retain_a_path_catalog() {
    UecSrc::_sender_cc_algo = UecSrc::LAPS;
    UecNIC nic(0, eventlist, speedFromGbps(100), 1);
    UecSrc non_laps_source(nullptr, eventlist, std::make_unique<UecMpEcmp>(1, false), nic, 1);
    UecSink sink(nullptr, nullptr, nic, 1);
    auto catalog = makeKnownCatalog(speedFromGbps(100), 1500);
    std::weak_ptr<const LapsPathCatalog> observed_catalog = catalog;

    sink.lapsSetPathCatalog(non_laps_source, 0, catalog);
    catalog.reset();

    assert(observed_catalog.expired());
}

void catalog_baseline_has_five_packet_margin_per_switch() {
    const linkspeed_bps rate = speedFromGbps(100);
    const auto catalog = makeKnownCatalog(rate, 1500);
    const auto& entry = catalog->entry(0);
    const simtime_picosec serialization_delay =
        static_cast<simtime_picosec>((1500 * 8 * timeFromSec(1.0)) / rate);
    assert(entry.base_val == entry.uncongested_data_delay +
               5 * entry.switch_count * serialization_delay);
}

}  // namespace

int main() {
    catalog_assigns_stable_pid_and_reverse_route();
    catalog_baseline_has_five_packet_margin_per_switch();
    catalog_owns_selected_route_pairs_after_candidate_container_is_destroyed();
    non_laps_sink_does_not_retain_a_path_catalog();
}
