#include "datacenter/fat_tree_topology.h"
#include "prime_path_catalog.h"
#include "uec_mp.h"

#include <array>
#include <cassert>
#include <memory>
#include <set>
#include <vector>

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

std::shared_ptr<const PrimePathCatalog> twoByTwoCatalog() {
    FatTreeTopologyCfg config(3, 16, speedFromGbps(100), memFromPkt(100),
                              timeFromUs(uint32_t{1}), 0, COMPOSITE, FAIR_PRIO);
    FatTreeTopology topology(&config, nullptr, &eventlist, nullptr);
    return PrimePathCatalog::build(takeBidirectionalPaths(topology, 0, 8), 0, 4);
}

const PrimeTuple& tupleFor(const std::shared_ptr<const PrimePathCatalog>& catalog, uint32_t entropy) {
    return catalog->entryForEntropy(entropy).tuple;
}

uint32_t entropyFor(const std::shared_ptr<const PrimePathCatalog>& catalog,
                    std::initializer_list<uint16_t> ports) {
    const std::vector<uint16_t> wanted(ports);
    for (uint16_t index = 0; index < catalog->size(); ++index) {
        const PrimePathEntry& entry = catalog->entryForIndex(index);
        if (entry.tuple.ports == wanted) return entry.entropy;
    }
    assert(false && "test catalog is missing its expected tuple");
    return 0;
}

void explores_the_full_two_by_two_cartesian_cycle_with_mixed_radix_carry() {
    const auto catalog = twoByTwoCatalog();
    UecMpPrime prime(false, PrimeConfig{1, 4, 1});
    prime.configureCatalog(catalog, 0, 47);

    std::array<unsigned, 2> leaf{}, agg{};
    std::set<std::vector<uint16_t>> tuples;
    std::vector<std::vector<uint16_t>> ordered;
    for (unsigned i = 0; i < 4; ++i) {
        const PrimeTuple& tuple = tupleFor(catalog, prime.nextEntropy(0, 0));
        ++leaf.at(tuple.ports.at(0));
        ++agg.at(tuple.ports.at(1));
        tuples.insert(tuple.ports);
        ordered.push_back(tuple.ports);
    }

    assert((leaf == std::array<unsigned, 2>{2, 2}));
    assert((agg == std::array<unsigned, 2>{2, 2}));
    assert((tuples == std::set<std::vector<uint16_t>>{
                          {0, 0}, {0, 1}, {1, 0}, {1, 1}}));
    // The lowest tier moves on every candidate; the upper tier moves only
    // when the lowest cursor wraps.
    assert(ordered.at(0).at(0) != ordered.at(1).at(0));
    assert(ordered.at(0).at(1) == ordered.at(1).at(1));
    assert(ordered.at(2).at(0) != ordered.at(3).at(0));
    assert(ordered.at(2).at(1) == ordered.at(3).at(1));
}

void reshuffles_each_tier_without_losing_any_tuple_from_a_complete_cycle() {
    const auto catalog = twoByTwoCatalog();
    UecMpPrime prime(false, PrimeConfig{1, 4, 1});
    prime.configureCatalog(catalog, 1000000, 91);

    for (unsigned cycle = 0; cycle < 8; ++cycle) {
        std::set<std::vector<uint16_t>> tuples;
        for (unsigned candidate = 0; candidate < 4; ++candidate) {
            tuples.insert(tupleFor(catalog, prime.nextEntropy(0, 0)).ports);
        }
        assert(tuples.size() == 4);
    }
}

void explores_unconditionally_until_the_configured_bdp_has_been_sent() {
    const auto catalog = twoByTwoCatalog();
    UecMpPrime prime(false, PrimeConfig{1, 4, 0});
    prime.configurePrimeCatalog(catalog, 1000, 5);

    (void)prime.nextEntropy(0, 0);
    assert(prime.primeSnapshot().selection_reason == PrimeSelectionReason::EXPLORATION);
    prime.notePrimeBytesSent(999);
    (void)prime.nextEntropy(0, 0);
    assert(prime.primeSnapshot().selection_reason == PrimeSelectionReason::EXPLORATION);
    prime.notePrimeBytesSent(1);
    (void)prime.nextEntropy(0, 0);
    assert(prime.primeSnapshot().selection_reason == PrimeSelectionReason::CLEAR);
}

void applies_feedback_severity_and_only_initializes_ecn_penalties_once() {
    const auto catalog = twoByTwoCatalog();
    UecMpPrime prime(false, PrimeConfig{1, 4, 0});
    prime.configureCatalog(catalog, 0, 47);
    const uint32_t zero_zero = entropyFor(catalog, {0, 0});

    prime.processEv(zero_zero, UecMultipath::PATH_ECN);
    prime.processEv(zero_zero, UecMultipath::PATH_ECN);
    assert(prime.primeSnapshot().penalty.at(0).at(0) == 1);
    assert(prime.primeSnapshot().penalty.at(1).at(0) == 1);
    prime.processEv(zero_zero, UecMultipath::PATH_NACK);
    assert(prime.primeSnapshot().penalty.at(0).at(0) == 4);
    assert(prime.primeSnapshot().penalty.at(1).at(0) == 4);
    prime.processEv(zero_zero, UecMultipath::PATH_TIMEOUT);
    assert(prime.primeSnapshot().penalty.at(0).at(0) == 4);
    assert(prime.primeSnapshot().penalty.at(1).at(0) == 4);
}

