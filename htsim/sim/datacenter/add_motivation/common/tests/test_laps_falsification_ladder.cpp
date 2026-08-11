#include "laps_rate.h"
#include "pipe.h"
#define private public
#include "uec.h"
#undef private

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <fstream>
#include <functional>
#include <iostream>
#include <memory>
#include <optional>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

EventList eventlist;

class TraceRecorder {
public:
    TraceRecorder() {
        _rows << "tier\tevent\ttime_ps\tpid\tseq\tdelay_ps\tdetail\n";
    }

    void row(const std::string& tier, const std::string& event,
             std::optional<simtime_picosec> time = {}, std::optional<uint16_t> pid = {},
             std::optional<uint64_t> seq = {}, std::optional<simtime_picosec> delay = {},
             std::string detail = {}) {
        std::replace(detail.begin(), detail.end(), '\t', ' ');
        std::replace(detail.begin(), detail.end(), '\n', ' ');
        _rows << tier << '\t' << event << '\t';
        if (time) _rows << *time;
        _rows << '\t';
        if (pid) _rows << *pid;
        _rows << '\t';
        if (seq) _rows << *seq;
        _rows << '\t';
        if (delay) _rows << *delay;
        _rows << '\t' << detail << '\n';
    }

    std::string str() const { return _rows.str(); }

private:
    std::ostringstream _rows;
};

void writeTrace(const std::string& trace) {
    const char* path = std::getenv("LAPS_LADDER_TRACE");
    if (path == nullptr || *path == '\0') return;
    std::ofstream out(path);
    if (out) out << trace;
}

class LadderFailure : public std::runtime_error {
public:
    LadderFailure(const std::string& message, const std::string& trace)
        : std::runtime_error(message), _trace(trace) {}

    const std::string& trace() const { return _trace; }

private:
    std::string _trace;
};

void require(bool condition, const std::string& message, TraceRecorder& trace) {
    if (condition) return;
    trace.row("failure", "assertion", {}, {}, {}, {}, message);
    throw LadderFailure(message, trace.str());
}

void setLapsMode(UecSrc::Sender_CC mode) {
    UecSrc::_sender_based_cc = true;
    UecSrc::_receiver_based_cc = false;
    UecSrc::_sender_cc_algo = mode;
}

std::unique_ptr<UecMpLaps> makeLapsState(uint16_t path_count, UecSrc::Sender_CC mode) {
    setLapsMode(mode);
    return std::make_unique<UecMpLaps>(path_count, false, 1.0);
}

class CallbackSink final : public PacketSink {
public:
    CallbackSink(std::string name, std::function<void(Packet&)> callback)
        : _name(std::move(name)), _callback(std::move(callback)) {}

    void receivePacket(Packet& packet) override { _callback(packet); }
    const std::string& nodename() override { return _name; }

private:
    std::string _name;
    std::function<void(Packet&)> _callback;
};

struct DataObservation {
    uint16_t pid;
    UecDataPacket::seq_t seq;
    simtime_picosec send_time;
    simtime_picosec sink_time;
};

struct AckObservation {
    uint16_t pid;
    UecDataPacket::seq_t seq;
    simtime_picosec one_way_delay;
    simtime_picosec source_time;
    std::vector<UecMpLapsSnapshot> before;
    std::vector<UecMpLapsSnapshot> after;
};

using ProbeAckObservation = AckObservation;

