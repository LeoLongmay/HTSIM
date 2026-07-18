// -*- c-basic-offset: 4; indent-tabs-mode: nil -*-
#ifndef LAPS_RECOVERY_H
#define LAPS_RECOVERY_H

#include <cstdint>
#include <functional>
#include <list>
#include <map>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "eventlist.h"
#include "uecpacket.h"

struct LapsPathKey {
    std::string queue_fingerprint;

    LapsPathKey() = default;
    LapsPathKey(std::string fingerprint) : queue_fingerprint(std::move(fingerprint)) {}

    bool operator<(const LapsPathKey& other) const {
        return queue_fingerprint < other.queue_fingerprint;
    }
};

class LapsAttempt final {
public:
    LapsAttempt() = default;

    bool operator==(const LapsAttempt& other) const { return id_ == other.id_; }
    bool operator!=(const LapsAttempt& other) const { return !(*this == other); }
    explicit operator bool() const { return id_ != 0; }

private:
    explicit LapsAttempt(uint64_t id) : id_(id) {}

    uint64_t id_ = 0;

    friend class LapsRecoveryDomain;
};

class LapsRecoveryOwner {
public:
    virtual ~LapsRecoveryOwner() = default;

    virtual void lapsRecover(LapsAttempt attempt, UecBasePacket::seq_t seq,
                             mem_b bytes) = 0;
};

class LapsRecoveryDomain final : public EventSource {
public:
    // C++17 requires this literal spelling because timeFromUs() is not constexpr.
    static constexpr simtime_picosec kRto = 8000ULL * 1000000ULL;
    static constexpr simtime_picosec kBootstrapRto = 100ULL * 1000000ULL;

    explicit LapsRecoveryDomain(EventList& eventlist);

    LapsAttempt sent(LapsPathKey path, LapsRecoveryOwner& owner,
                     UecBasePacket::seq_t seq, mem_b bytes);
    bool acknowledge(LapsAttempt attempt,
                     std::optional<simtime_picosec> one_way_delay = std::nullopt);
    bool nack(LapsAttempt attempt);
    bool retire(LapsAttempt attempt);

    void removeOwner(LapsRecoveryOwner& owner);
    void doNextEvent() override;

private:
    struct OwnerPathKey {
        LapsPathKey path;
        LapsRecoveryOwner* owner = nullptr;

        bool operator<(const OwnerPathKey& other) const {
            if (path < other.path)
                return true;
            if (other.path < path)
                return false;
            return std::less<LapsRecoveryOwner*>{}(owner, other.owner);
        }
    };

    struct Record {
        LapsAttempt attempt;
        LapsRecoveryOwner* owner;
        UecBasePacket::seq_t seq;
        mem_b bytes;
    };

    struct PathState {
        std::list<Record> records;
        std::optional<simtime_picosec> one_way_delay;
        simtime_picosec deadline = 0;
    };

    struct LocatedAttempt {
        PathState* state;
        std::list<Record>::iterator record;
    };

    std::optional<LocatedAttempt> findAttempt(LapsAttempt attempt);
    bool detach(LapsAttempt attempt);
    void arm(PathState& state);
    void updateTimer();

    std::map<OwnerPathKey, PathState> paths_;
    EventList::Handle timer_handle_;
    simtime_picosec timer_deadline_;
    uint64_t next_attempt_id_ = 1;
};

#endif
