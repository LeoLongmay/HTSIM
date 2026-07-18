#include "laps_recovery.h"
#include "datacenter/fat_tree_topology.h"
#include "datacenter/fat_tree_switch.h"

#include <cassert>
#include <functional>
#include <map>
#include <string>
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

class ReRegisteringOwner final : public LapsRecoveryOwner {
public:
    ReRegisteringOwner(LapsRecoveryDomain& domain, LapsPathKey path)
        : domain_(domain), path_(path) {}

    void lapsRecover(UecBasePacket::seq_t seq, mem_b bytes) override {
        recovered.push_back({seq, bytes});
        if (seq == 130) {
            domain_.sent(path_, *this, 140, 2300);
        }
    }

    std::vector<std::pair<UecBasePacket::seq_t, mem_b>> recovered;

private:
    LapsRecoveryDomain& domain_;
    LapsPathKey path_;
};

class SendAt final : public EventSource {
public:
    SendAt(EventList& eventlist, std::function<void()> action)
        : EventSource(eventlist, "laps recovery test sender"), action_(std::move(action)) {}

    void doNextEvent() override { action_(); }

private:
    std::function<void()> action_;
};

class TestPacketSink final : public PacketSink {
public:
    void receivePacket(Packet&) override {}
    const string& nodename() override { return name_; }

private:
    string name_ = "laps path test sink";
};

class TestForwardPacket final : public Packet {
public:
    PktPriority priority() const override { return PRIO_LO; }
    void configure(PacketFlow& flow) { set_attrs(flow, 1500, 1); }
};

std::string serialize_queue_sequence(const std::vector<const BaseQueue*>& queues) {
    std::string serialized;
    for (const BaseQueue* queue : queues) {
        assert(queue != nullptr);
        if (!serialized.empty())
            serialized += " -> ";
        serialized += queue->queueName();
    }
    return serialized;
}

std::string forwarded_queue_sequence(FatTreeTopology& topology,
                                     const FatTreeTopologyCfg& config,
                                     uint32_t source, uint32_t destination,
                                     uint32_t flow_id, uint32_t entropy) {
    PacketFlow flow(nullptr);
    flow.set_flowid(flow_id);
    TestForwardPacket packet;
    packet.configure(flow);
    packet.set_src(source);
    packet.set_dst(destination);
    packet.set_pathid(entropy);

    std::vector<const BaseQueue*> queues;
    queues.push_back(topology.queues_ns_nlp[source][config.HOST_POD_SWITCH(source)][0]);
    FatTreeSwitch* current = dynamic_cast<FatTreeSwitch*>(
        topology.switches_lp[config.HOST_POD_SWITCH(source)]);
    assert(current != nullptr);
    const uint32_t destination_tor = config.HOST_POD_SWITCH(destination);

    for (uint32_t hop = 0; hop < 8; ++hop) {
        Route* route = current->getNextHop(packet, nullptr);
        assert(route != nullptr && route->size() > 0);
        BaseQueue* egress = dynamic_cast<BaseQueue*>(route->at(0));
        assert(egress != nullptr);
        queues.push_back(egress);
        if (current->getType() == FatTreeSwitch::TOR && current->getID() == destination_tor)
            return serialize_queue_sequence(queues);
        current = dynamic_cast<FatTreeSwitch*>(egress->getRemoteEndpoint());
        assert(current != nullptr);
    }
    assert(false);
    return {};
}