class LapsEndToEndFixture {
public:
    LapsEndToEndFixture(uint16_t path_count, UecSrc::Sender_CC mode,
                        simtime_picosec one_way_delay)
        : source_nic(0, eventlist, speedFromGbps(100), 1),
          sink_nic(1, eventlist, speedFromGbps(100), 1),
          source(nullptr, eventlist, makeLapsState(path_count, mode), source_nic, 1),
          sink(nullptr, nullptr, sink_nic, 1),
          _path_count(path_count),
          data_endpoint("ladder-data", [this](Packet& packet) { receiveData(packet); }),
          ack_endpoint("ladder-ack", [this](Packet& packet) { receiveAck(packet); }) {
        LapsRoutePairs pairs;
        for (uint16_t pid = 0; pid != path_count; ++pid) {
            forward_pipes.push_back(
                std::make_unique<Pipe>(one_way_delay, EventList::getTheEventList()));
            reverse_pipes.push_back(
                std::make_unique<Pipe>(one_way_delay / 2, EventList::getTheEventList()));
            auto forward = std::make_unique<Route>();
            auto reverse = std::make_unique<Route>();
            forward->push_back(forward_pipes.back().get());
            forward->push_back(&data_endpoint);
            reverse->push_back(reverse_pipes.back().get());
            reverse->push_back(&ack_endpoint);
            forward->set_reverse(reverse.get());
            reverse->set_reverse(forward.get());
            pairs.push_back({std::move(forward), std::move(reverse)});
        }
        catalog = LapsPathCatalog::build(std::move(pairs), 0, speedFromGbps(100),
                                         UecSrc::_mtu, path_count);
        ordinary_reverse_pipe =
            std::make_unique<Pipe>(one_way_delay / 2, EventList::getTheEventList());
        reverse_fib.push_back(ordinary_reverse_pipe.get());
        reverse_fib.push_back(&ack_endpoint);
        // Keep the fixture's normal flow-start event beyond every deterministic
        // assertion. Data sends below are deliberately driven one at a time.
        source.connectPort(0, forward_fib, reverse_fib, sink,
                           EventList::now() + timeFromSec(uint32_t{1}));
        source.lapsSetPathCatalog(0, catalog);
        sink.lapsSetPathCatalog(source, 0, catalog);
        for (uint16_t pid = 0; pid != path_count; ++pid) {
            const auto initial = laps().lapsPathSnapshot(pid);
            if (!initial) throw std::runtime_error("catalog did not configure LAPS path");
            laps().observeLapsDelay(pid, initial->base_val, EventList::now());
        }
        source._flow_size = 100'000'000;
        source._done_sending = false;
        source._last_event_time.emplace(EventList::now());
        source._flow_start_time = EventList::now();
        source._speculating = false;
    }

    UecMpLaps& laps() {
        auto* state = dynamic_cast<UecMpLaps*>(source._mp.get());
        if (state == nullptr) throw std::runtime_error("fixture has no UecMpLaps");
        return *state;
    }

    std::vector<UecMpLapsSnapshot> snapshots() {
        std::vector<UecMpLapsSnapshot> result;
        for (uint16_t pid = 0; pid != _path_count; ++pid) {
            const auto snapshot = laps().lapsSnapshot(pid, EventList::now());
            if (!snapshot) throw std::runtime_error("missing composite LAPS snapshot");
            result.push_back(*snapshot);
        }
        return result;
    }

    bool sendOneDataPacket() {
        const size_t ack_count = acks.size();
        source._backlog = 2 * UecSrc::_mtu;
        const mem_b sent = source.sendNewPacket(forward_fib);
        source._backlog = 0;
        if (sent == 0) return false;
        while (acks.size() == ack_count && EventList::doNextEvent()) {
        }
        return acks.size() == ack_count + 1;
    }

    void sendOneDataPacketWithoutAckRequest() {
        source._backlog = 2 * UecSrc::_mtu;
        const mem_b sent = source.sendNewPacket(forward_fib);
        source._backlog = 0;
        if (sent == 0) throw std::runtime_error("selected data send was not eligible");
    }

    void runUntil(simtime_picosec target) {
        class Marker final : public EventSource {
        public:
            explicit Marker(EventList& events) : EventSource(events, "ladder marker") {}
            void doNextEvent() override { fired = true; }
            bool fired = false;
        } marker(eventlist);
        EventList::sourceIsPending(marker, target);
        while (!marker.fired && EventList::doNextEvent()) {
        }
    }

