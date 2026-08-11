#include "datacenter/fat_tree_topology.h"
#include "ecn.h"
#include "pipe.h"
#include "prime_path_catalog.h"

#include <cassert>
#include <memory>
#include <string>
#include <vector>

#define private public
#include "uec.h"
#undef private

namespace {

EventList eventlist;

PrimeRoutePairs takeBidirectionalPaths(FatTreeTopology& topology, uint32_t src, uint32_t dst) {
    std::unique_ptr<std::vector<const Route*>> paths(topology.get_bidir_paths(src, dst, true));
    PrimeRoutePairs pairs;
    pairs.reserve(paths->size());
    for (const Route* forward : *paths) {
        Route* mutable_forward = const_cast<Route*>(forward);
        pairs.push_back({std::unique_ptr<Route>(mutable_forward),
                         std::unique_ptr<Route>(
                             const_cast<Route*>(mutable_forward->reverse()))});
    }
    return pairs;
}

enum class FeedbackMode { ECN_ACK, TRIM_NACK };

uint32_t feedbackEv(const Packet& pkt) {
    if (pkt.type() == UECACK) return static_cast<const UecAckPacket&>(pkt).ev();
    assert(pkt.type() == UECNACK);
    return static_cast<const UecNackPacket&>(pkt).ev();
}

class ForwardRoutePipe final : public Pipe {
public:
    ForwardRoutePipe(EventList& events, FeedbackMode feedback)
        : Pipe(timeFromNs(uint32_t{1}), events), feedback_(feedback) {}

    void receivePacket(Packet& pkt) override {
        const auto& data = static_cast<const UecDataPacket&>(pkt);
        last_route = pkt.route();
        last_entropy = data.path_id();
        last_catalog_index = data.primeCatalogIndex();
        last_catalog_index_valid = data.primeCatalogIndexValid();
        if (feedback_ == FeedbackMode::ECN_ACK) {
            pkt.set_flags(pkt.flags() | ECN_CE);
        } else {
            pkt.strip_payload(UecBasePacket::ACKSIZE);
        }
        Pipe::receivePacket(pkt);
    }

    const Route* last_route = nullptr;
    uint32_t last_entropy = UINT32_MAX;
    uint16_t last_catalog_index = 0;
    bool last_catalog_index_valid = false;

private:
    FeedbackMode feedback_;
};

class FeedbackRoutePipe final : public Pipe {
public:
    explicit FeedbackRoutePipe(EventList& events) : Pipe(timeFromNs(uint32_t{1}), events) {}

    void receivePacket(Packet& pkt) override {
        last_route = pkt.route();
        const auto& feedback = static_cast<const UecBasePacket&>(pkt);
        last_ev = feedbackEv(pkt);
        last_catalog_index = feedback.primeCatalogIndex();
        last_catalog_index_valid =
            feedback.primeCatalogIndexValid();
        ++received_packets;
        Pipe::receivePacket(pkt);
    }

