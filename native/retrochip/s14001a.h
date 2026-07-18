// Ported from MAME src/devices/sound/s14001a.cpp / s14001a.h
// Original license: BSD-3-Clause
// Original copyright-holders: Ed Bernard, Jonathan Gevaryahu, hap
// Original thanks-to: Kevin Horton
//
// Trimmed to standalone operation: device_t/device_sound_interface/
// device_rom_interface/save_item/devcb plumbing has been removed. The real
// chip is a direct word-index synthesizer (unlike tms5110.h's VSM-pointer
// scheme) - data_w() takes the 6-bit word number itself, and the chip walks
// its own per-word length/repeat/mirroring control bits baked into the ROM
// starting at that word's slot; there is no address-load step. start()
// here folds the real chip's START low-high-low pin pulse (see
// s14001a_device::start_w()) into a single call, since this port only ever
// speaks one word per trigger - never holds START high across multiple
// external clocks the way hardware bring-up sometimes does. The state
// machine (Clock()) and helper math (Mux8To2/CalculateIncrement/
// CalculateOutput) are otherwise unchanged from the original source.
#pragma once

#include <cstddef>
#include <cstdint>

namespace retrochip {

class S14001a {
public:
    S14001a();

    // Points the chip at its 2K mask ROM. Caller owns the buffer's lifetime.
    void set_rom(const uint8_t *data, size_t size) { m_rom = data; m_rom_size = size; }

    // Equivalent to data_w(): latches the 6-bit word number (0-63) to speak
    // on the next start().
    void write_word_index(uint8_t word) { m_uWord = word & 0x3f; }

    // Equivalent to pulsing START low-high-low (start_w(1) then start_w(0)):
    // begins speaking the word most recently latched by write_word_index().
    void start();

    // Equivalent to /BUSY: true while the chip is still speaking (or still
    // latching the word/control bits before PLAY - matches busy_r()).
    bool talking() const { return m_bBusyP1; }

    // Generate `count` samples (16-bit signed PCM) into buf. One call to
    // Clock() per sample, exactly matching sound_stream_update() - real
    // audio output only changes on alternating internal clock edges, so
    // consecutive samples repeat every other call.
    void generate(int16_t *buf, unsigned count);

private:
    enum class State : uint8_t { IDLE, WORDWAIT, CWARMSB, CWARLSB, DARMSB, CTRLBITS, PLAY, DELAY };

    uint8_t read_mem(uint16_t offset) const;
    void clock();

    const uint8_t *m_rom = nullptr;
    size_t m_rom_size = 0;

    bool m_bPhase1 = false;
    State m_uStateP1 = State::IDLE;
    State m_uStateP2 = State::IDLE;

    uint16_t m_uDAR13To05P1 = 0;
    uint16_t m_uDAR13To05P2 = 0;
    uint16_t m_uDAR04To00P1 = 0;
    uint16_t m_uDAR04To00P2 = 0;
    uint16_t m_uCWARP1 = 0;
    uint16_t m_uCWARP2 = 0;

    bool m_bStopP1 = false;
    bool m_bStopP2 = false;
    bool m_bVoicedP1 = false;
    bool m_bVoicedP2 = false;
    bool m_bSilenceP1 = false;
    bool m_bSilenceP2 = false;
    uint8_t m_uLengthP1 = 0;
    uint8_t m_uLengthP2 = 0;
    uint8_t m_uXRepeatP1 = 0;
    uint8_t m_uXRepeatP2 = 0;
    uint8_t m_uDeltaOldP1 = 0;
    uint8_t m_uDeltaOldP2 = 0;
    uint8_t m_uOutputP1 = 7;
    uint8_t m_uOutputP2 = 7;

    bool m_bDAR04To00CarryP2 = false;
    bool m_bPPQCarryP2 = false;
    bool m_bRepeatCarryP2 = false;
    bool m_bLengthCarryP2 = false;
    uint16_t m_uRomAddrP1 = 0;
    uint16_t m_uRomAddrP2 = 0;

    bool m_bBusyP1 = false;
    bool m_bStart = false;
    uint8_t m_uWord = 0;
};

} // namespace retrochip