    UecNIC source_nic;
    UecNIC sink_nic;
    UecSrc source;
    UecSink sink;
    Route forward_fib;
    Route reverse_fib;
    std::shared_ptr<const LapsPathCatalog> catalog;
    std::vector<DataObservation> data;
    std::vector<AckObservation> acks;
    std::vector<ProbeAckObservation> probe_acks;
    std::vector<simtime_picosec> probe_send_times;

private:
    void receiveData(Packet& packet) {
        auto& data_packet = static_cast<UecDataPacket&>(packet);
        if (data_packet.packet_type() == UecBasePacket::DATA_PROBE) {
            probe_send_times.push_back(data_packet.lapsSendTime());
        } else {
            data.push_back({data_packet.lapsPid(), data_packet.epsn(),
                            data_packet.lapsSendTime(), EventList::now()});
        }
        sink.receivePacket(packet, 0);
    }

    void receiveAck(Packet& packet) {
        auto& ack = static_cast<UecAckPacket&>(packet);
        if (ack.is_probe_ack()) {
            ProbeAckObservation observation{ack.lapsPid(), ack.acked_psn(), ack.lapsOneWayDelay(),
                                             EventList::now(), snapshots(), {}};
            source.receivePacket(packet, 0);
            observation.after = snapshots();
            probe_acks.push_back(std::move(observation));
            return;
        }
        AckObservation observation{ack.lapsPid(), ack.acked_psn(), ack.lapsOneWayDelay(),
                                   EventList::now(), snapshots(), {}};
        source.receivePacket(packet, 0);
        observation.after = snapshots();
        acks.push_back(std::move(observation));
    }

    uint16_t _path_count;
    CallbackSink data_endpoint;
    CallbackSink ack_endpoint;
    std::vector<std::unique_ptr<Pipe>> forward_pipes;
    std::vector<std::unique_ptr<Pipe>> reverse_pipes;
    std::unique_ptr<Pipe> ordinary_reverse_pipe;
};

struct ControlTrace {
    std::vector<simtime_picosec> probe_send_offsets;
    std::vector<std::pair<uint64_t, simtime_picosec>> ack_offsets;
};

ControlTrace runControlTrace(UecSrc::Sender_CC mode) {
    TraceRecorder trace_recorder;
    const simtime_picosec start = EventList::now();
    LapsEndToEndFixture fixture(1, mode, timeFromUs(uint32_t{1}));
    fixture.source.scheduleLapsProbe();
    fixture.runUntil(start + timeFromUs(uint32_t{5}));
    require(fixture.sendOneDataPacket(), "first control packet did not receive its common ACK",
            trace_recorder);
    fixture.sendOneDataPacketWithoutAckRequest();
    fixture.runUntil(EventList::now() + 3 * timeFromUs(uint32_t{1}));

    ControlTrace trace;
    for (const auto time : fixture.probe_send_times) trace.probe_send_offsets.push_back(time - start);
    for (const auto& ack : fixture.acks) trace.ack_offsets.push_back({ack.seq, ack.source_time - start});
    return trace;
}

void paired_control_trace_matches_until_the_intentional_ack_difference() {
    TraceRecorder trace;
    const ControlTrace legacy = runControlTrace(UecSrc::LAPS_CONTROL);
    const ControlTrace paperack = runControlTrace(UecSrc::LAPS_CONTROL_PAPERACK);
    require(legacy.ack_offsets.size() == 1, "legacy control unexpectedly ACKed the second packet", trace);
    require(paperack.ack_offsets.size() == 2, "paperack did not ACK the second packet", trace);
    require(legacy.ack_offsets.front() == paperack.ack_offsets.front(),
            "common first ACK event differed between paired traces", trace);
    const auto intentional_ack = paperack.ack_offsets[1];
    trace.row("T0", "intentional_ack_difference", intentional_ack.second, {}, intentional_ack.first);
    const auto through = [intentional_ack](const std::vector<simtime_picosec>& values) {
        std::vector<simtime_picosec> result;
        std::copy_if(values.begin(), values.end(), std::back_inserter(result),
                     [intentional_ack](simtime_picosec value) { return value <= intentional_ack.second; });
        return result;
    };
    const auto legacy_probes = through(legacy.probe_send_offsets);
    const auto paperack_probes = through(paperack.probe_send_offsets);
    for (const auto time : legacy_probes) trace.row("T0", "legacy_probe_sent", time);
    for (const auto time : paperack_probes) trace.row("T0", "paperack_probe_sent", time);
    require(!legacy_probes.empty(), "paired trace observed no probe before the ACK divergence", trace);
    require(legacy_probes == paperack_probes,
            "control probe-send timestamps differed before the intentional ACK event", trace);
}

