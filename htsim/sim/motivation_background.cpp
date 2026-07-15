// -*- c-basic-offset: 4; indent-tabs-mode: nil -*-
#include "motivation_background.h"

#include <algorithm>
#include <charconv>
#include <cctype>
#include <fstream>
#include <iomanip>
#include <limits>
#include <locale>
#include <sstream>
#include <stdexcept>
#include <unordered_set>
#include <utility>

#include "cbrpacket.h"
#include "pipe.h"
#include "queue.h"

namespace {

constexpr const char* kConfigHeader =
    "background_id,src,dst,path_index,rate_gbps,start_ps,stop_ps";
constexpr uint64_t kPacketBitsPicoseconds =
    static_cast<uint64_t>(kMotivationBackgroundPacketBytes) * 8 *
    UINT64_C(1000000000000);
// Keep trace-rate arithmetic in the range where integer bps are exactly representable as double.
constexpr linkspeed_bps kMaximumExactTraceRate = UINT64_C(1) << 53;

class MotivationBackgroundPacket final : public CbrPacket {
public:
    static MotivationBackgroundPacket* newpkt(PacketFlow& flow, route_t& route,
                                              packetid_t id, uint32_t size) {
        MotivationBackgroundPacket* packet = _packetdb.allocPacket();
        packet->set_route(flow, route, size, id);
        return packet;
    }

