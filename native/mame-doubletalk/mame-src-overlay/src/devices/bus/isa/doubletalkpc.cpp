// license:BSD-3-Clause
// copyright-holders:
#include "emu.h"
#include "doubletalkpc.h"

#include "sound/dac.h"

#include "speaker.h"

DEFINE_DEVICE_TYPE(ISA8_DOUBLETALKPC, doubletalkpc_isa_device, "doubletalkpc_isa", "RC Systems DoubleTalk PC")

doubletalkpc_isa_device::doubletalkpc_isa_device(const machine_config &mconfig, const char *tag, device_t *owner, uint32_t clock) :
	device_t(mconfig, ISA8_DOUBLETALKPC, tag, owner, clock),
	device_isa8_card_interface(mconfig, *this),
	m_tts_status(0),
	m_lpc_status(0),
	m_mailbox_data(0),
	m_mailbox_pending(false),
	m_cpu(*this, "doubletalkpc_cpu")
{
}

// -----------------------------------------------------------------------
// Host (ISA bus) side. Port pair is LPC (offset 0) / TTS (offset 1),
// jumper-selectable base per the Linux dtlk driver's dtlk_portlist[]:
// 0x25e, 0x29e, 0x2de, 0x31e, 0x35e, 0x39e. Hardcoded to 0x25e for now.
//
// CONFIRMED (phase1_findings.md addendum): a TTS-port write reaches the
// firmware via a one-byte mailbox at physical address 0xA100 (see
// mailbox_r()/mailbox_w()) plus an INT1 doorbell - see pulse_int1(). The
// firmware writes its complete host-visible TTS status byte to onboard CPU
// port 0x40; tts_status_w() owns RDY as well as SYNC/SYNC2/AF/AE. The LPC
// port's CPU-side wiring is still unconfirmed (not yet traced).
// -----------------------------------------------------------------------

uint8_t doubletalkpc_isa_device::host_r(offs_t offset)
{
	if (offset == 0)
	{
		logerror("%s: host LPC port read -> %02x\n", machine().describe_context(), m_lpc_status);
		return m_lpc_status;
	}
	else
	{
		logerror("%s: host TTS port read -> %02x\n", machine().describe_context(), m_tts_status);
		return m_tts_status;
	}
}

void doubletalkpc_isa_device::host_w(offs_t offset, uint8_t data)
{
	if (offset == 0)
	{
		logerror("%s: host LPC port write <- %02x\n", machine().describe_context(), data);
	}
	else
	{
		logerror("%s: host TTS port write <- %02x%s\n", machine().describe_context(), data,
			(data == 0x18) ? " (DTLK_CLEAR)" : "");
		// Real hardware: a well-behaved host checks RDY first and won't
		// overrun this, but nothing stops it - matches the manual's own
		// warning ("To avoid losing data, your program should test the RDY
		// flag before each byte is output"), i.e. an overrun silently loses
		// the previous unconsumed byte rather than blocking or asserting.
		m_mailbox_data = data;
		m_mailbox_pending = true;
		pulse_int1();
	}
}

uint8_t doubletalkpc_isa_device::mailbox_r(offs_t offset)
{
	// This handler covers the single confirmed 80C188EB mailbox byte.
	if (offset != 0)
		return 0xff;
	// The ISR at 0x81D26 reads this address as its first instruction
	// unconditionally, for every byte - so this is the reliable point to
	// deassert INT1, not a fixed delay after the assert. The firmware issues
	// EOI through the 80C188EB peripheral block before returning.
	m_mailbox_pending = false;
	m_cpu->int1_w(0);
	return m_mailbox_data;
}

void doubletalkpc_isa_device::mailbox_w(offs_t offset, uint8_t data)
{
	if (offset != 0)
		return;
	// Not expected in practice - the mailbox is host-to-CPU only as far as
	// we've traced - but store it rather than dropping it silently, in
	// case some untraced code path does write here.
	m_mailbox_data = data;
}

// -----------------------------------------------------------------------
// Onboard 80C188EB. The 512KB ROM dump fits
// exactly into the top half of the CPU's 1MB real-mode address space,
// which lines up with the reset vector we found at file offset 0x7FFF0
// (= physical 0xFFFF0 when ROM is based at 0x80000). RAM size below that
// is not confirmed - sized generously here as a placeholder; the firmware's
// own stack setup (SS:SP = 002D:107E, physical ~0x134E) only needs a few KB.
// -----------------------------------------------------------------------

void doubletalkpc_isa_device::cpu_map(address_map &map)
{
	map(0x00000, 0xa0ff).ram();
	map(0xa100, 0xa100).rw(FUNC(doubletalkpc_isa_device::mailbox_r), FUNC(doubletalkpc_isa_device::mailbox_w));
	map(0xa101, 0x1ffff).ram();
	map(0x80000, 0xfffff).rom().region("doubletalkpc_cpu", 0);
}

