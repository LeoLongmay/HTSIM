// -*- c-basic-offset: 4; indent-tabs-mode: nil -*-
#ifndef UEC_MP_H
#define UEC_MP_H

#include <cstdint>
#include <list>
#include <deque>
#include <functional>
#include <map>
#include <optional>
#include <random>
#include <set>
#include <string>
#include <vector>
#include "eventlist.h"
#include "buffer_reps.h"

struct UecMpCacheSlot {
    uint16_t slot = UINT16_MAX;
    uint64_t generation = 0;
    uint32_t entropy = 0;
    bool valid = false;
    bool ack_validated = false;
};

struct UecMpAdmission {
    uint16_t cache_slot = UINT16_MAX;
    uint64_t cache_generation = 0;
    uint32_t entropy = 0;
    bool written = false;
};

struct UecMpSelection {
    enum Source : uint8_t { UNKNOWN, RECYCLED, FIRST_WINDOW, RANDOM_EMPTY };
    static constexpr uint64_t NO_TOKEN = UINT64_MAX;
    uint32_t entropy = 0;
    Source source = UNKNOWN;
    uint64_t token_id = NO_TOKEN;
    uint16_t cache_slot = UINT16_MAX;
    uint64_t cache_generation = 0;
};

struct UecMpTokenEvent {
    enum Operation : uint8_t {
        ENQUEUE_GOOD_ACK,
        OVERWRITE_GOOD_ACK,
        REJECT_HIGH_RESIDUAL,
        DEQUEUE_RECYCLE,
        SELECT_FIRST_WINDOW,
        SELECT_RANDOM_EMPTY
    };
    static constexpr uint64_t NO_EVENT = UINT64_MAX;
    Operation operation;
    uint64_t token_id;
    uint32_t entropy;
    uint32_t queue_depth_before;
    uint32_t queue_depth_after;
    uint64_t related_ack_event_seq = NO_EVENT;
    uint16_t cache_slot = UINT16_MAX;
    uint64_t cache_generation = 0;
    bool admission_written = false;
};

struct UecMpLapsSignal {
    bool ready = false;
    bool all_paths_high = false;
    uint16_t sampled_paths = 0;
    simtime_picosec threshold = 0;
    simtime_picosec max_real_latency = 0;
};

class UecMultipath {
public:
    enum PathFeedback {PATH_GOOD, PATH_GOOD_HIGH_RESIDUAL, PATH_ECN, PATH_NACK, PATH_TIMEOUT};
    enum EvDefaults {UNKNOWN_EV};
    UecMultipath(bool debug): _debug(debug), _debug_tag("") {};
    virtual ~UecMultipath() {};
    virtual void set_debug_tag(string debug_tag) { _debug_tag = debug_tag; };
    /**
     * @param uint32_t path_id The path ID/entropy value as received by ACK/NACK
     * @param PathFeedback path_id The ACK/NACK response
     */
    virtual void processEv(uint32_t path_id, PathFeedback feedback) = 0;
    /**
     * @param uint64_t seq_sent The sequence number to be sent
     * @param uint64_t cur_cwnd_in_pkts The current congestion window in packets.
     */
    virtual uint32_t nextEntropy(uint64_t seq_sent, uint64_t cur_cwnd_in_pkts) = 0;
    using TokenObserver = std::function<void(const UecMpTokenEvent&)>;
    virtual UecMpSelection lastSelection() const { return {}; }
    virtual std::vector<UecMpCacheSlot> cacheSlots() const { return {}; }
    virtual bool invalidateCacheSlot(uint16_t, uint64_t) { return false; }
    virtual bool reserveCacheSlot(uint16_t, uint64_t) { return false; }
    virtual void clearReservedCacheSlots() {}
    virtual UecMpAdmission lastAdmission() const { return {}; }
    virtual bool isFrozen() const { return false; }
    virtual void setTokenObserver(TokenObserver) {}
    virtual void setFeedbackTraceContext(uint64_t) {}
    virtual void observeLapsDelay(uint32_t, simtime_picosec, simtime_picosec) {}
    virtual void observeLapsProbe(uint32_t, simtime_picosec, simtime_picosec) {}
    virtual optional<uint32_t> nextLapsProbeEntropy(simtime_picosec) { return {}; }
    virtual UecMpLapsSignal lapsSignal(simtime_picosec, simtime_picosec) const { return {}; }
protected:
    bool _debug;
    string _debug_tag;
};

