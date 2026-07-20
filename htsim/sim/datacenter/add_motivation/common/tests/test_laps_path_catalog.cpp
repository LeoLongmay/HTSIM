#include "laps_path_catalog.h"
#include "datacenter/fat_tree_topology.h"

#include <cassert>
#include <memory>
#include <vector>

namespace {

EventList eventlist;

std::shared_ptr<const LapsPathCatalog> makeKnownCatalog(linkspeed_bps rate,
                                                        mem_b data_packet_bytes) {
    FatTreeTopologyCfg config(3, 16, rate, memFromPkt(100), timeFromUs(uint32_t{1}),
                              0, COMPOSITE, FAIR_PRIO);
    FatTreeTopology topology(&config, nullptr, &eventlist, nullptr);
    std::unique_ptr<std::vector<const Route*>> paths(topology.get_bidir_paths(0, 15, true));
    return LapsPathCatalog::build(*paths, 0, rate, data_packet_bytes, 4);
}

void catalog_assigns_stable_pid_and_reverse_route() {
    const linkspeed_bps rate = speedFromGbps(100);
    FatTreeTopologyCfg config(3, 16, rate, memFromPkt(100), timeFromUs(uint32_t{1}), 0,
                              COMPOSITE, FAIR_PRIO);
    FatTreeTopology topology(&config, nullptr, &eventlist, nullptr);
    std::unique_ptr<std::vector<const Route*>> paths(topology.get_bidir_paths(0, 15, true));
    const auto catalog = LapsPathCatalog::build(*paths, 0, rate, 1500, 4);

    assert(catalog->size() == 4);
    for (uint16_t pid = 0; pid < 4; ++pid) {
        const auto& entry = catalog->entry(pid);
        assert(entry.pid == pid);
        assert(entry.forward->reverse() == entry.reverse);
        assert(entry.reverse->reverse() == entry.forward);
    }
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
}
