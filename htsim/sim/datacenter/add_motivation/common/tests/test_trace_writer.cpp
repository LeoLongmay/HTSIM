#include "motivation_background.h"

#include <cassert>
#include <cstdio>
#include <fstream>
#include <stdexcept>
#include <string>

namespace {

constexpr const char* kPrefix = "/tmp/motivation_writer_test";

const char* const kSuffixes[] = {
    ".ack.csv", ".token.csv", ".epoch.csv", ".background.csv", ".pathmap.csv",
    ".linkmap.csv", ".coordination.csv"};

void removeTraceFiles(const std::string& prefix) {
    for (const char* suffix : kSuffixes) {
        std::remove((prefix + suffix).c_str());
    }
}

bool fileExists(const std::string& path) {
    std::ifstream input(path);
    return input.good();
}

std::string lineAt(const std::string& path, size_t line_number) {
    std::ifstream input(path);
    assert(input.good());

    std::string line;
    for (size_t current = 1; current <= line_number; ++current) {
        assert(std::getline(input, line));
    }
    return line;
}

}  // namespace

int main() {
    removeTraceFiles(kPrefix);
    removeTraceFiles("");

    MotivationTraceWriter disabled;
    disabled.configure("", "run", "scenario", 13, -1);
    assert(!disabled.enabled());
    assert(!disabled.enabledFor(7));
    disabled.close();
    for (const char* suffix : kSuffixes) {
        assert(!fileExists(suffix));
    }

    bool open_failed = false;
    try {
        MotivationTraceWriter invalid;
        invalid.configure("/dev/null/motivation_writer_test", "run", "scenario", 13, -1);
    } catch (const std::runtime_error&) {
        open_failed = true;
    }
    assert(open_failed);

    bool identity_failed = false;
    try {
        MotivationTraceWriter invalid;
        invalid.configure(kPrefix, "bad,run", "scenario", 13, -1);
    } catch (const std::invalid_argument&) {
        identity_failed = true;
    }
    assert(identity_failed);
    for (const char* suffix : kSuffixes) {
        assert(!fileExists(std::string(kPrefix) + suffix));
    }

    MotivationTraceWriter writer;
    writer.configure(kPrefix, "run", "scenario", 13, 7);
    assert(writer.enabled());
    assert(writer.enabledFor(7));
    assert(!writer.enabledFor(8));

    const uint64_t seq = writer.nextEventSeq();
    assert(writer.nextEventSeq() == seq + 1);
    const UecMpTokenEvent event{UecMpTokenEvent::ENQUEUE_GOOD_ACK, 17, 3, 0, 1, 19};
    writer.logToken(seq, 7, 1000, event);
    writer.logAck({writer.nextEventSeq(), 1100, 7, 2, 41, 3, 5, 700, 500, 200, true,
                   true, false, 80, "recycled", 17, 1200, 6400, 3200});
    writer.logEpoch({writer.nextEventSeq(), 7, 2, 100, 1200, 4, 500, 300, 550, 250,
                     "hold", "hold", true, 3, 2, 6400, 5200, 3200});
    writer.logCoordination({writer.nextEventSeq(), 1250, 7, 2, 1, 3, 5, 500, 300, 350, 50,
                            "retain", "residual_below_threshold", true, false, false, 3200,
                            "hold"});
    writer.logBackground({writer.nextEventSeq(), 1300, 9, "start", 1, 2, 3, 25, 0,
                          "q1|q2"});
    writer.logAck({writer.nextEventSeq(), 1350, 7, 3, 42, 4, 6, 710, 500, 210, false,
                   true, false, 90, "first_window", 18, 1300, 7700, 3300});
    writer.logBackground({writer.nextEventSeq(), 1400, 9, "finish", 1, 2, 3, 25, 6000,
                          "q1|q2"});
    writer.logBackground({writer.nextEventSeq(), 1450, 10, "start", 4, 5, 6, 0.123046875, 0,
                          "q3"});
    constexpr linkspeed_bps kMaximumExactTraceRate = UINT64_C(1) << 53;
    writer.logBackground({writer.nextEventSeq(), 1500, 11, "start", 7, 8, 9,
                          speedAsGbps(kMaximumExactTraceRate), 0, "q4"});
    writer.close();

    assert(lineAt(std::string(kPrefix) + ".ack.csv", 1) ==
           "schema_version,run_id,seed,scenario,event_seq,time_ps,flow_id,epoch_id,acked_psn,"
           "entropy,physical_path_id,raw_rtt_ps,base_rtt_ps,qdelay_ps,ecn,genuine_sample,"
           "retransmitted,forward_path_backlog_ps,selection_source,source_token_id,"
           "newly_acked_bytes,new_data_bytes_sent_total,cwnd_bytes");
    assert(lineAt(std::string(kPrefix) + ".token.csv", 1) ==
           "schema_version,run_id,event_seq,time_ps,flow_id,operation,reason,token_id,entropy,"
           "queue_depth_before,queue_depth_after,related_ack_event_seq");
    assert(lineAt(std::string(kPrefix) + ".epoch.csv", 1) ==
           "schema_version,run_id,event_seq,flow_id,epoch_id,start_ps,end_ps,sample_count,"
           "raw_floor_ps,raw_spread_ps,smooth_floor_ps,smooth_spread_ps,observed_region,"
           "actual_region,engaged,entropy_coverage,physical_path_coverage,"
           "new_data_bytes_sent_total,acked_bytes_total,cwnd_bytes");
    assert(lineAt(std::string(kPrefix) + ".background.csv", 1) ==
           "schema_version,run_id,event_seq,time_ps,background_id,operation,src,dst,path_index,"
           "configured_rate_gbps,delivered_bytes,queue_fingerprint");
    assert(lineAt(std::string(kPrefix) + ".pathmap.csv", 1) ==
           "schema_version,run_id,flow_id,entropy,physical_path_id,resolution_status,"
           "queue_fingerprint,bottleneck_rate_gbps,contains_reduced_link,ordered_queue_ids");
    assert(lineAt(std::string(kPrefix) + ".linkmap.csv", 1) ==
           "schema_version,run_id,queue_id,queue_name,rate_gbps,reduced_speed");
    assert(lineAt(std::string(kPrefix) + ".coordination.csv", 1) ==
           "schema_version,run_id,event_seq,time_ps,flow_id,epoch_id,round_id,cache_slot,"
           "cache_generation,floor_ps,spread_ps,spread_ref_ps,residual_ps,action,reason,"
           "refresh_complete,progress,handoff,cwnd_bytes,control_state");
    assert(lineAt(std::string(kPrefix) + ".token.csv", 2) ==
           "2,run,0,1000,7,enqueue_good_ack,good_ack,17,3,0,1,19");
    assert(lineAt(std::string(kPrefix) + ".ack.csv", 2) ==
           "2,run,13,scenario,2,1100,7,2,41,3,5,700,500,200,1,1,0,80,recycled,17,1200,"
           "6400,3200");
    assert(lineAt(std::string(kPrefix) + ".epoch.csv", 2) ==
           "2,run,3,7,2,100,1200,4,500,300,550,250,hold,hold,1,3,2,6400,5200,3200");
    assert(lineAt(std::string(kPrefix) + ".coordination.csv", 2) ==
           "2,run,4,1250,7,2,1,3,5,500,300,350,50,retain,residual_below_threshold,1,0,0,"
           "3200,hold");
    assert(lineAt(std::string(kPrefix) + ".background.csv", 2) ==
           "2,run,5,1300,9,start,1,2,3,25,0,q1|q2");
    assert(lineAt(std::string(kPrefix) + ".ack.csv", 3) ==
           "2,run,13,scenario,6,1350,7,3,42,4,6,710,500,210,0,1,0,90,first_window,18,1300,"
           "7700,3300");
    assert(lineAt(std::string(kPrefix) + ".background.csv", 3) ==
           "2,run,7,1400,9,finish,1,2,3,25,6000,q1|q2");
    assert(lineAt(std::string(kPrefix) + ".background.csv", 4) ==
           "2,run,8,1450,10,start,4,5,6,0.123046875,0,q3");
    const std::string boundary_row = lineAt(std::string(kPrefix) + ".background.csv", 5);
    assert(boundary_row ==
           "2,run,9,1500,11,start,7,8,9,9007199.2547409926,0,q4");
    assert(boundary_row.find(formatMotivationBackgroundRateGbps(
               speedAsGbps(kMaximumExactTraceRate))) != std::string::npos);
    assert(speedFromGbps(std::stod("9007199.2547409926")) == kMaximumExactTraceRate);

    removeTraceFiles(kPrefix);
}