void one_path_source_sink_ack_refreshes_the_only_pid() {
    TraceRecorder trace;
    LapsEndToEndFixture fixture(1, UecSrc::LAPS, timeFromUs(uint32_t{1}));
    for (uint32_t cycle = 0; cycle != 4; ++cycle) {
        require(fixture.sendOneDataPacket(), "eligible one-path data send produced no ACK", trace);
        const DataObservation& data = fixture.data.back();
        const AckObservation& ack = fixture.acks.back();
        trace.row("T1", "data_acked", ack.source_time, ack.pid, ack.seq, ack.one_way_delay);
        require(data.pid == 0 && ack.pid == 0 && ack.seq == data.seq,
                "one-path ACK did not preserve the selected data PID/sequence", trace);
        require(data.send_time < data.sink_time && data.sink_time < ack.source_time,
                "data did not traverse source-to-sink-to-source event times", trace);
        require(ack.one_way_delay == data.sink_time - data.send_time,
                "ACK did not carry the selected packet's one-way delay", trace);
        const auto& before = ack.before[0];
        const auto& state = ack.after[0];
        require(before.path.updated_at < ack.source_time,
                "one-path pre-ACK snapshot was not captured before source processing", trace);
        require(before.signal.calibrated && before.signal.sampled_paths == 1 &&
                    state.signal.calibrated && state.signal.sampled_paths == 1,
                "one-path composite snapshots omitted the aggregate LAPS signal", trace);
        trace.row("T1", "pit_after", state.path.updated_at, 0, ack.seq, state.path.real_val,
                  "selectable=" + std::to_string(state.path.selectable) +
                      " pending=" + std::to_string(state.path.probe_pending) +
                      " deadline=" +
                      (state.path.deadline ? std::to_string(*state.path.deadline) : "none"));
        require(state.path.selectable && !state.path.probe_pending &&
                    state.path.updated_at == ack.source_time &&
                    state.path.real_val == ack.one_way_delay &&
                    state.path.deadline == ack.source_time + 2 * ack.one_way_delay + 1,
                "source ACK processing did not refresh the one-path PIT snapshot", trace);
        require(fixture.source._laps_probe_sent == 0,
                "active probe fired while one-path data ACKs refreshed before the deadline", trace);
    }

    const auto before_probe = fixture.laps().lapsSnapshot(0, EventList::now());
    require(before_probe && before_probe->path.deadline,
            "one-path composite snapshot has no probe deadline", trace);
    const simtime_picosec expected_probe_at = *before_probe->path.deadline;
    fixture.runUntil(expected_probe_at + timeFromUs(uint32_t{1}) + 1);
    require(fixture.source._laps_probe_sent == 1 &&
                !fixture.probe_send_times.empty() &&
                fixture.probe_send_times.back() == expected_probe_at,
            "strict LAPS probe did not fire at the immutable snapshot deadline", trace);
    fixture.runUntil(expected_probe_at + 2 * timeFromUs(uint32_t{1}));
    const auto after_probe = fixture.laps().lapsSnapshot(0, EventList::now());
    require(after_probe && after_probe->path.selectable && !after_probe->path.probe_pending,
            "probe ACK did not restore the one-path PID", trace);
    require(fixture.sendOneDataPacket(), "eligible send did not resume after probe ACK", trace);
}