void materializes_canonical_ecmp_paths_before_data_forwarding(EventList& eventlist) {
    FatTreeTopologyCfg config(3, 16, speedFromGbps(100), memFromPkt(100),
                              timeFromUs(uint32_t{1}), 0, COMPOSITE, FAIR_PRIO);
    FatTreeTopology topology(&config, nullptr, &eventlist, nullptr);
    FatTreeSwitch::set_strategy(FatTreeSwitch::ECMP);

    constexpr uint32_t source = 0;
    constexpr uint32_t destination = 15;
    constexpr uint32_t first_flow = 1001;
    constexpr uint32_t second_flow = 2002;
    TestPacketSink first_sink;
    TestPacketSink second_sink;
    FatTreeSwitch* destination_switch =
        dynamic_cast<FatTreeSwitch*>(topology.switches_lp[config.HOST_POD_SWITCH(destination)]);
    assert(destination_switch != nullptr);
    destination_switch->addHostPort(destination, first_flow, &first_sink);
    destination_switch->addHostPort(destination, second_flow, &second_sink);

    // No packet has yet traversed this topology.  The strict LAPS resolver
    // must nevertheless materialize the exact FIB route vectors that packet
    // forwarding will later hash over.
    std::map<std::string, uint32_t> first_entropy_by_sequence;
    std::map<uint32_t, std::pair<std::string, uint32_t>> first_sequence_by_low_bucket;
    bool found_equal_sequences = false;
    bool found_distinct_same_bucket = false;
    uint32_t equal_entropy_a = UINT32_MAX;
    uint32_t equal_entropy_b = UINT32_MAX;
    uint32_t bucket_entropy_a = UINT32_MAX;
    uint32_t bucket_entropy_b = UINT32_MAX;

    for (uint32_t entropy = 0; entropy < 4096; ++entropy) {
        std::vector<const BaseQueue*> queues;
        assert(topology.resolve_or_materialize_ecmp_path(source, destination, first_flow,
                                                         entropy, queues));
        const std::string sequence = serialize_queue_sequence(queues);
        assert(!sequence.empty());

        const auto equal = first_entropy_by_sequence.emplace(sequence, entropy);
        if (!equal.second && equal.first->second != entropy) {
            found_equal_sequences = true;
            equal_entropy_a = equal.first->second;
            equal_entropy_b = entropy;
        }

        const uint32_t logical_low_bucket = entropy & 0x3u;
        const auto bucket = first_sequence_by_low_bucket.emplace(
            logical_low_bucket, std::make_pair(sequence, entropy));
        if (!bucket.second && bucket.first->second.first != sequence) {
            found_distinct_same_bucket = true;
            bucket_entropy_a = bucket.first->second.second;
            bucket_entropy_b = entropy;
        }

        if (found_equal_sequences && found_distinct_same_bucket)
            break;
    }
    assert(found_equal_sequences);
    assert(found_distinct_same_bucket);

    for (uint32_t entropy : {equal_entropy_a, equal_entropy_b,
                             bucket_entropy_a, bucket_entropy_b}) {
        assert(entropy != UINT32_MAX);
        std::vector<const BaseQueue*> resolved;
        assert(topology.resolve_or_materialize_ecmp_path(source, destination, first_flow,
                                                         entropy, resolved));
        assert(serialize_queue_sequence(resolved) ==
               forwarded_queue_sequence(topology, config, source, destination,
                                        first_flow, entropy));
    }

    std::vector<const BaseQueue*> equal_a;
    std::vector<const BaseQueue*> equal_b;
    std::vector<const BaseQueue*> bucket_a;
    std::vector<const BaseQueue*> bucket_b;
    assert(topology.resolve_or_materialize_ecmp_path(source, destination, first_flow,
                                                     equal_entropy_a, equal_a));
    assert(topology.resolve_or_materialize_ecmp_path(source, destination, first_flow,
                                                     equal_entropy_b, equal_b));
    assert(topology.resolve_or_materialize_ecmp_path(source, destination, first_flow,
                                                     bucket_entropy_a, bucket_a));
    assert(topology.resolve_or_materialize_ecmp_path(source, destination, first_flow,
                                                     bucket_entropy_b, bucket_b));
    assert(serialize_queue_sequence(equal_a) == serialize_queue_sequence(equal_b));
    assert((bucket_entropy_a & 0x3u) == (bucket_entropy_b & 0x3u));
    assert(serialize_queue_sequence(bucket_a) != serialize_queue_sequence(bucket_b));

    std::vector<const BaseQueue*> second_flow_queues;
    assert(topology.resolve_or_materialize_ecmp_path(source, destination, second_flow, 0,
                                                     second_flow_queues));
    assert(!serialize_queue_sequence(second_flow_queues).empty());
}

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

void expired_recovery_batch_is_removed_before_owner_can_reregister(
    EventList& eventlist, LapsRecoveryDomain& domain) {
    const LapsPathKey path{14, 8};
    ReRegisteringOwner owner(domain, path);

    domain.sent(path, owner, 130, 2200);
    assert(EventList::doNextEvent());
    assert(EventList::now() == timeFromUs(uint32_t{43000}));
    assert((owner.recovered ==
            std::vector<std::pair<UecBasePacket::seq_t, mem_b>>{{130, 2200}}));

    assert(EventList::doNextEvent());
    assert(EventList::now() == timeFromUs(uint32_t{51000}));
    assert((owner.recovered ==
            std::vector<std::pair<UecBasePacket::seq_t, mem_b>>{{130, 2200}, {140, 2300}}));
}

}  // namespace

int main() {
    EventList eventlist;
    materializes_canonical_ecmp_paths_before_data_forwarding(eventlist);
    LapsRecoveryDomain domain(eventlist);
    later_ack_recovers_shared_path_records_in_send_order(eventlist, domain);
    remove_owner_preserves_other_path_records(eventlist, domain);
    nonempty_paths_reset_their_rto(eventlist, domain);
    expired_recovery_batch_is_removed_before_owner_can_reregister(eventlist, domain);
}