void doubletalkpc_isa_device::cpu_io(address_map &map)
{
	// The 80C188EB Peripheral Control Block resets at 0xff00 in I/O space.
	// Firmware writes RELREG at 0xffa8 to relocate it to physical 0x9500;
	// the CPU core owns both locations.
	//
	// Genuine external accesses seen in the trace:
	//   0x80      - multi-mode board control latch
	//   0x00      - unsigned 8-bit PCM stream driven by the EB timer ISR
	//
	// Port 0x40 is the firmware-owned TTS status latch. The byte written from
	// DS:0x1a uses the exact host-visible SYNC/SYNC2/RDY/AF/AE bit layout.
	map(0x0000, 0x0000).w("dac", FUNC(dac_byte_interface::data_w)).umask16(0x00ff);
	map(0x0040, 0x0040).w(FUNC(doubletalkpc_isa_device::tts_status_w)).umask16(0x00ff);
}

void doubletalkpc_isa_device::tts_status_w(uint8_t data)
{
	m_tts_status = data;
	logerror("%s: firmware TTS status <- %02x\n", machine().describe_context(), data);
}

void doubletalkpc_isa_device::pulse_int1()
{
	// CONFIRMED (phase1_findings.md addendum): INT1's handler at physical
	// 0x81D26 reads the incoming byte from 0xA100 and checks it against
	// 0x18 (DTLK_CLEAR / Ctrl-X) - this is genuinely the host TTS data path,
	// not a guess like the removed synthetic INT0 timer. Stay asserted until
	// mailbox_r() proves the CPU consumed the byte; firmware owns masking and
	// EOI through the 80C188EB peripheral block.
	m_cpu->int1_w(1);
}

void doubletalkpc_isa_device::device_add_mconfig(machine_config &config)
{
	// A deliberate 2x overclock (stock is 20_MHz_XTAL / 10MHz processor
	// clock - see the real dtlk-pc driver upstream; a prior +10% version
	// of this experiment is in git history). The DAC is written directly
	// by CPU-timer code with no separate audio clock domain, so this
	// uniformly halves both the wall-clock time to synthesize a phrase
	// AND both ends of the card's own speech-rate range's real-time
	// duration (Ctrl+A <0-9> s) - verified on real captures (rate 5:
	// 1.0s -> 0.5s for an identical phrase, no desync/corruption at this
	// margin). Unlike the +10% version, this is paired with a
	// compensating fix in providers/doubletalk.py: since MAME's audio
	// mixer stream rate (48kHz) is fixed independent of CPU clock, the
	// captured samples encode "audio that happened 2x too fast" - halving
	// the *declared* sample rate on encode (not resampling, just the
	// header/metadata) exactly and losslessly undoes both the pitch rise
	// and the tempo speedup, verified to reproduce the stock-clock
	// duration/pitch exactly. Net effect: ~2x less real synthesis time
	// per request, no audible quality trade-off at all (unlike the +10%
	// version, which did trade off pitch).
	I80C188EB(config, m_cpu, XTAL(40'000'000)); // was 20_MHz_XTAL / 10MHz
	m_cpu->set_addrmap(AS_PROGRAM, &doubletalkpc_isa_device::cpu_map);
	m_cpu->set_addrmap(AS_IO, &doubletalkpc_isa_device::cpu_io);

	SPEAKER(config, "mono").front_center();
	DAC_8BIT_R2R(config, "dac", 0).add_route(ALL_OUTPUTS, "mono", 0.5);
}

ROM_START( doubletalkpc_isa )
	ROM_REGION( 0x80000, "doubletalkpc_cpu", 0 )
	ROM_LOAD( "doubletalkpc.bin", 0x0000, 0x80000, CRC(66685631) SHA1(bf7e78d6381c76d291ee069971873347a314ffff) )
ROM_END

const tiny_rom_entry *doubletalkpc_isa_device::device_rom_region() const
{
	return ROM_NAME( doubletalkpc_isa );
}

void doubletalkpc_isa_device::device_start()
{
	set_isa_device();
	m_isa->install_device(0x025e, 0x025f,
		read8sm_delegate(*this, FUNC(doubletalkpc_isa_device::host_r)),
		write8sm_delegate(*this, FUNC(doubletalkpc_isa_device::host_w)));
}

void doubletalkpc_isa_device::device_reset()
{
	m_tts_status = 0x00; // Firmware initializes the real value through onboard CPU port 0x40.
	m_lpc_status = 0x00;
	m_mailbox_data = 0;
	m_mailbox_pending = false;
}
