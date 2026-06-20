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

    // ρ-gate (combined-AND): spread_high = (c_spray >= t_spray) AND (c_spray >= rho*c_cc).
    // T_cc = T_spray = 6 (same arbitrary units as above). rho = 5.
    // Cost-type epoch: floor low (2<6), spread crosses absolute bar (7>=6) but NOT 5x floor (7<10) -> gate removes the HOLD.
    assert(decide_region(2, 7, 6, 6, 5.0) == INCREASE);  // rho-gate: spread does not dominate floor -> back to INCREASE
    assert(decide_region(2, 7, 6, 6)      == HOLD);       // 4-arg default (rho=0): unchanged -> still HOLD
    assert(decide_region(2, 7, 6, 6, 0.0) == HOLD);       // rho=0 explicit: byte-identical to today
    // Win-type epoch: spread massively dominates floor (20 >= 5*2=10) -> still HOLD.
    assert(decide_region(2, 20, 6, 6, 5.0) == HOLD);      // persistent large spread survives the gate
    // Clean-path edge: c_cc=0 -> rho*0=0, any spread>=t_spray stays HOLD (correct: a perfectly clean path exists).
    assert(decide_region(0, 20, 6, 6, 5.0) == HOLD);
    // Floor-high is unaffected by the gate: still DECREASE regardless of rho.
    assert(decide_region(9, 20, 6, 6, 5.0) == DECREASE);
    printf("ok decide_region rho-gate\n");

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
