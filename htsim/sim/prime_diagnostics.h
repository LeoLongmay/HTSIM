#ifndef PRIME_DIAGNOSTICS_H
#define PRIME_DIAGNOSTICS_H

#include <cstdint>
#include <fstream>
#include <memory>
#include <string>

#include "config.h"

// This is an observation-only trace.  Callers must take their snapshots around
// the real PRIME operation; the writer never owns or exposes PRIME state.
struct PrimeDiagnosticEvent {
    simtime_picosec time = 0;
    uint32_t flow = 0;
    std::string event;
    uint32_t entropy = 0;
    std::string tuple;
    std::string reason;
    std::string feedback;
    // Slash-separated by tuple tier, preserving the individual components
    // instead of collapsing the observation to a controller decision scalar.
    std::string penalty_before;
    std::string penalty_after;
};

class PrimeDiagnosticsWriter {
public:
    explicit PrimeDiagnosticsWriter(const char* path);

    static std::shared_ptr<PrimeDiagnosticsWriter> forRun(const char* path);
    bool enabled() const { return stream_.is_open(); }
    void log(const PrimeDiagnosticEvent& event);

private:
    std::ofstream stream_;
    // Deliberately owned by the writer rather than UecMpPrime: diagnostic
    // ordering is observation metadata, never controller state.
    uint64_t next_event_seq_ = 0;
    static std::shared_ptr<PrimeDiagnosticsWriter> active_writer_;
    static std::string active_path_;
};

#endif  // PRIME_DIAGNOSTICS_H
