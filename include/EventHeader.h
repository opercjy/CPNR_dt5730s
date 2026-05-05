#ifndef EVENT_HEADER_H
#define EVENT_HEADER_H
#include <cstdint>

constexpr int MAX_CH = 8;

#pragma pack(push, 1)
struct EventHeader {
  uint64_t ExtendedTTT;  // 8 Bytes: TTT Rollover Correction (Absolute Time)
  uint32_t EventID;      // 4 Bytes: Board internal event counter
  uint32_t RecordLength; // 4 Bytes: Waveform length per channel
  uint16_t ChannelMask;  // 2 Bytes: Active channels
  uint16_t Pattern;      // 2 Bytes: TRG-IN and Board specific patterns
  uint32_t Reserved;     // 4 Bytes: Padding for 8-byte boundary alignment (Total: 24 Bytes)
};
#pragma pack(pop)

#endif // EVENT_HEADER_H