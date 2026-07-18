#include "laps_recovery.h"

#include <cassert>
#include <functional>
#include <utility>
#include <vector>

namespace {

class FakeOwner final : public LapsRecoveryOwner {
public:
    void lapsRecover(UecBasePacket::seq_t seq, mem_b bytes) override {
        recovered.push_back({seq, bytes});
    }

    std::vector<std::pair<UecBasePacket::seq_t, mem_b>> recovered;
};

class SendAt final : public EventSource {
public:
    SendAt(EventList& eventlist, std::function<void()> action)
        : EventSource(eventlist, "laps recovery test sender"), action_(std::move(action)) {}

    void doNextEvent() override { action_(); }

private:
    std::function<void()> action_;
};

void later_ack_recovers_shared_path_records_in_send_order(EventList& eventlist,
                                                          LapsRecoveryDomain& domain) {
    FakeOwner owner_a;
    FakeOwner owner_b;
    FakeOwner isolated_owner;
    const LapsPathKey shared_path{9, 3};
    const LapsPathKey isolated_path{10, 4};

    domain.sent(shared_path, owner_a, 10, 1000);
    domain.sent(shared_path, owner_b, 20, 1100);
    domain.sent(shared_path, owner_a, 30, 1200);

    assert(!domain.acknowledge(shared_path, owner_b, 30, 1200));
    assert(!domain.acknowledge(shared_path, owner_a, 30, 999));
    assert(owner_a.recovered.empty());
    assert(owner_b.recovered.empty());

    assert(domain.acknowledge(shared_path, owner_a, 30, 1200));
    assert((owner_a.recovered == std::vector<std::pair<UecBasePacket::seq_t, mem_b>>{{10, 1000}}));
    assert((owner_b.recovered == std::vector<std::pair<UecBasePacket::seq_t, mem_b>>{{20, 1100}}));
    assert(!domain.acknowledge(shared_path, owner_a, 30, 1200));

    domain.sent(shared_path, owner_a, 40, 1300);
    SendAt send_isolated(eventlist, [&] { domain.sent(isolated_path, isolated_owner, 50, 1400); });
    eventlist.sourceIsPending(send_isolated, timeFromMs(1));

    assert(EventList::doNextEvent());
    assert(EventList::now() == timeFromMs(1));
    assert(EventList::doNextEvent());
    assert(EventList::now() == timeFromUs(uint32_t{8000}));
    assert((owner_a.recovered == std::vector<std::pair<UecBasePacket::seq_t, mem_b>>{{10, 1000}, {40, 1300}}));
    assert((owner_b.recovered == std::vector<std::pair<UecBasePacket::seq_t, mem_b>>{{20, 1100}}));
    assert(isolated_owner.recovered.empty());

    assert(EventList::doNextEvent());
    assert(EventList::now() == timeFromUs(uint32_t{9000}));
    assert((isolated_owner.recovered ==
            std::vector<std::pair<UecBasePacket::seq_t, mem_b>>{{50, 1400}}));
}

void remove_owner_preserves_other_path_records(EventList& eventlist, LapsRecoveryDomain& domain) {
    FakeOwner retained_owner;
    FakeOwner removed_owner;
    const LapsPathKey path{11, 5};

    domain.sent(path, retained_owner, 60, 1500);
    domain.sent(path, removed_owner, 70, 1600);
    domain.removeOwner(removed_owner);

    assert(!domain.acknowledge(path, removed_owner, 70, 1600));
    assert(EventList::doNextEvent());
    assert(EventList::now() == timeFromUs(uint32_t{17000}));
    assert((retained_owner.recovered ==
            std::vector<std::pair<UecBasePacket::seq_t, mem_b>>{{60, 1500}}));
    assert(removed_owner.recovered.empty());

    const LapsPathKey removed_only_path{12, 6};
    domain.sent(removed_only_path, removed_owner, 80, 1700);
    domain.removeOwner(removed_owner);
    assert(!EventList::doNextEvent());
}

void nonempty_paths_reset_their_rto(EventList& eventlist, LapsRecoveryDomain& domain) {
    FakeOwner owner_a;
    FakeOwner owner_b;
    const LapsPathKey path{13, 7};

    domain.sent(path, owner_a, 90, 1800);
    SendAt send_later(eventlist, [&] { domain.sent(path, owner_a, 100, 1900); });
    eventlist.sourceIsPending(send_later, EventList::now() + timeFromMs(1));

    assert(EventList::doNextEvent());
    assert(EventList::now() == timeFromUs(uint32_t{18000}));
    assert(EventList::doNextEvent());
    assert(EventList::now() == timeFromUs(uint32_t{26000}));
    assert((owner_a.recovered ==
            std::vector<std::pair<UecBasePacket::seq_t, mem_b>>{{90, 1800}, {100, 1900}}));

    domain.sent(path, owner_a, 110, 2000);
    domain.sent(path, owner_b, 120, 2100);
    SendAt acknowledge_later(eventlist, [&] {
        assert(domain.acknowledge(path, owner_a, 110, 2000));
    });
    eventlist.sourceIsPending(acknowledge_later, EventList::now() + timeFromMs(1));

    assert(EventList::doNextEvent());
    assert(EventList::now() == timeFromUs(uint32_t{27000}));
    assert(EventList::doNextEvent());
    assert(EventList::now() == timeFromUs(uint32_t{35000}));
    assert((owner_b.recovered ==
            std::vector<std::pair<UecBasePacket::seq_t, mem_b>>{{120, 2100}}));
}

}  // namespace

int main() {
    EventList eventlist;
    LapsRecoveryDomain domain(eventlist);
    later_ack_recovers_shared_path_records_in_send_order(eventlist, domain);
    remove_owner_preserves_other_path_records(eventlist, domain);
    nonempty_paths_reset_their_rto(eventlist, domain);
}
