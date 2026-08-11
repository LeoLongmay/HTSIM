#ifndef LAPS_DIAGNOSTICS_H
#define LAPS_DIAGNOSTICS_H

#include <cstdint>
#include <fstream>
#include <optional>
#include <memory>
#include <string>

#include "config.h"

struct LapsDiagnosticEvent {
    simtime_picosec time = 0;
    uint32_t flow = 0;
    std::string event_type;
    std::optional<uint32_t> pid;
    std::optional<uint64_t> seq;
    std::optional<uint64_t> bytes;
    std::optional<uint64_t> rate_bps;
    std::optional<uint64_t> target_rate_bps;
    std::optional<bool> all_paths_high;
    std::optional<simtime_picosec> target_delay;
    std::optional<simtime_picosec> min_delay;
    std::optional<simtime_picosec> one_way_delay;
    std::optional<simtime_picosec> timer_deadline;
    std::string recovery_cause;
    std::optional<bool> is_retransmission;
    std::optional<uint64_t> outstanding_probes;
    std::optional<bool> pit_valid;
    std::optional<bool> pit_selectable;
    std::optional<bool> pit_probe_pending;
    std::optional<simtime_picosec> pit_updated_at;
    std::optional<simtime_picosec> pit_deadline;
};

class LapsDiagnosticsWriter {
public:
    LapsDiagnosticsWriter(const char* path, bool strict_laps);

    static std::shared_ptr<LapsDiagnosticsWriter> forRun(const char* path, bool strict_laps);

    bool enabled() const { return stream_.is_open(); }
    void log(const LapsDiagnosticEvent& event);

private:
    std::ofstream stream_;
    uint64_t next_event_seq_ = 0;
    static std::shared_ptr<LapsDiagnosticsWriter> active_writer_;
    static std::string active_path_;
};

#endif  // LAPS_DIAGNOSTICS_H
