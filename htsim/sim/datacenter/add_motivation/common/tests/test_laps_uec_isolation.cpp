#include <cassert>
#include <algorithm>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <memory>
#include <string>
#include <vector>

#include "config.h"
#include "laps_diagnostics.h"
#define private public
#include "uec.h"
#undef private

namespace {

void setLapsGlobals() {
    UecSrc::_sender_based_cc = true;
    UecSrc::_receiver_based_cc = false;
    UecSrc::_sender_cc_algo = UecSrc::LAPS;
}

void setLapsControlGlobals() {
    UecSrc::_sender_based_cc = true;
    UecSrc::_receiver_based_cc = false;
    UecSrc::_sender_cc_algo = UecSrc::LAPS_CONTROL;
}

void setLapsControlPaperAckGlobals() {
    UecSrc::_sender_based_cc = true;
    UecSrc::_receiver_based_cc = false;
    UecSrc::_sender_cc_algo = UecSrc::LAPS_CONTROL_PAPERACK;
}

void laps_uses_pid_recovery_instead_of_the_generic_uec_rto(EventList& eventlist) {
    setLapsGlobals();

    UecNIC nic(0, eventlist, speedFromGbps(100), 1);
    UecSrc source(nullptr, eventlist, std::make_unique<UecMpLaps>(1, false, 1.0), nic, 1);
    assert(source.isLaps());
    // LAPS owns its recovery domain.  Its data packets must not arm UEC's
    // flow-global RTO, which otherwise times out an arbitrary oldest packet
    // rather than every outstanding record on the affected PID.

    source.createSendRecord(0, 1, 1'500, {});
    source.recalculateRTO();
    assert(!source._rtx_timeout_pending);
    source.cancelRTO();
}

void laps_rejects_an_ack_from_a_different_pid(EventList& eventlist) {
    setLapsGlobals();

    UecNIC nic(2, eventlist, speedFromGbps(100), 1);
    UecSrc source(nullptr, eventlist, std::make_unique<UecMpLaps>(2, false, 1.0), nic, 1);
    source.createSendRecord(0, 7, 1'500, {});
    assert(source._laps_attempts.count(7) == 1);
    assert(source._tx_bitmap.at(7).path_id == 0);

    source.lapsAcknowledge(7, 1, timeFromUs(uint32_t{3}));
    assert(source._laps_attempts.count(7) == 1);

    source.lapsAcknowledge(7, 0, timeFromUs(uint32_t{3}));
    assert(source._laps_attempts.count(7) == 0);
}

void laps_recovery_uses_the_local_pid_delay_for_high_entropy(EventList& eventlist) {
    setLapsGlobals();

    UecNIC nic(7, eventlist, speedFromGbps(100), 1);
    UecSrc source(nullptr, eventlist, std::make_unique<UecMpLaps>(8, false, 1.0), nic, 1);
    auto* laps = dynamic_cast<UecMpLaps*>(source._mp.get());
    assert(laps != nullptr);
    laps->configurePaths(std::vector<simtime_picosec>(8, timeFromUs(uint32_t{7})));
    laps->observeLapsDelay(2, timeFromUs(uint32_t{7}), eventlist.now());

    // The entropy encodes PID 2 in its low bits.  Recovery must use PID 2's
    // latest LAPS sample, rather than treating the full entropy as a PID and
    // falling back to the 100us bootstrap timeout.
    source.createSendRecord(0xb23a, 17, 1'500, {});
    assert(EventList::doNextEvent());
    assert(EventList::now() == 2 * timeFromUs(uint32_t{7}));
}

void non_laps_source_keeps_generic_uec_state(EventList& eventlist) {
    setLapsGlobals();

    UecNIC nic(1, eventlist, speedFromGbps(100), 1);
    UecSrc non_laps(nullptr, eventlist, std::make_unique<UecMpEcmp>(1, false), nic, 1);
    assert(!non_laps.isLaps());
    LapsPathKey ignored;
    non_laps.lapsSetPathResolver({});
    assert(!non_laps.lapsResolvePath(0, 0, ignored));

    non_laps.createSendRecord(0, 2, 1'500, {});
    non_laps.recalculateRTO();
    assert(non_laps._rtx_timeout_pending);
    non_laps.cancelRTO();
}

void laps_control_paperack_keeps_laps_path_control_but_uses_common_recovery(EventList& eventlist) {
    setLapsControlPaperAckGlobals();

    UecNIC nic(1, eventlist, speedFromGbps(100), 1);
    UecSrc source(nullptr, eventlist, std::make_unique<UecMpLaps>(1, false, 1.0), nic, 1);
    assert(source.isLapsControlPaperAck());
    assert(source.usesLapsPathControl());
    assert(!source.usesLapsPrivateRecovery());
    assert(!source._laps_recovery);

    // Unlike the retained strict-LAPS prototype, LAPS-Control must use the
    // same flow-global UEC RTO and packet record lifecycle as OPS/REPS/Prism.
    const auto send_time = eventlist.now();
    source.createSendRecord(0, 3, 1'500, {});
    source.startRTO(send_time);
    assert(source._rtx_timeout_pending);
    assert(source._rto_timer_handle != eventlist.nullHandle());
    assert(!source._laps_recovery);
    assert(source._laps_attempts.empty());
    source.cancelRTO();
}

void laps_control_keeps_laps_path_control_but_uses_common_recovery(EventList& eventlist) {
    setLapsControlGlobals();

    UecNIC nic(1, eventlist, speedFromGbps(100), 1);
    UecSrc source(nullptr, eventlist, std::make_unique<UecMpLaps>(1, false, 1.0), nic, 1);
    assert(source.isLapsControl());
    assert(source.usesLapsPathControl());
    assert(!source.usesLapsPrivateRecovery());
    assert(!source._laps_recovery);

    source.createSendRecord(0, 3, 1'500, {});
    source.recalculateRTO();
    assert(source._rtx_timeout_pending);
    assert(source._laps_attempts.empty());
    source.cancelRTO();
}

void laps_pacing_past_endtime_leaves_no_cancellable_timer(EventList& eventlist) {
    setLapsGlobals();
    // At 1 bit/s, one 4150-byte packet needs 33.2 seconds of pacing time,
    // well beyond this 1us simulation horizon.  EventList therefore rejects
    // the timer and returns its null handle.  LAPS must not retain a future
    // deadline paired with that null handle: a previously granted NIC send
    // may subsequently call noteLapsDataSent again and attempt to cancel it.
    EventList::setEndtime(timeFromUs(uint32_t{1}));
    {
        UecNIC nic(3, eventlist, speedFromGbps(100), 1);
        UecSrc source(nullptr, eventlist, std::make_unique<UecMpLaps>(1, false, 1.0), nic, 1);
        source._laps_rate = {1, 1, 0, 0, 0};

        source.noteLapsDataSent(4'150);

        assert(source._laps_rate_timer_when == 0);
        assert(source._laps_rate_timer_handle == eventlist.nullHandle());
    }
    EventList::setEndtime(0);
}

void laps_diagnostics_cover_every_laps_path_control_arm(EventList& eventlist) {
    const std::filesystem::path strict_trace =
        std::filesystem::temp_directory_path() / "htsim-laps-strict-diagnostics.csv";
    const std::filesystem::path control_trace =
        std::filesystem::temp_directory_path() / "htsim-laps-control-diagnostics.csv";
    const std::filesystem::path paperack_trace =
        std::filesystem::temp_directory_path() / "htsim-laps-paperack-diagnostics.csv";
    const std::filesystem::path non_laps_trace =
        std::filesystem::temp_directory_path() / "htsim-non-laps-diagnostics.csv";
    std::filesystem::remove(strict_trace);
    std::filesystem::remove(control_trace);
    std::filesystem::remove(paperack_trace);
    std::filesystem::remove(non_laps_trace);

    setenv("LAPS_DIAG", strict_trace.c_str(), 1);
    setLapsGlobals();
    {
        UecNIC nic(4, eventlist, speedFromGbps(100), 1);
        UecSrc strict(nullptr, eventlist, std::make_unique<UecMpLaps>(1, false, 1.0), nic, 1);
        assert(strict._laps_diagnostics);
        assert(strict._laps_diagnostics->enabled());
    }
    assert(std::filesystem::exists(strict_trace));

    setenv("LAPS_DIAG", control_trace.c_str(), 1);
    setLapsControlGlobals();
    {
        UecNIC nic(5, eventlist, speedFromGbps(100), 1);
        UecSrc control(nullptr, eventlist, std::make_unique<UecMpLaps>(1, false, 1.0), nic, 1);
        assert(control._laps_diagnostics);
        assert(control._laps_diagnostics->enabled());
    }
    assert(std::filesystem::exists(control_trace));

    setenv("LAPS_DIAG", paperack_trace.c_str(), 1);
    setLapsControlPaperAckGlobals();
    {
        UecNIC nic(6, eventlist, speedFromGbps(100), 1);
        UecSrc paperack(nullptr, eventlist, std::make_unique<UecMpLaps>(1, false, 1.0), nic, 1);
        assert(paperack._laps_diagnostics);
        assert(paperack._laps_diagnostics->enabled());
    }
    assert(std::filesystem::exists(paperack_trace));

    setenv("LAPS_DIAG", non_laps_trace.c_str(), 1);
    UecSrc::_sender_cc_algo = UecSrc::NSCC;
    {
        UecNIC nic(7, eventlist, speedFromGbps(100), 1);
        UecSrc non_laps(nullptr, eventlist, std::make_unique<UecMpEcmp>(1, false), nic, 1);
        assert(!non_laps._laps_diagnostics);
    }
    assert(!std::filesystem::exists(non_laps_trace));

    unsetenv("LAPS_DIAG");
    setLapsGlobals();
    std::filesystem::remove(strict_trace);
    std::filesystem::remove(control_trace);
    std::filesystem::remove(paperack_trace);
}

void laps_diagnostics_preserve_event_families(EventList& eventlist) {
    const std::filesystem::path trace =
        std::filesystem::temp_directory_path() / "htsim-laps-diagnostic-events.csv";
    std::filesystem::remove(trace);
    setenv("LAPS_DIAG", trace.c_str(), 1);
    setLapsGlobals();
    {
        UecNIC nic(6, eventlist, speedFromGbps(100), 1);
        UecSrc source(nullptr, eventlist, std::make_unique<UecMpLaps>(1, false, 1.0), nic, 1);
        for (const char* type : {"rate_update", "probe_sent", "probe_acked", "data_sent", "recovery"}) {
            LapsDiagnosticEvent event;
            event.time = eventlist.now();
            event.flow = source.flowId();
            event.event_type = type;
            event.pid = 0;
            source.logLapsDiagnostic(event);
        }
    }
    std::ifstream stream(trace);
    std::string line;
    std::vector<std::string> lines;
    while (std::getline(stream, line)) lines.push_back(line);
    assert(lines.size() == 6);
    for (size_t row = 1; row < lines.size(); ++row) {
        assert(std::count(lines[row].begin(), lines[row].end(), ',') == 21);
        assert(lines[row].find("," + std::to_string(row - 1) + ",") != std::string::npos);
    }
    unsetenv("LAPS_DIAG");
    std::filesystem::remove(trace);
}

void sink_delivery_summary_reports_exact_application_bytes(EventList& eventlist) {
    UecNIC nic(8, eventlist, speedFromGbps(100), 1);
    UecSink sink(nullptr, nullptr, nic, 1);
    sink._received_bytes = 12'345;
    assert(sink.deliveredBytes() == 12'345);
}

}  // namespace

int main() {
    EventList eventlist;
    laps_uses_pid_recovery_instead_of_the_generic_uec_rto(eventlist);
    assert(EventList::getPendingSources().empty());
    laps_rejects_an_ack_from_a_different_pid(eventlist);
    assert(EventList::getPendingSources().empty());
    laps_recovery_uses_the_local_pid_delay_for_high_entropy(eventlist);
    assert(EventList::getPendingSources().empty());
    non_laps_source_keeps_generic_uec_state(eventlist);
    assert(EventList::getPendingSources().empty());
    laps_control_keeps_laps_path_control_but_uses_common_recovery(eventlist);
    assert(EventList::getPendingSources().empty());
    laps_control_paperack_keeps_laps_path_control_but_uses_common_recovery(eventlist);
    assert(EventList::getPendingSources().empty());
    laps_pacing_past_endtime_leaves_no_cancellable_timer(eventlist);
    assert(EventList::getPendingSources().empty());
    laps_diagnostics_cover_every_laps_path_control_arm(eventlist);
    assert(EventList::getPendingSources().empty());
    laps_diagnostics_preserve_event_families(eventlist);
    assert(EventList::getPendingSources().empty());
    sink_delivery_summary_reports_exact_application_bytes(eventlist);
    assert(EventList::getPendingSources().empty());
}
