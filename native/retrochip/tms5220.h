// Ported from MAME src/devices/sound/tms5220.cpp / tms5220.h
// Original license: BSD-3-Clause
// Original copyright-holders: Frank Palazzolo, Aaron Giles, Jonathan Gevaryahu,
//   Raphael Nabet, Couriersud, Michael Zapf
//
// Trimmed to standalone, SPEAK EXTERNAL-only operation: this build always
// drives the chip via its live 16-byte LPC-10 frame FIFO (the "SPKEXT" mode),
// since it's used here with no VSM/speech-ROM attached. VSM/ROM word-lookup,
// RS/WS pin-level timing, IRQ/READY pin callbacks, and all MAME
// device_t/sound_stream/save-state plumbing have been removed; the
// synthesis math (parse_frame/lattice_filter/matrix_multiply/clip_analog)
// and the coefficient tables (from tms5110r.hxx, also BSD-3-Clause) are
// unchanged from the original source.
#pragma once

#include <cstddef>
#include <cstdint>

namespace retrochip {

enum class Tms5220Variant { TMS5220, TMS5200 };

class Tms5220 {
public:
    explicit Tms5220(Tms5220Variant variant = Tms5220Variant::TMS5220);

    // Equivalent to a RESET command (cmd 0x70)
    void reset();

    // Equivalent to a SPEAK EXTERNAL command (cmd 0x60): clears the FIFO
    // and switches the chip into FIFO-fed (DDIS) mode.
    void speak_external();

    // Feed one byte into the FIFO. Mirrors tms5220_device::data_w() in
    // MAME's default "hacky instant write" mode (m_true_timing == false),
    // DDIS/SPKEXT branch only.
    void write(uint8_t data);

    // True while the chip is speaking (SPEN || TALKD)
    bool talking() const { return m_SPEN || m_TALKD; }

    bool fifo_has_room() const { return m_fifo_count < kFifoSize; }

    // Generate `count` samples (16-bit signed PCM) into buf.
    void generate(int16_t *buf, unsigned count);

    // debug only
    void debug_state(bool &spen, bool &ddis, bool &talk, bool &talkd, unsigned &fifo_count) const {
        spen = m_SPEN; ddis = m_DDIS; talk = m_TALK; talkd = m_TALKD; fifo_count = m_fifo_count;
    }

    struct Coeffs {
        int num_k;
        int energy_bits;
        int pitch_bits;
        int kbits[10];
        uint16_t energytable[16];
        uint16_t pitchtable[64];
        int16_t ktable[10][32];
        int8_t chirptable[52];
        int8_t interp_coeff[8];
    };

private:
    static constexpr unsigned kFifoSize = 16;

    // internal helpers, ported ~verbatim from tms5220_device
    void data_write(int data);
    void update_fifo_status_and_ints();
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

    uint8_t m_fifo[kFifoSize] = {};
    uint8_t m_fifo_head = 0, m_fifo_tail = 0, m_fifo_count = 0, m_fifo_bits_taken = 0;

    bool m_previous_talk_status = false;
    bool m_SPEN = false;
    bool m_DDIS = false;
    bool m_TALK = false;
    bool m_TALKD = false;
    bool m_buffer_low = true;
    bool m_buffer_empty = true;

    uint8_t m_command_register = 0xff;

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
    uint8_t m_subc_reload = 1; // FORCE_SUBC_RELOAD
    uint8_t m_PC = 0;
    uint8_t m_IP = 0;
    bool m_inhibit = true;
    bool m_uv_zpar = false;
    bool m_zpar = false;
    bool m_pitch_zero = false;
    uint8_t m_c_variant_rate = 0; // no rate control on 5220/5200
    uint16_t m_pitch_count = 0;

    int32_t m_u[11] = {};
    int32_t m_x[10] = {};

    uint16_t m_RNG = 0x1FFF;
    int16_t m_excitation_data = 0;
};

} // namespace retrochip
