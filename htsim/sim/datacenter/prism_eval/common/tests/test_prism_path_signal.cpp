#include "prism_path_signal.h"

#include <cassert>
#include <cstdint>

int main() {
    prism::PathMedianEpoch epoch;
    const uint64_t values[] = {5000, 6000, 7000, 8000, 8000, 9000, 10000, 28000};
    for (uint32_t path = 0; path < 8; ++path) {
        for (int sample = 0; sample < 7; ++sample)
            epoch.observe(path, values[path]);
    }

    const auto signal = epoch.signal();
    assert(signal.observed_paths == 8);
    assert(signal.floor == 5000);
    assert(signal.spread == 23000);

    epoch.reset();
    epoch.observe(3, 9000);
    assert(epoch.signal().floor == 9000);
    assert(epoch.signal().spread == 0);

    epoch.reset();
    for (int sample = 0; sample < 7; ++sample) {
        epoch.observe(0, 8000);
        epoch.observe(1, sample == 3 ? 28000 : 8000);
    }
    const auto transient = epoch.signal();
    assert(transient.floor == 8000);
    assert(transient.spread == 0);

    epoch.reset();
    epoch.observe(0, 5000);
    epoch.observe(0, 5000);
    epoch.observe(1, 28000);
    epoch.observe(1, 28000);
    const auto covered = epoch.signal(2);
    assert(covered.observed_paths == 2);
    assert(covered.floor == 5000);
    assert(covered.spread == 23000);

    epoch.reset();
    epoch.observe(0, 5000);
    epoch.observe(0, 5000);
    epoch.observe(1, 28000);
    const auto insufficient = epoch.signal(2);
    assert(insufficient.observed_paths == 1);
    assert(insufficient.spread == 0);
    return 0;
}
