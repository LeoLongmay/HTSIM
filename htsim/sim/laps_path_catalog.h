#ifndef LAPS_PATH_CATALOG_H
#define LAPS_PATH_CATALOG_H

#include "config.h"

#include <cstdint>
#include <memory>
#include <vector>

class Route;

struct LapsPathEntry {
    uint16_t pid;
    uint32_t plane;
    const Route* forward;
    const Route* reverse;
    simtime_picosec uncongested_data_delay;
    simtime_picosec base_val;
    uint16_t switch_count;
};

class LapsPathCatalog {
public:
    static std::shared_ptr<const LapsPathCatalog> build(
        const std::vector<const Route*>& candidates, uint32_t plane,
        linkspeed_bps rate, mem_b data_packet_bytes, uint16_t requested_paths);

    const LapsPathEntry& entry(uint16_t pid) const;
    uint16_t size() const;

private:
    explicit LapsPathCatalog(std::vector<LapsPathEntry> entries);

    std::vector<LapsPathEntry> entries_;
};

#endif
