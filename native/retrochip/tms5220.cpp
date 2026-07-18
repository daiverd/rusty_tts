// Ported from MAME src/devices/sound/tms5220.cpp (BSD-3-Clause).
// See tms5220.h for details of what was trimmed for standalone use.
#include "tms5220.h"

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <iterator>

namespace retrochip {

namespace {

// Coefficient tables, transcribed verbatim from MAME's tms5110r.hxx
// (BSD-3-Clause, copyright-holders: Frank Palazzolo, Couriersud,
// Jonathan Gevaryahu).

constexpr uint16_t kEnergyLater[16] = {
    0, 1, 2, 3, 4, 6, 8, 11,
    16, 23, 33, 47, 63, 85, 114, 0
};

constexpr uint16_t kPitch5220[64] = {
    0, 15, 16, 17, 18, 19, 20, 21,
    22, 23, 24, 25, 26, 27, 28, 29,
    30, 31, 32, 33, 34, 35, 36, 37,
    38, 39, 40, 41, 42, 44, 46, 48,
    50, 52, 53, 56, 58, 60, 62, 65,
    68, 70, 72, 76, 78, 80, 84, 86,
    91, 94, 98, 101, 105, 109, 114, 118,
    122, 127, 132, 137, 142, 148, 153, 159
};

constexpr uint16_t kPitch2501E[64] = {
    0, 14, 15, 16, 17, 18, 19, 20,
    21, 22, 23, 24, 25, 26, 27, 28,
    29, 30, 31, 32, 34, 36, 38, 40,
    41, 43, 45, 48, 49, 51, 54, 55,
    57, 60, 62, 64, 68, 72, 74, 76,
    81, 85, 87, 90, 96, 99, 103, 107,
    112, 117, 122, 127, 133, 139, 145, 151,
    157, 164, 171, 178, 186, 194, 202, 211
};

constexpr int16_t kLpc5110_5220[10][32] = {
    /* K1  */
    { -501, -498, -497, -495, -493, -491, -488, -482,
      -478, -474, -469, -464, -459, -452, -445, -437,
      -412, -380, -339, -288, -227, -158,  -81,   -1,
        80,  157,  226,  287,  337,  379,  411,  436 },
    /* K2  */
    { -328, -303, -274, -244, -211, -175, -138,  -99,
       -59,  -18,   24,   64,  105,  143,  180,  215,
       248,  278,  306,  331,  354,  374,  392,  408,
       422,  435,  445,  455,  463,  470,  476,  506 },
    /* K3  */
    { -441, -387, -333, -279, -225, -171, -117,  -63,
        -9,   45,   98,  152,  206,  260,  314,  368 },
    /* K4  */
    { -328, -273, -217, -161, -106,  -50,    5,   61,
       116,  172,  228,  283,  339,  394,  450,  506 },
    /* K5  */
    { -328, -282, -235, -189, -142,  -96,  -50,   -3,
        43,   90,  136,  182,  229,  275,  322,  368 },
    /* K6  */
    { -256, -212, -168, -123,  -79,  -35,   10,   54,
        98,  143,  187,  232,  276,  320,  365,  409 },
    /* K7  */
    { -308, -260, -212, -164, -117,  -69,  -21,   27,
        75,  122,  170,  218,  266,  314,  361,  409 },
    /* K8  */
    { -256, -161,  -66,   29,  124,  219,  314,  409 },
    /* K9  */
    { -256, -176,  -96,  -15,   65,  146,  226,  307 },
    /* K10 */
    { -205, -132,  -59,   14,   87,  160,  234,  307 },
};

constexpr int16_t kLpc2801_2501E[10][32] = {
    /* K1  */
    { -501, -498, -495, -490, -485, -478, -469, -459,
      -446, -431, -412, -389, -362, -331, -295, -253,
      -207, -156, -102,  -45,   13,   70,  126,  179,
       228,  272,  311,  345,  374,  399,  420,  437 },
    /* K2  */
    { -376, -357, -335, -312, -286, -258, -227, -195,
      -161, -124,  -87,  -49,  -10,   29,   68,  106,
       143,  178,  212,  243,  272,  299,  324,  346,
       366,  384,  400,  414,  427,  438,  448,  506 },
    /* K3  */
    { -407, -381, -349, -311, -268, -218, -162, -102,
       -39,   25,   89,  149,  206,  257,  302,  341 },
    /* K4  */
    { -290, -252, -209, -163, -114,  -62,   -9,   44,
        97,  147,  194,  238,  278,  313,  344,  371 },
    /* K5  */
    { -318, -283, -245, -202, -156, -107,  -56,   -3,
        49,  101,  150,  196,  239,  278,  313,  344 },
    /* K6  */
    { -193, -152, -109,  -65,  -20,   26,   71,  115,
       158,  198,  235,  270,  301,  330,  355,  377 },
    /* K7  */
    { -254, -218, -180, -140,  -97,  -53,   -8,   36,
        81,  124,  165,  204,  240,  274,  304,  332 },
    /* K8  */
    { -205, -112,  -10,   92,  187,  269,  336,  387 },
    /* K9  */
    { -249, -183, -110,  -32,   48,  126,  198,  261 },
    /* K10 */
    { -190, -133,  -73,  -10,   53,  115,  173,  227 },
};

constexpr int8_t kChirpLater[52] = {
    0x00, 0x03, 0x0f, 0x28, 0x4c, 0x6c, 0x71, 0x50,
    0x25, 0x26, 0x4c, 0x44, 0x1a, 0x32, 0x3b, 0x13,
    0x37, 0x1a, 0x25, 0x1f, 0x1d, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00
};

constexpr int8_t kInterp[8] = { 0, 3, 3, 3, 2, 2, 1, 1 };

constexpr int kKbits[10] = { 5, 5, 4, 4, 4, 4, 4, 3, 3, 3 };

// helper to widen the transcribed K tables (which only fill the entries
// the chip's kbits width actually uses) into fixed [10][32] Coeffs arrays.
void copy_ktable(int16_t dst[10][32], const int16_t src[10][32]) {
    for (int i = 0; i < 10; i++)
        for (int j = 0; j < 32; j++)
            dst[i][j] = src[i][j];
}

Tms5220::Coeffs make_tms5220_coeffs() {
    Tms5220::Coeffs c{};
    c.num_k = 10;
    c.energy_bits = 4;
    c.pitch_bits = 6;
    for (int i = 0; i < 10; i++) c.kbits[i] = kKbits[i];
    for (int i = 0; i < 16; i++) c.energytable[i] = kEnergyLater[i];
    for (int i = 0; i < 64; i++) c.pitchtable[i] = kPitch5220[i];
    copy_ktable(c.ktable, kLpc5110_5220);
    for (int i = 0; i < 52; i++) c.chirptable[i] = kChirpLater[i];
    for (int i = 0; i < 8; i++) c.interp_coeff[i] = kInterp[i];
    return c;
}

Tms5220::Coeffs make_tms5200_coeffs() {
    Tms5220::Coeffs c{};
    c.num_k = 10;
    c.energy_bits = 4;
    c.pitch_bits = 6;
    for (int i = 0; i < 10; i++) c.kbits[i] = kKbits[i];
    for (int i = 0; i < 16; i++) c.energytable[i] = kEnergyLater[i];
    for (int i = 0; i < 64; i++) c.pitchtable[i] = kPitch2501E[i];
    copy_ktable(c.ktable, kLpc2801_2501E);
    for (int i = 0; i < 52; i++) c.chirptable[i] = kChirpLater[i];
    for (int i = 0; i < 8; i++) c.interp_coeff[i] = kInterp[i];
    return c;
}

const Tms5220::Coeffs &tms5220_coeffs() {
    static const Tms5220::Coeffs c = make_tms5220_coeffs();
    return c;
}

const Tms5220::Coeffs &tms5200_coeffs() {
    static const Tms5220::Coeffs c = make_tms5200_coeffs();
    return c;
}

} // namespace

Tms5220::Tms5220(Tms5220Variant variant) {
    m_coeff = (variant == Tms5220Variant::TMS5200) ? &tms5200_coeffs() : &tms5220_coeffs();
    reset();
}

void Tms5220::reset() {
    std::fill(std::begin(m_fifo), std::end(m_fifo), uint8_t{0});
    m_fifo_head = m_fifo_tail = m_fifo_count = m_fifo_bits_taken = 0;

    m_SPEN = m_DDIS = m_TALK = m_TALKD = m_previous_talk_status = false;
    m_buffer_empty = m_buffer_low = true;
    m_command_register = 0xff;

    m_new_frame_energy_idx = m_current_energy = m_previous_energy = 0;
    m_new_frame_pitch_idx = m_current_pitch = 0;
    m_zpar = m_uv_zpar = false;
    std::fill(std::begin(m_new_frame_k_idx), std::end(m_new_frame_k_idx), uint8_t{0});
    std::fill(std::begin(m_current_k), std::end(m_current_k), int16_t{0});

    m_inhibit = true;
    m_subcycle = m_c_variant_rate = 0;
    m_pitch_count = m_PC = 0;
    m_subc_reload = 1; // FORCE_SUBC_RELOAD
    m_OLDE = m_OLDP = true;
    m_IP = 0; // reload_table[0], no rate control on 5220/5200
    m_RNG = 0x1FFF;
    std::fill(std::begin(m_u), std::end(m_u), int32_t{0});
    std::fill(std::begin(m_x), std::end(m_x), int32_t{0});
}

void Tms5220::speak_external() {
    // SPKEXT going active clears the FIFO and its counters.
    std::fill(std::begin(m_fifo), std::end(m_fifo), uint8_t{0});
    m_fifo_head = m_fifo_tail = m_fifo_count = m_fifo_bits_taken = 0;
    m_DDIS = true; // speak using FIFO
    m_zpar = true;
    m_uv_zpar = true;
    m_OLDE = true;
    m_OLDP = true;
    m_new_frame_energy_idx = 0;
    m_new_frame_pitch_idx = 0;
    for (int i = 0; i < 4; i++) m_new_frame_k_idx[i] = 0;
    for (int i = 4; i < 7; i++) m_new_frame_k_idx[i] = 0xF;
    for (int i = 7; i < m_coeff->num_k; i++) m_new_frame_k_idx[i] = 0x7;
    m_command_register = 0xff;
    update_fifo_status_and_ints();
}

void Tms5220::write(uint8_t data) {
    data_write(data);
}

void Tms5220::data_write(int data) {
    bool old_buffer_low = m_buffer_low;

    if (!m_DDIS)
        return; // this build only supports SPKEXT/FIFO-driven operation

    if (m_fifo_count < kFifoSize) {
        m_fifo[m_fifo_tail] = static_cast<uint8_t>(data);
        m_fifo_tail = (m_fifo_tail + 1) % kFifoSize;
        m_fifo_count++;
        update_fifo_status_and_ints();

        if ((!m_SPEN) && (old_buffer_low && (!m_buffer_low))) {
            m_zpar = true;
            m_uv_zpar = true;
            m_OLDE = true;
            m_OLDP = true;
            m_SPEN = true;
            m_new_frame_energy_idx = 0;
            m_new_frame_pitch_idx = 0;
            for (int i = 0; i < 4; i++) m_new_frame_k_idx[i] = 0;
            for (int i = 4; i < 7; i++) m_new_frame_k_idx[i] = 0xF;
            for (int i = 7; i < m_coeff->num_k; i++) m_new_frame_k_idx[i] = 0x7;
        }
    }
    // else: FIFO full, byte dropped (caller should check fifo_has_room() first)
}

void Tms5220::update_fifo_status_and_ints() {
    if (m_fifo_count <= 8)
        m_buffer_low = true;
    else
        m_buffer_low = false;

    if (m_fifo_count == 0) {
        if (!m_buffer_empty && getenv("RETROCHIP_DEBUG"))
            std::fprintf(stderr, "[trace] buffer_empty set true (DDIS=%d SPEN=%d TALK=%d TALKD=%d)\n", m_DDIS, m_SPEN, m_TALK, m_TALKD);
        m_buffer_empty = true;
        if (m_DDIS)
            m_TALK = m_SPEN = false; // /BE clears TALK status via TCON, only when DDIS
    } else {
        m_buffer_empty = false;
    }

    if (m_previous_talk_status && !talking()) {
        if (getenv("RETROCHIP_DEBUG"))
            std::fprintf(stderr, "[trace] DDIS cleared on talk-status falling edge\n");
        m_DDIS = false;
        m_previous_talk_status = false;
    }
    m_previous_talk_status = talking();
}

int Tms5220::read_bits(int count) {
    int val = 0;
    // FIFO-only (SPKEXT); no VSM attached in this build.
    while (count--) {
        val = (val << 1) | ((m_fifo[m_fifo_head] >> m_fifo_bits_taken) & 1);
        m_fifo_bits_taken++;
        if (m_fifo_bits_taken >= 8) {
            m_fifo_count--;
            m_fifo[m_fifo_head] = 0;
            m_fifo_head = (m_fifo_head + 1) % kFifoSize;
            m_fifo_bits_taken = 0;
            update_fifo_status_and_ints();
        }
    }
    return val;
}

int16_t Tms5220::clip_analog(int16_t cliptemp) const {
    if (cliptemp > 2047) cliptemp = 2047;
    else if (cliptemp < -2048) cliptemp = -2048;
    cliptemp &= ~0xF;
    return (cliptemp << 4) | ((cliptemp & 0x7F0) >> 3) | ((cliptemp & 0x400) >> 10);
}

int32_t Tms5220::matrix_multiply(int32_t a, int32_t b) const {
    while (a > 511) a -= 1024;
    while (a < -512) a += 1024;
    while (b > 16383) b -= 32768;
    while (b < -16384) b += 32768;
    return (a * b) >> 9;
}

int32_t Tms5220::lattice_filter() {
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

void Tms5220::parse_frame() {
    m_uv_zpar = m_zpar = false;

    m_IP = 0; // reload_table[0]; no rate control on 5220/5200

    update_fifo_status_and_ints();
    if (m_DDIS && m_buffer_empty) return;

    m_new_frame_energy_idx = static_cast<uint8_t>(read_bits(m_coeff->energy_bits));
    update_fifo_status_and_ints();
    if (m_DDIS && m_buffer_empty) return;
    if (m_new_frame_energy_idx == 0 || m_new_frame_energy_idx == 15)
        return;

    int rep_flag = read_bits(1);

    m_new_frame_pitch_idx = static_cast<uint8_t>(read_bits(m_coeff->pitch_bits));
    m_uv_zpar = new_frame_unvoiced_flag();
    update_fifo_status_and_ints();
    if (m_DDIS && m_buffer_empty) return;
    if (rep_flag)
        return;

    for (int i = 0; i < 4; i++) {
        m_new_frame_k_idx[i] = static_cast<uint8_t>(read_bits(m_coeff->kbits[i]));
        update_fifo_status_and_ints();
        if (m_DDIS && m_buffer_empty) return;
    }

    if (m_new_frame_pitch_idx == 0)
        return;

    for (int i = 4; i < m_coeff->num_k; i++) {
        m_new_frame_k_idx[i] = static_cast<uint8_t>(read_bits(m_coeff->kbits[i]));
        update_fifo_status_and_ints();
        if (m_DDIS && m_buffer_empty) return;
    }
}

void Tms5220::process(int16_t *buffer, unsigned size) {
    int buf_count = 0;

    while (size > 0) {
        if (m_TALKD) {
            if ((m_IP == 0) && (m_PC == 12) && (m_subcycle == 1)) {
                m_IP = 0; // reload_table[0]

                parse_frame();

                if (new_frame_stop_flag()) {
                    m_TALK = m_SPEN = false;
                    update_fifo_status_and_ints();
                }

                if ((!old_frame_unvoiced_flag() && new_frame_unvoiced_flag())
                    || (old_frame_unvoiced_flag() && !new_frame_unvoiced_flag())
                    || (old_frame_silence_flag() && !new_frame_silence_flag())
                    || (old_frame_unvoiced_flag() && new_frame_silence_flag()))
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
                    update_fifo_status_and_ints();
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
                    update_fifo_status_and_ints();
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

void Tms5220::generate(int16_t *buf, unsigned count) {
    process(buf, count);
}

} // namespace retrochip
