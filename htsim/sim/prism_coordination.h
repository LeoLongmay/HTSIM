#ifndef PRISM_COORDINATION_H
#define PRISM_COORDINATION_H

#include <cstdint>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <vector>

#include "config.h"
#include "prism_decompose.h"
#include "uec_mp.h"

enum class PrismCoordinationMode {
    DISABLED,
    ORIGINAL_PRISM,
    PRISM_RECYCLE,
    FULL_PRISM,
    OUTCOME_RECYCLE,
};
enum class PrismCoordinationAction { RETAIN, INVALIDATE, PENDING, RESERVE,
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

struct PrismOutcomeWindow {
    simtime_picosec start_ps = 0;
    simtime_picosec end_ps = 0;
    uint64_t classified_bytes = 0;
    uint64_t harmful_bytes = 0;
    double exposure = 0.0;
};

struct PrismOutcome {
    uint64_t round_id = 0;
    simtime_picosec window_ps = 0;
    PrismOutcomeWindow pre;
    PrismOutcomeWindow post1;
    PrismOutcomeWindow post2;
};

bool applyPrismNoProgressHandoff(mem_b& cwnd, mem_b min_cwnd);

class PrismResidualCoordinator {
public:
    PrismResidualCoordinator(PrismCoordinationMode mode, simtime_picosec t_cc,
                             simtime_picosec t_spray, simtime_picosec base_rtt = 0);

    void observeAck(uint64_t epoch_id, uint16_t slot, uint64_t generation,
                    simtime_picosec qdelay, bool ecn, bool genuine);
    void observeReplacementReservation(uint16_t slot, uint64_t generation);
    void observeConsumedHighResidual(uint64_t epoch_id, uint16_t slot,
                                     uint64_t generation, uint32_t entropy,
                                     simtime_picosec residual_ps);
    bool observeReplacementAdmission(uint16_t slot, uint64_t generation);
    bool isOutcomeReplacement(uint16_t slot, uint64_t generation) const;
    void observeReplacementReuse(uint16_t slot, uint64_t generation,
                                 simtime_picosec residual_ps, bool ecn, bool genuine,
                                 simtime_picosec timestamp);
    void observeClassifiedAck(simtime_picosec timestamp, simtime_picosec residual_ps,
                              bool ecn, bool genuine, uint64_t acked_bytes);
    void setOutcomeBaseRtt(simtime_picosec base_rtt);
    bool outcomeTracking() const;
    bool outcomeReplacementsValidated() const;
    std::optional<PrismOutcome> takeOutcome();
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

    struct ReplacementState {
        uint64_t invalidated_generation = 0;
        uint64_t replacement_generation = 0;
        bool admitted = false;
        bool reuse_validated = false;
    };

    struct OutcomeBucket {
        simtime_picosec start = 0;
        uint64_t classified_bytes = 0;
        uint64_t harmful_bytes = 0;
    };

    struct ConsumedHighResidual {
        uint32_t entropy = 0;
        simtime_picosec residual_ps = 0;
    };

    bool enabled() const;
    bool outcomeEnabled() const;
    void beginOutcomeReplacement(uint16_t slot, uint64_t generation);
    void resetOutcomeValidationProgress();
    void resetOutcomeState();
    void observeOutcomeBaseline(simtime_picosec timestamp, simtime_picosec residual_ps,
                                bool ecn, uint64_t acked_bytes);
    void completeOutcomeBucket(const OutcomeBucket& bucket);
    void snapshotOutcomePre(simtime_picosec timestamp);
    PrismOutcomeWindow makeOutcomeWindow(const OutcomeBucket& bucket) const;
    void resetRound(bool reset_outcome = true);
    void addSlotAction(PrismCoordinationResult& result, const UecMpCacheSlot& slot,
                       PrismCoordinationAction action, simtime_picosec residual_ps,
                       const char* reason) const;

    PrismCoordinationMode _mode;
    simtime_picosec _t_cc;
    simtime_picosec _t_spray;
    simtime_picosec _outcome_window_ps;
    bool _round_active = false;
    bool _round_had_invalidation = false;
    uint64_t _round_id = 0;
    simtime_picosec _spread_ref = 0;
    std::set<uint16_t> _round_slots;
    std::set<uint16_t> _completed_slots;
    std::map<uint16_t, uint64_t> _invalidated_generations;
    std::map<ObservationKey, Observation> _observations;
    std::map<uint16_t, ReplacementState> _outcome_replacements;
    std::map<ObservationKey, ConsumedHighResidual> _outcome_consumed_high_residuals;
    bool _outcome_tracking = false;
    bool _outcome_replacements_validated = false;
    std::optional<OutcomeBucket> _outcome_baseline_bucket;
    std::optional<OutcomeBucket> _outcome_active_bucket;
    std::optional<OutcomeBucket> _outcome_last_pre_bucket;
    std::optional<PrismOutcomeWindow> _outcome_pre;
    std::optional<PrismOutcomeWindow> _outcome_post1;
    std::optional<PrismOutcomeWindow> _outcome_post2;
    std::optional<PrismOutcome> _outcome_event;
};

#endif  // PRISM_COORDINATION_H
