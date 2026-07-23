#include <cassert>
#include <memory>

#include "config.h"
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

void laps_control_keeps_laps_path_control_but_uses_common_recovery(EventList& eventlist) {
    setLapsControlGlobals();

    UecNIC nic(1, eventlist, speedFromGbps(100), 1);
    UecSrc source(nullptr, eventlist, std::make_unique<UecMpLaps>(1, false, 1.0), nic, 1);
    assert(source.isLapsControl());
    assert(source.usesLapsPathControl());
    assert(!source.usesLapsPrivateRecovery());
    assert(!source._laps_recovery);

    // Unlike the retained strict-LAPS prototype, LAPS-Control must use the
    // same flow-global UEC RTO and packet record lifecycle as OPS/REPS/Prism.
    source.createSendRecord(0, 3, 1'500, {});
    source.recalculateRTO();
    assert(source._rtx_timeout_pending);
    assert(source._laps_attempts.empty());
    source.cancelRTO();
}

}  // namespace

int main() {
    EventList eventlist;
    laps_uses_pid_recovery_instead_of_the_generic_uec_rto(eventlist);
    assert(EventList::getPendingSources().empty());
    laps_rejects_an_ack_from_a_different_pid(eventlist);
    assert(EventList::getPendingSources().empty());
    non_laps_source_keeps_generic_uec_state(eventlist);
    assert(EventList::getPendingSources().empty());
    laps_control_keeps_laps_path_control_but_uses_common_recovery(eventlist);
    assert(EventList::getPendingSources().empty());
}
