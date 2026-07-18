// Ported from MAME src/devices/sound/s14001a.cpp
// Original license: BSD-3-Clause
// Original copyright-holders: Ed Bernard, Jonathan Gevaryahu, hap
// Original thanks-to: Kevin Horton
// See s14001a.h for what was trimmed from the original device.
#include "s14001a.h"

namespace retrochip {

namespace {

uint8_t Mux8To2(bool bVoicedP2, uint8_t uPPQtrP2, uint8_t uDeltaAdrP2, uint8_t uRomDataP2) {
    // pick two bits of rom data as delta
    if (bVoicedP2 && (uPPQtrP2 & 0x01)) // mirroring
        uDeltaAdrP2 ^= 0x03; // count backwards

    // emulate 8 to 2 mux to obtain delta from byte (bigendian)
    return uRomDataP2 >> (~uDeltaAdrP2 << 1 & 0x06) & 0x03;
}

void CalculateIncrement(bool bVoicedP2, uint8_t uPPQtrP2, bool bPPQStartP2, uint8_t uDelta,
                         uint8_t uDeltaOldP2, uint8_t &uDeltaOldP1, uint8_t &uIncrementP2, bool &bAddP2) {
    // beginning of a pitch period
    if ((uPPQtrP2 == 0x00) && bPPQStartP2) // note this is done for voiced and unvoiced
        uDeltaOldP2 = 0x02;

    static constexpr uint8_t uIncrements[4][4] = {
        //    00  01  10  11
        { 3,  3,  1,  1,}, // 00
        { 1,  1,  0,  0,}, // 01
        { 0,  0,  1,  1,}, // 10
        { 1,  1,  3,  3 }, // 11
    };

    bool const MIRROR = (uPPQtrP2 & 0x01) != 0;

    // calculate increment from delta, always done even if silent to update uDeltaOld
    if (!bVoicedP2 || !MIRROR) {
        uIncrementP2 = uIncrements[uDelta][uDeltaOldP2];
        bAddP2 = uDelta >= 0x02;
    } else {
        uIncrementP2 = uIncrements[uDeltaOldP2][uDelta];
        bAddP2 = uDeltaOldP2 < 0x02;
    }
    uDeltaOldP1 = uDelta;
    if (bVoicedP2 && bPPQStartP2 && MIRROR)
        uIncrementP2 = 0; // no change when first starting mirroring
}

uint8_t CalculateOutput(bool bVoiced, bool bXSilence, uint8_t uPPQtr, bool bPPQStart,
                         uint8_t uLOutput, uint8_t uIncrementP2, bool bAddP2) {
    // limits output to 0x00 and 0x0f
    bool const SILENCE = (uPPQtr & 0x02) != 0;

    if (bXSilence || (bVoiced && SILENCE))
        return 7;

    // beginning of a pitch period
    if ((uPPQtr == 0x00) && bPPQStart) // note this is done for voiced and nonvoiced
        uLOutput = 7;

    // adder
    uint8_t uTmp = uLOutput;
    if (!bAddP2)
        uTmp ^= 0x0f; // turns subtraction into addition

    // add 0, 1, 3; limit at 15
    uTmp += uIncrementP2;
    if (uTmp > 15)
        uTmp = 15;

    if (!bAddP2)
        uTmp ^= 0x0f; // turns addition back to subtraction

    return uTmp;
}

} // namespace

S14001a::S14001a() = default;

uint8_t S14001a::read_mem(uint16_t offset) const {
    if (!m_rom || m_rom_size == 0)
        return 0;
    uint16_t idx = offset & 0xfff; // 11-bit internal address bus, per device_rom_interface<12>
    if (idx >= m_rom_size)
        idx = static_cast<uint16_t>(idx % m_rom_size); // ROM smaller than the address bus mirrors
    return m_rom[idx];
}

void S14001a::start() {
    // First half of the pulse: START rising edge kicks IDLE -> WORDWAIT
    // (see start_w()), then one full phase1/phase2 clock pair lets that
    // state transition and the word-number latch (WORDWAIT's own phase1
    // body) actually run while the pin is still high.
    if (!m_bStart)
        m_uStateP1 = State::WORDWAIT;
    m_bStart = true;
    clock();
    clock();

    // Falling edge: from here on Clock() advances CWARMSB -> ... -> PLAY.
    m_bStart = false;
}

void S14001a::generate(int16_t *buf, unsigned count) {
    for (unsigned i = 0; i < count; i++) {
        clock();
        // m_uOutputP2 ranges 0-15 (see CalculateOutput); center at 7 like
        // sound_stream_update()'s `s16 sample = m_uOutputP2 - 7` (range
        // -7..8), then scale the 4-bit DAC swing up to a usable 16-bit range.
        int16_t sample = static_cast<int16_t>(m_uOutputP2) - 7;
        buf[i] = static_cast<int16_t>(sample * 2048);
    }
}

void S14001a::clock() {
    if (m_bPhase1) {
        // transition to phase2
        m_bPhase1 = false;

        m_uStateP2 = m_uStateP1;
        m_uDAR13To05P2 = m_uDAR13To05P1;
        m_uDAR04To00P2 = m_uDAR04To00P1;
        m_uCWARP2 = m_uCWARP1;
        m_bStopP2 = m_bStopP1;
        m_bVoicedP2 = m_bVoicedP1;
        m_bSilenceP2 = m_bSilenceP1;
        m_uLengthP2 = m_uLengthP1;
        m_uXRepeatP2 = m_uXRepeatP1;
        m_uDeltaOldP2 = m_uDeltaOldP1;

        m_uOutputP2 = m_uOutputP1;
        m_uRomAddrP2 = m_uRomAddrP1;

        m_bDAR04To00CarryP2 = m_uDAR04To00P2 == 0x1f;
        m_bPPQCarryP2 = m_bDAR04To00CarryP2 && ((m_uLengthP2 & 0x03) == 0x03);
        m_bRepeatCarryP2 = m_bPPQCarryP2 && ((m_uLengthP2 & 0x0c) == 0x0c);
        m_bLengthCarryP2 = m_bRepeatCarryP2 && (m_uLengthP2 == 0x7f);
        return;
    }
    m_bPhase1 = true;

    switch (m_uStateP1) {
    case State::IDLE:
        m_uOutputP1 = 7;
        if (m_bStart)
            m_uStateP1 = State::WORDWAIT;
        m_bBusyP1 = false;
        break;

    case State::WORDWAIT:
        // the delta address register latches the word number into bits 03 to 08
        // all other bits forced to 0.  04 to 08 makes a multiply by two.
        m_uDAR13To05P1 = (m_uWord & 0x3c) >> 2;
        m_uDAR04To00P1 = (m_uWord & 0x03) << 3;
        m_uRomAddrP1 = (m_uDAR13To05P1 << 3) | (m_uDAR04To00P1 >> 2);

        m_uOutputP1 = 7;
        m_uStateP1 = m_bStart ? State::WORDWAIT : State::CWARMSB;
        m_bBusyP1 = true;
        break;

    case State::CWARMSB:
        m_uCWARP1 = static_cast<uint16_t>(read_mem(m_uRomAddrP2)) << 4;
        m_uDAR04To00P1 += 4;
        if (m_uDAR04To00P1 >= 32)
            m_uDAR04To00P1 = 0;
        m_uRomAddrP1 = (m_uDAR13To05P1 << 3) | (m_uDAR04To00P1 >> 2);

        m_uOutputP1 = 7;
        m_uStateP1 = m_bStart ? State::WORDWAIT : State::CWARLSB;
        break;

    case State::CWARLSB:
        m_uCWARP1 = m_uCWARP2 | (read_mem(m_uRomAddrP2) >> 4);
        m_uRomAddrP1 = m_uCWARP1;

        m_uOutputP1 = 7;
        m_uStateP1 = m_bStart ? State::WORDWAIT : State::DARMSB;
        break;

    case State::DARMSB:
        m_uDAR13To05P1 = static_cast<uint16_t>(read_mem(m_uRomAddrP2)) << 1;
        m_uDAR04To00P1 = 0;
        m_uCWARP1++;
        m_uRomAddrP1 = m_uCWARP1;

        m_uOutputP1 = 7;
        m_uStateP1 = m_bStart ? State::WORDWAIT : State::CTRLBITS;
        break;

    case State::CTRLBITS: {
        uint8_t data = read_mem(m_uRomAddrP2);

        m_bStopP1 = (data & 0x80) != 0;
        m_bVoicedP1 = (data & 0x40) != 0;
        m_bSilenceP1 = (data & 0x20) != 0;
        m_uXRepeatP1 = data & 0x03;
        m_uLengthP1 = static_cast<uint8_t>((data & 0x1f) << 2);
        m_uDAR04To00P1 = 0;
        m_uCWARP1++;
        m_uRomAddrP1 = (m_uDAR13To05P1 << 3) | (m_uDAR04To00P1 >> 2);

        m_uOutputP1 = 7;
        m_uStateP1 = m_bStart ? State::WORDWAIT : State::PLAY;
        break;
    }

    case State::PLAY: {
        uint8_t uDeltaP2 = Mux8To2(m_bVoicedP2,
            m_uLengthP2 & 0x03,
            m_uDAR04To00P2 & 0x03,
            read_mem(m_uRomAddrP2)
        );
        uint8_t uIncrementP2;
        bool bAddP2;
        CalculateIncrement(m_bVoicedP2,
            m_uLengthP2 & 0x03,
            m_uDAR04To00P2 == 0,
            uDeltaP2,
            m_uDeltaOldP2,
            m_uDeltaOldP1,
            uIncrementP2,
            bAddP2
        );
        m_uOutputP1 = CalculateOutput(m_bVoicedP2,
            m_bSilenceP2,
            m_uLengthP2 & 0x03,
            m_uDAR04To00P2 == 0,
            m_uOutputP2,
            uIncrementP2,
            bAddP2
        );

        m_uDAR04To00P1++;
        if (m_bDAR04To00CarryP2) {
            m_uDAR04To00P1 = 0;
            m_uLengthP1++;
            if (m_uLengthP1 >= 0x80)
                m_uLengthP1 = 0;
        }

        if (m_bVoicedP2 && m_bRepeatCarryP2) {
            m_uLengthP1 &= 0x70;
            m_uLengthP1 |= static_cast<uint8_t>(m_uXRepeatP1 << 2);
            m_uDAR13To05P1++;
            if (m_uDAR13To05P1 >= 0x200)
                m_uDAR13To05P1 = 0;
        }
        if (!m_bVoicedP2 && m_bDAR04To00CarryP2) {
            m_uDAR13To05P1++;
            if (m_uDAR13To05P1 >= 0x200)
                m_uDAR13To05P1 = 0;
        }

        m_uRomAddrP1 = m_uDAR04To00P1;
        if (m_bVoicedP2 && (m_uLengthP1 & 0x1))
            m_uRomAddrP1 ^= 0x1f;
        m_uRomAddrP1 = static_cast<uint16_t>((m_uDAR13To05P1 << 3) | (m_uRomAddrP1 >> 2));

        if (m_bStart)
            m_uStateP1 = State::WORDWAIT;
        else if (m_bStopP2 && m_bLengthCarryP2)
            m_uStateP1 = State::DELAY;
        else if (m_bLengthCarryP2) {
            m_uStateP1 = State::DARMSB;
            m_uRomAddrP1 = m_uCWARP1;
        } else
            m_uStateP1 = State::PLAY;
        break;
    }

    case State::DELAY:
        // Busy only clears on the next IDLE entry (see State::IDLE above),
        // matching the real chip - not here, matching s14001a_device::Clock().
        m_uOutputP1 = 7;
        m_uStateP1 = m_bStart ? State::WORDWAIT : State::IDLE;
        break;
    }
}

} // namespace retrochip
