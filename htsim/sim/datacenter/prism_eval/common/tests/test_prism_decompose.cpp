#include "prism_decompose.h"
#include <cassert>
#include <cstdio>
using namespace prism;

int main() {
    // Four quadrants: T_cc = 6, T_spray = 6 (arbitrary ps units). ">=" counts as "high".
    assert(decide_region(3, 3, 6, 6) == INCREASE);  // floor low, spread low
    assert(decide_region(3, 9, 6, 6) == HOLD);      // floor low, spread high
    assert(decide_region(9, 3, 6, 6) == DECREASE);  // floor high (uniform overload)
    assert(decide_region(9, 9, 6, 6) == DECREASE);  // floor high + spread high (mixed)
    assert(decide_region(6, 0, 6, 6) == DECREASE);  // C_cc == T_cc -> high -> decrease
    assert(decide_region(0, 6, 6, 6) == HOLD);      // C_cc=0<T_cc (floor low); C_spray=T_spray (spread high) -> HOLD
    printf("ok decide_region\n");

    // md_factor: NSCC's MD shape, driven by the floor. multiplier in [0.5, 1].
    assert(md_factor(3, 6, 0.8) == 1.0);            // C_cc <= T_cc -> no cut
    { double f = md_factor(12, 6, 0.8);             // 1 - 0.8*6/12 = 0.6
      assert(f > 0.5999 && f < 0.6001); }
    assert(md_factor(1000000, 1, 0.8) == 0.5);      // clamped to 0.5 floor
    printf("ok md_factor\n");

    // decide_loss: loss four-quadrant. args (last_hop, enough_evidence, clean_path_exists, streak_exceeded)
    assert(decide_loss(true,  true,  true,  false) == LOSS_CUT);   // last_hop incast -> cut
    assert(decide_loss(false, false, true,  false) == LOSS_CUT);   // not enough evidence yet (clean_path_exists ignored) -> cut
    assert(decide_loss(false, true,  true,  true)  == LOSS_CUT);   // streak valve tripped -> cut
    assert(decide_loss(false, true,  false, true)  == LOSS_CUT);   // streak valve tripped even w/o clean path -> cut
    assert(decide_loss(false, true,  true,  false) == LOSS_HOLD);  // concentrated/reroutable -> hold
    assert(decide_loss(false, true,  false, false) == LOSS_CUT);   // uniform loss -> cut
    printf("ok decide_loss\n");

    printf("ALL PASS\n");
    return 0;
}
