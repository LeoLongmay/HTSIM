#include "prism_decompose.h"
#include <cassert>

int main() {
    const auto hold = prism::decide_region(5, 20, 14, 14);
    const auto decrease = prism::decide_region(15, 20, 14, 14);
    assert(hold == prism::HOLD);
    assert(prism::apply_hold_override(hold, true) == prism::INCREASE);
    assert(decrease == prism::DECREASE);
    assert(prism::apply_hold_override(decrease, true) == prism::DECREASE);
}
