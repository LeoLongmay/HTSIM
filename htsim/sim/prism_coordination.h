#ifndef PRISM_COORDINATION_H
#define PRISM_COORDINATION_H

#include <cstdint>
#include <map>
#include <set>
#include <string>
#include <vector>

#include "config.h"
#include "prism_decompose.h"
#include "uec_mp.h"

enum class PrismCoordinationMode { DISABLED, ORIGINAL_PRISM, PRISM_RECYCLE, FULL_PRISM };
enum class PrismCoordinationAction { RETAIN, INVALIDATE, PENDING,
                                    ROUND_COMPLETE_PROGRESS, ROUND_COMPLETE_HANDOFF,
                                    ROUND_COMPLETE_RETRY, ROUND_COMPLETE_CLEAN };

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
    simtime_picosec residual_ps;
    std::string reason;
};

struct PrismCoordinationResult {
    uint64_t round_id = 0;
    simtime_picosec spread_ref_ps = 0;
    std::vector<PrismCoordinationAction> actions;
    std::vector<PrismCoordinationSlotAction> slot_actions;
    std::vector<uint16_t> retained_slots;
    std::vector<uint16_t> invalidated_slots;
    std::vector<uint16_t> pending_slots;
    bool round_complete = false;
    bool progress = false;
    bool handoff_requested = false;
};

bool applyPrismNoProgressHandoff(mem_b& cwnd, mem_b min_cwnd);

class PrismResidualCoordinator {
public:
    PrismResidualCoordinator(PrismCoordinationMode mode, simtime_picosec t_cc,
                             simtime_picosec t_spray);

    void observeAck(uint64_t epoch_id, uint16_t slot, uint64_t generation,
                    simtime_picosec qdelay, bool ecn, bool genuine);
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

    struct ObservationKey {
        uint64_t epoch_id;
        SlotGeneration slot_generation;

        bool operator<(const ObservationKey& other) const {
            return epoch_id != other.epoch_id ? epoch_id < other.epoch_id
                                               : slot_generation < other.slot_generation;
        }
    };

    bool enabled() const;
    void resetRound();
    void addSlotAction(PrismCoordinationResult& result, const UecMpCacheSlot& slot,
                       PrismCoordinationAction action, simtime_picosec residual_ps,
                       const char* reason) const;

    PrismCoordinationMode _mode;
    simtime_picosec _t_cc;
    simtime_picosec _t_spray;
    bool _round_active = false;
    bool _round_had_invalidation = false;
    uint64_t _round_id = 0;
    simtime_picosec _spread_ref = 0;
    std::set<uint16_t> _round_slots;
    std::set<uint16_t> _completed_slots;
    std::map<uint16_t, uint64_t> _invalidated_generations;
    std::map<ObservationKey, Observation> _observations;
};

#endif  // PRISM_COORDINATION_H
