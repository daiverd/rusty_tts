// retrochip: standalone CLI for the ported MAME speech-chip cores in this
// directory. Reads a chip-specific code stream from stdin and writes raw
// signed 16-bit little-endian PCM to stdout.
//
// Usage: retrochip --chip tms5220 [--variant tms5200] < frames.bin > out.raw
//        retrochip --chip sp0256 --rom sp0256-al2.bin < codes.bin > out.raw
//
// For tms5220/tms5200: stdin is a stream of LPC-10 frame bytes fed directly
// into the chip's SPEAK EXTERNAL FIFO (see tms5220.h). The stream should end
// with a stop frame (a frame whose energy nibble is 0xF); if it doesn't, the
// chip halts on its own once the FIFO drains (buffer-empty condition).
//
// For sp0256: stdin is a stream of allophone/opcode address bytes (one per
// ALD write, see sp0256.h), fed one at a time - the chip runs each to
// completion (standby) before the next byte is accepted.
//
// For votrax: stdin is a stream of phoneme code bytes (0-63, see votrax.h),
// fed one at a time - each phone's duration is computed from its ROM data.
//
// For tms5110: stdin is a stream of 2-byte big-endian VSM word addresses
// (see tms5110.h) - the real ROMs only span 0x0000-0x7fff, so 16 bits is
// generous. For each address: load_address(addr); speak(); then samples are
// generated until the chip stops talking, before moving to the next address.
//
// For s14001a: stdin is a stream of single-byte 6-bit word indices (0-63,
// see s14001a.h) - unlike tms5110's VSM pointers, this chip takes the word
// number directly. For each byte: write_word_index(b); start(); then
// samples are generated until the chip stops talking, before moving to the
// next byte.
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>

#include "s14001a.h"
#include "sp0256.h"
#include "tms5110.h"
#include "tms5220.h"
#include "votrax.h"

#if defined(_WIN32)
#include <fcntl.h>
#include <io.h>
#endif

