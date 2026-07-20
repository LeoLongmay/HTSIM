#ifndef LAPS_ROUTE_AUDIT_H
#define LAPS_ROUTE_AUDIT_H

#include "laps_path_catalog.h"
#include "uecpacket.h"

#include <cstdint>
#include <vector>

// Test-only, opt-in audit trail for strict LAPS source routing.  It observes
// the Route selected at the transport boundary; it never affects forwarding.
class LapsRouteAudit {
public:
    void registerCatalog(const LapsPathCatalog& catalog);
    void recordForward(flowid_t flow, UecBasePacket::seq_t seq, uint16_t pid,
                       const Route& route);
    void recordReverse(flowid_t flow, UecBasePacket::seq_t seq, uint16_t pid,
                       const Route& route);
    bool verify() const;

private:
    struct Record {
        flowid_t flow;
        UecBasePacket::seq_t seq;
        uint16_t pid;
        const Route* route;
        std::vector<const PacketSink*> hops;
    };

    static Record makeRecord(flowid_t flow, UecBasePacket::seq_t seq, uint16_t pid,
                             const Route& route);
    bool isCatalogRoute(const Record& record, bool forward) const;
    bool hasMatchingForward(const Record& reverse) const;

    std::vector<const LapsPathCatalog*> catalogs_;
    std::vector<Record> forward_;
    std::vector<Record> reverse_;
};

#endif
