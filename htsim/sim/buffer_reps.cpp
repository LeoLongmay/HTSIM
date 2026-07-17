#include "buffer_reps.h"

// Static member initialization, for now these are fixed to keep things simple. But ideally the user should be able to set these.
template <typename T> bool CircularBufferREPS<T>::repsUseFreezing = true;
template <typename T> uint16_t CircularBufferREPS<T>::repsBufferSize = 8;
template <typename T> uint16_t CircularBufferREPS<T>::repsMaxLifetimeEntropy = 1;
template <typename T> bool CircularBufferREPS<T>::compressed_acks_reuse = false;
template <typename T> uint64_t CircularBufferREPS<T>::exit_freeze_after = 10000000000;


// Constructor
template <typename T>
CircularBufferREPS<T>::CircularBufferREPS(uint16_t bufferSize) : max_size(bufferSize), head(0), tail(0), count(0) {
    buffer = new Element[max_size];
    for (int i = 0; i < max_size; i++) {
        buffer[i].isValid = false;
        buffer[i].usable_lifetime = 0;
        buffer[i].generation = 0;
        buffer[i].ack_validated = false;
    }
}

// Destructor
template <typename T> CircularBufferREPS<T>::~CircularBufferREPS() { delete[] buffer; }

// Adds an element to the buffer
template <typename T> typename CircularBufferREPS<T>::Admission CircularBufferREPS<T>::add(T element) {
    uint16_t slot = head;
    bool reserved_slot = false;
    if (!reserved_cache_slots.empty()) {
        slot = *reserved_cache_slots.begin();
        reserved_cache_slots.erase(reserved_cache_slots.begin());
        reserved_slot = true;
    }
    if (!buffer[slot].isValid) {
        number_fresh_entropies++;
    }
    buffer[slot].value = element;
    buffer[slot].isValid = true;
    buffer[slot].usable_lifetime = repsMaxLifetimeEntropy;
    buffer[slot].generation++;
    buffer[slot].ack_validated = true;
    if (!reserved_slot || slot == head) {
        head = (head + 1) % max_size;
    }

    if (number_fresh_entropies > max_size) {
        number_fresh_entropies = max_size;
    }
    count++;
    if (count > max_size) {
        count = max_size;
    }
    return {slot, buffer[slot].generation, element, true};
}

// Removes an element from the buffer, taking the earliest fresh element (FIFO order if valid)
template <typename T> T CircularBufferREPS<T>::remove_earliest_fresh() {
    if (count == 0 || number_fresh_entropies == 0) {
        throw std::underflow_error("Buffer is empty or no fresh entropies");
        exit(EXIT_FAILURE);
    }

    int offset = 0;
    if (head - number_fresh_entropies < 0) {
        offset = head + max_size - number_fresh_entropies;
        if (offset < 0) {
            throw std::underflow_error("Offset can not be negative 1");
            exit(EXIT_FAILURE);
        }
    } else {
        offset = head - number_fresh_entropies;
        if (offset < 0) {
            throw std::underflow_error("Offset can not be negative 2");
            exit(EXIT_FAILURE);
        }
    }
    T element = buffer[offset].value;

    if (compressed_acks_reuse) {
        buffer[offset].usable_lifetime--;
        if (buffer[offset].usable_lifetime <= 0) {
            buffer[offset].isValid = false;
            number_fresh_entropies--;
        }
    } else {
        buffer[offset].isValid = false;
        number_fresh_entropies--;
    }

    return element;
}

// Removes an element from the buffer, taking the earliest fresh element (FIFO order if valid)
template <typename T> typename CircularBufferREPS<T>::Selection CircularBufferREPS<T>::remove_earliest_fresh_with_slot() {
    if (count == 0 || number_fresh_entropies == 0) {
        throw std::underflow_error("Buffer is empty or no fresh entropies");
        exit(EXIT_FAILURE);
    }

    uint16_t offset = head;
    for (uint16_t scanned = 0; scanned < max_size; ++scanned) {
        const uint16_t candidate = (head + scanned) % max_size;
        if (buffer[candidate].isValid) {
            offset = candidate;
            break;
        }
    }
    Selection selection = {offset, buffer[offset].generation, buffer[offset].value};

    if (compressed_acks_reuse) {
        buffer[offset].usable_lifetime--;
        if (buffer[offset].usable_lifetime <= 0) {
            buffer[offset].isValid = false;
            number_fresh_entropies--;
        }
    } else {
        buffer[offset].isValid = false;
        number_fresh_entropies--;
    }

    return selection;
}


// Removes an element from the buffer
template <typename T> T CircularBufferREPS<T>::remove_frozen() {
    return remove_frozen_with_slot().value;
}

