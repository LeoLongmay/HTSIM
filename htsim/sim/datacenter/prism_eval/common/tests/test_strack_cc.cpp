#include "strack_cc.h"
#include <cassert>
#include <cstdio>
using namespace strack;
// target = 6, 2*target = 12 (picosecond-scale integers; units irrelevant to the logic).
int main() {
    // No ECN (ecn=false): increase branch.
    assert(decide_action(false, 3, 99, 6) == INCREASE_PROP);    // delay<target -> prop increase
    assert(decide_action(false, 13, 99, 6) == STARVATION_BUMP); // delay>2*target, no ECN -> beta bump
    assert(decide_action(false, 6, 99, 6) == HOLD);             // delay==target (not <) -> hold
    assert(decide_action(false, 9, 99, 6) == HOLD);             // target<delay<2*target -> hold
    assert(decide_action(false, 12, 99, 6) == HOLD);            // delay==2*target (not >) -> hold
    // ECN marked (ecn=true): decrease branch, keyed on AVG delay.
    assert(decide_action(true, 99, 9, 6) == MULT_DECREASE);     // avg>target -> MD
    assert(decide_action(true, 99, 6, 6) == HOLD);              // avg==target (not >) -> hold (path switch)
    assert(decide_action(true, 99, 3, 6) == HOLD);              // avg<target -> hold (Scenario #2)
    printf("ok strack decide_action\n");
    printf("ALL PASS\n");
    return 0;
}
