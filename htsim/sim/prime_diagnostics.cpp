#include "prime_diagnostics.h"

std::shared_ptr<PrimeDiagnosticsWriter> PrimeDiagnosticsWriter::active_writer_;
std::string PrimeDiagnosticsWriter::active_path_;

PrimeDiagnosticsWriter::PrimeDiagnosticsWriter(const char* path) {
    if (path == nullptr || *path == '\0') return;
    stream_.open(path);
    if (!stream_.is_open()) return;
    stream_ << "event_seq\ttime_ps\tflow\tevent\tentropy\ttuple\treason\tfeedback\tpenalty_before\tpenalty_after\n";
    stream_.flush();
}

std::shared_ptr<PrimeDiagnosticsWriter> PrimeDiagnosticsWriter::forRun(const char* path) {
    if (path == nullptr || *path == '\0') return {};
    if (active_writer_ && active_path_ == path) return active_writer_;
    auto writer = std::make_shared<PrimeDiagnosticsWriter>(path);
    if (!writer->enabled()) return {};
    active_path_ = path;
    active_writer_ = writer;
    return active_writer_;
}

void PrimeDiagnosticsWriter::log(const PrimeDiagnosticEvent& event) {
    if (!enabled()) return;
    stream_ << ++next_event_seq_ << '\t' << static_cast<uint64_t>(event.time) << '\t'
            << event.flow << '\t' << event.event << '\t' << event.entropy << '\t'
            << event.tuple << '\t' << event.reason << '\t' << event.feedback << '\t'
            << event.penalty_before << '\t' << event.penalty_after << '\n';
    stream_.flush();
}
