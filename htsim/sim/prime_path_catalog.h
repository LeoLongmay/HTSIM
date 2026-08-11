#ifndef PRIME_PATH_CATALOG_H
#define PRIME_PATH_CATALOG_H

#include "route.h"

#include <cstdint>
#include <memory>
#include <vector>

struct PrimeTuple {
    std::vector<uint16_t> ports;
    bool operator==(const PrimeTuple& other) const { return ports == other.ports; }
};

struct PrimePathEntry {
    uint16_t catalog_index;
    uint32_t entropy;
    PrimeTuple tuple;
    const Route* forward;
    const Route* reverse;
};

struct PrimeRoutePair {
    std::unique_ptr<Route> forward;
    std::unique_ptr<Route> reverse;
};

using PrimeRoutePairs = std::vector<PrimeRoutePair>;

void appendPrimeTransportEndpoints(PrimeRoutePairs& candidates,
                                   PacketSink& forward_endpoint,
                                   PacketSink& reverse_endpoint);

class PrimePathCatalog {
public:
    static std::shared_ptr<const PrimePathCatalog> build(PrimeRoutePairs candidates,
                                                          uint32_t plane,
                                                          uint16_t requested_paths);

    const PrimePathEntry& entryForEntropy(uint32_t entropy) const;
    const PrimePathEntry& entryForIndex(uint16_t catalog_index) const;
    uint16_t size() const;
    uint16_t tierCount() const;

private:
    PrimePathCatalog(std::vector<PrimePathEntry> entries, PrimeRoutePairs route_pairs,
                     uint16_t tier_count);

    std::vector<PrimePathEntry> entries_;
    PrimeRoutePairs route_pairs_;
    uint16_t tier_count_;
};

#endif