namespace {

std::vector<uint8_t> read_all_stdin() {
    std::vector<uint8_t> data;
    char buf[4096];
    size_t n;
    while ((n = std::fread(buf, 1, sizeof(buf), stdin)) > 0)
        data.insert(data.end(), buf, buf + n);
    return data;
}

int run_tms5220(retrochip::Tms5220Variant variant) {
    retrochip::Tms5220 chip(variant);
    chip.speak_external();

    std::vector<uint8_t> input = read_all_stdin();
    size_t pos = 0;

    const unsigned kChunk = 64;
    int16_t buf[kChunk];

    // Safety cap: at an 8kHz-ish sample rate (clock/80) this is well over a
    // minute of audio. A malformed/never-ending frame stream must not be
    // able to hang the process or grow output without bound.
    const unsigned long kMaxSamples = 8000UL * 90;
    unsigned long samples_written = 0;

    // Prime the FIFO, then keep it topped up between sample-generation
    // chunks until the input is exhausted and the chip stops talking.
    while (pos < input.size() && chip.fifo_has_room()) {
        chip.write(input[pos++]);
    }

    while (true) {
        chip.generate(buf, kChunk);
        std::fwrite(buf, sizeof(int16_t), kChunk, stdout);
        samples_written += kChunk;

        while (pos < input.size() && chip.fifo_has_room())
            chip.write(input[pos++]);

        if (getenv("RETROCHIP_DEBUG") && (samples_written % 6400 == 0)) {
            bool spen, ddis, talk, talkd; unsigned fc;
            chip.debug_state(spen, ddis, talk, talkd, fc);
            std::fprintf(stderr, "n=%lu pos=%zu/%zu SPEN=%d DDIS=%d TALK=%d TALKD=%d fifo=%u\n",
                         samples_written, pos, input.size(), spen, ddis, talk, talkd, fc);
        }
        if (pos >= input.size() && !chip.talking())
            break;
        if (samples_written >= kMaxSamples) {
            std::fprintf(stderr, "retrochip: hit safety sample cap, stopping\n");
            break;
        }
    }

    std::fflush(stdout);
    return 0;
}

int run_sp0256(const std::string &rom_path) {
    std::ifstream f(rom_path, std::ios::binary);
    if (!f) {
        std::fprintf(stderr, "retrochip: cannot open ROM file '%s'\n", rom_path.c_str());
        return 2;
    }
    std::vector<uint8_t> rom((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());

    retrochip::Sp0256 chip(rom);
    std::vector<uint8_t> input = read_all_stdin();

    // SP0256-AL2 boards commonly clock the chip at 3.12MHz; with the
    // chip's internal /336 divider that's ~9286Hz, widely rounded to
    // ~10kHz in enthusiast documentation. Only affects pitch/speed, since
    // this port (like tms5220.h) doesn't model real chip clock timing.
    const unsigned kSampleRate = 10000;

    const unsigned kChunk = 64;
    int16_t buf[kChunk];

    // Safety cap per allophone: a stuck/never-halting allophone code must
    // not be able to hang the process or grow output without bound.
    const unsigned long kMaxSamplesPerAllophone = kSampleRate * 5UL;

    for (uint8_t code : input) {
        chip.write_allophone(code);
        unsigned long samples_this_code = 0;
        while (!chip.standby()) {
            unsigned n = chip.generate(buf, kChunk);
            if (n == 0) break;
            std::fwrite(buf, sizeof(int16_t), n, stdout);
            samples_this_code += n;
            if (samples_this_code >= kMaxSamplesPerAllophone) {
                std::fprintf(stderr, "retrochip: hit per-allophone safety cap, moving on\n");
                break;
            }
        }
    }

    std::fflush(stdout);
    return 0;
}

int run_votrax(const std::string &rom_path) {
    std::ifstream f(rom_path, std::ios::binary);
    if (!f) {
        std::fprintf(stderr, "retrochip: cannot open ROM file '%s'\n", rom_path.c_str());
        return 2;
    }
    std::vector<uint8_t> rom((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());

    retrochip::Votrax chip(rom);
    std::vector<uint8_t> input = read_all_stdin();

    const unsigned kChunk = 64;
    int16_t buf[kChunk];

    // Safety cap per phone, same rationale as sp0256/tms5220.
    const unsigned long kMaxSamplesPerPhone = chip.sample_rate() * 5UL;

    for (uint8_t code : input) {
        unsigned n_samples = chip.speak_phone(code);
        if (n_samples > kMaxSamplesPerPhone) n_samples = static_cast<unsigned>(kMaxSamplesPerPhone);

        unsigned generated = 0;
        while (generated < n_samples) {
            unsigned chunk_n = n_samples - generated;
            if (chunk_n > kChunk) chunk_n = kChunk;
            chip.generate(buf, chunk_n);
            std::fwrite(buf, sizeof(int16_t), chunk_n, stdout);
            generated += chunk_n;
        }
    }

    std::fflush(stdout);
    return 0;
}

int run_tms5110(const std::string &rom_path) {
    std::ifstream f(rom_path, std::ios::binary);
    if (!f) {
        std::fprintf(stderr, "retrochip: cannot open ROM file '%s'\n", rom_path.c_str());
        return 2;
    }
    std::vector<uint8_t> rom((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());

    retrochip::Tms5110 chip;
    chip.set_vocab_rom(rom.data(), rom.size());

    std::vector<uint8_t> input = read_all_stdin();

    const unsigned kChunk = 64;
    int16_t buf[kChunk];

    // 8kHz sample rate (MASTER_CLOCK/80, see snspell.cpp/tms5110.cpp).
    const unsigned long kMaxSamplesPerWord = 8000UL * 5;

    for (size_t pos = 0; pos + 1 < input.size(); pos += 2) {
        uint32_t addr = (static_cast<uint32_t>(input[pos]) << 8) | input[pos + 1];
        chip.load_address(addr);
        chip.speak();

        unsigned long samples_this_word = 0;
        while (chip.talking()) {
            chip.generate(buf, kChunk);
            std::fwrite(buf, sizeof(int16_t), kChunk, stdout);
            samples_this_word += kChunk;
            if (samples_this_word >= kMaxSamplesPerWord) {
                std::fprintf(stderr, "retrochip: hit per-word safety cap, moving on\n");
                break;
            }
        }
    }

    std::fflush(stdout);
    return 0;
}

int run_s14001a(const std::string &rom_path) {
    std::ifstream f(rom_path, std::ios::binary);
    if (!f) {
        std::fprintf(stderr, "retrochip: cannot open ROM file '%s'\n", rom_path.c_str());
        return 2;
    }
    std::vector<uint8_t> rom((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());

    retrochip::S14001a chip;
    chip.set_rom(rom.data(), rom.size());
    std::vector<uint8_t> input = read_all_stdin();

    // No MAME driver clocks this chip for the actual TSI Speech+ calculator
    // (it's not a MAME-supported machine); 20000Hz is the documented clock
    // for this chip family's other real applications (see wolfpack.cpp's
    // S14001A instantiation - "likely factory set to 20000hz"). Only
    // affects pitch/speed, same caveat as sp0256/votrax's rate comments.
    const unsigned kSampleRate = 20000;

    const unsigned kChunk = 64;
    int16_t buf[kChunk];

    // Safety cap per word, same rationale as sp0256/votrax.
    const unsigned long kMaxSamplesPerWord = kSampleRate * 5UL;

    for (uint8_t word : input) {
        chip.write_word_index(word);
        chip.start();

        unsigned long samples_this_word = 0;
        while (chip.talking()) {
            chip.generate(buf, kChunk);
            std::fwrite(buf, sizeof(int16_t), kChunk, stdout);
            samples_this_word += kChunk;
            if (samples_this_word >= kMaxSamplesPerWord) {
                std::fprintf(stderr, "retrochip: hit per-word safety cap, moving on\n");
                break;
            }
        }
    }

    std::fflush(stdout);
    return 0;
}

} // namespace

int main(int argc, char **argv) {
#if defined(_WIN32)
    _setmode(_fileno(stdin), _O_BINARY);
    _setmode(_fileno(stdout), _O_BINARY);
#endif

    std::string chip = "tms5220";
    std::string variant = "tms5220";
    std::string rom_path;

    for (int i = 1; i < argc; i++) {
        std::string arg = argv[i];
        if (arg == "--chip" && i + 1 < argc) {
            chip = argv[++i];
        } else if (arg == "--variant" && i + 1 < argc) {
            variant = argv[++i];
        } else if (arg == "--rom" && i + 1 < argc) {
            rom_path = argv[++i];
        } else {
            std::fprintf(stderr, "retrochip: unknown argument '%s'\n", arg.c_str());
            return 2;
        }
    }

    if (chip == "tms5220") {
        auto v = (variant == "tms5200") ? retrochip::Tms5220Variant::TMS5200
                                         : retrochip::Tms5220Variant::TMS5220;
        return run_tms5220(v);
    }

    if (chip == "sp0256") {
        if (rom_path.empty()) {
            std::fprintf(stderr, "retrochip: --chip sp0256 requires --rom <path>\n");
            return 2;
        }
        return run_sp0256(rom_path);
    }

    if (chip == "votrax") {
        if (rom_path.empty()) {
            std::fprintf(stderr, "retrochip: --chip votrax requires --rom <path>\n");
            return 2;
        }
        return run_votrax(rom_path);
    }

    if (chip == "tms5110") {
        if (rom_path.empty()) {
            std::fprintf(stderr, "retrochip: --chip tms5110 requires --rom <path>\n");
            return 2;
        }
        return run_tms5110(rom_path);
    }

    if (chip == "s14001a") {
        if (rom_path.empty()) {
            std::fprintf(stderr, "retrochip: --chip s14001a requires --rom <path>\n");
            return 2;
        }
        return run_s14001a(rom_path);
    }

    std::fprintf(stderr, "retrochip: unsupported --chip '%s'\n", chip.c_str());
    return 2;
}
