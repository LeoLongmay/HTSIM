// -*- c-basic-offset: 4; indent-tabs-mode: nil -*-
#ifndef MOTIVATION_TRACE_H
#define MOTIVATION_TRACE_H

#include <cstdint>
#include <fstream>
#include <string>

#include "uec_mp.h"

struct MotivationTraceConfig {
    std::string prefix;
    std::string run_id;
    std::string scenario;
    uint32_t seed = 0;
    int64_t flow_filter = -1;
};

struct MotivationAckRecord {
    uint64_t event_seq;
    uint64_t time_ps;
    uint64_t flow_id;
    uint64_t epoch_id;
    uint64_t acked_psn;
    uint32_t entropy;
    uint64_t physical_path_id;
    uint64_t raw_rtt_ps;
    uint64_t base_rtt_ps;
    int64_t qdelay_ps;
    bool ecn;
    bool genuine_sample;
    bool retransmitted;
    uint64_t forward_path_backlog_ps;
    std::string selection_source;
    uint64_t source_token_id;
    uint64_t newly_acked_bytes;
    uint64_t new_data_bytes_sent_total;
    uint64_t cwnd_bytes;
};

struct MotivationEpochRecord {
    uint64_t event_seq;
    uint64_t flow_id;
    uint64_t epoch_id;
    uint64_t start_ps;
    uint64_t end_ps;
    uint32_t sample_count;
    uint64_t raw_floor_ps;
    uint64_t raw_spread_ps;
    uint64_t smooth_floor_ps;
    uint64_t smooth_spread_ps;
    std::string observed_region;
    std::string actual_region;
    bool engaged;
    uint32_t entropy_coverage;
    uint32_t physical_path_coverage;
    uint64_t new_data_bytes_sent_total;
    uint64_t acked_bytes_total;
    uint64_t cwnd_bytes;
};

struct MotivationBackgroundRecord {
    uint64_t event_seq;
    uint64_t time_ps;
    uint32_t background_id;
    std::string operation;
    uint32_t src;
    uint32_t dst;
    uint32_t path_index;
    double configured_rate_gbps;
    uint64_t delivered_bytes;
    std::string queue_fingerprint;
};

struct MotivationPathRecord {
    uint64_t flow_id;
    uint32_t entropy;
    uint64_t physical_path_id;
    std::string resolution_status;
    std::string queue_fingerprint;
    double bottleneck_rate_gbps;
    bool contains_reduced_link;
    std::string ordered_queue_ids;
};

struct MotivationLinkRecord {
    uint64_t queue_id;
    std::string queue_name;
    double rate_gbps;
    bool reduced_speed;
};

struct MotivationCoordinationRecord {
    uint64_t event_seq;
    uint64_t time_ps;
    uint64_t flow_id;
    uint64_t epoch_id;
    uint64_t round_id;
    uint32_t cache_slot;
    uint64_t cache_generation;
    uint64_t floor_ps;
    uint64_t spread_ps;
    uint64_t spread_ref_ps;
    uint64_t residual_ps;
    std::string action;
    std::string reason;
    bool refresh_complete;
    bool progress;
    bool handoff;
    uint64_t cwnd_bytes;
    std::string control_state;
};

struct MotivationOutcomeRecord {
    uint64_t event_seq;
    uint64_t time_ps;
    uint64_t flow_id;
    uint64_t round_id;
    uint64_t window_ps;
    uint64_t pre_classified_bytes;
    uint64_t pre_harmful_bytes;
    double pre_exposure;
    uint64_t post1_classified_bytes;
    uint64_t post1_harmful_bytes;
    double post1_exposure;
    uint64_t post2_classified_bytes;
    uint64_t post2_harmful_bytes;
    double post2_exposure;
};

class MotivationTraceWriter {
public:
    MotivationTraceWriter() = default;
    ~MotivationTraceWriter();

    MotivationTraceWriter(const MotivationTraceWriter&) = delete;
    MotivationTraceWriter& operator=(const MotivationTraceWriter&) = delete;

    void configure(const MotivationTraceConfig& config);
    void configure(const std::string& prefix, const std::string& run_id,
                   const std::string& scenario, uint32_t seed, int64_t flow_filter);
    bool enabled() const { return _enabled; }
    bool enabledFor(uint64_t flow_id) const;
    uint64_t nextEventSeq();

    void logAck(const MotivationAckRecord& record);
    void logToken(uint64_t event_seq, uint64_t flow_id, uint64_t time_ps,
                  const UecMpTokenEvent& event);
    void logEpoch(const MotivationEpochRecord& record);
    void logBackground(const MotivationBackgroundRecord& record);
    void logPath(const MotivationPathRecord& record);
    void logLink(const MotivationLinkRecord& record);
    void logCoordination(const MotivationCoordinationRecord& record);
    void logOutcome(const MotivationOutcomeRecord& record);

    void close();

private:
    MotivationTraceConfig _config;
    bool _enabled = false;
    uint64_t _event_seq = 0;
    std::ofstream _ack;
    std::ofstream _token;
    std::ofstream _epoch;
    std::ofstream _background;
    std::ofstream _path;
    std::ofstream _link;
    std::ofstream _coordination;
    std::ofstream _outcome;
};

#endif
