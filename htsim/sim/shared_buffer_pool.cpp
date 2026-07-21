#include "shared_buffer_pool.h"

#include <stdexcept>

SharedBufferPool::SharedBufferPool(mem_b capacity, mem_b pause_high,
                                   mem_b resume_low)
    : capacity_(capacity),
      pause_high_(pause_high),
      resume_low_(resume_low),
      used_(0),
      paused_(false) {
    if (capacity == 0 || pause_high == 0 || pause_high > capacity ||
        resume_low >= pause_high) {
        throw std::invalid_argument("invalid shared-buffer thresholds");
    }
}

bool SharedBufferPool::reserve(mem_b bytes) {
    if (bytes < 0 || bytes > capacity_ - used_) {
        return false;
    }
    used_ += bytes;
    if (used_ >= pause_high_) {
        paused_ = true;
    }
    return true;
}

void SharedBufferPool::release(mem_b bytes) {
    if (bytes < 0 || bytes > used_) {
        throw std::logic_error("shared-buffer underflow");
    }
    used_ -= bytes;
    if (used_ < resume_low_) {
        paused_ = false;
    }
}

mem_b SharedBufferPool::used() const {
    return used_;
}

mem_b SharedBufferPool::capacity() const {
    return capacity_;
}

bool SharedBufferPool::paused() const {
    return paused_;
}