void one_selection_decrements_every_nonzero_penalty_component_once() {
    const auto catalog = twoByTwoCatalog();
    UecMpPrime prime(false, PrimeConfig{1, 4, 1});
    prime.configureCatalog(catalog, 0, 13);
    const uint32_t zero_zero = entropyFor(catalog, {0, 0});
    prime.processEv(zero_zero, UecMultipath::PATH_NACK);

    const PrimeSnapshot before = prime.primeSnapshot();
    (void)prime.nextEntropy(0, 0);
    const PrimeSnapshot after = prime.primeSnapshot();
    for (uint16_t tier = 0; tier < before.penalty.size(); ++tier) {
        for (uint16_t port = 0; port < before.penalty.at(tier).size(); ++port) {
            const uint16_t expected = before.penalty.at(tier).at(port) == 0
                                          ? 0
                                          : static_cast<uint16_t>(before.penalty.at(tier).at(port) - 1);
            assert(after.penalty.at(tier).at(port) == expected);
        }
    }
}

void clear_selection_skips_a_penalized_tuple() {
    const auto catalog = twoByTwoCatalog();
    UecMpPrime prime(false, PrimeConfig{1, 4, 0});
    prime.configureCatalog(catalog, 0, 29);
    const uint32_t penalized = entropyFor(catalog, {0, 0});
    prime.processEv(penalized, UecMultipath::PATH_ECN);

    const uint32_t selected = prime.nextEntropy(0, 0);
    const PrimeTuple& tuple = tupleFor(catalog, selected);
    assert(prime.primeSnapshot().selection_reason == PrimeSelectionReason::CLEAR);
    assert(selected != penalized);
    assert(prime.primeSnapshot().penalty.at(0).at(tuple.ports.at(0)) == 0);
    assert(prime.primeSnapshot().penalty.at(1).at(tuple.ports.at(1)) == 0);
}

void bdp_transition_changes_penalized_exploration_into_clear_avoidance() {
    const auto catalog = twoByTwoCatalog();
    UecMpPrime prime(false, PrimeConfig{1, 4, 0});
    prime.configureCatalog(catalog, 1'000, 29);
    const uint32_t exploratory = prime.nextEntropy(0, 0);
    assert(prime.primeSnapshot().selection_reason == PrimeSelectionReason::EXPLORATION);

    prime.configureCatalog(catalog, 1'000, 29);
    prime.processEv(exploratory, UecMultipath::PATH_ECN);
    assert(prime.nextEntropy(0, 0) == exploratory);
    assert(prime.primeSnapshot().selection_reason == PrimeSelectionReason::EXPLORATION);

    prime.notePrimeBytesSent(1'000);
    const uint32_t post_bdp = prime.nextEntropy(0, 0);
    const PrimeTuple& tuple = tupleFor(catalog, post_bdp);
    assert(post_bdp != exploratory);
    assert(prime.primeSnapshot().selection_reason == PrimeSelectionReason::CLEAR);
    assert(prime.primeSnapshot().penalty.at(0).at(tuple.ports.at(0)) == 0);
    assert(prime.primeSnapshot().penalty.at(1).at(tuple.ports.at(1)) == 0);
}

void good_feedback_classes_leave_existing_penalties_unchanged() {
    const auto catalog = twoByTwoCatalog();
    UecMpPrime prime(false, PrimeConfig{1, 4, 0});
    prime.configureCatalog(catalog, 0, 29);
    const uint32_t entropy = entropyFor(catalog, {0, 0});
    prime.processEv(entropy, UecMultipath::PATH_ECN);
    const PrimeSnapshot expected = prime.primeSnapshot();

    prime.processEv(entropy, UecMultipath::PATH_GOOD);
    assert(prime.primeSnapshot().penalty == expected.penalty);
    prime.processEv(entropy, UecMultipath::PATH_GOOD_HIGH_RESIDUAL);
    assert(prime.primeSnapshot().penalty == expected.penalty);
}

void all_penalized_selection_uses_the_minimum_penalty_tuple() {
    const auto catalog = twoByTwoCatalog();
    UecMpPrime prime(false, PrimeConfig{1, 4, 0});
    prime.configureCatalog(catalog, 0, 13);

    prime.processEv(entropyFor(catalog, {0, 0}), UecMultipath::PATH_ECN);
    prime.processEv(entropyFor(catalog, {0, 1}), UecMultipath::PATH_NACK);
    prime.processEv(entropyFor(catalog, {1, 0}), UecMultipath::PATH_ECN);
    prime.processEv(entropyFor(catalog, {1, 1}), UecMultipath::PATH_ECN);

    const uint32_t selected = prime.nextEntropy(0, 0);
    assert(prime.primeSnapshot().selection_reason == PrimeSelectionReason::MINIMUM_PENALTY);
    assert((tupleFor(catalog, selected).ports == std::vector<uint16_t>{1, 0}));
}

}  // namespace

int main() {
    explores_the_full_two_by_two_cartesian_cycle_with_mixed_radix_carry();
    reshuffles_each_tier_without_losing_any_tuple_from_a_complete_cycle();
    explores_unconditionally_until_the_configured_bdp_has_been_sent();
    applies_feedback_severity_and_only_initializes_ecn_penalties_once();
    one_selection_decrements_every_nonzero_penalty_component_once();
    clear_selection_skips_a_penalized_tuple();
    bdp_transition_changes_penalized_exploration_into_clear_avoidance();
    good_feedback_classes_leave_existing_penalties_unchanged();
    all_penalized_selection_uses_the_minimum_penalty_tuple();
}
