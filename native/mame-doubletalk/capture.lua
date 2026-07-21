-- MAME autoboot Lua script for the RC Systems DoubleTalk PC ISA card (see
-- providers/doubletalk.py). No OS or disk involved - the card is a raw ISA
-- peripheral with its own onboard 80C188EB CPU running the card's own
-- firmware straight from ROM, addressed directly via the host-facing LPC/
-- TTS port pair (documented by the Linux `dtlk` driver) rather than any
-- keyboard/terminal device.
--
-- Uses emu.register_periodic() rather than a blocking `while ... emu.wait()`
-- RDY-poll loop, matching scripts/doubletalk_regression_declaration.lua in
-- the mame-doubletalk research repo (the proven-working reference). An
-- emu.wait()-based busy loop inside send_byte() was tried first and is
-- confirmed broken: it corrupts/hangs the card shortly after synthesis
-- starts, producing only a fixed ~0.2s blip regardless of input text or
-- length (reproduced with both "HELLO" and the full Declaration phrase).
-- register_periodic's callback interleaves properly with the emulation
-- instead of stalling it inside a coroutine wait loop.
--
-- Text mode (the card's default) does not begin speaking until it
-- receives a CR (0x0D) or Null (0x00) byte - see the RC Systems manual,
-- "TTS Operating Modes" - so this always appends one. A well-behaved
-- sender polls the RDY status bit (0x10) before every byte, same as a
-- real host driver would.
--
-- Done detection mirrors the regression script: once every byte is sent,
-- watch the card's own read/write buffer pointers (card CPU program space,
-- 0x000f/0x0011) until they're equal (buffer drained) and stay that way for
-- DRAIN_SETTLE seconds, then wait AUDIO_TAIL more for synthesis to finish
-- before exiting - cheaper and more accurate than a fixed sleep sized off
-- input length. DOUBLETALK_WAIT_AFTER (if set) is used only as the hard
-- timeout fallback, not the primary completion signal.

local HOST_CPU_TAG = ":maincpu"
local CARD_CPU_TAG = ":isa6:doubletalkpc:doubletalkpc_cpu"
local TTS_PORT = 0x025f
local RDY_BIT = 0x10
local SEND_AT = 0.5 -- let the host machine finish its own boot first
local DRAIN_SETTLE = 1.0
local AUDIO_TAIL = 20.0

local input_text = os.getenv("DOUBLETALK_INPUT") or "HELLO"
local timeout_at = tonumber(os.getenv("DOUBLETALK_WAIT_AFTER") or "40") + SEND_AT

local phrase = {}
for i = 1, #input_text do
	phrase[i] = string.byte(input_text, i)
end
phrase[#phrase + 1] = 0x0d -- CR - triggers speech (see manual)

local machine = manager.machine
local host_cpu = machine.devices[HOST_CPU_TAG]
local card_cpu = machine.devices[CARD_CPU_TAG]

assert(host_cpu, "doubletalk_capture: host CPU not found")
assert(card_cpu, "doubletalk_capture: card CPU not found")

local host_io = host_cpu.spaces["io"]
local card_program = card_cpu.spaces["program"]

local function read_u16(address)
	return card_program:read_u8(address) | (card_program:read_u8(address + 1) << 8)
end

local started_at = machine.time:as_double()
local next_byte = 1
local finished = false
local drained_at = nil

print("doubletalk_capture: sending: " .. input_text)

local function finish(reason)
	if finished then
		return
	end
	finished = true
	print("doubletalk_capture: done (" .. reason .. "), bytes_sent=" .. (next_byte - 1) .. "/" .. #phrase)
	machine:exit()
end

emu.register_periodic(function()
	if finished then
		return
	end

	local elapsed = machine.time:as_double() - started_at

	if (elapsed >= SEND_AT) and (next_byte <= #phrase) then
		local status = host_io:read_u8(TTS_PORT)
		if (status & RDY_BIT) ~= 0 then
			host_io:write_u8(TTS_PORT, phrase[next_byte])
			next_byte = next_byte + 1
		end
	end

	if next_byte > #phrase then
		local rp = read_u16(0x000f)
		local wp = read_u16(0x0011)
		if rp == wp then
			if not drained_at then
				drained_at = elapsed
			elseif elapsed >= drained_at + DRAIN_SETTLE + AUDIO_TAIL then
				finish("drained")
				return
			end
		else
			drained_at = nil
		end
	end

	if elapsed >= timeout_at then
		finish("timeout")
	end
end)
