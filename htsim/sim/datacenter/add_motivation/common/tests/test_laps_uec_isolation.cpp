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

void localized_laps_uses_the_generic_uec_rto(EventList& eventlist) {
    setLapsGlobals();

    UecNIC nic(0, eventlist, speedFromGbps(100), 1);
    UecSrc source(nullptr, eventlist, std::make_unique<UecMpLaps>(1, false, 1.0), nic, 1);
    assert(source.isLaps());
    assert(source.updateCwndOnAck == &UecSrc::updateCwndOnAck_NSCC);
    assert(source.updateCwndOnNack == &UecSrc::updateCwndOnNack_NSCC);

    source.createSendRecord(0, 1, 1'500, {});
    source.recalculateRTO();
    assert(source._rtx_timeout_pending);
    source.cancelRTO();
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

}  // namespace

int main() {
    EventList eventlist;
    localized_laps_uses_the_generic_uec_rto(eventlist);
    assert(EventList::getPendingSources().empty());
    non_laps_source_keeps_generic_uec_state(eventlist);
    assert(EventList::getPendingSources().empty());
}
