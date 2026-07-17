#include "uec_mp.h"
#include "eventlist.h"

#include <cassert>

namespace {

class NoopEventSource : public EventSource {
  public:
    explicit NoopEventSource(EventList& eventlist) : EventSource(eventlist, "noop") {}
    void doNextEvent() override {}
};

void fill_cache(UecMpReps& reps) {
    for (uint32_t entropy = 0; entropy < 8; ++entropy) {
        reps.processEv(entropy, UecMultipath::PATH_GOOD);
    }
}

void cache_slots_are_visible_invalidatable_and_selected_by_slot() {
    UecMpReps reps(16, false, true);
    fill_cache(reps);

    const auto slots = reps.cacheSlots();
    assert(slots.size() == 8);
    assert(slots[3].valid);
    const uint64_t generation = slots[3].generation;

    assert(reps.invalidateCacheSlot(3, generation));
    assert(!reps.cacheSlots()[3].valid);
    assert(!reps.invalidateCacheSlot(3, generation));

    (void)reps.nextEntropy(0, 8);
    const UecMpSelection selection = reps.lastSelection();
    assert(selection.source == UecMpSelection::RECYCLED);
    assert(selection.cache_slot == 0);
    assert(selection.cache_generation == slots[0].generation);
}

void good_ack_admission_identifies_the_physical_slot_written() {
    UecMpReps reps(16, false, true);
    reps.processEv(7, UecMultipath::PATH_GOOD);

    const UecMpAdmission first = reps.lastAdmission();
    assert(first.written);
    assert(first.entropy == 7);
    const auto first_slots = reps.cacheSlots();
    assert(first.cache_slot < first_slots.size());
    assert(first_slots[first.cache_slot].generation == first.cache_generation);
    assert(first_slots[first.cache_slot].entropy == first.entropy);
    assert(first_slots[first.cache_slot].valid);
    assert(first_slots[first.cache_slot].ack_validated);

    assert(reps.invalidateCacheSlot(first.cache_slot, first.cache_generation));
    for (uint32_t entropy = 8; entropy < 16; ++entropy) {
        reps.processEv(entropy, UecMultipath::PATH_GOOD);
    }

    const UecMpAdmission replacement = reps.lastAdmission();
    assert(replacement.cache_slot == first.cache_slot);
    assert(replacement.cache_generation > first.cache_generation);
}

void stale_generation_cannot_invalidate_a_replacement() {
    UecMpReps reps(16, false, true);
    reps.processEv(3, UecMultipath::PATH_GOOD);
    const UecMpAdmission original = reps.lastAdmission();
    assert(reps.invalidateCacheSlot(original.cache_slot, original.cache_generation));

    for (uint32_t entropy = 4; entropy < 12; ++entropy) {
        reps.processEv(entropy, UecMultipath::PATH_GOOD);
    }

    const UecMpAdmission replacement = reps.lastAdmission();
    assert(replacement.cache_slot == original.cache_slot);
    assert(replacement.cache_generation > original.cache_generation);
    assert(!reps.invalidateCacheSlot(original.cache_slot, original.cache_generation));
    assert(reps.cacheSlots()[replacement.cache_slot].valid);
}

void non_good_feedback_clears_last_admission() {
    UecMpReps reps(16, false, true);
    reps.processEv(7, UecMultipath::PATH_GOOD);
    assert(reps.lastAdmission().written);

    reps.processEv(7, UecMultipath::PATH_ECN);
    assert(!reps.lastAdmission().written);

    reps.processEv(7, UecMultipath::PATH_TIMEOUT);
    assert(!reps.lastAdmission().written);
}

void reserved_invalid_slot_is_refilled_before_the_circular_head() {
    UecMpReps reps(16, false, true);
    fill_cache(reps);

    const auto original = reps.cacheSlots()[3];
    assert(reps.invalidateCacheSlot(original.slot, original.generation));
    assert(reps.reserveCacheSlot(original.slot, original.generation));

    reps.processEv(31, UecMultipath::PATH_GOOD_HIGH_RESIDUAL);
    assert(!reps.lastAdmission().written);
    assert(!reps.cacheSlots()[3].valid);

    reps.processEv(32, UecMultipath::PATH_GOOD);
    const UecMpAdmission reserved = reps.lastAdmission();
    assert(reserved.written);
    assert(reserved.cache_slot == 3);
    assert(reserved.cache_generation > original.generation);

    assert(reps.invalidateCacheSlot(reserved.cache_slot, reserved.cache_generation));
    assert(reps.reserveCacheSlot(reserved.cache_slot, reserved.cache_generation));
    reps.clearReservedCacheSlots();

    reps.processEv(33, UecMultipath::PATH_GOOD);
    assert(reps.lastAdmission().cache_slot == 0);
}

void reserved_head_slot_advances_after_replacement_admission() {
    UecMpReps reps(16, false, true);
    fill_cache(reps);

    const auto original = reps.cacheSlots()[0];
    assert(reps.invalidateCacheSlot(original.slot, original.generation));
    assert(reps.reserveCacheSlot(original.slot, original.generation));

    reps.processEv(32, UecMultipath::PATH_GOOD);
    const UecMpAdmission replacement = reps.lastAdmission();
    assert(replacement.cache_slot == 0);

    reps.processEv(33, UecMultipath::PATH_GOOD);
    assert(reps.lastAdmission().cache_slot == 1);
    assert(reps.cacheSlots()[0].generation == replacement.cache_generation);
}

void reset_buffer_clears_reserved_slot_before_path_good_admission() {
    EventList& eventlist = EventList::getTheEventList();
    NoopEventSource timer(eventlist);
    const uint64_t original_exit_freeze_after = CircularBufferREPS<uint16_t>::exit_freeze_after;
    CircularBufferREPS<uint16_t>::exit_freeze_after = 1;

    UecMpReps reps(16, false, true);
    fill_cache(reps);
    const auto original = reps.cacheSlots()[3];
    assert(reps.invalidateCacheSlot(original.slot, original.generation));
    assert(reps.reserveCacheSlot(original.slot, original.generation));

    reps.processEv(31, UecMultipath::PATH_TIMEOUT);
    EventList::sourceIsPending(timer, 2);
    assert(EventList::doNextEvent());

    reps.processEv(32, UecMultipath::PATH_GOOD);
    assert(reps.lastAdmission().written);
    assert(reps.lastAdmission().cache_slot == 0);

    CircularBufferREPS<uint16_t>::exit_freeze_after = original_exit_freeze_after;
}

}  // namespace

int main() {
    cache_slots_are_visible_invalidatable_and_selected_by_slot();
    good_ack_admission_identifies_the_physical_slot_written();
    stale_generation_cannot_invalidate_a_replacement();
    non_good_feedback_clears_last_admission();
    reserved_invalid_slot_is_refilled_before_the_circular_head();
    reserved_head_slot_advances_after_replacement_admission();
    reset_buffer_clears_reserved_slot_before_path_good_admission();
}
