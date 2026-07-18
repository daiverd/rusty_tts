// Ported from MAME src/devices/sound/tms5110.cpp / tms5110.h
// Original license: BSD-3-Clause
// Original copyright-holders: Frank Palazzolo, Jarek Burczynski, Aaron Giles,
//   Jonathan Gevaryahu, Couriersud
//
// Trimmed to standalone, VSM/vocabulary-ROM-only operation: the real chip's
// CTL/PDC pin-level protocol (tms5110_device::PDC_set(), the nybble-at-a-time
// LOAD_ADDRESS/SPEAK/READ_BIT/TEST_TALK command state machine) and the
// tms6100_device VSM companion-chip pin protocol have both been replaced by
// a direct high-level API purpose-built for this port: set_vocab_rom() points
// the chip at a flat byte array standing in for the tms6100 (only its
// TMC0281-mode 1-bit LSB-first-per-byte serial read order is modeled - see
// tms6100_device::handle_command()'s M_TB case in MAME's tms6100.cpp - the
// 4-bit and reversed-bit VSM-emulator modes used by other, unrelated
// machines are not needed here), load_address() sets the read position, and
// speak() triggers the same state reset CMD_SPEAK causes on the real chip.
// All MAME device_t/sound_stream/save-state plumbing has been removed; the
// synthesis math (parse_frame/lattice_filter/matrix_multiply/clip_analog)
// and the coefficient tables (from tms5110r.hxx, also BSD-3-Clause) are
// unchanged from the original source.
#pragma once

#include <cstddef>
#include <cstdint>

namespace retrochip {

// All three validated Speak & Spell vocabulary regions (US 1980, UK 1978,
// Japan) use the TMC0281 chip variant (sns_tmc0281 machine config in MAME's
// src/mame/ti/snspell.cpp), which shares its coefficient table with the
// plain TMS5100. Only that one variant is implemented here.
enum class Tms5110Variant { TMC0281_TMS5100 };

class Tms5110 {
public:
    explicit Tms5110(Tms5110Variant variant = Tms5110Variant::TMC0281_TMS5100);

    // Equivalent to a RESET command (cmd 0x0)
    void reset();

    // Points the chip at a vocabulary ROM byte array (stands in for the real
    // chip's tms6100/VSM companion). Caller owns the buffer's lifetime.
    void set_vocab_rom(const uint8_t *data, size_t size) { m_rom = data; m_rom_size = size; }

    // Equivalent to a LOAD ADDRESS command sequence: sets the internal bit
    // read position to the start of the given byte address in the VSM.
    void load_address(uint32_t byte_addr) { m_bit_pos = static_cast<uint64_t>(byte_addr) * 8; }

    // Equivalent to a SPEAK command (cmd 0xa): mirrors PDC_set()'s
    // CMD_SPEAK case - starts the chip talking from the current VSM address.
    void speak();

    // True while the chip is speaking (SPEN || TALKD)
    bool talking() const { return m_SPEN || m_TALKD; }

    // Generate `count` samples (16-bit signed PCM) into buf.
    void generate(int16_t *buf, unsigned count);

    struct Coeffs {
        int num_k;
        int energy_bits;
        int pitch_bits;
        int kbits[10];
        uint16_t energytable[16];
        uint16_t pitchtable[32];
        int16_t ktable[10][32];
        int8_t chirptable[52];
        int8_t interp_coeff[8];
    };

private:
    // internal helpers, ported ~verbatim from tms5110_device
    int read_bits(int count);
    void process(int16_t *buffer, unsigned size);
    int16_t clip_analog(int16_t cliptemp) const;
    int32_t matrix_multiply(int32_t a, int32_t b) const;
    int32_t lattice_filter();
    void parse_frame();
    bool old_frame_unvoiced_flag() const { return m_OLDP; }
    bool old_frame_silence_flag() const { return m_OLDE; }
    bool new_frame_stop_flag() const { return m_new_frame_energy_idx == 0x0F; }
    bool new_frame_silence_flag() const { return m_new_frame_energy_idx == 0; }
    bool new_frame_unvoiced_flag() const { return m_new_frame_pitch_idx == 0; }

    const Coeffs *m_coeff;

    const uint8_t *m_rom = nullptr;
    size_t m_rom_size = 0;
    uint64_t m_bit_pos = 0;

    bool m_SPEN = false;
    bool m_TALK = false;
    bool m_TALKD = false;

    bool m_OLDE = true;
    bool m_OLDP = true;

    uint8_t m_new_frame_energy_idx = 0;
    uint8_t m_new_frame_pitch_idx = 0;
    uint8_t m_new_frame_k_idx[10] = {};

    int16_t m_current_energy = 0;
    int16_t m_current_pitch = 0;
    int16_t m_current_k[10] = {};
    uint16_t m_previous_energy = 0;

    uint8_t m_subcycle = 0;
    uint8_t m_subc_reload = 1;
    uint8_t m_PC = 0;
    uint8_t m_IP = 0;
    bool m_inhibit = true;
    bool m_uv_zpar = false;
    bool m_zpar = false;
    bool m_pitch_zero = false;
    uint16_t m_pitch_count = 0;

    int32_t m_u[11] = {};
    int32_t m_x[10] = {};

    uint16_t m_RNG = 0x1FFF;
    int16_t m_excitation_data = 0;
};

} // namespace retrochip
