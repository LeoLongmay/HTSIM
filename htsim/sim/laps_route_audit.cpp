#include "laps_route_audit.h"

#include <algorithm>

void LapsRouteAudit::registerCatalog(const LapsPathCatalog& catalog) {
    if (std::find(catalogs_.begin(), catalogs_.end(), &catalog) == catalogs_.end())
        catalogs_.push_back(&catalog);
}

LapsRouteAudit::Record LapsRouteAudit::makeRecord(
    flowid_t flow, UecBasePacket::seq_t seq, uint16_t pid, const Route& route) {
    Record result{flow, seq, pid, &route, {}};
    result.hops.reserve(route.size());
    for (size_t hop = 0; hop < route.size(); ++hop)
        result.hops.push_back(route.at(hop));
    return result;
}

void LapsRouteAudit::recordForward(flowid_t flow, UecBasePacket::seq_t seq, uint16_t pid,
                                   const Route& route) {
    forward_.push_back(makeRecord(flow, seq, pid, route));
}

void LapsRouteAudit::recordReverse(flowid_t flow, UecBasePacket::seq_t seq, uint16_t pid,
                                   const Route& route) {
    reverse_.push_back(makeRecord(flow, seq, pid, route));
}

bool LapsRouteAudit::isCatalogRoute(const Record& record, bool forward) const {
    if (record.route == nullptr || record.hops.size() != record.route->size()) return false;
    for (size_t hop = 0; hop < record.hops.size(); ++hop)
        if (record.hops[hop] != record.route->at(hop)) return false;
    for (const LapsPathCatalog* catalog : catalogs_) {
        if (catalog != nullptr && record.pid < catalog->size()) {
            const LapsPathEntry& entry = catalog->entry(record.pid);
            if (record.route == (forward ? entry.forward : entry.reverse)) return true;
        }
    }
    return false;
}

bool LapsRouteAudit::hasMatchingForward(const Record& reverse) const {
    return std::any_of(forward_.begin(), forward_.end(), [&reverse](const Record& forward) {
        return forward.flow == reverse.flow && forward.seq == reverse.seq &&
               forward.pid == reverse.pid && forward.route != nullptr &&
               forward.route->reverse() == reverse.route;
    });
}

bool LapsRouteAudit::verify() const {
    if (catalogs_.empty()) return false;
    for (const Record& forward : forward_)
        if (!isCatalogRoute(forward, true)) return false;
    for (const Record& reverse : reverse_)
        if (!isCatalogRoute(reverse, false) || !hasMatchingForward(reverse)) return false;
    return true;
}