    PktPriority priority() const override { return Packet::PRIO_LO; }
    void free() override { _packetdb.freePacket(this); }

private:
    static PacketDB<MotivationBackgroundPacket> _packetdb;
};

PacketDB<MotivationBackgroundPacket> MotivationBackgroundPacket::_packetdb;

std::vector<std::string> splitFields(const std::string& line) {
    std::vector<std::string> fields;
    size_t begin = 0;
    while (true) {
        const size_t comma = line.find(',', begin);
        fields.push_back(line.substr(begin, comma - begin));
        if (comma == std::string::npos) {
            break;
        }
        begin = comma + 1;
    }
    return fields;
}

void validateFieldWhitespace(const std::string& field, size_t line_number) {
    if (field.empty() || std::isspace(static_cast<unsigned char>(field.front())) ||
        std::isspace(static_cast<unsigned char>(field.back()))) {
        throw std::invalid_argument("invalid motivation background field on line " +
                                    std::to_string(line_number));
    }
}

template <typename Integer>
Integer parseInteger(const std::string& field, const char* name, size_t line_number) {
    Integer value = 0;
    const char* begin = field.data();
    const char* end = begin + field.size();
    const auto result = std::from_chars(begin, end, value, 10);
    if (result.ec != std::errc() || result.ptr != end) {
        throw std::invalid_argument("invalid " + std::string(name) + " on line " +
                                    std::to_string(line_number));
    }
    return value;
}

linkspeed_bps parseRate(const std::string& field, size_t line_number) {
    const size_t decimal = field.find('.');
    if (decimal != std::string::npos && field.find('.', decimal + 1) != std::string::npos) {
        throw std::invalid_argument("invalid rate_gbps on line " +
                                    std::to_string(line_number));
    }

    const size_t whole_digits = decimal == std::string::npos ? field.size() : decimal;
    const size_t fractional_begin = decimal == std::string::npos ? field.size() : decimal + 1;
    if (whole_digits == 0 && fractional_begin == field.size()) {
        throw std::invalid_argument("invalid rate_gbps on line " +
                                    std::to_string(line_number));
    }
    for (size_t index = 0; index < field.size(); ++index) {
        if (index != decimal && (field[index] < '0' || field[index] > '9')) {
            throw std::invalid_argument("invalid rate_gbps on line " +
                                        std::to_string(line_number));
        }
    }

    linkspeed_bps whole_gbps = 0;
    if (whole_digits != 0) {
        const char* begin = field.data();
        const auto result = std::from_chars(begin, begin + whole_digits, whole_gbps, 10);
        if (result.ec != std::errc()) {
            throw std::invalid_argument("overflowing rate_gbps on line " +
                                        std::to_string(line_number));
        }
    }

    constexpr linkspeed_bps kBpsPerGbps = UINT64_C(1000000000);
    const linkspeed_bps maximum = std::numeric_limits<linkspeed_bps>::max();
    if (whole_gbps > maximum / kBpsPerGbps) {
        throw std::invalid_argument("overflowing rate_gbps on line " +
                                    std::to_string(line_number));
    }

    linkspeed_bps fractional_bps = 0;
    const size_t fractional_digits = field.size() - fractional_begin;
    const size_t converted_digits = std::min<size_t>(fractional_digits, 9);
    for (size_t index = 0; index < converted_digits; ++index) {
        fractional_bps = fractional_bps * 10 + (field[fractional_begin + index] - '0');
    }
    for (size_t index = converted_digits; index < 9; ++index) {
        fractional_bps *= 10;
    }
    for (size_t index = 9; index < fractional_digits; ++index) {
        if (field[fractional_begin + index] != '0') {
            throw std::invalid_argument("rate_gbps has fractional bps on line " +
                                        std::to_string(line_number));
        }
    }

    const linkspeed_bps whole_bps = whole_gbps * kBpsPerGbps;
    if (fractional_bps > maximum - whole_bps) {
        throw std::invalid_argument("overflowing rate_gbps on line " +
                                    std::to_string(line_number));
    }
    const linkspeed_bps rate = whole_bps + fractional_bps;
    if (rate == 0) {
        throw std::invalid_argument("rate_gbps must represent at least one bps on line " +
                                    std::to_string(line_number));
    }
    if (rate > kMaximumExactTraceRate) {
        throw std::invalid_argument("rate_gbps exceeds exact trace maximum of 2^53 bps on line " +
                                    std::to_string(line_number));
    }

    const std::string trace_rate =
        formatMotivationBackgroundRateGbps(speedAsGbps(rate));
    double parsed_trace_rate = 0;
    const char* trace_begin = trace_rate.data();
    const char* trace_end = trace_begin + trace_rate.size();
    const auto trace_result = std::from_chars(
        trace_begin, trace_end, parsed_trace_rate, std::chars_format::general);
    if (trace_result.ec != std::errc() || trace_result.ptr != trace_end ||
        speedFromGbps(parsed_trace_rate) != rate) {
        throw std::invalid_argument(
            "rate_gbps does not round-trip exactly through the background trace on line " +
            std::to_string(line_number));
    }
    return rate;
}

std::string csvField(const std::string& value) {
    if (value.find_first_of(",\"\r\n") == std::string::npos) {
        return value;
    }
    std::string escaped;
    escaped.reserve(value.size() + 2);
    escaped.push_back('"');
    for (char character : value) {
        if (character == '"') {
            escaped.push_back('"');
        }
        escaped.push_back(character);
    }
    escaped.push_back('"');
    return escaped;
}

}  // namespace

std::string formatMotivationBackgroundRateGbps(double rate_gbps) {
    std::ostringstream output;
    output.imbue(std::locale::classic());
    output << std::defaultfloat
           << std::setprecision(std::numeric_limits<double>::max_digits10)
           << rate_gbps;
    return output.str();
}

