#!/usr/bin/env bash
# Fetches the proprietary chip ROM/vocabulary dumps some retro speech-chip
# providers need (see native/retrochip and providers/sp0256.py, votrax.py,
# etc.) into a gitignored roms/ directory, verifying CRC32 against the
# values MAME's own device sources declare. Also fetches the Apple IIe/
# Disk II system ROMs and the real Textalker driver disk image needed for
# the MAME-based Echo II Plus automation (see providers/textalker.py), plus
# the firmware ROMs for the Votrax Type 'N Talk and Personal Speech System
# machine automations (see providers/votrax_tnt.py, votrax_pss.py), and the
# RC Systems DoubleTalk PC firmware plus its GLaBIOS boot ROM (see
# providers/doubletalk.py), into a gitignored mame_roms/ directory.
#
# These files are NOT redistributed by this repo or baked into the Docker
# image - they're proprietary silicon-vendor/publisher data (GI/Votrax/TI/
# Apple/Street Electronics/RC Systems) with no license grant from this
# project (GLaBIOS is the one exception - open-source, GPL3). This script's
# sources are MAME ROM-set collections and platform BIOS packs already
# hosted on the public Internet Archive, plus one long-standing Apple II
# preservation mirror for a single PROM not present in that collection
# under an obvious name. Run it yourself, once, on a machine you control.
#
# Usage: scripts/fetch_roms.sh
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
mkdir -p roms mame_roms/apple2ee mame_roms/disks mame_roms/votrtnt mame_roms/votrpss \
    mame_roms/doubletalkpc_isa mame_roms/pcv20

need() {
    command -v "$1" >/dev/null 2>&1 || { echo "fetch_roms.sh: '$1' is required (apt install $2)" >&2; exit 1; }
}
need wget wget
need 7z p7zip-full
need python3 python3

crc32_of() {
    python3 -c "import zlib,sys; print(format(zlib.crc32(open(sys.argv[1],'rb').read()),'08x'))" "$1"
}

# Downloads a file (optionally extracting one member from a .7z/.zip
# archive) into out_dir/out_file, verifying CRC32. Skips re-downloading if
# a valid copy is already present.
fetch_and_extract() {
    local name="$1" url="$2" archive_member="$3" out_dir="$4" out_file="$5" expected_crc32="$6"

    if [ -f "${out_dir}/${out_file}" ]; then
        local have_crc
        have_crc=$(crc32_of "${out_dir}/${out_file}")
        if [ "${have_crc}" = "${expected_crc32}" ]; then
            echo "[skip] ${name}: ${out_dir}/${out_file} already present, CRC32 OK"
            return 0
        fi
        echo "[warn] ${name}: ${out_dir}/${out_file} exists but CRC32 mismatch (${have_crc} != ${expected_crc32}), re-fetching"
    fi

    local tmpdir
    tmpdir=$(mktemp -d)
    trap 'rm -rf "${tmpdir}"' RETURN

    echo "[fetch] ${name}: ${url}"
    wget -q "${url}" -O "${tmpdir}/archive"

    case "${url}" in
        *.7z) 7z x "${tmpdir}/archive" -o"${tmpdir}/extracted" -y >/dev/null ;;
        *.zip) python3 -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "${tmpdir}/archive" "${tmpdir}/extracted" ;;
        *) mkdir -p "${tmpdir}/extracted"; cp "${tmpdir}/archive" "${tmpdir}/extracted/${archive_member}" ;;
    esac

    local found
    found=$(find "${tmpdir}/extracted" -name "${archive_member}" -print -quit)
    if [ -z "${found}" ]; then
        echo "[error] ${name}: '${archive_member}' not found in downloaded archive" >&2
        exit 1
    fi

    local got_crc
    got_crc=$(crc32_of "${found}")
    if [ "${got_crc}" != "${expected_crc32}" ]; then
        echo "[error] ${name}: CRC32 mismatch, got ${got_crc}, expected ${expected_crc32}" >&2
        exit 1
    fi

    mkdir -p "${out_dir}"
    cp "${found}" "${out_dir}/${out_file}"
    echo "[ok] ${name}: ${out_dir}/${out_file} (CRC32 ${got_crc} verified)"
}

# --- Speech-chip ROMs (used directly by native/retrochip) ---

