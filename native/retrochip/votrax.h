// Ported from MAME src/devices/sound/votrax.cpp / votrax.h
// Original license: BSD-3-Clause
// Original copyright-holders: Olivier Galibert
//
// Trimmed to standalone, single-phone-at-a-time operation: MAME's
// timer-driven /AR (request) line and the ~72-main-clock-tick ROM access
// delay between a write() and the parameters actually committing are not
// modeled (that delay is ~100us at the reference 720kHz clock, well below
// audible/perceptible - this build commits a phone's ROM parameters
// immediately). The analog filter simulation (chip_update/analog_calc and
// the build_*_filter transfer-function math) is unchanged from the
// original source, as is the phone ROM bit-layout decode and the phoneme
// name table (also BSD-3-Clause).
#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

namespace retrochip {

class Votrax {
public:
    // rom: the SC-01A internal phone ROM dump (512 bytes = 64 x 8-byte
    // little-endian entries, matching MAME's ROM_REGION64_LE).
    // main_clock: reference design (Votrax's own "Personal Speech System")
    // runs the chip at 720kHz; sample rate is main_clock/18.
    explicit Votrax(const std::vector<uint8_t> &rom, uint32_t main_clock = 720000);

    void set_inflection(uint8_t data);

    // Commit a new phone (6-bit code, 0-63) and return how many samples it
    // will occupy before the chip is ready for the next one (this is the
    // real hardware's phone duration, computed from the ROM data - not an
    // arbitrary choice).
    unsigned speak_phone(uint8_t code);

    unsigned sample_rate() const { return static_cast<unsigned>(m_sclock + 0.5); }

    // Generate up to `count` samples (16-bit signed PCM) into buf.
    void generate(int16_t *buf, unsigned count);

private:
    static const char *const kPhoneTable[64];
    static const double kGlottalWave[9];

    void phone_commit();
    static void interpolate(uint8_t &reg, uint8_t target);
    void chip_update();
    void filters_commit(bool force);
    double analog_calc();

    void build_standard_filter(double *a, double *b, double c1t, double c1b,
                                double c2t, double c2b, double c3, double c4);
    void build_noise_shaper_filter(double *a, double *b, double c1, double c2t,
                                    double c2b, double c3, double c4);
    void build_lowpass_filter(double *a, double *b, double c1t, double c1b);
    void build_injection_filter(double *a, double *b, double c1b, double c2t,
                                 double c2b, double c3, double c4);

    static double bits_to_caps(uint32_t value, std::initializer_list<double> caps_values);
    template <unsigned N>
    static void shift_hist(double val, double (&hist_array)[N]) {
        for (unsigned i = N - 1; i > 0; i--) hist_array[i] = hist_array[i - 1];
        hist_array[0] = val;
    }
    template <unsigned Nx, unsigned Ny, unsigned Na, unsigned Nb>
    static double apply_filter(const double (&x)[Nx], const double (&y)[Ny],
                                const double (&a)[Na], const double (&b)[Nb]) {
        double total = 0;
        for (unsigned i = 0; i < Na; i++) total += x[i] * a[i];
        for (unsigned i = 1; i < Nb; i++) total -= y[i - 1] * b[i];
        return total / b[0];
    }

    std::vector<uint64_t> m_rom; // 64 entries

    uint32_t m_mainclock;
    double m_sclock; // stream sample clock (40kHz nominal, main/18)
    double m_cclock; // 20kHz capacitor switching clock (main/36)
    uint32_t m_sample_count = 0;

    uint8_t m_inflection = 0;
    uint8_t m_phone = 0x3f;

    uint8_t m_rom_duration = 0;
    uint8_t m_rom_vd = 0, m_rom_cld = 0;
    uint8_t m_rom_fa = 0, m_rom_fc = 0, m_rom_va = 0;
    uint8_t m_rom_f1 = 0, m_rom_f2 = 0, m_rom_f2q = 0, m_rom_f3 = 0;
    bool m_rom_closure = false;
    bool m_rom_pause = false;

    uint8_t m_cur_fa = 0, m_cur_fc = 0, m_cur_va = 0;
    uint8_t m_cur_f1 = 0, m_cur_f2 = 0, m_cur_f2q = 0, m_cur_f3 = 0;

    uint8_t m_filt_fa = 0, m_filt_fc = 0, m_filt_va = 0;
    uint8_t m_filt_f1 = 0, m_filt_f2 = 0, m_filt_f2q = 0, m_filt_f3 = 0;

    uint16_t m_phonetick = 0;
    uint8_t m_ticks = 0;
    uint8_t m_pitch = 0;
    uint8_t m_closure = 0;
    uint8_t m_update_counter = 0;

    bool m_cur_closure = true;
    uint16_t m_noise = 0;
    bool m_cur_noise = false;

    double m_voice_1[4] = {}, m_voice_2[4] = {}, m_voice_3[4] = {};
    double m_noise_1[3] = {}, m_noise_2[3] = {}, m_noise_3[2] = {}, m_noise_4[2] = {};
    double m_vn_1[4] = {}, m_vn_2[4] = {}, m_vn_3[4] = {}, m_vn_4[4] = {}, m_vn_5[2] = {}, m_vn_6[2] = {};

    double m_f1_a[4] = {}, m_f1_b[4] = {};
    double m_f2v_a[4] = {}, m_f2v_b[4] = {};
    double m_f2n_a[2] = {}, m_f2n_b[2] = {};
    double m_f3_a[4] = {}, m_f3_b[4] = {};
    double m_f4_a[4] = {}, m_f4_b[4] = {};
    double m_fx_a[1] = {}, m_fx_b[2] = {};
    double m_fn_a[3] = {}, m_fn_b[3] = {};
};

} // namespace retrochip