bool samePath(const UecMpLapsPathSnapshot& lhs, const UecMpLapsPathSnapshot& rhs) {
    return lhs.valid == rhs.valid && lhs.selectable == rhs.selectable &&
           lhs.probe_pending == rhs.probe_pending && lhs.base_val == rhs.base_val &&
           lhs.real_val == rhs.real_val && lhs.updated_at == rhs.updated_at &&
           lhs.deadline == rhs.deadline;
}

void eight_path_source_sink_ack_changes_only_selected_pid() {
    TraceRecorder trace;
    srandom(47);
    LapsEndToEndFixture fixture(8, UecSrc::LAPS, timeFromUs(uint32_t{1}));
    std::set<uint16_t> covered;
    for (uint32_t attempt = 0; attempt != 128 && covered.size() != 8; ++attempt) {
        require(fixture.sendOneDataPacket(), "eight-path eligible data send produced no ACK", trace);
        const DataObservation& data = fixture.data.back();
        const AckObservation& ack = fixture.acks.back();
        covered.insert(data.pid);
        trace.row("T2", "data_acked", ack.source_time, ack.pid, ack.seq, ack.one_way_delay);
        require(data.pid == ack.pid && data.seq == ack.seq,
                "ACK PID/sequence did not match the selected data packet", trace);
        require(fixture.laps().localPid(data.pid) == data.pid,
                "selected entropy did not map back to its local PID", trace);
        require(ack.one_way_delay == data.sink_time - data.send_time,
                "eight-path ACK carried the wrong one-way sample", trace);
        require(ack.before[ack.pid].path.updated_at < ack.source_time,
                "selected PID pre-ACK snapshot was not captured before source processing", trace);
        require(ack.before[ack.pid].signal.calibrated &&
                    ack.before[ack.pid].signal.sampled_paths != 0 &&
                    ack.after[ack.pid].signal.calibrated &&
                    ack.after[ack.pid].signal.sampled_paths != 0,
                "eight-path composite snapshots omitted the aggregate LAPS signal", trace);
        for (uint16_t pid = 0; pid != 8; ++pid) {
            if (pid == ack.pid) {
                const auto& state = ack.after[pid].path;
                require(state.selectable && !state.probe_pending &&
                            state.updated_at == ack.source_time &&
                            state.real_val == ack.one_way_delay &&
                            state.deadline == ack.source_time + 2 * ack.one_way_delay + 1,
                        "selected ACK did not refresh the selected PID", trace);
            } else {
                require(samePath(ack.before[pid].path, ack.after[pid].path),
                        "source ACK processing changed a non-selected PID", trace);
            }
        }
        require(fixture.laps().hasSelectablePath(),
                "continuous eight-path ACK traffic left every PID pending", trace);
    }
    require(covered.size() == 8, "deterministic eight-path fixture did not cover every PID", trace);
    require(!fixture.probe_acks.empty(),
            "eight-path event fixture did not exercise an active probe ACK", trace);
    uint32_t pending_probe_acks = 0;
    for (const auto& probe : fixture.probe_acks) {
        trace.row("T2", "probe_acked", probe.source_time, probe.pid, probe.seq,
                  probe.one_way_delay);
        trace.row("T2", "probe_pit_before", probe.before[probe.pid].path.updated_at,
                  probe.pid, probe.seq, probe.before[probe.pid].path.real_val,
                  "selectable=" + std::to_string(probe.before[probe.pid].path.selectable) +
                      " pending=" + std::to_string(probe.before[probe.pid].path.probe_pending));
        trace.row("T2", "probe_pit_after", probe.after[probe.pid].path.updated_at,
                  probe.pid, probe.seq, probe.after[probe.pid].path.real_val,
                  "selectable=" + std::to_string(probe.after[probe.pid].path.selectable) +
                      " pending=" + std::to_string(probe.after[probe.pid].path.probe_pending));
        if (probe.before[probe.pid].path.probe_pending) {
            ++pending_probe_acks;
            require(!probe.before[probe.pid].path.selectable &&
                        probe.after[probe.pid].path.selectable &&
                        !probe.after[probe.pid].path.probe_pending &&
                        probe.after[probe.pid].path.updated_at == probe.source_time,
                    "probe ACK did not restore the probed PID", trace);
        }
        for (uint16_t pid = 0; pid != 8; ++pid) {
            if (pid != probe.pid) {
                require(samePath(probe.before[pid].path, probe.after[pid].path),
                        "probe ACK changed a non-probed PID", trace);
            }
        }
    }
    require(pending_probe_acks != 0,
            "no probe ACK observed a still-pending PID", trace);
    require(fixture.laps().hasSelectablePath(),
            "continuous ACK traffic left every PID probe-pending", trace);
    require(fixture.sendOneDataPacket(), "continuous ACK traffic lost eligible-send liveness", trace);
}

