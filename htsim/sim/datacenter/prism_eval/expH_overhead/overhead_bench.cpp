// overhead_bench.cpp — PRISM overhead microbench (measurement-only; NEVER links the simulator).
// Times each scheme's per-ACK congestion-signal-extraction routine and sizeof's its per-flow
// signal-state group, using the standalone CC headers. Writes CSVs to argv[1] (default "data").
// Build: g++ -O2 -std=c++17 -I ../../.. overhead_bench.cpp -o overhead_bench   (from this folder;
//        -I points at htsim/sim so the headers resolve).
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <chrono>
#include <string>
#include "prism_decompose.h"
#include "mnscc_median.h"
#include "swift_cc.h"
#include "strack_cc.h"

typedef uint64_t u64;
using clk = std::chrono::steady_clock;

// --- representative signal-state groups, mirroring the real UecSrc members (file:line) ---
struct PrismState  { u64 start; uint32_t min,max,ccc,cspray,samples; uint8_t region; bool genuine; }; // PRISM per-flow state mirroring uec.h: start is an absolute timestamp (64-bit); min/max/ccc/cspray are queuing DELAYS (<2^32 ps -> 32-bit); region has 3 states (8-bit). ccc/cspray double as the A1 EWMA floor/spread (folded in-place, no extra state) -> 32 B
struct MnsccState  { uint32_t window[32]; uint32_t wcount, whead; };                                  // uec.h (MNSCC_MAX_H=32); window holds queuing-delay samples at the SAME 32-bit width as PRISM, for an apples-to-apples per-sample comparison -> 136 B
struct MswiftState { uint32_t window[64]; uint32_t wcount, whead; };                                  // median window (SWIFT_MAX_H=64), same 32-bit per-sample width; overcount is LSwift-base state, excluded for apples-to-apples vs MNSCC -> 264 B
struct SwiftState  { u64 last_dec; };                                                                // uec.h:~1699
struct NsccState   { u64 reuse; };          // NSCC reuses base UecSrc scalars; no signal buffer     // uec.h:1460-1507
struct RepsElem    { uint16_t value; bool isValid; int usable_lifetime; };                           // buffer_reps.h
struct RepsState   { RepsElem buf[8]; int16_t head, tail; uint16_t count; };                         // repsBufferSize=8

// deterministic per-iteration pseudo-random queuing delay in [base, base+~16us) picoseconds
static inline u64 q_of(long i) { u64 x = (u64)i*6364136223846793005ULL + 1442695040888963407ULL; return 2000ULL + (x >> 50); }

template <typename F>
static double bench_ns(F&& fn, long iters) {
    volatile u64 sink = 0;
    for (long i = 0; i < iters/10; ++i) sink ^= fn(i);     // warm
    auto t0 = clk::now();
    for (long i = 0; i < iters; ++i) sink ^= fn(i);
    auto t1 = clk::now();
    (void)sink;
    return std::chrono::duration<double, std::nano>(t1 - t0).count() / (double)iters;
}

