// Ported from MAME src/devices/sound/votrax.cpp (BSD-3-Clause).
// See votrax.h for details of what was trimmed for standalone use.
#include "votrax.h"

#include <cmath>


namespace retrochip {

namespace {

// Matches MAME's util::bitswap(): the first listed bit becomes the MSB of
// the right-aligned output field, the last listed bit becomes the LSB.
template <typename T>
constexpr uint64_t bit_of(T val, unsigned n) {
    return (static_cast<uint64_t>(val) >> n) & 1ull;
}

template <typename T, typename... Rest>
constexpr uint64_t bitswap(T val, unsigned b, Rest... rest) {
    if constexpr (sizeof...(rest) > 0)
        return (bit_of(val, b) << sizeof...(rest)) | bitswap(val, rest...);
    else
        return bit_of(val, b);
}

} // namespace

const char *const Votrax::kPhoneTable[64] = {
    "EH3", "EH2", "EH1", "PA0", "DT", "A1", "A2", "ZH",
    "AH2", "I3", "I2", "I1", "M", "N", "B", "V",
    "CH", "SH", "Z", "AW1", "NG", "AH1", "OO1", "OO",
    "L", "K", "J", "H", "G", "F", "D", "S",
    "A", "AY", "Y1", "UH3", "AH", "P", "O", "I",
    "U", "Y", "T", "R", "E", "W", "AE", "AE1",
    "AW2", "UH2", "UH1", "UH", "O2", "O1", "IU", "U1",
    "THV", "TH", "ER", "EH", "E1", "AW", "PA1", "STOP",
};

const double Votrax::kGlottalWave[9] = {
    0, -4 / 7.0, 7 / 7.0, 6 / 7.0, 5 / 7.0, 4 / 7.0, 3 / 7.0, 2 / 7.0, 1 / 7.0,
};

Votrax::Votrax(const std::vector<uint8_t> &rom, uint32_t main_clock) {
    m_rom.resize(64, 0);
    for (size_t i = 0; i < 64 && (i + 1) * 8 <= rom.size(); i++) {
        uint64_t v = 0;
        for (int b = 0; b < 8; b++)
            v |= static_cast<uint64_t>(rom[i * 8 + b]) << (8 * b);
        m_rom[i] = v;
    }

    m_mainclock = main_clock;
    m_sclock = m_mainclock / 18.0;
    m_cclock = m_mainclock / 36.0;

    phone_commit();
    m_cur_fa = m_cur_fc = m_cur_va = 0;
    m_cur_f1 = m_cur_f2 = m_cur_f2q = m_cur_f3 = 0;
    filters_commit(true);
}

void Votrax::set_inflection(uint8_t data) {
    m_inflection = data & 3;
}

void Votrax::phone_commit() {
    m_phonetick = 0;
    m_ticks = 0;

    for (int i = 0; i < 64; i++) {
        uint64_t val = m_rom[i];
        if (m_phone == ((val >> 56) & 0x3f)) {
            m_rom_f1 = static_cast<uint8_t>(bitswap(val, 0, 7, 14, 21));
            m_rom_va = static_cast<uint8_t>(bitswap(val, 1, 8, 15, 22));
            m_rom_f2 = static_cast<uint8_t>(bitswap(val, 2, 9, 16, 23));
            m_rom_fc = static_cast<uint8_t>(bitswap(val, 3, 10, 17, 24));
            m_rom_f2q = static_cast<uint8_t>(bitswap(val, 4, 11, 18, 25));
            m_rom_f3 = static_cast<uint8_t>(bitswap(val, 5, 12, 19, 26));
            m_rom_fa = static_cast<uint8_t>(bitswap(val, 6, 13, 20, 27));

            m_rom_cld = static_cast<uint8_t>(bitswap(val, 34, 32, 30, 28));
            m_rom_vd = static_cast<uint8_t>(bitswap(val, 35, 33, 31, 29));

            m_rom_closure = bitswap(val, 36) != 0;
            m_rom_duration = static_cast<uint8_t>(bitswap(~val, 37, 38, 39, 40, 41, 42, 43));

            m_rom_pause = (m_phone == 0x03) || (m_phone == 0x3e);

            if (m_rom_cld == 0)
                m_cur_closure = m_rom_closure;

            return;
        }
    }
}

void Votrax::interpolate(uint8_t &reg, uint8_t target) {
    reg = static_cast<uint8_t>(reg - (reg >> 3) + (target << 1));
}

unsigned Votrax::speak_phone(uint8_t code) {
    m_phone = code & 0x3f;
    phone_commit();

    // Matches MAME's phone_tick() T_COMMIT_PHONE handler:
    //   m_timer->adjust(attotime::from_ticks(16*(m_rom_duration*4+1)*4*9+2, m_mainclock), T_END_OF_PHONE);
    uint64_t duration_ticks = 16ull * (static_cast<uint64_t>(m_rom_duration) * 4 + 1) * 4 * 9 + 2;
    unsigned samples = static_cast<unsigned>(duration_ticks / 18);
    return samples == 0 ? 1 : samples;
}

void Votrax::chip_update() {
    if (m_ticks != 0x10) {
        m_phonetick++;
        if (m_phonetick == ((m_rom_duration << 2) | 1)) {
            m_phonetick = 0;
            m_ticks++;
            if (m_ticks == m_rom_cld)
                m_cur_closure = m_rom_closure;
        }
    }

    m_update_counter++;
    if (m_update_counter == 0x30) m_update_counter = 0;

    bool tick_625 = !(m_update_counter & 0xf);
    bool tick_208 = m_update_counter == 0x28;

    if (tick_208 && (!m_rom_pause || !(m_filt_fa || m_filt_va))) {
        interpolate(m_cur_fc, m_rom_fc);
        interpolate(m_cur_f1, m_rom_f1);
        interpolate(m_cur_f2, m_rom_f2);
        interpolate(m_cur_f2q, m_rom_f2q);
        interpolate(m_cur_f3, m_rom_f3);
    }

    if (tick_625) {
        if (m_ticks >= m_rom_vd)
            interpolate(m_cur_fa, m_rom_fa);
        if (m_ticks >= m_rom_cld)
            interpolate(m_cur_va, m_rom_va);
    }

    if (!m_cur_closure && (m_filt_fa || m_filt_va))
        m_closure = 0;
    else if (m_closure != (7 << 2))
        m_closure++;

    m_pitch = (m_pitch + 1) & 0xff;
    if (m_pitch == ((0xe0 ^ (m_inflection << 5) ^ (m_filt_f1 << 1)) + 2))
        m_pitch = 0;

    if ((m_pitch & 0xf9) == 0x08)
        filters_commit(false);

    bool inp = m_cur_noise && (m_noise != 0x7fff);
    m_noise = static_cast<uint16_t>(((m_noise << 1) & 0x7ffe) | (inp ? 1 : 0));
    m_cur_noise = !(((m_noise >> 14) ^ (m_noise >> 13)) & 1);
}

double Votrax::bits_to_caps(uint32_t value, std::initializer_list<double> caps_values) {
    double total = 0;
    for (double d : caps_values) {
        if (value & 1) total += d;
        value >>= 1;
    }
    return total;
}

void Votrax::build_standard_filter(double *a, double *b, double c1t, double c1b,
                                    double c2t, double c2b, double c3, double c4) {
    constexpr double PI = 3.14159265358979323846;

    double k0 = c1t / (m_cclock * c1b);
    double k1 = c4 * c2t / (m_cclock * c1b * c3);
    double k2 = c4 * c2b / (m_cclock * m_cclock * c1b * c3);

    double fpeak = std::sqrt(std::fabs(k0 * k1 - k2)) / (2 * PI * k2);
    double zc = 2 * PI * fpeak / std::tan(PI * fpeak / m_sclock);

    double m0 = zc * k0;
    double m1 = zc * k1;
    double m2 = zc * zc * k2;

    a[0] = 1 + m0;
    a[1] = 3 + m0;
    a[2] = 3 - m0;
    a[3] = 1 - m0;
    b[0] = 1 + m1 + m2;
    b[1] = 3 + m1 - m2;
    b[2] = 3 - m1 - m2;
    b[3] = 1 - m1 + m2;
}

void Votrax::build_lowpass_filter(double *a, double *b, double c1t, double c1b) {
    constexpr double PI = 3.14159265358979323846;

    double k = c1b / (m_cclock * c1t) * (150.0 / 4000.0);
    double fpeak = 1 / (2 * PI * k);
    double zc = 2 * PI * fpeak / std::tan(PI * fpeak / m_sclock);
    double m = zc * k;

    a[0] = 1;
    b[0] = 1 + m;
    b[1] = 1 - m;
}

void Votrax::build_noise_shaper_filter(double *a, double *b, double c1, double c2t,
                                        double c2b, double c3, double c4) {
    constexpr double PI = 3.14159265358979323846;

    double k0 = c2t * c3 * c2b / c4;
    double k1 = c2t * (m_cclock * c2b);
    double k2 = c1 * c2t * c3 / (m_cclock * c4);

    double fpeak = std::sqrt(1 / k2) / (2 * PI);
    double zc = 2 * PI * fpeak / std::tan(PI * fpeak / m_sclock);

    double m0 = zc * k0;
    double m1 = zc * k1;
    double m2 = zc * zc * k2;

    a[0] = m0;
    a[1] = 0;
    a[2] = -m0;
    b[0] = 1 + m1 + m2;
    b[1] = 2 - 2 * m2;
    b[2] = 1 - m1 + m2;
}

void Votrax::build_injection_filter(double *a, double *b, double c1b, double c2t,
                                     double c2b, double c3, double c4) {
    double k0 = m_cclock * c2t;
    double k1 = m_cclock * (c1b * c3 / c2t - c2t);
    double k2 = c2b;

    double zc = 2 * m_sclock;
    double m = zc * k2;

    a[0] = k0 + m;
    a[1] = k0 - m;
    b[0] = k1 + m;
    b[1] = k1 - m;
    (void)c4;
}

void Votrax::filters_commit(bool force) {
    m_filt_fa = m_cur_fa >> 4;
    m_filt_fc = m_cur_fc >> 4;
    m_filt_va = m_cur_va >> 4;

    if (force || m_filt_f1 != (m_cur_f1 >> 4)) {
        m_filt_f1 = m_cur_f1 >> 4;
        build_standard_filter(m_f1_a, m_f1_b,
                               11247, 11797, 949, 52067,
                               2280 + bits_to_caps(m_filt_f1, {2546, 4973, 9861, 19724}),
                               166272);
    }

    if (force || m_filt_f2 != (m_cur_f2 >> 3) || m_filt_f2q != (m_cur_f2q >> 4)) {
        m_filt_f2 = m_cur_f2 >> 3;
        m_filt_f2q = m_cur_f2q >> 4;

        build_standard_filter(m_f2v_a, m_f2v_b,
                               24840, 29154,
                               829 + bits_to_caps(m_filt_f2q, {1390, 2965, 5875, 11297}),
                               38180,
                               2352 + bits_to_caps(m_filt_f2, {833, 1663, 3164, 6327, 12654}),
                               34270);

        build_injection_filter(m_f2n_a, m_f2n_b,
                                29154,
                                829 + bits_to_caps(m_filt_f2q, {1390, 2965, 5875, 11297}),
                                38180,
                                2352 + bits_to_caps(m_filt_f2, {833, 1663, 3164, 6327, 12654}),
                                34270);
    }

    if (force || m_filt_f3 != (m_cur_f3 >> 4)) {
        m_filt_f3 = m_cur_f3 >> 4;
        build_standard_filter(m_f3_a, m_f3_b,
                               0, 17594, 868, 18828,
                               8480 + bits_to_caps(m_filt_f3, {2226, 4485, 9056, 18111}),
                               50019);
    }

    if (force) {
        build_standard_filter(m_f4_a, m_f4_b, 0, 28810, 1165, 21457, 8558, 7289);
        build_lowpass_filter(m_fx_a, m_fx_b, 1122, 23131);
        build_noise_shaper_filter(m_fn_a, m_fn_b, 15500, 14854, 8450, 9523, 14083);
    }
}

double Votrax::analog_calc() {
    double v = m_pitch >= (9 << 3) ? 0 : kGlottalWave[m_pitch >> 3];
    v = v * m_filt_va / 15.0;
    shift_hist(v, m_voice_1);

    v = apply_filter(m_voice_1, m_voice_2, m_f1_a, m_f1_b);
    shift_hist(v, m_voice_2);

    v = apply_filter(m_voice_2, m_voice_3, m_f2v_a, m_f2v_b);
    shift_hist(v, m_voice_3);

    double n = 1e4 * ((m_pitch & 0x40 ? m_cur_noise : false) ? 1 : -1);
    n = n * m_filt_fa / 15.0;
    shift_hist(n, m_noise_1);

    n = apply_filter(m_noise_1, m_noise_2, m_fn_a, m_fn_b);
    shift_hist(n, m_noise_2);

    double n2 = n * m_filt_fc / 15.0;
    shift_hist(n2, m_noise_3);

    n2 = apply_filter(m_noise_3, m_noise_4, m_f2n_a, m_f2n_b);
    shift_hist(n2, m_noise_4);

    double vn = v + n2;
    shift_hist(vn, m_vn_1);

    vn = apply_filter(m_vn_1, m_vn_2, m_f3_a, m_f3_b);
    shift_hist(vn, m_vn_2);

    vn += n * (5 + (15 ^ m_filt_fc)) / 20.0;
    shift_hist(vn, m_vn_3);

    vn = apply_filter(m_vn_3, m_vn_4, m_f4_a, m_f4_b);
    shift_hist(vn, m_vn_4);

    vn = vn * (7 ^ (m_closure >> 2)) / 7.0;
    shift_hist(vn, m_vn_5);

    vn = apply_filter(m_vn_5, m_vn_6, m_fx_a, m_fx_b);
    shift_hist(vn, m_vn_6);

    return vn * 0.35;
}

void Votrax::generate(int16_t *buf, unsigned count) {
    for (unsigned i = 0; i < count; i++) {
        m_sample_count++;
        if (m_sample_count & 1) chip_update();

        double s = analog_calc();
        // analog_calc()'s output is a small-signal voltage-ish value
        // (unitless in the original, fed straight into MAME's normalized
        // sound_stream, roughly within +-1 in typical operation, though
        // not hard-clamped there either). Scale to 16-bit PCM and clamp
        // for safety against any transient excursions.
        double scaled = s * 32767.0;
        if (scaled > 32767.0) scaled = 32767.0;
        if (scaled < -32768.0) scaled = -32768.0;
        buf[i] = static_cast<int16_t>(scaled);
    }
}

} // namespace retrochip