// Removes an element from the frozen buffer.
template <typename T> typename CircularBufferREPS<T>::Selection CircularBufferREPS<T>::remove_frozen_with_slot() {
    if (count == 0) {
        throw std::underflow_error("Buffer is empty");
    }
    if (!frozen_mode) {
        throw std::runtime_error("Using Remove Frozen without being in frozen mode");
    }

    bool old_validity = buffer[head_frozen_mode].isValid;

    Selection selection = {static_cast<uint16_t>(head_frozen_mode),
                           buffer[head_frozen_mode].generation,
                           buffer[head_frozen_mode].value};

    if (compressed_acks_reuse) {
        buffer[head_frozen_mode].usable_lifetime--;
        if (buffer[head_frozen_mode].usable_lifetime < 0) {
            buffer[head_frozen_mode].isValid = false;
            if (old_validity) {
                number_fresh_entropies--;
            }
        }
    } else {
        if (old_validity) {
            number_fresh_entropies--;
        }
        buffer[head_frozen_mode].isValid = false;
    }

    head_frozen_mode = (head_frozen_mode + 1) % getSize();

    return selection;
}

// Removes an element from the buffer
template <typename T> bool CircularBufferREPS<T>::is_valid_frozen() {
    if (count == 0) {
        throw std::underflow_error("Buffer is empty");
    }
    if (!frozen_mode) {
        throw std::runtime_error("Using Remove Frozen without being in frozen mode");
    }
    return buffer[head_frozen_mode].isValid;
}


template <typename T> void CircularBufferREPS<T>::resetBuffer() {
    for (int i = 0; i < max_size; i++) {
        buffer[i].value = 0;
        buffer[i].isValid = false;
        buffer[i].usable_lifetime = 0;
        buffer[i].ack_validated = false;
    }
    head = 0;
    tail = 0;
    count = 0;
    head_frozen_mode = 0;
    head_round = 0;
    number_fresh_entropies = 0;
    reserved_cache_slots.clear();
}

// Returns the number of elements in the buffer
template <typename T> uint16_t CircularBufferREPS<T>::getSize() const { return count; }

// Returns the number of elements in the buffer
template <typename T> uint16_t CircularBufferREPS<T>::getNumberFreshEntropies() const { return number_fresh_entropies; }

// Checks if the buffer is empty
template <typename T> bool CircularBufferREPS<T>::isEmpty() const { return count == 0; }

// Checks if the buffer is full
template <typename T> bool CircularBufferREPS<T>::isFull() const { return count == max_size; }

// Count how many elements are valiud
template <typename T> uint16_t CircularBufferREPS<T>::numValid() const {
    uint16_t num_valid = 0;
    for (int i = 0; i < count; ++i) {
        if (buffer[i].isValid) {
            num_valid++;
        }
    }
    return num_valid;
}

template <typename T> std::vector<typename CircularBufferREPS<T>::SlotSnapshot> CircularBufferREPS<T>::cacheSlots() const {
    std::vector<SlotSnapshot> snapshots;
    snapshots.reserve(max_size);
    for (uint16_t slot = 0; slot < max_size; ++slot) {
        const Element& element = buffer[slot];
        snapshots.push_back({slot, element.generation, element.value, element.isValid, element.ack_validated});
    }
    return snapshots;
}

template <typename T> bool CircularBufferREPS<T>::invalidateCacheSlot(uint16_t slot, uint64_t generation) {
    if (slot >= max_size || !buffer[slot].isValid || buffer[slot].generation != generation) {
        return false;
    }
    buffer[slot].isValid = false;
    buffer[slot].ack_validated = false;
    number_fresh_entropies--;
    return true;
}

template <typename T> bool CircularBufferREPS<T>::reserveCacheSlot(uint16_t slot,
                                                                      uint64_t generation) {
    if (slot >= max_size || buffer[slot].isValid || buffer[slot].generation != generation) {
        return false;
    }
    reserved_cache_slots.insert(slot);
    return true;
}

template <typename T> void CircularBufferREPS<T>::clearReservedCacheSlots() {
    reserved_cache_slots.clear();
}

// Prints the elements of the buffer
template <typename T> void CircularBufferREPS<T>::print() {
    std::cout << "Buffer elements frozen " << isFrozenMode() << " (value, isValid): ";
    for (int i = 0; i < max_size; i++) {
        std::cout << "(" << buffer[i].value << ", " << buffer[i].isValid << ") ";
    }
    std::cout << std::endl;
}

// Prints the elements of the buffer
template <typename T> bool CircularBufferREPS<T>::containsEntropy(uint16_t givenEntropy) {
    for (int i = 0; i < max_size; i++) {
        if (buffer[i].value == givenEntropy) {
            return true;
        }
    }
    return false;
}

template class CircularBufferREPS<uint16_t>;
