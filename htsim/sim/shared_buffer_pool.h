#ifndef SHARED_BUFFER_POOL_H
#define SHARED_BUFFER_POOL_H

#include "config.h"

class SharedBufferPool {
public:
    SharedBufferPool(mem_b capacity, mem_b pause_high, mem_b resume_low);

    bool reserve(mem_b bytes);
    void release(mem_b bytes);

    mem_b used() const;
    mem_b capacity() const;
    bool paused() const;

private:
    mem_b capacity_;
    mem_b pause_high_;
    mem_b resume_low_;
    mem_b used_;
    bool paused_;
};

#endif
