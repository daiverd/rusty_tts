// Ported from MAME src/devices/sound/sp0256.cpp / sp0256.h
// Original license: BSD-3-Clause
// Original copyright-holders: Joseph Zbiciak, Tim Lindner
//
// Trimmed to standalone, single-allophone-at-a-time operation: the SPB640
// FIFO peripheral (an optional add-on chip some boards used for CPU-less
// multi-allophone streaming) is not modeled - this build always drives the
// chip the simple way real speech-synth cards did, one ALD (Address LoaD)
// write per allophone, polling standby() before sending the next. MAME
// device_t/sound_stream/save-state plumbing has been removed; the
// microsequencer (micro()/getb()) and 12-pole lattice filter (lpc12_t) are
// unchanged from the original source, as are the data-format/coefficient
// tables (also BSD-3-Clause).
#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

namespace retrochip {

class Sp0256 {
public:
    // rom: the SP0256-AL2 mask ROM dump (2048 bytes), loaded at its real
    // address offset (0x1000) within the chip's 64K address space, matching
    // MAME's coco_ssc ROM_LOAD("sp0256-al2.bin", 0x1000, 0x0800, ...).
    explicit Sp0256(const std::vector<uint8_t> &rom);

    // Equivalent to ald_w(): load one allophone/opcode address (0-255).
    // Real hardware drops writes while busy (!lrq) - callers should poll
    // ready() and wait for it before sending the next code.
    void write_allophone(uint8_t code);

    bool ready() const { return m_lrq != 0; }     // lrq_r()
    bool standby() const { return m_sby_line != 0; } // sby_r()

    // Generate up to `count` samples (16-bit signed PCM) into buf. Returns
    // the number of samples actually written (may return 0 once standby).
    unsigned generate(int16_t *buf, unsigned count);

private:
    struct Lpc12 {
        int update(int num_samp, int16_t *out);
        void regdec();

        int rpt = -1, cnt = 0;
        uint32_t per = 0, rng = 1;
        int amp = 0;
        int16_t f_coef[6] = {};
        int16_t b_coef[6] = {};
        int16_t z_data[6][2] = {};
        uint8_t r[16] = {};
        int interp = 0;

        static int16_t limit(int16_t s);
    };

    uint32_t getb(int len);
    void micro();
    void set_sby(int state) { m_sby_line = state; }

    std::vector<uint8_t> m_rom; // 64K address space (only 0x1000-0x17ff populated)

    int m_sby_line = 1;
    int m_silent = 1;

    Lpc12 m_filt;
    int m_lrq = 1;
    int m_ald = 0;
    int m_pc = 0;
    int m_stack = 0;
    int m_halted = 1;
    uint32_t m_mode = 0;
    uint32_t m_page = 0x1000 << 3;
};

} // namespace retrochip
