#ifndef PRISM_COORDINATION_H
#define PRISM_COORDINATION_H

#include <cstdint>
#include <map>
#include <set>
#include <vector>

#include "config.h"
#include "prism_decompose.h"
#include "uec_mp.h"

enum class PrismCoordinationMode { DISABLED, ORIGINAL_PRISM, PRISM_RECYCLE, FULL_PRISM };
enum class PrismCoordinationAction { RETAIN, INVALIDATE, PENDING,
                                    ROUND_COMPLETE_PROGRESS, ROUND_COMPLETE_HANDOFF };

struct PrismCoordinationEpoch {
    uint64_t epoch_id;
    simtime_picosec floor;
    simtime_picosec spread;
    prism::Region region;
    bool frozen;
    std::vector<UecMpCacheSlot> slots;
};

struct PrismCoordinationSlotAction {
    uint16_t slot;
    uint64_t generation;
    PrismCoordinationAction action;
};

struct PrismCoordinationResult {
    std::vector<PrismCoordinationAction> actions;
    std::vector<PrismCoordinationSlotAction> slot_actions;
    std::vector<uint16_t> retained_slots;
    std::vector<uint16_t> invalidated_slots;
    std::vector<uint16_t> pending_slots;
    bool round_complete = false;
    bool progress = false;
    bool handoff = false;
};

class PrismResidualCoordinator {
public:
    PrismResidualCoordinator(PrismCoordinationMode mode, simtime_picosec threshold);

    void observeAck(uint16_t slot, uint64_t generation, simtime_picosec qdelay,
                    bool ecn, bool genuine);
    PrismCoordinationResult closeEpoch(const PrismCoordinationEpoch& epoch);

private:
    struct SlotGeneration {
        uint16_t slot;
        uint64_t generation;

        bool operator<(const SlotGeneration& other) const {
            return slot != other.slot ? slot < other.slot : generation < other.generation;
        }
    };

    struct Observation {
        simtime_picosec qdelay;
        bool ecn;
    };

    bool enabled() const;
    void resetRound();
    void addSlotAction(PrismCoordinationResult& result, const UecMpCacheSlot& slot,
                       PrismCoordinationAction action) const;

    PrismCoordinationMode _mode;
    simtime_picosec _threshold;
    bool _round_active = false;
    simtime_picosec _spread_ref = 0;
    std::set<SlotGeneration> _completed;
    std::map<SlotGeneration, Observation> _observations;
};

#endif  // PRISM_COORDINATION_H