fetch_and_extract \
    "SP0256-AL2" \
    "https://archive.org/download/mame-0.272-romset-complete-merged/devices/coco_ssc.7z" \
    "sp0256-al2.bin" \
    "roms" "sp0256-al2.bin" \
    "b504ac15"

fetch_and_extract \
    "Votrax SC-01A" \
    "https://archive.org/download/mame-0.272-romset-complete-merged/devices/votrsc01a.7z" \
    "sc01a.bin" \
    "roms" "sc01a.bin" \
    "fc416227"

# --- Apple IIe / Disk II / Echo II Plus system ROMs (used by the MAME-based
#     Textalker automation, see docker-compose.yml's mame_roms mount) ---

for pair in \
    "341-0132-d.e12:c506efb9" \
    "342-0265-a.chr:2651014d" \
    "342-0303-a.e8:95e10034" \
    "342-0304-a.e10:443aa7c4"
do
    fname="${pair%%:*}"
    crc="${pair##*:}"
    fetch_and_extract \
        "Apple IIe enhanced ROM (${fname})" \
        "https://archive.org/download/mame-0.272-romset-complete-merged/mess/apple2e.7z" \
        "${fname}" \
        "mame_roms/apple2ee" "${fname}" \
        "${crc}"
done

fetch_and_extract \
    "Disk II P5 PROM" \
    "https://archive.org/download/mame-0.272-romset-complete-merged/devices/a2diskiing.7z" \
    "341-0027-a.p5" \
    "mame_roms/apple2ee" "341-0027-a.p5" \
    "ce7144f6"

# Not present under an obvious name in the archive.org MAME romset
# collection; sourced from the long-standing Apple II Documentation
# Project mirror instead.
fetch_and_extract \
    "Disk II P6 PROM" \
    "https://mirrors.apple2.org.za/Apple%20II%20Documentation%20Project/Interface%20Cards/Disk%20Drive%20Controllers/Apple%20Disk%20II%20Interface%20Card/ROM%20Images/Apple%20Disk%20II%2016%20Sector%20Interface%20Card%20ROM%20P6%20-%20341-0028.bin" \
    "341-0028-a.rom" \
    "mame_roms/apple2ee" "341-0028-a.rom" \
    "b72a2c70"

# Votrax ROM is also usable as an alternate voice card on this machine;
# reuse the copy already fetched into roms/ above.
cp -n "roms/sc01a.bin" "mame_roms/apple2ee/sc01a.bin" 2>/dev/null || true

# --- Textalker driver disk (real historical Echo II Plus screen-reader
#     software, commercial/copyrighted, not just a silicon-vendor ROM) ---

fetch_and_extract \
    "Textalker 1.3 disk image" \
    "https://archive.org/download/Textalker1.3/Textalker_1.3.dsk" \
    "Textalker_1.3.dsk" \
    "mame_roms/disks" "Textalker_1.3.dsk" \
    "00da4aef"

# --- Votrax Type 'N Talk (standalone RS-232 speech synthesizer, 1980) ---

fetch_and_extract \
    "Votrax Type 'N Talk firmware" \
    "https://archive.org/download/mame-0.272-romset-complete-merged/mess/votrtnt.7z" \
    "cn49752n.bin" \
    "mame_roms/votrtnt" "cn49752n.bin" \
    "a44e1af3"

cp -n "roms/sc01a.bin" "mame_roms/votrtnt/sc01a.bin" 2>/dev/null || true

# --- Votrax Personal Speech System (Z80-based speech synthesizer, 1982) ---

for pair in \
    "u-2.v3.c.bin:410c58cf" \
    "u-3.v3.c.bin:1439492e" \
    "u-4.v3.1.bin:0b7c4260"
do
    fname="${pair%%:*}"
    crc="${pair##*:}"
    fetch_and_extract \
        "Votrax Personal Speech System ROM (${fname})" \
        "https://archive.org/download/mame-0.272-romset-complete-merged/mess/votrpss.7z" \
        "${fname}" \
        "mame_roms/votrpss" "${fname}" \
        "${crc}"
done

cp -n "roms/sc01a.bin" "mame_roms/votrpss/sc01a.bin" 2>/dev/null || true

# --- RC Systems DoubleTalk PC (ISA text-to-speech card, 1990s) - see
#     providers/doubletalk.py. Firmware ROM is the archive.org dump used
#     throughout the doubletalk-pc/mame-doubletalk research repos (not
#     mirrored in a MAME romset collection like the chips above, since
#     DoubleTalk PC support isn't upstreamed to mamedev/mame - see
#     native/mame-doubletalk/). GLaBIOS is an open-source (GPL3) XT-clone
#     BIOS used as the host machine's boot ROM instead of the real
#     (copyrighted) IBM PC BIOS - see https://github.com/640-KB/GLaBIOS.

