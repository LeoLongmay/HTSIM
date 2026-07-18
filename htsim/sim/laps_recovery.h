// -*- c-basic-offset: 4; indent-tabs-mode: nil -*-
#ifndef LAPS_RECOVERY_H
#define LAPS_RECOVERY_H

#include <cstdint>
#include <list>
#include <map>
#include <vector>

#include "eventlist.h"
#include "uecpacket.h"

struct LapsPathKey {
    uint32_t destination;
    uint32_t entropy;

    bool operator<(const LapsPathKey& other) const {
        if (destination != other.destination) {
            return destination < other.destination;
        }
        return entropy < other.entropy;
    }
};

class LapsRecoveryOwner {
public:
    virtual ~LapsRecoveryOwner() = default;
    virtual void lapsRecover(UecBasePacket::seq_t seq, mem_b bytes) = 0;
};

class LapsRecoveryDomain final : public EventSource {
public:
    // C++17 requires this literal spelling because timeFromUs() is not constexpr.
    static constexpr simtime_picosec kRto = 8000ULL * 1000000ULL;

    explicit LapsRecoveryDomain(EventList& eventlist);

    void sent(LapsPathKey path, LapsRecoveryOwner& owner, UecBasePacket::seq_t seq, mem_b bytes);
    bool acknowledge(LapsPathKey path, LapsRecoveryOwner& owner, UecBasePacket::seq_t seq,
                     mem_b bytes);
    void removeOwner(LapsRecoveryOwner& owner);
    void doNextEvent() override;

private:
    struct Record {
        LapsRecoveryOwner* owner;
        UecBasePacket::seq_t seq;
        mem_b bytes;
    };

    struct PathState {
        std::list<Record> records;
        simtime_picosec deadline;
    };

    void updateTimer();

    std::map<LapsPathKey, PathState> paths_;
    EventList::Handle timer_handle_;
    simtime_picosec timer_deadline_;
};

#endif
