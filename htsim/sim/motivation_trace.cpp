// -*- c-basic-offset: 4; indent-tabs-mode: nil -*-
#include "motivation_trace.h"

#include <array>
#include <stdexcept>
#include <utility>

namespace {

constexpr uint32_t kSchemaVersion = 1;

void validateCsvIdentity(const std::string& name, const std::string& value) {
    if (value.find_first_of(",\r\n") != std::string::npos) {
        throw std::invalid_argument(name + " must not contain commas or newlines");
    }
}

void openCsv(std::ofstream& stream, const std::string& path) {
    stream.open(path, std::ios::out | std::ios::trunc);
    if (!stream.is_open()) {
        throw std::runtime_error("failed to open motivation trace: " + path);
    }
}

std::pair<const char*, const char*> tokenOperation(UecMpTokenEvent::Operation operation) {
    switch (operation) {
    case UecMpTokenEvent::ENQUEUE_GOOD_ACK:
        return {"enqueue_good_ack", "good_ack"};
    case UecMpTokenEvent::DEQUEUE_RECYCLE:
        return {"dequeue_recycle", "recycle"};
    case UecMpTokenEvent::SELECT_FIRST_WINDOW:
        return {"select_first_window", "first_window"};
    case UecMpTokenEvent::SELECT_RANDOM_EMPTY:
        return {"select_random_empty", "random_empty"};
    }
    throw std::invalid_argument("unknown UEC multipath token operation");
}

}  // namespace

MotivationTraceWriter::~MotivationTraceWriter() {
    close();
}

void MotivationTraceWriter::configure(const std::string& prefix, const std::string& run_id,
                                      const std::string& scenario, uint32_t seed,
                                      int64_t flow_filter) {
    configure({prefix, run_id, scenario, seed, flow_filter});
}

void MotivationTraceWriter::configure(const MotivationTraceConfig& config) {
    close();
    _config = config;
    _event_seq = 0;

    if (_config.prefix.empty()) {
        return;
    }

    validateCsvIdentity("run_id", _config.run_id);
    validateCsvIdentity("scenario", _config.scenario);

    try {
        openCsv(_ack, _config.prefix + ".ack.csv");
        openCsv(_token, _config.prefix + ".token.csv");
        openCsv(_epoch, _config.prefix + ".epoch.csv");
        openCsv(_path, _config.prefix + ".pathmap.csv");
        openCsv(_link, _config.prefix + ".linkmap.csv");
    } catch (...) {
        close();
        throw;
    }

    _ack << "schema_version,run_id,seed,scenario,event_seq,time_ps,flow_id,epoch_id,acked_psn,"
            "entropy,physical_path_id,raw_rtt_ps,base_rtt_ps,qdelay_ps,ecn,genuine_sample,"
            "retransmitted,forward_path_backlog_ps,selection_source,source_token_id\n";
    _token << "schema_version,run_id,event_seq,time_ps,flow_id,operation,reason,token_id,entropy,"
              "queue_depth_before,queue_depth_after,related_ack_event_seq\n";
    _epoch << "schema_version,run_id,event_seq,flow_id,epoch_id,start_ps,end_ps,sample_count,"
              "raw_floor_ps,raw_spread_ps,smooth_floor_ps,smooth_spread_ps,observed_region,"
              "actual_region,engaged,entropy_coverage,physical_path_coverage\n";
    _path << "schema_version,run_id,flow_id,entropy,physical_path_id,resolution_status,"
             "queue_fingerprint,bottleneck_rate_gbps,contains_reduced_link,ordered_queue_ids\n";
    _link << "schema_version,run_id,queue_id,queue_name,rate_gbps,reduced_speed\n";
    _enabled = true;
}

bool MotivationTraceWriter::enabledFor(uint64_t flow_id) const {
    return _enabled &&
           (_config.flow_filter < 0 || static_cast<uint64_t>(_config.flow_filter) == flow_id);
}

uint64_t MotivationTraceWriter::nextEventSeq() {
    return _event_seq++;
}

void MotivationTraceWriter::logAck(const MotivationAckRecord& record) {
    if (!_enabled) {
        return;
    }
    _ack << kSchemaVersion << ',' << _config.run_id << ',' << _config.seed << ','
         << _config.scenario << ',' << record.event_seq << ',' << record.time_ps << ','
         << record.flow_id << ',' << record.epoch_id << ',' << record.acked_psn << ','
         << record.entropy << ',' << record.physical_path_id << ',' << record.raw_rtt_ps << ','
         << record.base_rtt_ps << ',' << record.qdelay_ps << ',' << record.ecn << ','
         << record.genuine_sample << ',' << record.retransmitted << ','
         << record.forward_path_backlog_ps << ',' << record.selection_source << ','
         << record.source_token_id << '\n';
}

void MotivationTraceWriter::logToken(uint64_t event_seq, uint64_t flow_id, uint64_t time_ps,
                                     const UecMpTokenEvent& event) {
    if (!_enabled) {
        return;
    }
    const auto operation = tokenOperation(event.operation);
    _token << kSchemaVersion << ',' << _config.run_id << ',' << event_seq << ',' << time_ps << ','
           << flow_id << ',' << operation.first << ',' << operation.second << ',' << event.token_id
           << ',' << event.entropy << ',' << event.queue_depth_before << ','
           << event.queue_depth_after << ',' << event.related_ack_event_seq << '\n';
}

void MotivationTraceWriter::logEpoch(const MotivationEpochRecord& record) {
    if (!_enabled) {
        return;
    }
    _epoch << kSchemaVersion << ',' << _config.run_id << ',' << record.event_seq << ','
           << record.flow_id << ',' << record.epoch_id << ',' << record.start_ps << ','
           << record.end_ps << ',' << record.sample_count << ',' << record.raw_floor_ps << ','
           << record.raw_spread_ps << ',' << record.smooth_floor_ps << ','
           << record.smooth_spread_ps << ',' << record.observed_region << ','
           << record.actual_region << ',' << record.engaged << ',' << record.entropy_coverage << ','
           << record.physical_path_coverage << '\n';
}

void MotivationTraceWriter::logPath(const MotivationPathRecord& record) {
    if (!_enabled) {
        return;
    }
    _path << kSchemaVersion << ',' << _config.run_id << ',' << record.flow_id << ','
          << record.entropy << ',' << record.physical_path_id << ',' << record.resolution_status
          << ',' << record.queue_fingerprint << ',' << record.bottleneck_rate_gbps << ','
          << record.contains_reduced_link << ',' << record.ordered_queue_ids << '\n';
}

void MotivationTraceWriter::logLink(const MotivationLinkRecord& record) {
    if (!_enabled) {
        return;
    }
    _link << kSchemaVersion << ',' << _config.run_id << ',' << record.queue_id << ','
          << record.queue_name << ',' << record.rate_gbps << ',' << record.reduced_speed << '\n';
}

void MotivationTraceWriter::close() {
    _enabled = false;
    const std::array<std::ofstream*, 5> streams = {&_ack, &_token, &_epoch, &_path, &_link};
    for (std::ofstream* stream : streams) {
        if (stream->is_open()) {
            stream->close();
        }
    }
}
