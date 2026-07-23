#include "laps_recovery.h"

#include <cassert>
#include <utility>
#include <vector>

namespace {

class Owner final : public LapsRecoveryOwner {
public:
    void lapsRecover(LapsAttempt, UecBasePacket::seq_t seq, mem_b bytes) override {
        recovered.push_back({seq, bytes});
    }
    std::vector<std::pair<UecBasePacket::seq_t, mem_b>> recovered;
};

class Advance final : public EventSource {
public:
    explicit Advance(EventList& events) : EventSource(events, "pfc pause advance") {}
    void doNextEvent() override {}
};

}  // namespace

int main() {
    EventList events;
    LapsRecoveryDomain recovery(events);
    Owner owner;
    Advance advance(events);
    const simtime_picosec sent_at = EventList::now();

    recovery.sent({1}, owner, 7, 1500);
    recovery.pause();
    EventList::sourceIsPending(advance, sent_at + timeFromUs(uint32_t{25}));
    assert(EventList::doNextEvent());
    assert(owner.recovered.empty());

    recovery.resume(timeFromUs(uint32_t{25}));
    assert(EventList::doNextEvent());
    assert(EventList::now() == sent_at + LapsRecoveryDomain::kBootstrapRto +
                               timeFromUs(uint32_t{25}));
    assert((owner.recovered ==
            std::vector<std::pair<UecBasePacket::seq_t, mem_b>>{{7, 1500}}));
}
