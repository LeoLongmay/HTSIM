#include "laps_diagnostics.h"

namespace {
template <typename T>
std::string csvValue(const std::optional<T>& value) {
    return value ? std::to_string(*value) : "";
}

std::string csvBool(const std::optional<bool>& value) {
    return value ? (*value ? "1" : "0") : "";
}

std::optional<uint64_t> nsValue(const std::optional<simtime_picosec>& value) {
    return value ? std::optional<uint64_t>(static_cast<uint64_t>(timeAsNs(*value)))
                 : std::optional<uint64_t>{};
}
}  // namespace

std::shared_ptr<LapsDiagnosticsWriter> LapsDiagnosticsWriter::active_writer_;
std::string LapsDiagnosticsWriter::active_path_;

LapsDiagnosticsWriter::LapsDiagnosticsWriter(const char* path, bool strict_laps) {
    if (!strict_laps || path == nullptr || *path == '\0') return;
    stream_.open(path);
    if (!stream_.is_open()) return;
    stream_ << "time_ns,event_seq,flow,event_type,pid,seq,bytes,rate_bps,target_rate_bps,"
               "all_paths_high,target_delay_ns,min_delay_ns,one_way_delay_ns,recovery_cause,"
               "timer_deadline_ns,is_retransmission,outstanding_probes,pit_valid,pit_selectable,"
               "pit_probe_pending,pit_updated_at_ns,pit_deadline_ns\n";
    stream_.flush();
}

std::shared_ptr<LapsDiagnosticsWriter> LapsDiagnosticsWriter::forRun(const char* path,
                                                                       bool strict_laps) {
    if (!strict_laps || path == nullptr || *path == '\0') return {};
    if (active_writer_ && active_path_ == path) return active_writer_;
    auto writer = std::make_shared<LapsDiagnosticsWriter>(path, true);
    if (!writer->enabled()) return {};
    active_path_ = path;
    active_writer_ = writer;
    return active_writer_;
}

void LapsDiagnosticsWriter::log(const LapsDiagnosticEvent& event) {
    if (!enabled()) return;
    stream_ << static_cast<uint64_t>(timeAsNs(event.time)) << ',' << next_event_seq_++ << ','
            << event.flow << ',' << event.event_type << ',' << csvValue(event.pid) << ','
            << csvValue(event.seq) << ',' << csvValue(event.bytes) << ','
            << csvValue(event.rate_bps) << ',' << csvValue(event.target_rate_bps) << ','
            << csvBool(event.all_paths_high) << ',' << csvValue(nsValue(event.target_delay)) << ','
            << csvValue(nsValue(event.min_delay)) << ',' << csvValue(nsValue(event.one_way_delay))
            << ',' << event.recovery_cause << ',' << csvValue(nsValue(event.timer_deadline))
            << ',' << csvBool(event.is_retransmission) << ','
            << csvValue(event.outstanding_probes) << ',' << csvBool(event.pit_valid) << ','
            << csvBool(event.pit_selectable) << ',' << csvBool(event.pit_probe_pending) << ','
            << csvValue(nsValue(event.pit_updated_at)) << ','
            << csvValue(nsValue(event.pit_deadline)) << '\n';
    stream_.flush();
}