fetch_and_extract \
    "DoubleTalk PC firmware" \
    "https://archive.org/download/doubletalkpc/doubletalkpc.BIN" \
    "doubletalkpc.BIN" \
    "mame_roms/doubletalkpc_isa" "doubletalkpc.bin" \
    "66685631"

fetch_and_extract \
    "GLaBIOS 0.2.4 (pcv20 boot ROM)" \
    "https://github.com/640-KB/GLaBIOS/releases/download/v0.2.4/GLABIOS_0.2.4_VT.ROM" \
    "GLABIOS_0.2.4_VT.ROM" \
    "mame_roms/pcv20" "glabios_0.2.4_vt.rom" \
    "7c173fe3"

# --- TI Speak & Spell (TMS5100/TMC0281 chip) vocabulary ROMs, used directly
#     by native/retrochip's tms5110 core - see providers/snspell.py. Only the
#     validated two-ROM regions with correct English vocabulary word-list
#     parsing are fetched (see providers/snspell.py's docstring for why the
#     single-ROM and Spanish variants are skipped).

fetch_and_extract \
    "Speak & Spell (US, 1980) ROM 0" \
    "https://archive.org/download/mame-0.272-romset-complete-merged/mess/snspell.7z" \
    "tmc0351n2l" \
    "roms/snspell/us" "tmc0351n2l.bin" \
    "2d03b292"

fetch_and_extract \
    "Speak & Spell (US, 1980) ROM 1" \
    "https://archive.org/download/mame-0.272-romset-complete-merged/mess/snspell.7z" \
    "tmc0352n2l" \
    "roms/snspell/us" "tmc0352n2l.bin" \
    "a6d56883"

fetch_and_extract \
    "Speak & Spell (US, 1978) ROM 0" \
    "https://archive.org/download/mame-0.272-romset-complete-merged/mess/snspell.7z" \
    "tmc0351nl" \
    "roms/snspell/us_1978" "tmc0351nl.bin" \
    "beea3373"

fetch_and_extract \
    "Speak & Spell (US, 1978) ROM 1" \
    "https://archive.org/download/mame-0.272-romset-complete-merged/mess/snspell.7z" \
    "tmc0352nl" \
    "roms/snspell/us_1978" "tmc0352nl.bin" \
    "d51f0587"

fetch_and_extract \
    "Speak & Spell (UK, 1978) ROM 0" \
    "https://archive.org/download/mame-0.272-romset-complete-merged/mess/snspell.7z" \
    "cd2303" \
    "roms/snspell/uk" "cd2303.bin" \
    "0fae755c"

fetch_and_extract \
    "Speak & Spell (UK, 1978) ROM 1" \
    "https://archive.org/download/mame-0.272-romset-complete-merged/mess/snspell.7z" \
    "cd2304" \
    "roms/snspell/uk" "cd2304.bin" \
    "e2a270eb"

fetch_and_extract \
    "Speak & Spell (Japan) ROM 0" \
    "https://archive.org/download/mame-0.272-romset-complete-merged/mess/snspell.7z" \
    "cd2321" \
    "roms/snspell/jp" "cd2321.bin" \
    "ac010cce"

fetch_and_extract \
    "Speak & Spell (Japan) ROM 1" \
    "https://archive.org/download/mame-0.272-romset-complete-merged/mess/snspell.7z" \
    "cd2322" \
    "roms/snspell/jp" "cd2322.bin" \
    "b6f4bba4"

# --- TSI/Silicon Systems S14001A (TSI Speech+ talking calculator, 1976),
#     used directly by native/retrochip's s14001a core - see
#     providers/s14001a_calculator.py. Direct binary download, not an
#     archive member, same pattern as the Disk II P6 PROM above.

fetch_and_extract \
    "TSI Speech+ S14001A mask ROM" \
    "https://seanriddle.com/tsispeechplusmaskrom.bin" \
    "tsispeechplusmaskrom.bin" \
    "roms/tsispeech" "tsispeechplusmaskrom.bin" \
    "543b46d4"

echo "Done. ROMs are in roms/ and mame_roms/ (both gitignored)."
