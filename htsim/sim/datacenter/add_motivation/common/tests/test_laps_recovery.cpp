#include "laps_recovery.h"
#include "datacenter/fat_tree_topology.h"
#include "datacenter/fat_tree_switch.h"

#include <cassert>
#include <map>
#include <string>
#include <utility>
#include <vector>

namespace {

class FakeOwner final : public LapsRecoveryOwner {
public:
    void lapsRecover(LapsAttempt attempt, UecBasePacket::seq_t seq, mem_b bytes) override {
        callbacks.push_back({attempt, seq, bytes});
        if (attempt == active_attempt) {
            recovered.push_back({seq, bytes});
        }
    }

    void makeCurrent(LapsAttempt attempt) { active_attempt = attempt; }

    struct Callback {
        LapsAttempt attempt;
        UecBasePacket::seq_t seq;
        mem_b bytes;
    };

    LapsAttempt active_attempt{};
    std::vector<Callback> callbacks;
    std::vector<std::pair<UecBasePacket::seq_t, mem_b>> recovered;
};

class ReRegisteringOwner final : public LapsRecoveryOwner {
public:
    ReRegisteringOwner(LapsRecoveryDomain& domain, LapsPathKey path)
        : domain_(domain), path_(path) {}

    void lapsRecover(LapsAttempt attempt, UecBasePacket::seq_t seq, mem_b bytes) override {
        recovered.push_back({seq, bytes});
        if (seq == 130) {
            retried_attempt = domain_.sent(path_, *this, 140, 2300);
        }
    }