std::vector<MotivationBackgroundSpec> loadMotivationBackgroundConfig(
    const std::string& path) {
    if (path.empty()) {
        return {};
    }

    std::ifstream input(path);
    if (!input.is_open()) {
        throw std::runtime_error("failed to open motivation background config: " + path);
    }

    std::string line;
    if (!std::getline(input, line) || line != kConfigHeader) {
        throw std::invalid_argument("motivation background config header mismatch");
    }

    std::vector<MotivationBackgroundSpec> specs;
    std::unordered_set<uint32_t> background_ids;
    size_t line_number = 1;
    while (std::getline(input, line)) {
        ++line_number;
        const std::vector<std::string> fields = splitFields(line);
        if (fields.size() != 7) {
            throw std::invalid_argument("motivation background field count mismatch on line " +
                                        std::to_string(line_number));
        }
        for (const std::string& field : fields) {
            validateFieldWhitespace(field, line_number);
        }

        MotivationBackgroundSpec spec{
            parseInteger<uint32_t>(fields[0], "background_id", line_number),
            parseInteger<uint32_t>(fields[1], "src", line_number),
            parseInteger<uint32_t>(fields[2], "dst", line_number),
            parseInteger<uint32_t>(fields[3], "path_index", line_number),
            parseRate(fields[4], line_number),
            parseInteger<simtime_picosec>(fields[5], "start_ps", line_number),
            parseInteger<simtime_picosec>(fields[6], "stop_ps", line_number)};
        if (!background_ids.insert(spec.background_id).second) {
            throw std::invalid_argument("duplicate motivation background ID on line " +
                                        std::to_string(line_number));
        }
        if (spec.src == spec.dst) {
            throw std::invalid_argument("motivation background src equals dst on line " +
                                        std::to_string(line_number));
        }
        if (spec.start_ps >= spec.stop_ps) {
            throw std::invalid_argument("motivation background start must precede stop on line " +
                                        std::to_string(line_number));
        }
        specs.push_back(spec);
    }
    return specs;
}

std::string motivationBackgroundQueueFingerprint(const route_t& route) {
    std::ostringstream fingerprint;
    bool first = true;
    for (PacketSink* element : route) {
        const BaseQueue* queue = dynamic_cast<const BaseQueue*>(element);
        if (queue == nullptr) {
            continue;
        }
        if (!first) {
            fingerprint << '|';
        }
        fingerprint << queue->queueName();
        first = false;
    }
    return fingerprint.str();
}

simtime_picosec motivationBackgroundRouteDrainBound(const route_t& route) {
    if (route.size() == 0) {
        throw std::invalid_argument("motivation background route is empty");
    }

    simtime_picosec bound = 0;
    const auto add_duration = [&bound](simtime_picosec duration) {
        if (duration > std::numeric_limits<simtime_picosec>::max() - bound) {
            throw std::overflow_error("motivation background route drain bound overflow");
        }
        bound += duration;
    };

    for (PacketSink* element : route) {
        if (const auto* queue = dynamic_cast<const BaseQueue*>(element)) {
            if (queue->bitrate() == 0 || queue->maxsize() < 0) {
                throw std::invalid_argument(
                    "motivation background route has an unbounded queue: " +
                    queue->queueName());
            }
            const uint64_t queued_bytes = static_cast<uint64_t>(queue->maxsize());
            if (queued_bytes > std::numeric_limits<uint64_t>::max() -
                                   kMotivationBackgroundPacketBytes) {
                throw std::overflow_error(
                    "motivation background queue drain byte bound overflow");
            }
            const unsigned __int128 bits_picoseconds =
                static_cast<unsigned __int128>(queued_bytes +
                                               kMotivationBackgroundPacketBytes) *
                8 * UINT64_C(1000000000000);
            const unsigned __int128 duration =
                (bits_picoseconds + queue->bitrate() - 1) / queue->bitrate();
            if (duration > std::numeric_limits<simtime_picosec>::max()) {
                throw std::overflow_error(
                    "motivation background queue drain time overflow");
            }
            add_duration(static_cast<simtime_picosec>(duration));
            continue;
        }
        if (auto* pipe = dynamic_cast<Pipe*>(element)) {
            add_duration(pipe->delay());
            continue;
        }
        throw std::invalid_argument(
            "motivation background route contains an element without a drain bound");
    }
    return bound;
}

void MotivationBackgroundSink::receivePacket(Packet& packet) {
    const uint64_t packet_bytes = packet.size();
    if (packet_bytes > std::numeric_limits<uint64_t>::max() - _delivered_bytes) {
        packet.free();
        throw std::overflow_error("motivation background delivered-byte counter overflow");
    }
    _delivered_bytes += packet_bytes;
    packet.free();
}