class UecMpOblivious : public UecMultipath {
public:
    UecMpOblivious(uint16_t no_of_paths, bool debug);
    void processEv(uint32_t path_id, PathFeedback feedback) override;
    uint32_t nextEntropy(uint64_t seq_sent, uint64_t cur_cwnd_in_pkts) override;
private:
    uint16_t _no_of_paths;       // must be a power of 2
    uint16_t _path_random;       // random upper bits of EV, set at startup and never changed
    uint16_t _path_xor;          // random value set each time we wrap the entropy values - XOR with
                                 // _current_ev_index
    uint16_t _current_ev_index;  // count through _no_of_paths and then wrap.  XOR with _path_xor to
};

class UecMpLaps : public UecMultipath {
public:
    UecMpLaps(uint16_t no_of_paths, bool debug, double beta);
    void processEv(uint32_t path_id, PathFeedback feedback) override;
    uint32_t nextEntropy(uint64_t seq_sent, uint64_t cur_cwnd_in_pkts) override;
    void observeLapsDelay(uint32_t path_id, simtime_picosec delay,
                          simtime_picosec now) override;
    void observeLapsProbe(uint32_t path_id, simtime_picosec delay,
                          simtime_picosec now) override;
    optional<uint32_t> nextLapsProbeEntropy(simtime_picosec now) override;
    UecMpLapsSignal lapsSignal(simtime_picosec now,
                               simtime_picosec queue_margin) const override;
private:
    struct LapsPathState {
        bool valid = false;
        simtime_picosec base_latency = 0;
        simtime_picosec real_latency = 0;
        simtime_picosec observed_latency = 0;
        simtime_picosec last_update = 0;
        simtime_picosec last_probe = 0;
    };

    uint32_t pathIndex(uint32_t entropy) const;
    uint32_t entropyForPath(uint32_t path_id) const;
    bool isStale(const LapsPathState& state, simtime_picosec now) const;
    bool isControllerStale(const LapsPathState& state, simtime_picosec now) const;
    void observe(uint32_t path_id, simtime_picosec delay, simtime_picosec now);

    uint16_t _no_of_paths;
    uint16_t _path_random;
    uint32_t _bootstrap_path;
    uint32_t _next_stale_probe;
    double _beta;
    vector<LapsPathState> _paths;
};

class UecMpBitmap : public UecMultipath {
public:
    UecMpBitmap(uint16_t no_of_paths, bool debug);
    void processEv(uint32_t path_id, PathFeedback feedback) override;
    uint32_t nextEntropy(uint64_t seq_sent, uint64_t cur_cwnd_in_pkts) override;
private:
    uint16_t _no_of_paths;       // must be a power of 2
    uint16_t _path_random;       // random upper bits of EV, set at startup and never changed
    uint16_t _path_xor;          // random value set each time we wrap the entropy values - XOR with
                                 // _current_ev_index
    uint16_t _current_ev_index;  // count through _no_of_paths and then wrap.  XOR with _path_xor to
    vector<uint8_t> _ev_skip_bitmap;  // paths scores for load balancing

    uint16_t _ev_skip_count;
    uint8_t _max_penalty;             // max value we allow in _path_penalties (typically 1 or 2).
};

class UecMpRepsLegacy : public UecMultipath {
public:
    UecMpRepsLegacy(uint16_t no_of_paths, bool debug);
    void processEv(uint32_t path_id, PathFeedback feedback) override;
    uint32_t nextEntropy(uint64_t seq_sent, uint64_t cur_cwnd_in_pkts) override;
    optional<uint32_t> nextEntropyRecycle();
    UecMpSelection lastSelection() const override { return _last_selection; }
    void setTokenObserver(TokenObserver observer) override { _token_observer = observer; }
    void setFeedbackTraceContext(uint64_t feedback_event_seq) override { _feedback_event_seq = feedback_event_seq; }
private:
    struct Token { uint32_t entropy; uint64_t id; };
    uint16_t _no_of_paths;
    uint32_t _crt_path;
    list<Token> _next_tokens;
    uint64_t _next_token_id = 0;
    uint64_t _feedback_event_seq = UecMpTokenEvent::NO_EVENT;
    UecMpSelection _last_selection;
    TokenObserver _token_observer;
};


