-- Generic MAME autoboot Lua script for standalone speech-synthesizer
-- machines that take plain ASCII text via a keyboard/terminal device with
-- no OS or disk to boot first (Votrax Type 'N Talk, Votrax Personal
-- Speech System - see providers/votrax_tnt.py, votrax_pss.py). Unlike the
-- Textalker automation (native/mame-textalker/), these are small embedded
-- systems that are ready to receive text within a second of power-on, so
-- there's no banner/boot-detection to wait for - just a short settle
-- delay, then post the text and wait proportional to its length.
--
-- Sequencing uses emu.wait(), not emu.add_machine_frame_notifier() - see
-- native/mame-textalker/textalker_capture.lua for why.

local input_text = os.getenv("MAME_RS232_INPUT") or "HELLO"
local wait_after = tonumber(os.getenv("MAME_RS232_WAIT_AFTER") or "10")
local boot_wait = tonumber(os.getenv("MAME_RS232_BOOT_WAIT") or "1.0")

local nat = manager.machine.natkeyboard

emu.wait(boot_wait)
print("votrax_capture: speaking: " .. input_text)
nat:post_coded(input_text)
emu.wait(wait_after)

print("votrax_capture: done")
manager.machine:exit()
