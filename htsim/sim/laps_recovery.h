// -*- c-basic-offset: 4; indent-tabs-mode: nil -*-
#ifndef LAPS_RECOVERY_H
#define LAPS_RECOVERY_H

#include <cstdint>
#include <list>
#include <map>
#include <string>
#include <utility>
#include <vector>

#include "eventlist.h"
#include "uecpacket.h"

struct LapsPathKey {
    std::string queue_fingerprint;

    LapsPathKey() = default;
    LapsPathKey(std::string fingerprint) : queue_fingerprint(std::move(fingerprint)) {}

    // The UEC caller is migrated in the following task.  This constructor is
    // source compatibility only; it cannot participate in attempt lookup.
    [[deprecated("strict LAPS requires a queue fingerprint")]]
    LapsPathKey(uint32_t destination, uint32_t entropy)
        : queue_fingerprint("unmigrated:" + std::to_string(destination) + ":" +
                            std::to_string(entropy)) {}

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

    // Kept temporarily so the domain change can be compiled independently of
    // the UEC call-site migration.  The strict domain never invokes it.
    virtual void lapsRecover(UecBasePacket::seq_t seq, mem_b bytes) = 0;
    virtual void lapsRecover(LapsAttempt attempt, UecBasePacket::seq_t seq, mem_b bytes) {}
};

class LapsRecoveryDomain final : public EventSource {
public:
    // C++17 requires this literal spelling because timeFromUs() is not constexpr.
    static constexpr simtime_picosec kRto = 8000ULL * 1000000ULL;

    explicit LapsRecoveryDomain(EventList& eventlist);

    LapsAttempt sent(LapsPathKey path, LapsRecoveryOwner& owner,
                     UecBasePacket::seq_t seq, mem_b bytes);
    bool acknowledge(LapsAttempt attempt);
    bool nack(LapsAttempt attempt);
    bool retire(LapsAttempt attempt);

    // Transitional no-op until the strict UEC send records carry LapsAttempt.
    // It deliberately never looks up records by owner/sequence/byte count.
    bool acknowledge(LapsPathKey, LapsRecoveryOwner&, UecBasePacket::seq_t, mem_b) {
        return false;
    }
    void removeOwner(LapsRecoveryOwner& owner);
    void doNextEvent() override;

private:
    struct Record {
        LapsAttempt attempt;
        LapsRecoveryOwner* owner;
        UecBasePacket::seq_t seq;
        mem_b bytes;
    };

    struct PathState {
        std::list<Record> records;
        simtime_picosec deadline;
    };

    bool detachWithInference(LapsAttempt attempt);
    void updateTimer();

    std::map<LapsPathKey, PathState> paths_;
    EventList::Handle timer_handle_;
    simtime_picosec timer_deadline_;
    uint64_t next_attempt_id_ = 1;
};

#endif