MotivationBackgroundSource::MotivationBackgroundSource(
    EventList& eventlist, const MotivationBackgroundSpec& spec,
    MotivationTraceWriter& trace_writer, std::string queue_fingerprint)
    : EventSource(eventlist, "motivation_background_source"),
      _spec(spec),
      _trace_writer(trace_writer),
      _queue_fingerprint(std::move(queue_fingerprint)),
      _flow(nullptr),
      _period(0) {
    if (_spec.rate == 0) {
        throw std::invalid_argument("motivation background rate must be positive");
    }
    if (_spec.src == _spec.dst) {
        throw std::invalid_argument("motivation background src must differ from dst");
    }
    if (_spec.start_ps >= _spec.stop_ps) {
        throw std::invalid_argument("motivation background start must precede stop");
    }

    _period = kPacketBitsPicoseconds / _spec.rate;
    if (kPacketBitsPicoseconds % _spec.rate != 0) {
        ++_period;
    }
    if (_period == 0) {
        throw std::overflow_error("motivation background packet period is zero");
    }
}

void MotivationBackgroundSource::connect(route_t& route, MotivationBackgroundSink& sink) {
    if (_route != nullptr || _sink != nullptr) {
        throw std::logic_error("motivation background source already connected");
    }
    if (route.size() == 0 || route.at(route.size() - 1) != &sink) {
        throw std::invalid_argument("motivation background route must end at its sink");
    }
    if (_spec.start_ps < eventlist().now()) {
        throw std::invalid_argument("motivation background start is in the past");
    }
    _route = &route;
    _sink = &sink;
    // Register finish before packet events exist. Equivalent-time EventList entries retain
    // insertion order, so the finish snapshot excludes an arrival exactly at stop_ps.
    eventlist().sourceIsPending(*this, _spec.start_ps);
    eventlist().sourceIsPending(*this, _spec.stop_ps);
}

void MotivationBackgroundSource::doNextEvent() {
    const simtime_picosec now = eventlist().now();
    if (now == _spec.stop_ps) {
        if (_finished || !_started) {
            throw std::logic_error("invalid motivation background finish event");
        }
        _finished = true;
        log("finish", _sink->deliveredBytes());
        return;
    }
    if (now < _spec.start_ps || now >= _spec.stop_ps || _finished) {
        throw std::logic_error("invalid motivation background packet event");
    }
    if (!_started) {
        if (now != _spec.start_ps) {
            throw std::logic_error("motivation background missed start event");
        }
        _started = true;
        log("start", 0);
    }

    sendPacket();
    const simtime_picosec remaining = _spec.stop_ps - now;
    if (_period < remaining) {
        eventlist().sourceIsPending(*this, now + _period);
    }
}

void MotivationBackgroundSource::log(const char* operation, uint64_t delivered_bytes) {
    _trace_writer.logBackground({_trace_writer.nextEventSeq(),
                                 eventlist().now(),
                                 _spec.background_id,
                                 operation,
                                 _spec.src,
                                 _spec.dst,
                                 _spec.path_index,
                                 speedAsGbps(_spec.rate),
                                 delivered_bytes,
                                 csvField(_queue_fingerprint)});
}

void MotivationBackgroundSource::sendPacket() {
    if (_route == nullptr || _sink == nullptr) {
        throw std::logic_error("motivation background source is not connected");
    }
    if (_sent_bytes > std::numeric_limits<uint64_t>::max() -
                          kMotivationBackgroundPacketBytes) {
        throw std::overflow_error("motivation background sent-byte counter overflow");
    }
    if (_next_packet_id > std::numeric_limits<packetid_t>::max()) {
        throw std::overflow_error("motivation background packet ID overflow");
    }

    CbrPacket* packet = MotivationBackgroundPacket::newpkt(
        _flow, *_route, static_cast<packetid_t>(_next_packet_id),
        kMotivationBackgroundPacketBytes);
    ++_next_packet_id;
    _sent_bytes += kMotivationBackgroundPacketBytes;
    packet->set_src(_spec.src);
    packet->set_dst(_spec.dst);
    packet->set_pathid(_spec.path_index);
    packet->sendOn();
}