class UecMpReps : public UecMultipath {
public:
    UecMpReps(uint16_t no_of_paths, bool debug, bool is_trimming_enabled);
    void processEv(uint32_t path_id, PathFeedback feedback) override;
    uint32_t nextEntropy(uint64_t seq_sent, uint64_t cur_cwnd_in_pkts) override;
    UecMpSelection lastSelection() const override { return _last_selection; }
    std::vector<UecMpCacheSlot> cacheSlots() const override;
    bool invalidateCacheSlot(uint16_t slot, uint64_t generation) override;
    bool reserveCacheSlot(uint16_t slot, uint64_t generation) override;
    void clearReservedCacheSlots() override;
    UecMpAdmission lastAdmission() const override { return _last_admission; }
    bool isFrozen() const override;
    void setTokenObserver(TokenObserver observer) override { _token_observer = observer; }
    void setFeedbackTraceContext(uint64_t feedback_event_seq) override {
        _feedback_event_seq = feedback_event_seq;
    }
private:
    uint16_t _no_of_paths;
    CircularBufferREPS<uint16_t> *circular_buffer_reps;
    uint32_t _crt_path;
    list<uint32_t> _next_pathid;
    bool _is_trimming_enabled = true;  // whether to trim the circular buffer
    uint64_t _feedback_event_seq = UecMpTokenEvent::NO_EVENT;
    UecMpSelection _last_selection;
    UecMpAdmission _last_admission;
    TokenObserver _token_observer;
};

class UecMpMixed : public UecMultipath {
public:
    UecMpMixed(uint16_t no_of_paths, bool debug);
    void processEv(uint32_t path_id, PathFeedback feedback) override;
    uint32_t nextEntropy(uint64_t seq_sent, uint64_t cur_cwnd_in_pkts) override;
    void set_debug_tag(string debug_tag) override;
private:
    UecMpBitmap _bitmap;
    UecMpRepsLegacy _reps_legacy;
};

class UecMpEcmp : public UecMultipath {
public:
    UecMpEcmp(uint16_t no_of_paths, bool debug);
    void processEv(uint32_t path_id, PathFeedback feedback) override;
    uint32_t nextEntropy(uint64_t seq_sent, uint64_t cur_cwnd_in_pkts) override;
private:
    uint32_t _crt_path;
};

class UecMpSource : public UecMultipath {
public:
    enum class Strategy { RANDOM, ECMP, OPS, FLICR, FLOW_V1, FLOW_V2 };

    struct SpritzConfig {
        int explore_threshold = 10;
        int ecn_threshold = 8;
        int weight_scaling = 1;
        bool sort_buffer_insert = false;
        bool small_flows_bias = false;
        mem_b small_flows_threshold = 524288;
        double small_flows_weight = 10.0;
    };

    UecMpSource(const string& base_host_table_path,
                uint32_t src,
                uint32_t dst,
                uint32_t hosts_per_switch,
                bool debug);
    UecMpSource(const string& base_host_table_path,
                uint32_t src,
                uint32_t dst,
                uint32_t hosts_per_switch,
                Strategy strategy,
                const SpritzConfig& config,
                simtime_picosec base_rtt,
                mem_b flow_size,
                bool debug);
    void processEv(uint32_t path_id, PathFeedback feedback) override;
    uint32_t nextEntropy(uint64_t seq_sent, uint64_t cur_cwnd_in_pkts) override;
private:
    using FlowPair = std::pair<uint32_t, uint32_t>;

    void load_paths(const string& base_host_table_path,
                    uint32_t src,
                    uint32_t dst,
                    uint32_t hosts_per_switch);
    void update_weighted_dist();
    uint32_t stable_hash(uint32_t a, uint32_t b) const;

    Strategy _strategy;
    SpritzConfig _config;
    FlowPair _flow_pair;
    vector<uint32_t> _paths;
    std::map<uint32_t, size_t> _path_index_map;
    std::vector<double> _weights;
    std::mt19937 _rng;
    std::uniform_int_distribution<size_t> _dist;
    std::discrete_distribution<size_t> _dist_weighted;
    simtime_picosec _base_rtt;
    mem_b _flow_size;
    int _packet_count;
    int _ecn_count;
    bool _first_rtt;
    simtime_picosec _last_timestamp;
    std::map<FlowPair, int> _ecn_counts;

    static std::map<FlowPair, simtime_picosec> _last_ack_timestamp;
    static std::map<FlowPair, std::deque<uint32_t>> _good_paths;
    static std::map<FlowPair, std::set<uint32_t>> _bad_paths;
};

#endif  // UEC_MP_H
