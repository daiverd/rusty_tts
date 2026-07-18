#!/usr/bin/env bash
# Fetches the proprietary chip ROM/vocabulary dumps some retro speech-chip
# providers need (see native/retrochip and providers/sp0256.py, votrax.py,
# etc.) into a gitignored roms/ directory, verifying CRC32 against the
# values MAME's own device sources declare. Also fetches the Apple IIe/
# Disk II system ROMs and the real Textalker driver disk image needed for
# the MAME-based Echo II Plus automation (see providers/tms5220.py), into
# a gitignored mame_roms/ directory.
#
# These files are NOT redistributed by this repo or baked into the Docker
# image - they're proprietary silicon-vendor/publisher data (GI/Votrax/TI/
# Apple/Street Electronics) with no license grant from this project. This
# script's sources are MAME ROM-set collections and platform BIOS packs
# already hosted on the public Internet Archive, plus one long-standing
# Apple II preservation mirror for a single PROM not present in that
# collection under an obvious name. Run it yourself, once, on a machine
# you control.
#
# Usage: scripts/fetch_roms.sh
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
mkdir -p roms mame_roms/apple2ee mame_roms/disks

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

echo "Done. ROMs are in roms/ and mame_roms/ (both gitignored)."
