#ifndef CIRCULARBUFFERREPS_H
#define CIRCULARBUFFERREPS_H

#include <iostream>
#include <stdexcept>
#include <vector>
#include "stdint.h"

template <typename T> class CircularBufferREPS {
  public:
    struct SlotSnapshot {
        uint16_t slot = UINT16_MAX;
        uint64_t generation = 0;
        T value = T();
        bool valid = false;
        bool ack_validated = false;
    };

    struct Admission {
        uint16_t slot = UINT16_MAX;
        uint64_t generation = 0;
        T value = T();
        bool written = false;
    };

    struct Selection {
        uint16_t slot = UINT16_MAX;
        uint64_t generation = 0;
        T value = T();
    };

  private:
    struct Element {
        T value;
        bool isValid;
        int usable_lifetime = 0;
        uint64_t generation = 0;
        bool ack_validated = false;

        Element() : value(T()), isValid(false) {}
    };

    Element *buffer; // Pointer to dynamically allocated buffer array
    uint16_t max_size;    // Size of the circular buffer
    int16_t head = 0;    // Points to the next element to be written
    uint16_t tail = 0;    // Points to the next element to be read
    uint16_t count = 0;   // Number of elements in the buffer
    int16_t head_frozen_mode = 0;
    int16_t head_round = 0;
    int16_t number_fresh_entropies = 0;

    bool frozen_mode = false;
    bool circle_mode = true;

  public:
    CircularBufferREPS(uint16_t bufferSize = 8); // Default size is 8
    ~CircularBufferREPS();
    Admission add(T element);
    T remove_earliest_fresh();
    Selection remove_earliest_fresh_with_slot();
    T remove_frozen();
    Selection remove_frozen_with_slot();
    bool is_valid_frozen();
    uint16_t getSize() const;
    uint16_t getNumberFreshEntropies() const;
    bool containsEntropy(uint16_t ev);
    bool isEmpty() const;
    bool isFull() const;
    void print();
    void resetBuffer();
    uint16_t numValid() const;
    std::vector<SlotSnapshot> cacheSlots() const;
    bool invalidateCacheSlot(uint16_t slot, uint64_t generation);
    void setFrozenMode(bool mode) {
        if (repsUseFreezing) {
            frozen_mode = mode;
        }
    };
    bool isFrozenMode() const { return frozen_mode; };
    static void setUseFreezing(bool enable_freezing_mode) { repsUseFreezing = enable_freezing_mode; };
    static void setBufferSize(uint16_t buff_size) { repsBufferSize = buff_size; };
    static void setUsableLifetime(uint16_t max_life) {
        repsMaxLifetimeEntropy = max_life;
        if (repsMaxLifetimeEntropy > 1) {
            compressed_acks_reuse = true;
        }
    };
    static bool repsUseFreezing;
    static uint16_t repsBufferSize;
    static uint16_t repsMaxLifetimeEntropy;
    static bool compressed_acks_reuse;

    uint64_t can_enter_frozen_mode = 0;
    uint64_t can_exit_frozen_mode = 0;
    static uint64_t exit_freeze_after;


    uint64_t last_received_ack = 0;
    uint16_t explore_counter = 0;
};

#endif // CIRCULARBUFFERREPS_H
