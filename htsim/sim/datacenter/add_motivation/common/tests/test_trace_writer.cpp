#include "motivation_trace.h"

#include <cassert>
#include <cstdio>
#include <fstream>
#include <stdexcept>
#include <string>

namespace {

constexpr const char* kPrefix = "/tmp/motivation_writer_test";

const char* const kSuffixes[] = {
    ".ack.csv", ".token.csv", ".epoch.csv", ".pathmap.csv", ".linkmap.csv"};

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
    writer.close();

    assert(lineAt(std::string(kPrefix) + ".ack.csv", 1) ==
           "schema_version,run_id,seed,scenario,event_seq,time_ps,flow_id,epoch_id,acked_psn,"
           "entropy,physical_path_id,raw_rtt_ps,base_rtt_ps,qdelay_ps,ecn,genuine_sample,"
           "retransmitted,forward_path_backlog_ps,selection_source,source_token_id");
    assert(lineAt(std::string(kPrefix) + ".token.csv", 1) ==
           "schema_version,run_id,event_seq,time_ps,flow_id,operation,reason,token_id,entropy,"
           "queue_depth_before,queue_depth_after,related_ack_event_seq");
    assert(lineAt(std::string(kPrefix) + ".epoch.csv", 1) ==
           "schema_version,run_id,event_seq,flow_id,epoch_id,start_ps,end_ps,sample_count,"
           "raw_floor_ps,raw_spread_ps,smooth_floor_ps,smooth_spread_ps,observed_region,"
           "actual_region,engaged,entropy_coverage,physical_path_coverage");
    assert(lineAt(std::string(kPrefix) + ".pathmap.csv", 1) ==
           "schema_version,run_id,flow_id,entropy,physical_path_id,resolution_status,"
           "queue_fingerprint,bottleneck_rate_gbps,contains_reduced_link,ordered_queue_ids");
    assert(lineAt(std::string(kPrefix) + ".linkmap.csv", 1) ==
           "schema_version,run_id,queue_id,queue_name,rate_gbps,reduced_speed");
    assert(lineAt(std::string(kPrefix) + ".token.csv", 2) ==
           "1,run,0,1000,7,enqueue_good_ack,good_ack,17,3,0,1,19");

    removeTraceFiles(kPrefix);
}
