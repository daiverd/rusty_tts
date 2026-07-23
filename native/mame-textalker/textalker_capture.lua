-- MAME autoboot Lua script: boots an emulated Apple //e with a real Street
-- Electronics Echo Plus card (TMS5220C) in slot 4. The floppy's HELLO
-- program (DOS 3.3's autoexec) has been replaced per-request by
-- providers/textalker.py (via AppleCommander) with a tiny Applesoft
-- program that BRUNs the real Textalker 1.3 driver and PRINTs the
-- requested phrase - so this script requires NO keyboard input at all:
-- DOS runs HELLO automatically on boot.
--
-- This is a deliberate second generation of this script. The first typed
-- "BRUN TEXTALKER.BLIND" and "PRINT "text"" character by character via
-- natkeyboard, which (a) had real per-character timing/drop risk and (b)
-- meant Textalker spoke back every typed character as an echo, requiring
-- a fragile crop marker to remove. Baking the commands into HELLO removes
-- both problems: there is no typing to drop characters during, and no
-- typed-character echo speech to crop - only Textalker's own fixed
-- startup banner precedes the actual phrase, and unlike keyboard timing
-- that's now perfectly deterministic.
--
-- Sequencing uses emu.wait(), not emu.add_machine_frame_notifier(): MAME's
-- autoboot script runs as a coroutine (lua_engine::invoke() wraps the call
-- in a sol::coroutine), so emu.wait(seconds) yields on actual emulated
-- machine time. The frame notifier is tied to video/vblank timing and was
-- found to silently stop firing after ~2 emulated seconds under -video
-- none; emu.wait() has no such issue.

local wait_after = tonumber(os.getenv("TEXTALKER_WAIT_AFTER") or "10")
local banner_marker = os.getenv("TEXTALKER_BANNER_MARKER") or "COPYRIGHT 1981"
local banner_timeout = tonumber(os.getenv("TEXTALKER_BANNER_TIMEOUT") or "20")

local function read_text_screen()
    local pspace = manager.machine.devices[":maincpu"].spaces["program"]
    local lines = {}
    for row = 0, 23 do
        local base = 0x400 + (row % 8) * 0x80 + math.floor(row / 8) * 0x28
        local chars = {}
        for col = 0, 39 do
            local b = pspace:read_u8(base + col) & 0x7F
            if b < 32 then b = 32 end
            chars[#chars + 1] = string.char(b)
        end
        lines[#lines + 1] = table.concat(chars)
    end
    return table.concat(lines, "\n")
end

local function wait_for_screen_text(marker, timeout_s)
    local elapsed = 0
    while elapsed < timeout_s do
        if read_text_screen():find(marker, 1, true) then
            return true
        end
        emu.wait(0.25)
        elapsed = elapsed + 0.25
    end
    return false
end

print("textalker: booting, HELLO auto-runs (BRUN + PRINT baked in)")

-- Textalker's fixed startup banner's last line, printed right as it
-- finishes installing and hands control back to HELLO for the PRINT of
-- the actual phrase. Mark the emulated-time position here so
-- providers/textalker.py can crop the WAV capture to start after it.
-- The exact banner text (and how long it takes to appear) differs by
-- driver version - see providers/textalker.py's _VOICES table.
local banner_seen = wait_for_screen_text(banner_marker, banner_timeout)
print("textalker: banner_seen=" .. tostring(banner_seen))
print("textalker: speech_starts_at_seconds=" .. string.format("%.3f", emu.time()))

emu.wait(wait_after)

print("textalker: done")
manager.machine:exit()
