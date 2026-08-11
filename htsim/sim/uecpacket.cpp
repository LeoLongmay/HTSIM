#include "uecpacket.h"

PacketDB<UecDataPacket> UecDataPacket::_packetdb;
PacketDB<UecAckPacket> UecAckPacket::_packetdb;
PacketDB<UecNackPacket> UecNackPacket::_packetdb;
PacketDB<UecPullPacket> UecPullPacket::_packetdb;
PacketDB<UecRtsPacket> UecRtsPacket::_packetdb;

void UecBasePacket::resetLapsRouteMetadata() {
  _laps_pid = 0;
  _laps_pid_valid = false;
  _laps_pinned_route = false;
  _prime_catalog_index = 0;
  _prime_catalog_index_valid = false;
  _prime_pinned_route = false;
}

void UecDataPacket::resetLapsMetadata() {
  resetLapsRouteMetadata();
  _laps_send_time = 0;
  _laps_send_time_valid = false;
}

void UecAckPacket::resetLapsMetadata() {
  resetLapsRouteMetadata();
  _laps_one_way_delay = 0;
  _laps_delay_valid = false;
}

UecBasePacket::pull_quanta
UecBasePacket::quantize_floor(mem_b bytes) {
  return bytes >> UEC_PULL_SHIFT;
}

UecBasePacket::pull_quanta
UecBasePacket::quantize_ceil(mem_b bytes) {
  return (bytes + UEC_PULL_QUANTUM - 1) / UEC_PULL_QUANTUM;
}

mem_b
UecBasePacket::unquantize(UecBasePacket::pull_quanta credit_chunks) {
  return credit_chunks << UEC_PULL_SHIFT;
}