    const Route* last_route = nullptr;
    uint32_t last_ev = UINT32_MAX;
    uint16_t last_catalog_index = 0;
    bool last_catalog_index_valid = false;
    unsigned received_packets = 0;
};

struct SourceControlSnapshot {
    bool cc_algorithm_is_nscc;
    bool has_private_recovery;
};

std::unique_ptr<UecMultipath> makePrimeMultipath() {
    UecSrc::_sender_based_cc = true;
    UecSrc::_receiver_based_cc = false;
    UecSrc::_sender_cc_algo = UecSrc::NSCC;
    return std::make_unique<UecMpPrime>(false);
}

class PrimeFixture {
public:
    explicit PrimeFixture(FeedbackMode feedback = FeedbackMode::ECN_ACK,
                          bool initialize_nscc_before_catalog = true)
        : topology_config(3, 16, speedFromGbps(100), memFromPkt(100),
                          timeFromUs(uint32_t{1}), 0, COMPOSITE, FAIR_PRIO),
          topology(&topology_config, nullptr, &eventlist, nullptr),
          source_nic(0, eventlist, speedFromGbps(100), 1),
          sink_nic(1, eventlist, speedFromGbps(100), 1),
          source(nullptr, eventlist, makePrimeMultipath(), source_nic, 1),
          sink(nullptr, nullptr, sink_nic, 1) {
        source.getPort(0)->setRoute(source_fib);
        sink.connectPort(0, source, sink_fib);
        source._sink = &sink;
        source.setFlowsize(1'500);
        if (initialize_nscc_before_catalog) initializeNscc();

        PrimeRoutePairs candidates = takeBidirectionalPaths(topology, 8, 0);
        forward_pipes.reserve(4);
        feedback_pipes.reserve(4);
        for (uint16_t index = 0; index < 4; ++index) {
            forward_pipes.push_back(std::make_unique<ForwardRoutePipe>(eventlist, feedback));
            feedback_pipes.push_back(std::make_unique<FeedbackRoutePipe>(eventlist));
            candidates.at(index).forward->push_back(forward_pipes.back().get());
            candidates.at(index).reverse->push_back(feedback_pipes.back().get());
        }
        appendPrimeTransportEndpoints(candidates, *sink.getPort(0), *source.getPort(0));
        catalog = PrimePathCatalog::build(std::move(candidates), 0, 4);
        source.primeSetPathCatalog(catalog);
        sink.primeSetPathCatalog(source, catalog);
        if (!initialize_nscc_before_catalog) initializeNscc();
    }

    uint32_t sendOneDataPacket() {
        source._backlog = 1'500;
        assert(source.sendNewPacket(source_fib) == 1'500);
        return source._tx_bitmap.at(0).path_id;
    }

    uint32_t sendOneRtxPacket() {
        constexpr UecDataPacket::seq_t seqno = 17;
        source._rtx_queue.emplace(seqno, 1'500);
        source._rtx_backlog = 1'500;
        assert(source.sendRtxPacket(source_fib) == 1'500);
        return source._tx_bitmap.at(seqno).path_id;
    }

    UecDataPacket* makeSinkDeliveredData(UecBasePacket::seq_t seqno, uint32_t entropy) {
        const PrimePathEntry& entry = catalog->entryForEntropy(entropy);
        UecDataPacket* data = UecDataPacket::newpkt(
            *source.flow(), *entry.forward, seqno, 1'500, UecDataPacket::DATA_PULL, 0);
        data->set_pathid(entropy);
        data->setPrimeCatalogIndex(entry.catalog_index);
        data->setPrimePinnedRoute(true);
        return data;
    }

    void deliverEcnAckForLastPacket() {
        deliverAckCount(1);
    }

    void deliverAckCount(int32_t expected_acks) {
        for (unsigned events = 0; events < 256 && source.stats().acks_received < expected_acks;
             ++events) {
            assert(EventList::doNextEvent());
        }
        assert(source.stats().acks_received == expected_acks);
    }

    void deliverNackForLastPacket() {
        source._send_blocked_on_nic = true;
        for (unsigned events = 0; events < 256 && source.stats().nacks_received == 0; ++events) {
            assert(EventList::doNextEvent());
        }
        assert(source.stats().nacks_received == 1);
    }

    const ForwardRoutePipe* lastForwardPipe() const {
        for (const auto& pipe : forward_pipes) {
            if (pipe->last_route != nullptr) return pipe.get();
        }
        return nullptr;
    }

    const Route* lastAckRoute() const {
        for (const auto& pipe : feedback_pipes) {
            if (pipe->last_route != nullptr) return pipe->last_route;
        }
        return nullptr;
    }

    const FeedbackRoutePipe* lastFeedbackPipe() const {
        for (const auto& pipe : feedback_pipes) {
            if (pipe->last_route != nullptr) return pipe.get();
        }
        return nullptr;
    }

    unsigned feedbackPacketCount() const {
        unsigned count = 0;
        for (const auto& pipe : feedback_pipes) count += pipe->received_packets;
        return count;
    }

    SourceControlSnapshot sourceControlSnapshot() const {
        return {UecSrc::_sender_cc_algo == UecSrc::NSCC, source._laps_recovery != nullptr};
    }

    UecMpPrime& prime() const {
        auto* result = dynamic_cast<UecMpPrime*>(source._mp.get());
        assert(result != nullptr);
        return *result;
    }

private:
    void initializeNscc() {
        UecSrc::initNsccParams(timeFromUs(uint32_t{10}), speedFromGbps(100),
                               timeFromUs(uint32_t{1}), 3, true);
        source.initNscc(0, timeFromUs(uint32_t{10}));
    }

    FatTreeTopologyCfg topology_config;
    FatTreeTopology topology;
    UecNIC source_nic;
    UecNIC sink_nic;
    Route source_fib;
    Route sink_fib;
    std::vector<std::unique_ptr<ForwardRoutePipe>> forward_pipes;
    std::vector<std::unique_ptr<FeedbackRoutePipe>> feedback_pipes;

public:
    std::shared_ptr<const PrimePathCatalog> catalog;
    UecSrc source;
    UecSink sink;
};

void prime_data_and_ecn_ack_use_the_same_catalog_route_pair() {
    PrimeFixture f;

    const uint32_t entropy = f.sendOneDataPacket();
    const PrimePathEntry& entry = f.catalog->entryForEntropy(entropy);
    f.deliverEcnAckForLastPacket();

    const ForwardRoutePipe* forward = f.lastForwardPipe();
    assert(forward != nullptr);
    assert(forward->last_route == entry.forward);
    assert(forward->last_entropy == entropy);
    assert(forward->last_catalog_index_valid);
    assert(forward->last_catalog_index == entry.catalog_index);
    assert(f.lastAckRoute() == entry.reverse);
    const FeedbackRoutePipe* ack = f.lastFeedbackPipe();
    assert(ack != nullptr);
    assert(ack->last_ev == entropy);
    assert(ack->last_catalog_index_valid);
    assert(ack->last_catalog_index == entry.catalog_index);
    assert(f.feedbackPacketCount() == 1);
    assert(f.prime().primeSnapshot().penalty.at(0).at(entry.tuple.ports.at(0)) == 1);
    const SourceControlSnapshot control = f.sourceControlSnapshot();
    assert(control.cc_algorithm_is_nscc);
    assert(!control.has_private_recovery);
}

void assert_only_resolved_tuple_components_change(const PrimeSnapshot& before,
                                                  const PrimeSnapshot& after,
                                                  const PrimeTuple& tuple,
                                                  uint16_t expected_penalty) {
    assert(before.penalty.size() == after.penalty.size());
    for (uint16_t tier = 0; tier < before.penalty.size(); ++tier) {
        assert(before.penalty.at(tier).size() == after.penalty.at(tier).size());
        for (uint16_t port = 0; port < before.penalty.at(tier).size(); ++port) {
            const uint16_t expected = port == tuple.ports.at(tier)
                                          ? expected_penalty
                                          : before.penalty.at(tier).at(port);
            assert(after.penalty.at(tier).at(port) == expected);
        }
    }
}

void received_ecn_ack_and_trim_nack_update_only_their_received_ev_tuple() {
    for (const FeedbackMode feedback : {FeedbackMode::ECN_ACK, FeedbackMode::TRIM_NACK}) {
        PrimeFixture f(feedback);
        f.source.primeSetPathCatalog(f.catalog, 0, 37);
        const uint32_t first_entropy = f.sendOneDataPacket();
        const PrimePathEntry& entry = f.catalog->entryForEntropy(first_entropy);
        const PrimeSnapshot before = f.prime().primeSnapshot();
        if (feedback == FeedbackMode::ECN_ACK) {
            f.deliverEcnAckForLastPacket();
        } else {
            f.deliverNackForLastPacket();
        }

        const FeedbackRoutePipe* received = f.lastFeedbackPipe();
        assert(received != nullptr);
        assert(received->last_ev == first_entropy);
        assert(f.feedbackPacketCount() == 1);
        assert_only_resolved_tuple_components_change(
            before, f.prime().primeSnapshot(), entry.tuple,
            feedback == FeedbackMode::ECN_ACK ? 1 : 4);

        const uint32_t next_entropy = f.prime().nextEntropy(0, 0);
        const PrimeTuple& first = entry.tuple;
        const PrimeTuple& next = f.catalog->entryForEntropy(next_entropy).tuple;
        assert(next_entropy != first_entropy);
        assert(next.ports.at(0) != first.ports.at(0));
        assert(next.ports.at(1) != first.ports.at(1));
        assert(f.prime().primeSnapshot().selection_reason == PrimeSelectionReason::CLEAR);
    }
}

void threshold_coalesced_ack_carries_the_threshold_crossing_packets_ev() {
    const mem_b original_threshold = UecSink::_bytes_unacked_threshold;
    UecSink::_bytes_unacked_threshold = 3'000;

    PrimeFixture f;
    f.source.setFlowsize(10'000);
    // Avoid the sink's special first-packet force-ACK so the threshold is the
    // only ACK trigger in this fixture.
    f.sink._received_bytes = 1;
    const uint32_t first_entropy = f.catalog->entryForIndex(0).entropy;
    const uint32_t threshold_entropy = f.catalog->entryForIndex(1).entropy;
    assert(first_entropy != threshold_entropy);
    UecDataPacket* first = f.makeSinkDeliveredData(0, first_entropy);
    UecDataPacket* threshold_crossing = f.makeSinkDeliveredData(1, threshold_entropy);

    f.sink.processData(*first);
    assert(!f.sink.shouldSack());
    assert(f.sink._accepted_bytes == 1'500);
    assert(f.feedbackPacketCount() == 0);

    f.sink.processData(*threshold_crossing);
    // The second ordinary packet is neither ECN-marked nor force-ACKed.  Its
    // threshold crossing is therefore the only branch that can create this
    // ACK; processData resets the counter after sending it.
    assert(f.sink._accepted_bytes == 0);
    f.deliverAckCount(1);

    const FeedbackRoutePipe* ack = f.lastFeedbackPipe();
    assert(ack != nullptr);
    assert(f.feedbackPacketCount() == 1);
    assert(ack->last_ev == threshold_entropy);
    assert(ack->last_ev != first_entropy);
    // This threshold ACK is ordinary (not ECN), so its feedback must not
    // change either tuple's controller penalty.
    for (const std::vector<uint16_t>& tier : f.prime().primeSnapshot().penalty) {
        for (uint16_t penalty : tier) assert(penalty == 0);
    }

    first->free();
    threshold_crossing->free();
    UecSink::_bytes_unacked_threshold = original_threshold;
}

void prime_and_laps_metadata_are_mutually_exclusive_in_every_cross_combination() {
    PacketFlow flow(nullptr);
    Route route;
    const auto require_rejection = [&](auto first, auto second) {
        UecDataPacket* packet =
            UecDataPacket::newpkt(flow, route, 0, 1'500, UecDataPacket::DATA_PULL, 0);
        first(*packet);
        bool rejected = false;
        try {
            second(*packet);
        } catch (const std::logic_error&) {
            rejected = true;
        }
        assert(rejected);
        packet->free();
    };
    require_rejection([](UecDataPacket& p) { p.setPrimeCatalogIndex(0); },
                      [](UecDataPacket& p) { p.setLapsPinnedRoute(true); });
    require_rejection([](UecDataPacket& p) { p.setLapsPinnedRoute(true); },
                      [](UecDataPacket& p) { p.setPrimeCatalogIndex(0); });
    require_rejection([](UecDataPacket& p) { p.setLapsPid(0); },
                      [](UecDataPacket& p) { p.setPrimePinnedRoute(true); });
    require_rejection([](UecDataPacket& p) { p.setPrimePinnedRoute(true); },
                      [](UecDataPacket& p) { p.setLapsPid(0); });
}

void prime_catalog_configuration_tracks_nscc_bdp_when_setup_is_late() {
    PrimeFixture f(FeedbackMode::ECN_ACK, false);
    assert(f.prime().primeSnapshot().bdp == 125'000);
}

void prime_rtx_keeps_the_selected_forward_catalog_route_and_index() {
    PrimeFixture f;
    const uint32_t entropy = f.sendOneRtxPacket();
    const PrimePathEntry& entry = f.catalog->entryForEntropy(entropy);
    f.deliverEcnAckForLastPacket();

    const ForwardRoutePipe* forward = f.lastForwardPipe();
    assert(forward != nullptr);
    assert(forward->last_route == entry.forward);
    assert(forward->last_entropy == entropy);
    assert(forward->last_catalog_index_valid);
    assert(forward->last_catalog_index == entry.catalog_index);
}

void prime_trim_nack_keeps_the_received_catalog_reverse_route_and_index() {
    PrimeFixture f(FeedbackMode::TRIM_NACK);
    const uint32_t entropy = f.sendOneDataPacket();
    const PrimePathEntry& entry = f.catalog->entryForEntropy(entropy);
    f.deliverNackForLastPacket();

    const ForwardRoutePipe* forward = f.lastForwardPipe();
    const FeedbackRoutePipe* nack = f.lastFeedbackPipe();
    assert(forward != nullptr && nack != nullptr);
    assert(forward->last_route == entry.forward);
    assert(forward->last_entropy == entropy);
    assert(forward->last_catalog_index_valid);
    assert(forward->last_catalog_index == entry.catalog_index);
    assert(nack->last_route == entry.reverse);
    assert(nack->last_ev == entropy);
    assert(nack->last_catalog_index_valid);
    assert(nack->last_catalog_index == entry.catalog_index);
    assert(f.feedbackPacketCount() == 1);
}

}  // namespace

int main() {
    prime_data_and_ecn_ack_use_the_same_catalog_route_pair();
    received_ecn_ack_and_trim_nack_update_only_their_received_ev_tuple();
    threshold_coalesced_ack_carries_the_threshold_crossing_packets_ev();
    prime_and_laps_metadata_are_mutually_exclusive_in_every_cross_combination();
    prime_catalog_configuration_tracks_nscc_bdp_when_setup_is_late();
    prime_rtx_keeps_the_selected_forward_catalog_route_and_index();
    prime_trim_nack_keeps_the_received_catalog_reverse_route_and_index();
}
