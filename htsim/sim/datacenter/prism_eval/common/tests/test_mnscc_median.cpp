#include "mnscc_median.h"
#include <cassert>
#include <cstdio>
#include <cstdint>
using namespace mnscc;
int main() {
    // median_of: odd window -> middle element
    { uint64_t b[] = {30, 10, 20}; assert(median_of(b, 3) == 20); }
    // even window -> average of the two middle elements
    { uint64_t b[] = {10, 20, 30, 40}; assert(median_of(b, 4) == 25); }   // (20+30)/2
    // even window, odd sum -> floor of the midpoint (truncation, not rounding)
    { uint64_t b[] = {10, 11}; assert(median_of(b, 2) == 10); }
    // overflow-safety: two near-UINT64_MAX values must not wrap
    { uint64_t b[] = {0xFFFFFFFFFFFFFFFEULL, 0xFFFFFFFFFFFFFFFFULL}; assert(median_of(b, 2) == 0xFFFFFFFFFFFFFFFEULL); }
    // n==1 -> identity (degenerates to the latest delay == plain NSCC)
    { uint64_t b[] = {17}; assert(median_of(b, 1) == 17); }
    // robustness: a single huge outlier does not move the median (the whole point)
    { uint64_t b[] = {10, 12, 11, 9, 100000}; assert(median_of(b, 5) == 11); }
    // nyquist_h: H = max(min(W/2,4),1)
    assert(nyquist_h(0) == 1);
    assert(nyquist_h(1) == 1);
    assert(nyquist_h(2) == 1);    // 2/2=1
    assert(nyquist_h(4) == 2);    // 4/2=2
    assert(nyquist_h(8) == 4);    // 8/2=4 (cap)
    assert(nyquist_h(100) == 4);  // capped at 4
    printf("ok mnscc median + nyquist_h\n");
    printf("ALL PASS\n");
    return 0;
}
