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
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>

#include "sp0256.h"
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

    std::fprintf(stderr, "retrochip: unsupported --chip '%s'\n", chip.c_str());
    return 2;
}
