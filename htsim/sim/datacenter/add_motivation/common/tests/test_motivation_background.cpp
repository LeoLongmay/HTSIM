#include "motivation_background.h"

#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

#include "pipe.h"
#include "queue.h"

namespace {

constexpr const char* kHeader =
    "background_id,src,dst,path_index,rate_gbps,start_ps,stop_ps";
constexpr const char* kConfig = "/tmp/motivation_background_test.csv";
constexpr const char* kMissingConfig = "/tmp/motivation_background_missing.csv";
constexpr const char* kTracePrefix = "/tmp/motivation_background_trace";

const char* const kTraceSuffixes[] = {
    ".ack.csv", ".token.csv", ".epoch.csv", ".background.csv", ".pathmap.csv",
    ".linkmap.csv"};

void removeFiles() {
    std::remove(kConfig);
    std::remove(kMissingConfig);
    for (const char* suffix : kTraceSuffixes) {
        std::remove((std::string(kTracePrefix) + suffix).c_str());
    }
}

struct Cleanup {
    ~Cleanup() { removeFiles(); }
};

void writeConfig(const std::string& body) {
    std::ofstream output(kConfig, std::ios::out | std::ios::trunc);
    assert(output.good());
    output << body;
    output.close();
}

void expectInvalid(const std::string& body) {
    writeConfig(body);
    bool failed = false;
    try {
        (void)loadMotivationBackgroundConfig(kConfig);
    } catch (const std::invalid_argument&) {
        failed = true;
    }
    assert(failed);
}

void expectInvalidContaining(const std::string& body, const std::string& message) {
    writeConfig(body);
    try {
        (void)loadMotivationBackgroundConfig(kConfig);
    } catch (const std::invalid_argument& error) {
        assert(std::string(error.what()).find(message) != std::string::npos);
        return;
    }
    assert(false);
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

class ForwardingQueue : public BaseQueue {
public:
    ForwardingQueue(EventList& eventlist, const std::string& name,
                    linkspeed_bps rate = speedFromGbps(100), mem_b maximum = 0)
        : BaseQueue(rate, eventlist, nullptr), _maximum(maximum) {
        forceName(name);
    }

    void receivePacket(Packet& packet) override { packet.sendOn(); }
    void doNextEvent() override {}
    mem_b queuesize() const override { return 0; }
    mem_b maxsize() const override { return _maximum; }

private:
    mem_b _maximum;
};

void testConfigParsing() {
    writeConfig(std::string(kHeader) + "\n0,16,0,3,25,200000000,1200000000\n");
    const std::vector<MotivationBackgroundSpec> specs =
        loadMotivationBackgroundConfig(kConfig);
    assert(specs.size() == 1);
    assert(specs[0].background_id == 0);
    assert(specs[0].src == 16);
    assert(specs[0].dst == 0);
    assert(specs[0].path_index == 3);
    assert(specs[0].rate == UINT64_C(25000000000));
    assert(specs[0].start_ps == UINT64_C(200000000));
    assert(specs[0].stop_ps == UINT64_C(1200000000));

    writeConfig(std::string(kHeader) +
                "\n1,16,0,3,.123456789,200000000,1200000000\n"
                "2,17,1,2,0.000000001,200000000,1200000000\n"
                "3,18,2,1,25.0000000000,200000000,1200000000\n"
                "4,19,3,0,25.,200000000,1200000000\n"
                "5,20,4,0,0.1,200000000,1200000000\n"
                "6,21,5,0,9007199.254740991,200000000,1200000000\n"
                "7,22,6,0,9007199.254740992,200000000,1200000000\n");
    const std::vector<MotivationBackgroundSpec> exact_rates =
        loadMotivationBackgroundConfig(kConfig);
    assert(exact_rates.size() == 7);
    assert(exact_rates[0].rate == UINT64_C(123456789));
    assert(exact_rates[1].rate == UINT64_C(1));
    assert(exact_rates[2].rate == UINT64_C(25000000000));
    assert(exact_rates[3].rate == UINT64_C(25000000000));
    assert(exact_rates[4].rate == UINT64_C(100000000));
    assert(exact_rates[5].rate == (UINT64_C(1) << 53) - 1);
    assert(exact_rates[6].rate == (UINT64_C(1) << 53));

    expectInvalid(std::string(kHeader) +
                  "\n0,16,0,3,25,200000000,1200000000\n"
                  "0,17,1,2,10,300000000,900000000\n");
    expectInvalid("id,src,dst,path_index,rate_gbps,start_ps,stop_ps\n"
                  "0,16,0,3,25,200000000,1200000000\n");
    expectInvalid(std::string(kHeader) + "\n0, 16,0,3,25,200000000,1200000000\n");
    expectInvalid(std::string(kHeader) + "\n0,16,0,3,25,200000000,1200000000 \n");

    for (const char* row : {
             "x,16,0,3,25,200000000,1200000000",
             "-1,16,0,3,25,200000000,1200000000",
             "4294967296,16,0,3,25,200000000,1200000000",
             "0,4294967296,0,3,25,200000000,1200000000",
             "0,16,0,4294967296,25,200000000,1200000000",
             "0,16,0,3,25,18446744073709551616,18446744073709551617",
         }) {
        expectInvalid(std::string(kHeader) + "\n" + row + "\n");
    }

    for (const char* rate : {"nan",
                             "inf",
                             "0",
                             "-1",
                             "+1",
                             "1e0",
                             "0x1p0",
                             ".",
                             "1.2.3",
                             "0.0000000015",
                             "9007199.254740993",
                             "18446744073.709551616",
                             "18446744074"}) {
        expectInvalid(std::string(kHeader) + "\n0,16,0,3," + rate +
                      ",200000000,1200000000\n");
    }
    expectInvalidContaining(
        std::string(kHeader) +
            "\n0,16,0,3,9007199.254740990,200000000,1200000000\n",
        "does not round-trip exactly through the background trace");
    expectInvalid(std::string(kHeader) + "\n0,16,16,3,25,200000000,1200000000\n");
    expectInvalid(std::string(kHeader) + "\n0,16,0,3,25,1200000000,1200000000\n");
    expectInvalid(std::string(kHeader) + "\n0,16,0,3,25,1200000001,1200000000\n");
}

void testAbsentConfigDoesNotPerturbRng() {
    srandom(101);
    const long expected_random = random();
    srandom(101);
    assert(loadMotivationBackgroundConfig("").empty());
    assert(random() == expected_random);

    srand(202);
    const int expected_rand = rand();
    srand(202);
    assert(loadMotivationBackgroundConfig("").empty());
    assert(rand() == expected_rand);

    srandom(303);
    const long expected_missing = random();
    srandom(303);
    bool failed = false;
    try {
        (void)loadMotivationBackgroundConfig(kMissingConfig);
    } catch (const std::runtime_error&) {
        failed = true;
    }
    assert(failed);
    assert(random() == expected_missing);

    writeConfig("bad header\n");
    srandom(404);
    const long expected_malformed_random = random();
    srandom(404);
    expectInvalid("bad header\n");
    assert(random() == expected_malformed_random);

    srand(505);
    const int expected_malformed_rand = rand();
    srand(505);
    expectInvalid("bad header\n");
    assert(rand() == expected_malformed_rand);
}

void testRouteDrainBound(EventList& eventlist) {
    ForwardingQueue first(eventlist, "bounded-a", speedFromGbps(100), 1500);
    Pipe pipe(UINT64_C(1000000), eventlist);
    ForwardingQueue second(eventlist, "bounded-b", speedFromGbps(25), 3000);
    Route route;
    route.push_back(&first);
    route.push_back(&pipe);
    route.push_back(&second);
    assert(motivationBackgroundRouteDrainBound(route) == UINT64_C(2680000));

    MotivationBackgroundSink unsupported;
    Route unsupported_route;
    unsupported_route.push_back(&unsupported);
    bool unsupported_failed = false;
    try {
        (void)motivationBackgroundRouteDrainBound(unsupported_route);
    } catch (const std::invalid_argument&) {
        unsupported_failed = true;
    }
    assert(unsupported_failed);

    ForwardingQueue unbounded(eventlist, "unbounded", speedFromGbps(100), -1);
    Route unbounded_route;
    unbounded_route.push_back(&unbounded);
    bool unbounded_failed = false;
    try {
        (void)motivationBackgroundRouteDrainBound(unbounded_route);
    } catch (const std::invalid_argument&) {
        unbounded_failed = true;
    }
    assert(unbounded_failed);

    Pipe maximum_delay(std::numeric_limits<simtime_picosec>::max(), eventlist);
    Pipe overflow_delay(1, eventlist);
    Route overflow_route;
    overflow_route.push_back(&maximum_delay);
    overflow_route.push_back(&overflow_delay);
    bool overflow_failed = false;
    try {
        (void)motivationBackgroundRouteDrainBound(overflow_route);
    } catch (const std::overflow_error&) {
        overflow_failed = true;
    }
    assert(overflow_failed);
}

void testDeterministicTrafficAndTrace() {
    EventList eventlist;
    eventlist.setEndtime(UINT64_C(7000000));
    testRouteDrainBound(eventlist);

    MotivationTraceWriter writer;
    writer.configure(kTracePrefix, "background-run", "m2", 77, -1);

    const MotivationBackgroundSpec ceil_spec{
        8, 18, 2, 1, UINT64_C(7000000000), UINT64_C(1000000), UINT64_C(2000000)};
    MotivationBackgroundSource ceil_source(eventlist, ceil_spec, writer, "ceil-queue");
    assert(ceil_source.period() == UINT64_C(1714286));
    bool zero_rate_failed = false;
    try {
        const MotivationBackgroundSpec zero_rate_spec{
            7, 19, 3, 1, 0, UINT64_C(1000000), UINT64_C(2000000)};
        MotivationBackgroundSource zero_rate_source(
            eventlist, zero_rate_spec, writer, "zero-rate-queue");
    } catch (const std::invalid_argument&) {
        zero_rate_failed = true;
    }
    assert(zero_rate_failed);

    ForwardingQueue first(eventlist, "queue-a");
    ForwardingQueue second(eventlist, "queue-b");
    MotivationBackgroundSink sink;
    Route route;
    route.push_back(&first);
    route.push_back(&second);
    route.push_back(&sink);
    assert(motivationBackgroundQueueFingerprint(route) == "queue-a|queue-b");

    const MotivationBackgroundSpec spec{
        9, 16, 0, 3, UINT64_C(12000000000), UINT64_C(2000000), UINT64_C(5000000)};
    MotivationBackgroundSource source(eventlist, spec, writer, "queue-a|queue-b");
    assert(source.period() == UINT64_C(1000000));
    source.connect(route, sink);

    Pipe delayed_pipe(UINT64_C(200000), eventlist);
    MotivationBackgroundSink delayed_sink;
    Route delayed_route;
    delayed_route.push_back(&delayed_pipe);
    delayed_route.push_back(&delayed_sink);
    const MotivationBackgroundSpec delayed_spec{
        10, 17, 1, 0, UINT64_C(12000000000), UINT64_C(5200000), UINT64_C(5400000)};
    MotivationBackgroundSource delayed_source(
        eventlist, delayed_spec, writer, "delayed-queue");
    delayed_source.connect(delayed_route, delayed_sink);

    while (eventlist.doNextEvent()) {
    }
    assert(source.sentBytes() == 4500);
    assert(sink.deliveredBytes() == 4500);
    assert(delayed_source.sentBytes() == 1500);
    assert(delayed_sink.deliveredBytes() == 1500);
    writer.close();

    const std::string trace = std::string(kTracePrefix) + ".background.csv";
    assert(lineAt(trace, 2) ==
           "2,background-run,0,2000000,9,start,16,0,3,12,0,queue-a|queue-b");
    assert(lineAt(trace, 3) ==
           "2,background-run,1,5000000,9,finish,16,0,3,12,4500,queue-a|queue-b");
    assert(lineAt(trace, 4) ==
           "2,background-run,2,5200000,10,start,17,1,0,12,0,delayed-queue");
    assert(lineAt(trace, 5) ==
           "2,background-run,3,5400000,10,finish,17,1,0,12,0,delayed-queue");
}

}  // namespace

int main() {
    removeFiles();
    Cleanup cleanup;
    testConfigParsing();
    testAbsentConfigDoesNotPerturbRng();
    testDeterministicTrafficAndTrace();
}
