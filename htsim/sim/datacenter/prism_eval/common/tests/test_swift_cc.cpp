#include "swift_cc.h"
#include <cassert>
#include <cstdio>
#include <cmath>
#include <cstdint>
using namespace swift;
int main() {
    double a, b;
    const double R = 7000.0;                 // fs_range (ps); fs_min=0.1, fs_max=100 packets
    fs_coeffs(R, 0.1, 100.0, a, b);
    // at cwnd == fs_max_cwnd (100) the scaling term is ~0 -> target == base
    assert(target_delay_q(100.0, 14000, a, b, R) == 14000);
    // at cwnd == fs_min_cwnd (0.1) the scaling term saturates at fs_range -> target == base + R
    { uint64_t t = target_delay_q(0.1, 14000, a, b, R);
      assert(t >= 14000 + (uint64_t)R - 1 && t <= 14000 + (uint64_t)R + 1); }
    // monotonic: a smaller cwnd yields a larger target
    assert(target_delay_q(4.0, 14000, a, b, R) > target_delay_q(64.0, 14000, a, b, R));
    // cwnd <= 0 -> base (no scaling)
    assert(target_delay_q(0.0, 14000, a, b, R) == 14000);
    assert(target_delay_q(-1.0, 14000, a, b, R) == 14000);  // negative cwnd -> base (no scaling)
    // md_factor: delay == target -> factor 1.0 (no decrease)
    assert(std::fabs(md_factor(14000, 14000, 0.8, 0.5) - 1.0) < 1e-9);
    // delay slightly above target -> just below 1, above the 1-max_mdf floor
    { double f = md_factor(15000, 14000, 0.8, 0.5); assert(f < 1.0 && f > 0.5); }
    // delay >> target -> clamped at 1 - max_mdf = 0.5
    assert(std::fabs(md_factor(1000000, 14000, 0.8, 0.5) - 0.5) < 1e-9);
    printf("ok swift target_delay_q + md_factor\n");
    printf("ALL PASS\n");
    return 0;
}
