// Ported from MAME src/devices/sound/tms5110.cpp (BSD-3-Clause).
// See tms5110.h for details of what was trimmed for standalone use.
#include "tms5110.h"

#include <algorithm>
#include <iterator>

namespace retrochip {

namespace {

// Coefficient table, transcribed verbatim from MAME's tms5110r.hxx
// (BSD-3-Clause, copyright-holders: Frank Palazzolo, Couriersud, Jonathan
// Gevaryahu), specifically T0280B_0281A_coeff - the TMC0281/TMS5100
// variant used by every validated Speak & Spell region (sns_tmc0281 in
// src/mame/ti/snspell.cpp).

constexpr uint16_t kEnergy0281[16] = {
    0, 0, 1, 1, 2, 3, 5, 7,
    10, 15, 21, 30, 43, 61, 86, 0
};

constexpr uint16_t kPitch0281[32] = {
    0, 41, 43, 45, 47, 49, 51, 53,
    55, 58, 60, 63, 66, 70, 73, 76,
    79, 83, 87, 90, 94, 99, 103, 107,
    112, 118, 123, 129, 134, 140, 147, 153
};

constexpr int16_t kLpc0281[10][32] = {
    /* K1  */
    { -501, -497, -493, -488, -480, -471, -460, -446,
      -427, -405, -378, -344, -305, -259, -206, -148,
       -86,  -21,   45,  110,  171,  227,  277,  320,
       357,  388,  413,  434,  451,  464,  474,  498 },
    /* K2  */
    { -349, -328, -305, -280, -252, -223, -192, -158,
      -124,  -88,  -51,  -14,   23,   60,   97,  133,
       167,  199,  230,  259,  286,  310,  333,  354,
       372,  389,  404,  417,  429,  439,  449,  506 },
    /* K3  */
    { -397, -365, -327, -282, -229, -170, -104,  -36,
        35,  104,  169,  228,  281,  326,  364,  396 },
    /* K4  */
    { -369, -334, -293, -245, -191, -131,  -67,   -1,
        64,  128,  188,  243,  291,  332,  367,  397 },
    /* K5  */
    { -319, -286, -250, -211, -168, -122,  -74,  -25,
        24,   73,  121,  167,  210,  249,  285,  318 },
    /* K6  */
    { -290, -252, -209, -163, -114,  -62,   -9,   44,
        97,  147,  194,  238,  278,  313,  344,  371 },
    /* K7  */
    { -291, -256, -216, -174, -128,  -80,  -31,   19,
        69,  117,  163,  206,  246,  283,  316,  345 },
    /* K8  */
    { -218, -133,  -38,   59,  152,  235,  305,  361 },
    /* K9  */
    { -226, -157,  -82,   -3,   76,  151,  220,  280 },
    /* K10 */
    { -179, -122,  -61,    1,   62,  123,  179,  231 },
};

// Values above 0x7f are negative int8_t's; kept as int16_t here and cast
// down when copied into Coeffs, matching the original C aggregate-init
// (allowed to narrow implicitly there, but not in a C++ braced-init-list).
constexpr int16_t kChirp0281[52] = {
    0x00, 0x2a, 0xd4, 0x32, 0xb2, 0x12, 0x25, 0x14,
    0x02, 0xe1, 0xc5, 0x02, 0x5f, 0x5a, 0x05, 0x0f,
    0x26, 0xfc, 0xa5, 0xa5, 0xd6, 0xdd, 0xdc, 0xfc,
    0x25, 0x2b, 0x22, 0x21, 0x0f, 0xff, 0xf8, 0xee,
    0xed, 0xef, 0xf7, 0xf6, 0xfa, 0x00, 0x03, 0x02,
    0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00
};

constexpr int8_t kInterp[8] = { 0, 3, 3, 3, 2, 2, 1, 1 };

constexpr int kKbits[10] = { 5, 5, 4, 4, 4, 4, 4, 3, 3, 3 };

void copy_ktable(int16_t dst[10][32], const int16_t src[10][32]) {
    for (int i = 0; i < 10; i++)
        for (int j = 0; j < 32; j++)
            dst[i][j] = src[i][j];
}

Tms5110::Coeffs make_tmc0281_coeffs() {
    Tms5110::Coeffs c{};
    c.num_k = 10;
    c.energy_bits = 4;
    c.pitch_bits = 5;
    for (int i = 0; i < 10; i++) c.kbits[i] = kKbits[i];
    for (int i = 0; i < 16; i++) c.energytable[i] = kEnergy0281[i];
    for (int i = 0; i < 32; i++) c.pitchtable[i] = kPitch0281[i];
    copy_ktable(c.ktable, kLpc0281);
    for (int i = 0; i < 52; i++) c.chirptable[i] = static_cast<int8_t>(kChirp0281[i]);
    for (int i = 0; i < 8; i++) c.interp_coeff[i] = kInterp[i];
    return c;
}

const Tms5110::Coeffs &tmc0281_coeffs() {
    static const Tms5110::Coeffs c = make_tmc0281_coeffs();
    return c;
}

} // namespace

Tms5110::Tms5110(Tms5110Variant variant) {
    (void)variant; // only one variant implemented, see header
    m_coeff = &tmc0281_coeffs();
    reset();
}

void Tms5110::reset() {
    m_SPEN = m_TALK = m_TALKD = false;

    m_new_frame_energy_idx = m_current_energy = m_previous_energy = 0;
    m_new_frame_pitch_idx = m_current_pitch = 0;
    m_zpar = m_uv_zpar = false;
    std::fill(std::begin(m_new_frame_k_idx), std::end(m_new_frame_k_idx), uint8_t{0});
    std::fill(std::begin(m_current_k), std::end(m_current_k), int16_t{0});

    m_inhibit = true;
    m_subcycle = 0;
    m_pitch_count = 0;
    m_pitch_zero = false;
    m_PC = 0;
    m_subc_reload = 1;
    m_OLDE = m_OLDP = true;
    m_IP = 0;
    m_RNG = 0x1FFF;
    std::fill(std::begin(m_u), std::end(m_u), int32_t{0});
    std::fill(std::begin(m_x), std::end(m_x), int32_t{0});

    m_bit_pos = 0;
}

void Tms5110::speak() {
    // Mirrors PDC_set()'s CMD_SPEAK case (device_reset() equivalent parts
    // already hold from construction/reset(); this only re-applies what a
    // real SPEAK command changes).
    m_SPEN = true;
    m_TALK = true; // FAST_START_HACK, matches upstream default
    m_zpar = true;
    m_uv_zpar = true;
    m_OLDE = true;
    m_OLDP = true;
    m_subc_reload = 1;
}

int Tms5110::read_bits(int count) {
    int val = 0;
    while (count--) {
        int bit = 0;
        size_t byte_idx = static_cast<size_t>(m_bit_pos >> 3);
        if (m_rom && byte_idx < m_rom_size) {
            // Real chip's VSM (tms6100, 1-bit/non-reversed mode) shifts
            // each byte out LSB-first - see tms6100_device::handle_command()
            // M_TB case in MAME's tms6100.cpp.
            unsigned bit_in_byte = static_cast<unsigned>(m_bit_pos & 7);
            bit = (m_rom[byte_idx] >> bit_in_byte) & 1;
        }
        m_bit_pos++;
        val = (val << 1) | bit;
    }
    return val;
}

int16_t Tms5110::clip_analog(int16_t cliptemp) const {
    if (cliptemp > 2047) cliptemp = 2047;
    else if (cliptemp < -2048) cliptemp = -2048;
    cliptemp &= ~0xF;
    return (cliptemp << 4) | ((cliptemp & 0x7F0) >> 3) | ((cliptemp & 0x400) >> 10);
}

int32_t Tms5110::matrix_multiply(int32_t a, int32_t b) const {
    while (a > 511) a -= 1024;
    while (a < -512) a += 1024;
    while (b > 16383) b -= 32768;
    while (b < -16384) b += 32768;
    return (a * b) >> 9;
}

int32_t Tms5110::lattice_filter() {
    m_u[10] = matrix_multiply(m_previous_energy, (m_excitation_data << 6));
    m_u[9] = m_u[10] - matrix_multiply(m_current_k[9], m_x[9]);
    m_u[8] = m_u[9] - matrix_multiply(m_current_k[8], m_x[8]);
    m_u[7] = m_u[8] - matrix_multiply(m_current_k[7], m_x[7]);
    m_u[6] = m_u[7] - matrix_multiply(m_current_k[6], m_x[6]);
    m_u[5] = m_u[6] - matrix_multiply(m_current_k[5], m_x[5]);
    m_u[4] = m_u[5] - matrix_multiply(m_current_k[4], m_x[4]);
    m_u[3] = m_u[4] - matrix_multiply(m_current_k[3], m_x[3]);
    m_u[2] = m_u[3] - matrix_multiply(m_current_k[2], m_x[2]);
    m_u[1] = m_u[2] - matrix_multiply(m_current_k[1], m_x[1]);
    m_u[0] = m_u[1] - matrix_multiply(m_current_k[0], m_x[0]);
    m_x[9] = m_x[8] + matrix_multiply(m_current_k[8], m_u[8]);
    m_x[8] = m_x[7] + matrix_multiply(m_current_k[7], m_u[7]);
    m_x[7] = m_x[6] + matrix_multiply(m_current_k[6], m_u[6]);
    m_x[6] = m_x[5] + matrix_multiply(m_current_k[5], m_u[5]);
    m_x[5] = m_x[4] + matrix_multiply(m_current_k[4], m_u[4]);
    m_x[4] = m_x[3] + matrix_multiply(m_current_k[3], m_u[3]);
    m_x[3] = m_x[2] + matrix_multiply(m_current_k[2], m_u[2]);
    m_x[2] = m_x[1] + matrix_multiply(m_current_k[1], m_u[1]);
    m_x[1] = m_x[0] + matrix_multiply(m_current_k[0], m_u[0]);
    m_x[0] = m_u[0];
    m_previous_energy = m_current_energy;
    return m_u[0];
}

void Tms5110::parse_frame() {
    m_uv_zpar = m_zpar = false;

    m_new_frame_energy_idx = static_cast<uint8_t>(read_bits(m_coeff->energy_bits));
    if (m_new_frame_energy_idx == 0 || m_new_frame_energy_idx == 15)
        return;

    int rep_flag = read_bits(1);

    m_new_frame_pitch_idx = static_cast<uint8_t>(read_bits(m_coeff->pitch_bits));
    m_uv_zpar = new_frame_unvoiced_flag();
    if (rep_flag)
        return;

    for (int i = 0; i < 4; i++)
        m_new_frame_k_idx[i] = static_cast<uint8_t>(read_bits(m_coeff->kbits[i]));

    if (m_new_frame_pitch_idx == 0)
        return;

    for (int i = 4; i < m_coeff->num_k; i++)
        m_new_frame_k_idx[i] = static_cast<uint8_t>(read_bits(m_coeff->kbits[i]));
}

void Tms5110::process(int16_t *buffer, unsigned size) {
    int buf_count = 0;

    while (size > 0) {
        if (m_TALKD) {
            if ((m_IP == 0) && (m_PC == 12) && (m_subcycle == 1)) {
                parse_frame();

                if (new_frame_stop_flag())
                    m_TALK = m_SPEN = false;

                // Inhibit conditions per tms5110.cpp's process() (TMC0281
                // variant: the extra OLDP&&NEWE==silence case tms5220 carries
                // is not present here - it was noted upstream as buggy/absent
                // on rev A/B TMS51xx and is commented out even there).
                if ((!old_frame_unvoiced_flag() && new_frame_unvoiced_flag())
                    || (old_frame_unvoiced_flag() && !new_frame_unvoiced_flag())
                    || (old_frame_silence_flag() && !new_frame_silence_flag()))
                    m_inhibit = true;
                else
                    m_inhibit = false;
            } else {
                bool inhibit_state = (m_inhibit && (m_IP != 0));
                if (m_subcycle == 2) {
                    switch (m_PC) {
                        case 0:
                            if (m_IP == 0) m_pitch_zero = false;
                            m_current_energy = static_cast<int16_t>(
                                (m_current_energy + (((m_coeff->energytable[m_new_frame_energy_idx] - m_current_energy) * (1 - inhibit_state)) >> m_coeff->interp_coeff[m_IP])) * (1 - m_zpar));
                            break;
                        case 1:
                            m_current_pitch = static_cast<int16_t>(
                                (m_current_pitch + (((m_coeff->pitchtable[m_new_frame_pitch_idx] - m_current_pitch) * (1 - inhibit_state)) >> m_coeff->interp_coeff[m_IP])) * (1 - m_zpar));
                            break;
                        case 2: case 3: case 4: case 5: case 6:
                        case 7: case 8: case 9: case 10: case 11: {
                            int k = m_PC - 2;
                            bool zp = (k < 4) ? m_zpar : m_uv_zpar;
                            m_current_k[k] = static_cast<int16_t>(
                                (m_current_k[k] + (((m_coeff->ktable[k][m_new_frame_k_idx[k]] - m_current_k[k]) * (1 - inhibit_state)) >> m_coeff->interp_coeff[m_IP])) * (1 - zp));
                            break;
                        }
                    }
                }
            }

            if (old_frame_unvoiced_flag()) {
                if (m_RNG & 1)
                    m_excitation_data = static_cast<int16_t>(~0x3F);
                else
                    m_excitation_data = 0x40;
            } else {
                if (m_pitch_count >= 51)
                    m_excitation_data = m_coeff->chirptable[51];
                else
                    m_excitation_data = m_coeff->chirptable[m_pitch_count];
            }

            for (int i = 0; i < 20; i++) {
                int bitout = ((m_RNG >> 12) & 1) ^ ((m_RNG >> 3) & 1) ^ ((m_RNG >> 2) & 1) ^ (m_RNG & 1);
                m_RNG <<= 1;
                m_RNG |= bitout;
            }

            int32_t this_sample = lattice_filter();

            while (this_sample > 16383) this_sample -= 32768;
            while (this_sample < -16384) this_sample += 32768;
            buffer[buf_count] = clip_analog(static_cast<int16_t>(this_sample));

            m_subcycle++;
            if ((m_subcycle == 2) && (m_PC == 12)) {
                if ((m_IP == 7) && m_inhibit) m_pitch_zero = true;
                if (m_IP == 7) {
                    m_OLDE = new_frame_silence_flag();
                    m_OLDP = new_frame_unvoiced_flag();
                    m_TALKD = m_TALK;
                    if ((!m_TALK) && m_SPEN) m_TALK = true;
                }
                m_subcycle = m_subc_reload;
                m_PC = 0;
                m_IP++;
                m_IP &= 0x7;
            } else if (m_subcycle == 3) {
                m_subcycle = m_subc_reload;
                m_PC++;
            }
            m_pitch_count++;
            if ((m_pitch_count >= static_cast<uint16_t>(m_current_pitch)) || m_pitch_zero) m_pitch_count = 0;
            m_pitch_count &= 0x1FF;
        } else {
            m_subcycle++;
            if ((m_subcycle == 2) && (m_PC == 12)) {
                if (m_IP == 7) {
                    m_TALKD = m_TALK;
                    if ((!m_TALK) && m_SPEN) m_TALK = true;
                }
                m_subcycle = m_subc_reload;
                m_PC = 0;
                m_IP++;
                m_IP &= 0x7;
            } else if (m_subcycle == 3) {
                m_subcycle = m_subc_reload;
                m_PC++;
            }
            buffer[buf_count] = -1;
        }
        buf_count++;
        size--;
    }
}

void Tms5110::generate(int16_t *buf, unsigned count) {
    process(buf, count);
}

} // namespace retrochip
