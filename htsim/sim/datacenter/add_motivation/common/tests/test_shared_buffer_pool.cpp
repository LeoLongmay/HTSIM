#include "shared_buffer_pool.h"

#include <cassert>
#include <stdexcept>

int main() {
  bool threw = false;
  try {
    SharedBufferPool invalid_capacity(0, 80, 60);
  } catch (const std::invalid_argument&) {
    threw = true;
  }
  assert(threw);

  threw = false;
  try {
    SharedBufferPool invalid_high(100, 0, 0);
  } catch (const std::invalid_argument&) {
    threw = true;
  }
  assert(threw);

  threw = false;
  try {
    SharedBufferPool high_above_capacity(100, 101, 60);
  } catch (const std::invalid_argument&) {
    threw = true;
  }
  assert(threw);

  threw = false;
  try {
    SharedBufferPool invalid_hysteresis(100, 80, 80);
  } catch (const std::invalid_argument&) {
    threw = true;
  }
  assert(threw);

  SharedBufferPool pool(100, 80, 60);
  assert(pool.reserve(79));
  assert(!pool.paused());
  assert(pool.reserve(1));
  assert(pool.used() == 80 && pool.paused());
  pool.release(21);
  assert(pool.used() == 59 && !pool.paused());
  assert(!pool.reserve(42));
  assert(pool.used() == 59);
  threw = false;
  try {
    pool.release(60);
  } catch (const std::logic_error&) {
    threw = true;
  }
  assert(threw);
}