int main(int argc, char** argv) {
    std::string dir = (argc > 1) ? argv[1] : "data";
    const long N = 20000000;                 // iters per timing
    const u64 T_CC = 14000, T_SPRAY = 14000; // ps targets (~14us)

    // ---- per-ACK signal extraction ----
    // PRISM per-ACK: running min/max update (the only per-ACK work; decompose is per-epoch).
    PrismState ps{}; ps.min = ~0u; ps.max = 0;
    double ns_prism = bench_ns([&](long i){ u64 q=q_of(i); if(q<ps.min)ps.min=q; if(q>ps.max)ps.max=q; ps.samples++; return ps.min^ps.max; }, N);
    // PRISM per-decision: decide_region + md_factor (runs once per epoch, reported separately).
    double ns_prism_dec = bench_ns([&](long i){ u64 cc=q_of(i), sp=q_of(i+1); int r=prism::decide_region(cc,sp,T_CC,T_SPRAY); double m=prism::md_factor(cc,T_CC,0.8); return (u64)r ^ (u64)(m*1e6); }, N);
    // NSCC per-ACK: a target comparison (representative O(1)).
    double ns_nscc = bench_ns([&](long i){ u64 q=q_of(i); bool hi=q>=T_CC; return (u64)hi; }, N);
    // STrack per-ACK: decide_action (O(1)).
    double ns_strack = bench_ns([&](long i){ u64 q=q_of(i); int a=strack::decide_action((i&1), q, q, T_CC); return (u64)a; }, N);
    // Swift per-ACK: flow-scaled target + md_factor (O(1)).
    double a_, b_; swift::fs_coeffs(20000.0, 4.0, 64.0, a_, b_);
    double ns_swift = bench_ns([&](long i){ u64 q=q_of(i); u64 tgt=swift::target_delay_q((double)(i%64+1), T_CC, a_, b_, 20000.0); double m = (q>tgt)? swift::md_factor(q,tgt,0.8,0.5):1.0; return tgt ^ (u64)(m*1e6); }, N);
    // MNSCC / MSwift per-ACK: ring push + median_of(window,H).
    MnsccState ms{}; auto mnscc_at=[&](int H){ ms.window[ms.whead]=0; return bench_ns([&](long i){ ms.window[ms.whead]=q_of(i); ms.whead=(ms.whead+1)%H; return mnscc::median_of(ms.window,H); }, N/4); };
    MswiftState mw{}; auto mswift_at=[&](int H){ return bench_ns([&](long i){ mw.window[mw.whead]=q_of(i); mw.whead=(mw.whead+1)%H; return mnscc::median_of(mw.window,H); }, N/4); };  // MSwift reuses mnscc::median_of (mnscc_median.h:16-24); only window size differs (64 vs MNSCC's 32)

    // ---- write bench_compute.csv ----
    FILE* f = fopen((dir+"/bench_compute.csv").c_str(), "w");
    if(!f){ fprintf(stderr,"BENCH FAIL: cannot open %s/bench_compute.csv\n", dir.c_str()); return 1; }
    fprintf(f, "algo,h,ns_per_op\n");
    fprintf(f, "prism,0,%.4f\n", ns_prism);
    fprintf(f, "prism_decision,0,%.4f\n", ns_prism_dec);
    fprintf(f, "nscc,0,%.4f\n", ns_nscc);
    fprintf(f, "strack,0,%.4f\n", ns_strack);
    fprintf(f, "swift,0,%.4f\n", ns_swift);
    const int HS[] = {2,4,8,16,32,48,64};
    double mnscc32=0, mswift64=0;
    for(int H: HS){ double v=mnscc_at(H); fprintf(f,"mnscc,%d,%.4f\n",H,v); if(H==32) mnscc32=v; }
    for(int H: HS){ double v=mswift_at(H); fprintf(f,"mswift,%d,%.4f\n",H,v); if(H==64) mswift64=v; }
    fclose(f);

    // ---- bench_state.csv (signal-state bytes per flow) ----
    f = fopen((dir+"/bench_state.csv").c_str(), "w");
    if(!f){ fprintf(stderr,"BENCH FAIL: cannot open %s/bench_state.csv\n", dir.c_str()); return 1; }
    fprintf(f, "algo,bytes\n");
    fprintf(f, "prism,%zu\n", sizeof(PrismState));
    fprintf(f, "nscc,%zu\n",  sizeof(NsccState));
    fprintf(f, "strack,%zu\n",sizeof(NsccState));  // STrack: O(1), stateless decision logic (strack_cc.h) reusing NSCC's base scalars -> same minimal footprint
    fprintf(f, "swift,%zu\n", sizeof(SwiftState));
    fprintf(f, "mnscc,%zu\n", sizeof(MnsccState));
    fprintf(f, "mswift,%zu\n",sizeof(MswiftState));
    fprintf(f, "reps,%zu\n",  sizeof(RepsState));
    fclose(f);

    // ---- bench_state_paths.csv (bytes vs #paths: prism/reps flat, bitmap O(#paths)) ----
    f = fopen((dir+"/bench_state_paths.csv").c_str(), "w");
    if(!f){ fprintf(stderr,"BENCH FAIL: cannot open %s/bench_state_paths.csv\n", dir.c_str()); return 1; }
    fprintf(f, "paths,prism,reps,bitmap\n");
    for(int p : {8,16,32,64,128}) fprintf(f, "%d,%zu,%zu,%d\n", p, sizeof(PrismState), sizeof(RepsState), p); // bitmap = vector<uint8_t> _ev_skip_bitmap (uec_mp.cpp:61-149), sized #paths -> one byte per path
    fclose(f);

    // ---- sanity invariants (the test) ----
    if(!(mnscc32 > ns_prism*2))   { fprintf(stderr,"BENCH FAIL: mnscc@32 (%.2f) not >> prism (%.2f)\n", mnscc32, ns_prism); return 1; }
    if(!(mswift64 > mnscc32))     { fprintf(stderr,"BENCH FAIL: mswift@64 (%.2f) not > mnscc@32 (%.2f)\n", mswift64, mnscc32); return 1; }
    if(!(sizeof(MnsccState) > sizeof(PrismState) && sizeof(MswiftState) > sizeof(MnsccState))) { fprintf(stderr,"BENCH FAIL: state size ordering\n"); return 1; }
    printf("BENCH OK  prism=%.2fns nscc=%.2f swift=%.2f strack=%.2f  mnscc@32=%.2f mswift@64=%.2f  | state prism=%zuB mnscc=%zuB mswift=%zuB\n",
           ns_prism, ns_nscc, ns_swift, ns_strack, mnscc32, mswift64, sizeof(PrismState), sizeof(MnsccState), sizeof(MswiftState));
    return 0;
}
