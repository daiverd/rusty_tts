-- Generic MAME autoboot Lua script for standalone speech-synthesizer
-- machines that take plain ASCII text via a keyboard/terminal device with
-- no OS or disk to boot first (Votrax Type 'N Talk, Votrax Personal
-- Speech System - see providers/votrax_tnt.py, votrax_pss.py). Unlike the
-- Textalker automation (native/mame-textalker/), these are small embedded
-- systems with no disk/OS boot process - but both still play a fixed
-- power-on "system ready" announcement of their own before they'll accept
-- our text, taking anywhere from ~1.5s (TNT) to ~7.5s (PSS) depending on
-- the machine - boot_wait needs to clear that per provider (see each
-- engine's synthesize()). print()ing speech_starts_at_seconds right before
-- posting marks where to crop the WAV so that announcement doesn't end up
-- in the output, same technique as textalker_capture.lua's banner-marker
-- crop.
--
-- Sequencing uses emu.wait(), not emu.add_machine_frame_notifier() - see
-- native/mame-textalker/textalker_capture.lua for why.

local input_text = os.getenv("MAME_RS232_INPUT") or "HELLO"
local wait_after = tonumber(os.getenv("MAME_RS232_WAIT_AFTER") or "10")
local boot_wait = tonumber(os.getenv("MAME_RS232_BOOT_WAIT") or "1.0")
local force_parallel_input = os.getenv("MAME_VOTRAX_DSW1_PARALLEL") == "1"

-- The Votrax PSS defaults to expecting text over its (unconnected, in this
-- setup) RS-232 serial port rather than the parallel/terminal-keyboard
-- path natkeyboard actually posts to - by design it silently ignores
-- parallel input in that mode (see votrpss.cpp's DSW1 "Default Input
-- Port" notes), so without this override it just plays its ready
-- announcement and never speaks the requested text at all.
if force_parallel_input then
    local dsw1 = manager.machine.ioport.ports[":DSW1"]
    dsw1.fields["Default Input Port"]:set_value(0x40)
    print("votrax_capture: forced DSW1 Default Input Port to Parallel")
end

local nat = manager.machine.natkeyboard

emu.wait(boot_wait)
print("votrax_capture: speech_starts_at_seconds=" .. string.format("%.3f", emu.time()))
print("votrax_capture: speaking: " .. input_text)
nat:post_coded(input_text)
emu.wait(wait_after)

print("votrax_capture: done")
manager.machine:exit()
