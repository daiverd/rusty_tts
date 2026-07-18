#!/usr/bin/env bash
# Fetches the proprietary chip ROM/vocabulary dumps some retro speech-chip
# providers need (see native/retrochip and providers/sp0256.py, votrax.py,
# etc.) into a gitignored roms/ directory, verifying CRC32 against the
# values MAME's own device sources declare.
#
# These files are NOT redistributed by this repo or baked into the Docker
# image - they're proprietary silicon-vendor data (GI/Votrax) with no
# license grant from this project. This script's sources are MAME ROM-set
# collections already hosted on the public Internet Archive. Run it
# yourself, once, on a machine you control.
#
# Usage: scripts/fetch_roms.sh
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
mkdir -p roms

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

echo "Done. ROMs are in roms/ (gitignored)."
