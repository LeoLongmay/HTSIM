#include "uec_mp.h"

#include <cassert>
#include <cstdlib>
#include <vector>

namespace {

std::vector<uint32_t> entropy_sequence(bool observe) {
    srandom(12345);
    UecMpRepsLegacy reps(8, false);
    std::vector<UecMpTokenEvent> events;
    if (observe) {
        reps.setTokenObserver([&](const UecMpTokenEvent& event) {
            events.push_back(event);
        });
    }

    std::vector<uint32_t> entropies;
    for (uint64_t seq = 8; seq < 108; ++seq) {
        entropies.push_back(reps.nextEntropy(seq, 8));
    }
    return entropies;
}

}  // namespace

int main() {
    UecMpRepsLegacy reps(8, false);
    std::vector<UecMpTokenEvent> events;
    reps.setTokenObserver([&](const UecMpTokenEvent& event) {
        events.push_back(event);
    });

    (void)reps.nextEntropy(0, 8);
    assert(reps.lastSelection().source == UecMpSelection::FIRST_WINDOW);
    assert(events.back().operation == UecMpTokenEvent::SELECT_FIRST_WINDOW);

    reps.setFeedbackTraceContext(41);
    reps.processEv(3, UecMultipath::PATH_GOOD);
    assert(events.back().operation == UecMpTokenEvent::ENQUEUE_GOOD_ACK);
    assert(events.back().related_ack_event_seq == 41);
    const uint64_t good_ack_token_id = events.back().token_id;

    uint32_t entropy = reps.nextEntropy(8, 8);
    assert(entropy == 3);
    assert(reps.lastSelection().source == UecMpSelection::RECYCLED);
    assert(reps.lastSelection().token_id == good_ack_token_id);
    assert(events.back().operation == UecMpTokenEvent::DEQUEUE_RECYCLE);
    assert(events.back().token_id == good_ack_token_id);

    (void)reps.nextEntropy(9, 8);
    assert(reps.lastSelection().source == UecMpSelection::RANDOM_EMPTY);
    assert(events.back().operation == UecMpTokenEvent::SELECT_RANDOM_EMPTY);

    assert(entropy_sequence(false) == entropy_sequence(true));
}