void two_path_softmax_probe_and_aimd_state_machine() {
    constexpr double beta = 0.1;
    const simtime_picosec low_delay = timeFromUs(uint32_t{10});
    const simtime_picosec high_delay = timeFromUs(uint32_t{20});
    const simtime_picosec one_paper_microsecond = timeFromUs(uint32_t{1});
    TraceRecorder trace;

    srandom(47);
    UecMpLaps laps(2, false, beta);
    laps.configurePaths({low_delay, high_delay});
    laps.observeLapsDelay(0, low_delay, timeFromUs(uint32_t{30}));
    laps.observeLapsDelay(1, high_delay, timeFromUs(uint32_t{1}));

    const double low_paper_delay = static_cast<double>(low_delay) / one_paper_microsecond;
    const double high_paper_delay = static_cast<double>(high_delay) / one_paper_microsecond;
    const double expected_low_share = std::exp(-beta * low_paper_delay) /
                                      (std::exp(-beta * low_paper_delay) +
                                       std::exp(-beta * high_paper_delay));
    uint32_t low_selections = 0;
    constexpr uint32_t choices = 20'000;
    for (uint32_t choice = 0; choice != choices; ++choice) {
        const auto selected = laps.nextLapsPid();
        require(selected.has_value(), "Softmax returned no selectable PID", trace);
        require(*selected < 2, "Softmax returned an invalid PID", trace);
        low_selections += *selected == 0;
    }
    const double observed_low_share = static_cast<double>(low_selections) / choices;
    trace.row("T3", "softmax", {}, {}, choices, {},
              "expected=" + std::to_string(expected_low_share) +
                  " observed=" + std::to_string(observed_low_share));
    require(std::abs(observed_low_share - expected_low_share) < 0.02,
            "unequal-delay Softmax share differs from Equation 1", trace);

    const UecMpLapsSignal non_high = laps.lapsSignal(timeFromUs(uint32_t{30}));
    require(non_high.calibrated && !non_high.all_paths_high &&
                non_high.target_delay == high_delay && non_high.min_delay == low_delay,
            "two-path ACK samples did not produce the expected non-high signal", trace);

    const auto before_probe = laps.lapsSnapshot(1, timeFromUs(uint32_t{30}));
    require(before_probe.has_value() && before_probe->path.deadline.has_value(),
            "PID 1 had no probe deadline after its ACK", trace);
    const simtime_picosec due_at = before_probe->path.updated_at + 2 * before_probe->path.real_val + 1;
    require(*before_probe->path.deadline == due_at,
            "PID 1 deadline is not updated_at + 2 * real_val + 1", trace);
    const auto probed = laps.nextLapsProbePid(due_at);
    require(probed == 1, "PID 1 was not selected when its deadline became due", trace);
    const auto pending = laps.lapsSnapshot(1, due_at);
    require(pending.has_value() && pending->path.probe_pending && !pending->path.selectable &&
                !pending->path.deadline.has_value(),
            "due PID 1 was not marked pending and excluded", trace);
    for (uint32_t choice = 0; choice != 32; ++choice) {
        require(laps.nextLapsPid() == 0, "probe-pending PID 1 retained Softmax weight", trace);
    }

    const simtime_picosec probe_ack_at = due_at + 1;
    laps.observeLapsProbe(1, high_delay, probe_ack_at);
    const auto restored = laps.lapsSnapshot(1, probe_ack_at);
    require(restored.has_value() && restored->path.selectable && !restored->path.probe_pending &&
                restored->path.real_val == high_delay && restored->path.updated_at == probe_ack_at,
            "probe ACK did not restore PID 1", trace);

    laps.observeLapsDelay(0, timeFromUs(uint32_t{21}), timeFromUs(uint32_t{90}));
    laps.observeLapsDelay(1, timeFromUs(uint32_t{22}), timeFromUs(uint32_t{90}));
    const UecMpLapsSignal all_high = laps.lapsSignal(timeFromUs(uint32_t{90}));
    require(all_high.calibrated && all_high.all_paths_high &&
                all_high.target_delay == high_delay && all_high.min_delay == timeFromUs(uint32_t{21}),
            "high ACK samples did not produce the expected all-high signal", trace);

    const LapsRateState initial = {speedFromGbps(100), speedFromGbps(100), 0, 0, 0};
    const linkspeed_bps nic = speedFromGbps(100);
    const LapsRateSignal all_high_rate = {all_high.calibrated, all_high.all_paths_high,
                                          all_high.target_delay, all_high.min_delay};
    const LapsRateState decreased =
        advanceLapsRate(initial, all_high_rate, timeFromUs(uint32_t{100}), nic);
    require(decreased.cur_rate == initial.cur_rate / 2,
            "all-high signal did not halve the LAPS rate", trace);
    // Algorithm 2 uses 2t, so 2 * min_delay is paper-pseudocode fidelity;
    // the prose's one adjustment per 2T is a paper-prose divergence.
    require(decreased.next_decrease_at == timeFromUs(uint32_t{100}) + 2 * all_high_rate.min_delay,
            "all-high cooldown is not Now + 2 * min_delay", trace);
    const LapsRateState held =
        advanceLapsRate(decreased, all_high_rate, timeFromUs(uint32_t{101}), nic);
    require(held.cur_rate == decreased.cur_rate,
            "all-high rate decreased again before the 2 * min_delay cooldown", trace);

    const LapsRateSignal non_high_rate = {non_high.calibrated, non_high.all_paths_high,
                                           non_high.target_delay, non_high.min_delay};
    const LapsRateState non_saturated =
        {speedFromGbps(50), speedFromGbps(100), 0, 0, 0};
    const LapsRateState increased =
        advanceLapsRate(non_saturated, non_high_rate, timeFromUs(uint32_t{100}), nic);
    require(increased.cur_rate == speedFromGbps(75),
            "non-high signal did not raise the non-saturated LAPS rate to 75 Gbps", trace);
    require(increased.inc_stage == non_saturated.inc_stage + 1,
            "non-high signal did not increment the AIMD stage once", trace);
    require(increased.next_increase_at == timeFromUs(uint32_t{100}) + 2 * non_high_rate.min_delay,
            "non-high cooldown is not Now + 2 * min_delay", trace);

    std::cout << "Tier 3 timing interpretation\n"
              << "paper-pseudocode fidelity: Algorithm 2 uses 2t and code uses 2 * min_delay\n"
              << "paper-prose divergence: prose says one adjustment per 2T\n";
}

}  // namespace

int main() {
    try {
        paired_control_trace_matches_until_the_intentional_ack_difference();
        one_path_source_sink_ack_refreshes_the_only_pid();
        eight_path_source_sink_ack_changes_only_selected_pid();
        two_path_softmax_probe_and_aimd_state_machine();
    } catch (const LadderFailure& error) {
        writeTrace(error.trace());
        std::cerr << error.what() << '\n';
        return 1;
    } catch (const std::exception& error) {
        TraceRecorder trace;
        trace.row("failure", "exception", {}, {}, {}, {}, error.what());
        writeTrace(trace.str());
        std::cerr << error.what() << '\n';
        return 1;
    }
}
