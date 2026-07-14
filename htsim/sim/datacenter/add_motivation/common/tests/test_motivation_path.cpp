#include "motivation_trace.h"
#include "queue.h"
#include "uec.h"

#include <cassert>
#include <cstdio>
#include <fstream>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

constexpr const char* kPrefix = "/tmp/motivation_path_test";

void removeTraceFiles() {
    for (const char* suffix : {".ack.csv", ".token.csv", ".epoch.csv", ".background.csv",
                               ".pathmap.csv", ".linkmap.csv"}) {
        std::remove((std::string(kPrefix) + suffix).c_str());
    }
}

std::vector<std::string> dataRows(const std::string& suffix) {
    std::ifstream input(std::string(kPrefix) + suffix);
    assert(input.is_open());

    std::vector<std::string> rows;
    std::string line;
    std::getline(input, line);
    while (std::getline(input, line)) {
        rows.push_back(line);
    }
    return rows;
}

std::vector<std::string> fields(const std::string& row) {
    std::vector<std::string> result;
    std::string field;
    bool quoted = false;
    for (size_t index = 0; index < row.size(); ++index) {
        const char value = row[index];
        if (value == '"') {
            if (quoted && index + 1 < row.size() && row[index + 1] == '"') {
                field.push_back('"');
                ++index;
            } else {
                quoted = !quoted;
            }
        } else if (value == ',' && !quoted) {
            result.push_back(field);
            field.clear();
        } else {
            field.push_back(value);
        }
    }
    assert(!quoted);
    result.push_back(field);
    return result;
}

void emitsStablePathAndDeduplicatedLinkMetadata() {
    removeTraceFiles();
    UecSrc::configureMotivationTrace(kPrefix, "run", "path_fixture", 13, -1);
    UecSrc::initNsccParams(timeFromUs(uint32_t{12}), speedFromGbps(100),
                           timeFromUs(uint32_t{12}), 0, false);

    EventList event_list;
    UecNIC nic(0, event_list, speedFromGbps(100), 1);
    UecSrc source(nullptr, event_list, std::make_unique<UecMpEcmp>(3, false), nic, 1);
    source.setFlowId(77);
    source.setDst(9);

    Queue first_a(speedFromGbps(100), 10000, event_list, nullptr);
    Queue first_b(speedFromGbps(25), 10000, event_list, nullptr);
    Queue second_a(speedFromGbps(100), 10000, event_list, nullptr);
    Queue second_b(speedFromGbps(25), 10000, event_list, nullptr);
    first_a.forceName("queue-a,100");
    first_b.forceName("queue-b,25");
    second_a.forceName("queue-a,100");
    second_b.forceName("queue-b,25");

    int resolver_calls = 0;
    source.motivationSetPathResolver(
        [&](uint32_t flow_id, uint32_t entropy, std::vector<const BaseQueue*>& queues) {
            ++resolver_calls;
            assert(flow_id == 77);
            if (entropy == 0) {
                queues = {&first_a, &first_b};
                return true;
            }
            if (entropy == 1) {
                queues = {&second_a, &second_b};
                return true;
            }
            return false;
        },
        3);
    UecSrc::motivationTrace().close();

    assert(resolver_calls == 3);
    const auto paths = dataRows(".pathmap.csv");
    const auto links = dataRows(".linkmap.csv");
    assert(paths.size() == 3);
    assert(links.size() == 2);

    const auto path0 = fields(paths[0]);
    const auto path1 = fields(paths[1]);
    const auto path2 = fields(paths[2]);
    assert(path0.size() == 10);
    assert(path1.size() == 10);
    assert(path2.size() == 10);
    assert(path0[4] == path1[4]);
    assert(path0[5] == "resolved");
    assert(path1[5] == "resolved");
    assert(path0[6] == "queue-a,100|queue-b,25");
    assert(path0[7] == "25");
    assert(path0[8] == "1");
    assert(path0[9] == path1[9]);
    assert(path2[4] == std::to_string(UINT64_MAX));
    assert(path2[5] == "resolution_failed");
    assert(path2[6].empty());
    assert(path2[7] == "-1");
    assert(path2[8] == "0");
    assert(path2[9].empty());

    const auto link0 = fields(links[0]);
    const auto link1 = fields(links[1]);
    assert(link0.size() == 6);
    assert(link1.size() == 6);
    assert(link0[3] == "queue-a,100");
    assert(link0[4] == "100");
    assert(link0[5] == "0");
    assert(link1[3] == "queue-b,25");
    assert(link1[4] == "25");
    assert(link1[5] == "1");

    assert(first_a.bitrate() == speedFromGbps(100));
    assert(first_a.queueName() == "queue-a,100");
    UecSrc::configureMotivationTrace("", "", "", 0, -1);
    resolver_calls = 0;
    source.motivationSetPathResolver(
        [&](uint32_t, uint32_t, std::vector<const BaseQueue*>&) {
            ++resolver_calls;
            return false;
        },
        2);
    assert(resolver_calls == 0);
    removeTraceFiles();
}

void validatesMotivationTraceStartupConstraints() {
    UecSrc::configureMotivationTrace(kPrefix, "run", "validation_fixture", 19, -1);

    UecSrc::_sender_based_cc = true;
    UecSrc::_receiver_based_cc = false;
    UecSrc::validateMotivationTraceRuntimeConfig(true, 1);

    bool rejected = false;
    try {
        UecSrc::validateMotivationTraceRuntimeConfig(false, 1);
    } catch (const std::invalid_argument& error) {
        rejected = true;
        assert(std::string(error.what()) ==
               "Motivation tracing path metadata currently supports only Legacy REPS "
               "runs: require -load_balancing_algo reps or reps_legacy, -planes 1, "
               "sender-side CC active, and receiver-side CC inactive.");
    }
    assert(rejected);

    UecSrc::configureMotivationTrace("", "", "", 0, -1);
    UecSrc::_sender_based_cc = false;
    UecSrc::_receiver_based_cc = true;
    UecSrc::validateMotivationTraceRuntimeConfig(false, 4);
    removeTraceFiles();
}

}  // namespace

int main() {
    emitsStablePathAndDeduplicatedLinkMetadata();
    validatesMotivationTraceStartupConstraints();
}