    std::vector<std::pair<UecBasePacket::seq_t, mem_b>> recovered;
    LapsAttempt retried_attempt{};

private:
    LapsRecoveryDomain& domain_;
    LapsPathKey path_;
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

void attempt_lifecycle_is_path_scoped_and_attempt_safe(EventList& eventlist,
                                                        LapsRecoveryDomain& domain) {
    FakeOwner owner_a;
    FakeOwner owner_b;
    const LapsPathKey shared_path{"queue-a\\x1fqueue-b"};

    const LapsAttempt a_first = domain.sent(shared_path, owner_a, 10, 1000);
    const LapsAttempt b_only = domain.sent(shared_path, owner_b, 20, 1100);
    const LapsAttempt a_later = domain.sent(shared_path, owner_a, 30, 1200);
    owner_a.makeCurrent(a_first);
    owner_b.makeCurrent(b_only);

    assert(domain.acknowledge(a_later, timeFromUs(uint32_t{7})));
    assert((owner_a.recovered ==
            std::vector<std::pair<UecBasePacket::seq_t, mem_b>>{{10, 1000}}));
    assert(owner_b.recovered.empty());
    assert(owner_a.callbacks.size() == 1);
    assert(owner_a.callbacks.front().attempt == a_first);

    const size_t callbacks_before = owner_a.callbacks.size();
    assert(!domain.acknowledge(a_first, timeFromUs(uint32_t{7})));
    assert(!domain.nack(a_first));
    assert(!domain.retire(a_first));
    assert(owner_a.callbacks.size() == callbacks_before);

    assert(domain.retire(b_only));
    assert(!domain.retire(b_only));
    assert(!EventList::doNextEvent());
}

void acknowledge_does_not_cross_paths_and_retimes_the_tail(
    EventList& eventlist, LapsRecoveryDomain& domain) {
    FakeOwner owner;
    const LapsPathKey path_a{"queue-c\\x1fqueue-d"};
    const LapsPathKey path_b{"queue-e\\x1fqueue-f"};

    const LapsAttempt path_a_record = domain.sent(path_a, owner, 90, 900);
    const LapsAttempt path_b_record = domain.sent(path_b, owner, 95, 950);
    owner.makeCurrent(path_a_record);
    assert(domain.acknowledge(path_b_record, timeFromUs(uint32_t{7})));
    assert(owner.recovered.empty());
    assert(domain.retire(path_a_record));
    assert(!EventList::doNextEvent());

    const LapsAttempt first = domain.sent(path_a, owner, 100, 1000);
    const LapsAttempt middle = domain.sent(path_a, owner, 110, 1000);
    const LapsAttempt tail = domain.sent(path_a, owner, 120, 1000);
    owner.makeCurrent(first);
    assert(domain.acknowledge(middle, timeFromUs(uint32_t{7})));
    owner.makeCurrent(tail);

    const size_t callbacks_before = owner.callbacks.size();
    assert(!domain.acknowledge(first, timeFromUs(uint32_t{7})));
    assert(!domain.nack(first));
    assert(!domain.retire(first));
    assert(owner.callbacks.size() == callbacks_before);

    assert(EventList::doNextEvent());
    assert(EventList::now() == timeFromUs(uint32_t{14}));
    assert((owner.recovered ==
            std::vector<std::pair<UecBasePacket::seq_t, mem_b>>{{100, 1000}, {120, 1000}}));
    assert(owner.callbacks.back().attempt == tail);

    const size_t expired_callbacks_before = owner.callbacks.size();
    assert(!domain.acknowledge(tail, timeFromUs(uint32_t{7})));
    assert(!domain.nack(tail));
    assert(!domain.retire(tail));
    assert(owner.callbacks.size() == expired_callbacks_before);
}

void no_sample_uses_the_bootstrap_rto(EventList& eventlist, LapsRecoveryDomain& domain) {
    FakeOwner owner;
    const LapsPathKey path{"queue-g\\x1fqueue-h"};
    const simtime_picosec sent_at = EventList::now();

    const LapsAttempt lone = domain.sent(path, owner, 125, 2100);
    owner.makeCurrent(lone);
    assert(EventList::doNextEvent());
    assert(EventList::now() == sent_at + LapsRecoveryDomain::kBootstrapRto);
    assert((owner.recovered ==
            std::vector<std::pair<UecBasePacket::seq_t, mem_b>>{{125, 2100}}));
    assert(owner.callbacks.back().attempt == lone);
}

void nack_detaches_the_old_attempt_before_retry(EventList& eventlist, LapsRecoveryDomain& domain) {
    FakeOwner owner;
    const LapsPathKey path{"queue-e\\x1fqueue-f"};
    const simtime_picosec retry_sent_at = EventList::now();

    const LapsAttempt old_attempt = domain.sent(path, owner, 40, 1300);
    owner.makeCurrent(old_attempt);
    assert(domain.nack(old_attempt));
    const LapsAttempt retry = domain.sent(path, owner, 40, 1300);
    assert(old_attempt != retry);
    owner.makeCurrent(retry);

    // A delayed callback tagged with the replaced attempt cannot affect the retry.
    owner.lapsRecover(old_attempt, 40, 1300);
    assert(owner.recovered.empty());
    assert(EventList::doNextEvent());
    assert(EventList::now() == retry_sent_at + LapsRecoveryDomain::kBootstrapRto);
    assert((owner.recovered ==
            std::vector<std::pair<UecBasePacket::seq_t, mem_b>>{{40, 1300}}));
    assert(owner.callbacks.back().attempt == retry);
}

void expired_recovery_batch_is_removed_before_owner_can_reregister(
    EventList& eventlist, LapsRecoveryDomain& domain) {
    const LapsPathKey path{"queue-g\\x1fqueue-h"};
    ReRegisteringOwner owner(domain, path);
    const simtime_picosec first_sent_at = EventList::now();

    const LapsAttempt first = domain.sent(path, owner, 130, 2200);
    assert(EventList::doNextEvent());
    assert(EventList::now() == first_sent_at + LapsRecoveryDomain::kBootstrapRto);
    assert((owner.recovered ==
            std::vector<std::pair<UecBasePacket::seq_t, mem_b>>{{130, 2200}}));
    assert(owner.retried_attempt != first);

    assert(EventList::doNextEvent());
    assert(EventList::now() == first_sent_at + 2 * LapsRecoveryDomain::kBootstrapRto);
    assert((owner.recovered ==
            std::vector<std::pair<UecBasePacket::seq_t, mem_b>>{{130, 2200}, {140, 2300}}));
}

}  // namespace

int main() {
    EventList eventlist;
    materializes_canonical_ecmp_paths_before_data_forwarding(eventlist);
    LapsRecoveryDomain domain(eventlist);
    attempt_lifecycle_is_path_scoped_and_attempt_safe(eventlist, domain);
    acknowledge_does_not_cross_paths_and_retimes_the_tail(eventlist, domain);
    no_sample_uses_the_bootstrap_rto(eventlist, domain);
    nack_detaches_the_old_attempt_before_retry(eventlist, domain);
    expired_recovery_batch_is_removed_before_owner_can_reregister(eventlist, domain);
}
