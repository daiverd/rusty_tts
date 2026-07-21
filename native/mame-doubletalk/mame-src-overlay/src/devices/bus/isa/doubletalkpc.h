// license:BSD-3-Clause
// copyright-holders:
#ifndef MAME_BUS_ISA_DOUBLETALKPC_H
#define MAME_BUS_ISA_DOUBLETALKPC_H

#pragma once

#include "isa.h"

#include "cpu/i86/i186.h"


// RC Systems DoubleTalk PC - 8-bit ISA text-to-speech card.
//
// Single onboard 10 MHz 80C188EB CPU runs the card's own
// firmware (TTS engine + LPC/PCM/CVSD synthesis + tone generator) out of a
// 512KB ROM. The host communicates via two I/O ports (LPC port = base,
// TTS port = base+1), documented by the Linux `dtlk` driver:
//   - jumper-selectable base address, one of 0x25e/0x29e/0x2de/0x31e/0x35e/0x39e
//   - TTS port: write = data byte to speak/command char; read = status bits
//     (TTS_READABLE 0x80, TTS_SPEAKING 0x40, TTS_SPEAKING2 0x20,
//      TTS_WRITABLE 0x10, TTS_ALMOST_FULL 0x08, TTS_ALMOST_EMPTY 0x04)
//   - LPC port: read = status bits (LPC_SPEAKING 0x80, LPC_BUFFER_LOW 0x40,
//      LPC_BUFFER_EMPTY 0x20) / index markers; write = LPC speak command
//
// CONFIRMED by debugger trace + disassembly of the installed interrupt
// vectors: INT1 is the host "byte arrived" doorbell. Its handler (physical
// 0x81D26)
//          reads the incoming byte from a fixed memory-mapped address,
//          0xA100, and compares it against 0x18 (DTLK_CLEAR / Ctrl-X per
//          the RC Systems manual) to detect the clear/reinit command -
//          unambiguous confirmation this is genuinely the TTS data path.
// The firmware relocates the EB Peripheral Control Block to physical 0x9500
// and issues its own EOI through offset 0x02. INT0 is reserved for the
// external sample device; no source is asserted until that hardware is modeled.
//
// The firmware writes byte DS:0x1a to onboard CPU port 0x40. Its bit layout
// exactly matches the host-visible TTS status register, so tts_status_w()
// drives RDY/SYNC/SYNC2/AF/AE directly from firmware state. The LPC port is
// still a static stub.

class doubletalkpc_isa_device : public device_t,
							public device_isa8_card_interface
{
public:
	doubletalkpc_isa_device(const machine_config &mconfig, const char *tag, device_t *owner, uint32_t clock);

protected:
	// device-level overrides
	virtual void device_start() override ATTR_COLD;
	virtual void device_reset() override ATTR_COLD;

	// optional information overrides
	virtual const tiny_rom_entry *device_rom_region() const override ATTR_COLD;
	virtual void device_add_mconfig(machine_config &config) override ATTR_COLD;

private:
	// host (ISA bus) side: LPC port at offset 0, TTS port at offset 1
	uint8_t host_r(offs_t offset);
	void host_w(offs_t offset, uint8_t data);
	void tts_status_w(uint8_t data);

	// CPU-side end of the TTS byte mailbox at physical 0xA100 (see cpu_map).
	// Modeled as a one-byte input latch: writable by the host (host_w sets
	// pending and asserts INT1), and clearing "pending" when the CPU reads it
	// back (matching
	// the confirmed real handler at 0x81D26, whose first action is reading
	// this exact address). RDY is independently owned by the firmware status
	// latch at port 0x40.
	uint8_t mailbox_r(offs_t offset);
	void mailbox_w(offs_t offset, uint8_t data);

	void cpu_map(address_map &map) ATTR_COLD;
	void cpu_io(address_map &map) ATTR_COLD;

	void pulse_int1();

	uint8_t m_tts_status;
	uint8_t m_lpc_status;
	uint8_t m_mailbox_data;
	bool m_mailbox_pending;

	required_device<i80186_cpu_device> m_cpu;
};

DECLARE_DEVICE_TYPE(ISA8_DOUBLETALKPC, doubletalkpc_isa_device)

#endif // MAME_BUS_ISA_DOUBLETALKPC_H
